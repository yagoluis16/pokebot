"""Cura do player por hotkey, com cooldown independente da duração da tecla.

Preserva Healer(ctx, bus, resolver) e as chaves usadas pela GUI.
MP não é necessário nem consultado nesta versão de cura por HP.
"""

from __future__ import annotations

import logging
import math
import time

from modules.base import Module

log = logging.getLogger("pokebot.modules.healer")

_VK_MAP = {f"F{number}": 0x6F + number for number in range(1, 13)}
_VK_MAP.update({str(number): ord(str(number)) for number in range(10)})


def _resolve_vk(hotkey: str) -> int:
    key = str(hotkey).strip().upper()
    if key in _VK_MAP:
        return _VK_MAP[key]
    try:
        code = int(key, 0)
    except ValueError as exc:
        raise ValueError(f"hotkey inválida: {hotkey!r}") from exc
    if not 1 <= code <= 0xFE:
        raise ValueError(f"VK fora do intervalo: {hotkey!r}")
    return code


class Healer(Module):
    """Cura normal e de emergência usando a fila de input existente."""

    name = "healer"
    config_key = "healer"

    def __init__(self, ctx=None, bus=None, resolver=None):
        super().__init__(ctx, bus)
        self.resolver = resolver
        self.log = log
        self._last_heal_ts = None
        self._last_emergency_ts = None
        self.heals_sent = 0
        self.emergency_heals_sent = 0
        self.last_hp = None
        self.last_hp_max = None
        self.last_pct = None
        self.last_skip_reason = None
        self._load_settings()

    def _load_settings(self):
        def setting(name, default, alias=None):
            fallback = self.ctx.get("healer", alias, default=default) if alias else default
            return self.ctx.get("healer", name, default=fallback)

        self.hp_threshold_pct = float(setting("hp_percent_threshold", 60))
        self.emergency_threshold_pct = float(setting("panic_hp_percent", 25, "emergency_threshold_pct"))
        self.hotkey = setting("hp_hotkey", "F1", "hotkey")
        self.emergency_hotkey = setting("panic_hotkey", "F3", "emergency_hotkey")
        self.cooldown_ms = float(setting("cooldown_ms", 800, "delay_between_heals_ms"))
        self.emergency_cooldown_ms = float(setting("emergency_cooldown_ms", 400))
        self.hold_ms = float(setting("hold_ms", 50))
        if not 0 <= self.emergency_threshold_pct <= self.hp_threshold_pct <= 100:
            raise ValueError("thresholds inválidos: 0 <= emergência <= normal <= 100")
        if any(not math.isfinite(value) or value < 0 for value in
               (self.cooldown_ms, self.emergency_cooldown_ms, self.hold_ms)):
            raise ValueError("cooldown e hold_ms devem ser finitos e não negativos")
        self._vk_normal = _resolve_vk(self.hotkey)
        self._vk_emergency = _resolve_vk(self.emergency_hotkey)

    def tick(self):
        self._load_settings()
        self.last_hp = None
        self.last_hp_max = None
        self.last_pct = None
        if self.resolver is None:
            self.last_skip_reason = "resolver indisponível"
            return
        hp = self.resolver.read_field("player", "hp")
        hp_max = self.resolver.read_field("player", "hp_max")
        self.last_hp = hp
        self.last_hp_max = hp_max
        if hp is None or hp_max is None:
            self.last_skip_reason = f"leitura HP falhou (hp={hp!r}, hp_max={hp_max!r})"
        elif hp_max <= 0 or hp < 0 or hp > hp_max:
            self.last_skip_reason = f"HP inválido: {hp}/{hp_max}"
        elif hp == 0:
            self.last_pct = 0
            self.last_skip_reason = "HP zerado"
        else:
            self.last_pct = hp * 100.0 / hp_max
            self._heal_if_needed()
            return
        self.log.debug(self.last_skip_reason)

    def _heal_if_needed(self):
        emergency = self.last_pct < self.emergency_threshold_pct
        if not emergency and self.last_pct >= self.hp_threshold_pct:
            self.last_skip_reason = "HP acima ou igual ao threshold"
            return
        now = time.monotonic()
        previous = self._last_emergency_ts if emergency else self._last_heal_ts
        cooldown = self.emergency_cooldown_ms if emergency else self.cooldown_ms
        if previous is not None and (now - previous) * 1000 < cooldown:
            self.last_skip_reason = "emergência em cooldown" if emergency else "cura em cooldown"
            self.log.debug(self.last_skip_reason)
            return
        code = self._vk_emergency if emergency else self._vk_normal
        if not self.press(code, hold_ms=self.hold_ms, priority=1 if emergency else 5):
            self.last_skip_reason = "fila de input recusou a cura"
            self.log.debug(self.last_skip_reason)
            return
        self._last_heal_ts = now
        if emergency:
            self._last_emergency_ts = now
            self.emergency_heals_sent += 1
        else:
            self.heals_sent += 1
        self.last_skip_reason = None
        self.ctx.inc_stat("heals")
        self.log.log(
            logging.WARNING if emergency else logging.INFO,
            "%s: hp=%d/%d (%.1f%%) -> %s (enfileirado)",
            "EMERGÊNCIA" if emergency else "curando",
            self.last_hp, self.last_hp_max, self.last_pct,
            self.emergency_hotkey if emergency else self.hotkey,
        )

    @property
    def stats(self):
        return {
            "heals_sent": self.heals_sent,
            "emergency_heals_sent": self.emergency_heals_sent,
            "last_hp": self.last_hp,
            "last_hp_max": self.last_hp_max,
            "last_hp_pct": round(self.last_pct, 1) if self.last_pct is not None else None,
            "hp_threshold_pct": self.hp_threshold_pct,
            "emergency_threshold_pct": self.emergency_threshold_pct,
            "hotkey": self.hotkey,
            "emergency_hotkey": self.emergency_hotkey,
            "last_skip_reason": self.last_skip_reason,
        }
