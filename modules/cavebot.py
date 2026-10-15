# pokebot/modules/cavebot.py
"""Cavebot module: waypoint walking with combat pause."""

from __future__ import annotations
import logging
from modules.base import Module
from navigator import Navigator

log = logging.getLogger("pokebot.modules.cavebot")


class Cavebot(Module):
    name = "cavebot"
    config_key = "cavebot"

    def __init__(self, ctx=None, bus=None, resolver=None):
        super().__init__(ctx, bus)
        self.navigator = Navigator(resolver=resolver, ctx=ctx, bus=bus)
        self._combat_pause_until = 0.0
        self.load_waypoints()

    def load_waypoints(self):
        self.navigator.load_waypoints()

    def tick(self):
        if self.ctx.is_stopped() or self.ctx.is_paused():
            return

        import time
        if time.monotonic() < self._combat_pause_until:
            return

        # Pause if creatures nearby
        pause_radius = self.ctx.get("cavebot", "pause_on_creature_within_tiles", default=2)
        if pause_radius > 0 and self.navigator.creatures_nearby(pause_radius):
            return

        self.navigator.tick()

    def pause_for_combat(self, seconds: float = None):
        import time
        if seconds is None:
            seconds = self.ctx.get("cavebot", "resume_after_combat_seconds", default=4)
        self._combat_pause_until = time.monotonic() + seconds

    def pause(self):
        self.navigator.pause()

    def resume(self):
        self.navigator.resume()

    def get_progress(self) -> dict:
        return self.navigator.get_progress()

    def add_waypoint(self, x: int, y: int, z: int, name: str = ""):
        self.navigator.add_waypoint(x, y, z, name)

    def remove_waypoint(self, index: int):
        self.navigator.remove_waypoint(index)

    def clear_waypoints(self):
        self.navigator.clear_waypoints()