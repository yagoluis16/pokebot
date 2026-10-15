# pokebot/modules/healer.py
"""Healer module: HP/MP monitoring with hysteresis and panic mode."""

from __future__ import annotations
import logging
from modules.base import Module

log = logging.getLogger("pokebot.modules.healer")


class Healer(Module):
    name = "healer"
    config_key = "healer"

    def __init__(self, ctx=None, bus=None, resolver=None):
        super().__init__(ctx, bus)
        self.resolver = resolver
        self._last_hp_pct = 100
        self._last_mp_pct = 100
        self._hp_hotkey_vk = 0
        self._mp_hotkey_vk = 0
        self._panic_hotkey_vk = 0
        self._load_hotkeys()

    def _load_hotkeys(self):
        from inputbus import InputBus
        # Convert hotkey strings to VK codes
        hk = {
            "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74,
            "F6": 0x75, "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79,
            "F11": 0x7A, "F12": 0x7B,
        }
        hp_hk = self.ctx.get("healer", "hp_hotkey", default="F1")
        mp_hk = self.ctx.get("healer", "mp_hotkey", default="F2")
        panic_hk = self.ctx.get("healer", "panic_hotkey", default="F3")
        self._hp_hotkey_vk = hk.get(hp_hk.upper(), 0x70)
        self._mp_hotkey_vk = hk.get(mp_hk.upper(), 0x71)
        self._panic_hotkey_vk = hk.get(panic_hk.upper(), 0x72)

    def tick(self):
        if not self.resolver:
            return

        # Read HP/MP from memory
        hp = self.resolver.read_field("player", "hp")
        hp_max = self.resolver.read_field("player", "hp_max")
        mp = self.resolver.read_field("player", "mp")
        mp_max = self.resolver.read_field("player", "mp_max")

        if hp is None or hp_max is None or hp_max == 0:
            return
        if mp is None or mp_max is None or mp_max == 0:
            return

        hp_pct = (hp * 100) // hp_max
        mp_pct = (mp * 100) // mp_max

        # Panic mode (highest priority)
        panic_hp = self.ctx.get("healer", "panic_hp_percent", default=25)
        if hp_pct <= panic_hp:
            if self._last_hp_pct > panic_hp:
                log.warning("HEALER PANIC: HP %d%% <= %d%%", hp_pct, panic_hp)
            self.press(self._panic_hotkey_vk, hold_ms=self.ctx.get("healer", "panic_delay_ms", default=250))
            self._last_hp_pct = hp_pct
            self.ctx.inc_stat("heals")
            return

        # Normal HP heal with hysteresis
        hp_threshold = self.ctx.get("healer", "hp_percent_threshold", default=60)
        hp_above = self.ctx.get("healer", "hp_above_percent", default=85)
        if hp_pct <= hp_threshold and self._last_hp_pct < hp_above:
            log.info("HEALER: HP %d%% <= %d%%, pressing heal", hp_pct, hp_threshold)
            self.press(self._hp_hotkey_vk, hold_ms=self.ctx.get("healer", "delay_between_heals_ms", default=650))
            self.ctx.inc_stat("heals")
        self._last_hp_pct = hp_pct

        # MP heal with hysteresis
        mp_threshold = self.ctx.get("healer", "mp_percent_threshold", default=40)
        mp_above = self.ctx.get("healer", "mp_above_percent", default=90)
        if mp_pct <= mp_threshold and self._last_mp_pct < mp_above:
            log.info("HEALER: MP %d%% <= %d%%, pressing mana", mp_pct, mp_threshold)
            self.press(self._mp_hotkey_vk, hold_ms=self.ctx.get("healer", "delay_between_heals_ms", default=650))
            self.ctx.inc_stat("mana_heals")
        self._last_mp_pct = mp_pct