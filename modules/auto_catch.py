# pokebot/modules/auto_catch.py
"""Auto-catch module: throw balls after creature death."""

from __future__ import annotations
import logging
import time
from modules.base import Module

log = logging.getLogger("pokebot.modules.auto_catch")


class AutoCatch(Module):
    name = "auto_catch"
    config_key = "auto_catch"

    def __init__(self, ctx=None, bus=None, resolver=None):
        super().__init__(ctx, bus)
        self.resolver = resolver
        self._last_throw = 0.0
        self._throw_count = 0
        self._catch_hotkey_vk = 0
        self._load_hotkey()

    def _load_hotkey(self):
        hk = {
            "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74,
            "F6": 0x75, "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79,
            "F11": 0x7A, "F12": 0x7B,
        }
        catch_hk = self.ctx.get("auto_catch", "catch_ball_hotkey", default="F6")
        self._catch_hotkey_vk = hk.get(catch_hk.upper(), 0x75)

    def tick(self):
        if not self.resolver:
            return

        # Check if enabled creatures list
        names = self.ctx.get("auto_catch", "enabled_creature_names", default=[])
        if not names:
            return

        import time
        now = time.monotonic()

        # Cooldown between throws
        if now - self._last_throw < self.ctx.get("auto_catch", "throw_delay_ms", default=750) / 1000.0:
            return

        # Check if we have a target that just died
        # This requires creature_list and targeting to be working
        # Placeholder for when offsets are calibrated
        target_id = self._get_dead_target_id(names)
        if target_id is None:
            return

        # Stop if target HP above threshold
        hp_pct = self._get_target_hp_percent(target_id)
        if hp_pct is not None:
            stop_above = self.ctx.get("auto_catch", "stop_when_hp_above_percent", default=60)
            if hp_pct > stop_above:
                return

        # Throw
        if self._throw_count < self.ctx.get("auto_catch", "throw_count", default=3):
            log.info("AUTO_CATCH: throwing ball at creature %d", target_id)
            self.press(self._catch_hotkey_vk)
            self._throw_count += 1
            self._last_throw = now
        else:
            # Reset after sequence
            self._throw_count = 0

    def _get_dead_target_id(self, names: list) -> int | None:
        """Returns creature_id of a dead target matching names. Placeholder."""
        # PLACEHOLDER — needs entity list offsets, not yet reversed
        # TODO: reverse entity iteration, stable IDs, names and death/corpse state before matching targets.
        return None

    def _get_target_hp_percent(self, creature_id: int) -> int | None:
        """Returns HP% of creature. Placeholder."""
        # PLACEHOLDER — needs entity list offsets, not yet reversed
        # TODO: reverse ID-to-entity lookup and validate HP percentage field/type/lifetime in CE.
        return None
