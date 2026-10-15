# pokebot/modules/auto_food.py
"""Auto-food module: periodic eating with jitter and HP pause."""

from __future__ import annotations
import logging
import random
import time
from modules.base import Module

log = logging.getLogger("pokebot.modules.auto_food")


class AutoFood(Module):
    name = "auto_food"
    config_key = "auto_food"

    def __init__(self, ctx=None, bus=None, resolver=None):
        super().__init__(ctx, bus)
        self.resolver = resolver
        self._next_eat = 0.0
        self._food_hotkey_vk = 0
        self._load_hotkey()

    def _load_hotkey(self):
        hk = {
            "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74,
            "F6": 0x75, "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79,
            "F11": 0x7A, "F12": 0x7B,
        }
        food_hk = self.ctx.get("auto_food", "food_hotkey", default="F4")
        self._food_hotkey_vk = hk.get(food_hk.upper(), 0x73)

    def tick(self):
        if not self.resolver:
            return

        now = time.monotonic()
        if now < self._next_eat:
            return

        # Check HP pause condition
        hp = self.resolver.read_field("player", "hp")
        hp_max = self.resolver.read_field("player", "hp_max")
        if hp is None or hp_max is None or hp_max == 0:
            # Cannot read HP, don't eat
            self._next_eat = now + 5.0
            return

        hp_pct = (hp * 100) // hp_max
        pause_below = self.ctx.get("auto_food", "pause_when_hp_below_percent", default=30)
        if hp_pct <= pause_below:
            # Reschedule soon, don't eat while critical
            self._next_eat = now + 5.0
            return

        # Eat
        log.info("AUTO_FOOD: eating")
        self.press(self._food_hotkey_vk)
        self.ctx.inc_stat("food_eaten")

        # Schedule next with jitter
        interval = self.ctx.get("auto_food", "interval_seconds", default=60)
        jitter = self.ctx.get("auto_food", "jitter_seconds", default=8)
        self._next_eat = now + interval + random.uniform(-jitter, jitter)