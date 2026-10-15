# pokebot/modules/auto_target.py
"""Auto-target module: creature selection and attack."""

from __future__ import annotations
import logging
import time
from modules.base import Module

log = logging.getLogger("pokebot.modules.auto_target")


class AutoTarget(Module):
    name = "auto_target"
    config_key = "auto_target"

    def __init__(self, ctx=None, bus=None, resolver=None):
        super().__init__(ctx, bus)
        self.resolver = resolver
        self._last_attack = 0.0
        self._current_target_id = None
        self._attack_hotkey_vk = 0
        self._load_hotkey()

    def _load_hotkey(self):
        hk = {
            "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74,
            "F6": 0x75, "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79,
            "F11": 0x7A, "F12": 0x7B,
        }
        atk_hk = self.ctx.get("auto_target", "attack_hotkey", default="F5")
        self._attack_hotkey_vk = hk.get(atk_hk.upper(), 0x74)

    def tick(self):
        if not self.resolver:
            return

        import time
        now = time.monotonic()

        # Cooldown
        cd = self.ctx.get("auto_target", "attack_cooldown_ms", default=900) / 1000.0
        if now - self._last_attack < cd:
            return

        # Get creatures from memory
        creatures = self._get_creatures()
        if not creatures:
            return

        # Filter and select target
        target = self._select_target(creatures)
        if not target:
            return

        # Attack
        creature_id = target.get("creature_id")
        if creature_id is not None:
            log.info("AUTO_TARGET: attacking creature %d (HP%%: %s)", creature_id, target.get("hp_percent"))
            self.press(self._attack_hotkey_vk)
            self._last_attack = now
            self._current_target_id = creature_id
            self.ctx.inc_stat("creatures_killed")

    def _get_creatures(self) -> list[dict]:
        """Read creature list from memory. Returns list of dicts."""
        # PLACEHOLDER — needs entity list offsets, not yet reversed
        # TODO: reverse container root/layout, iteration bounds and entity id/name/HP/position fields.
        if not self.resolver:
            return []
        # This uses the creature_list block which needs ptr_chain calibrated
        # Filling offsets alone is insufficient; container iteration still needs implementation.
        try:
            base = self.resolver.resolve_block("creature_list")
            if base is None:
                return []
            # The iter block defines how to iterate creatures
            # This is a placeholder - full implementation needs calibrated offsets
            return []
        except Exception:
            return []

    def _select_target(self, creatures: list[dict]) -> dict | None:
        if not creatures:
            return None

        # Apply filters
        filtered = []
        for c in creatures:
            if self.ctx.get("auto_target", "ignore_players", default=True) and c.get("is_player"):
                continue
            if self.ctx.get("auto_target", "ignore_npcs", default=True) and c.get("is_npc"):
                continue
            if self.ctx.get("auto_target", "ignore_dead", default=True) and c.get("is_dead"):
                continue
            hp_pct = c.get("hp_percent", 100)
            if hp_pct <= 0:
                continue
            # Range check (requires player pos + creature pos)
            # Placeholder
            filtered.append(c)

        if not filtered:
            return None

        # Prioritize
        mode = self.ctx.get("auto_target", "prioritize", default="lowest_hp_percent")
        if mode == "lowest_hp_percent":
            filtered.sort(key=lambda c: c.get("hp_percent", 100))
        elif mode == "nearest":
            # Would need distance calc
            pass
        elif mode == "highest_level":
            filtered.sort(key=lambda c: c.get("level", 1), reverse=True)

        return filtered[0]
