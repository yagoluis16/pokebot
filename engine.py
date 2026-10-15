# pokebot/engine.py
"""Module engine: lifecycle management for all bot modules."""

from __future__ import annotations
import logging
import threading
from typing import Optional

from context import get_context, BotContext
from inputbus import get_bus, shutdown_bus
from modules.base import Module
from modules.healer import Healer
from modules.auto_food import AutoFood
from modules.cavebot import Cavebot
from modules.auto_target import AutoTarget
from modules.auto_catch import AutoCatch
from modules.alarms import Alarms
from navigator import Navigator

log = logging.getLogger("pokebot.engine")


class Engine:
    """Orchestrates all modules, resolver, and input bus."""

    def __init__(self, config_path: str = None, resolver=None):
        self.ctx: BotContext = get_context(config_path)
        self.resolver = resolver
        self.bus = get_bus()
        self.navigator = Navigator(resolver=resolver, ctx=self.ctx, bus=self.bus)

        self.modules: dict[str, Module] = {}
        self._init_modules()

    def _init_modules(self):
        # Order matters: healer first (highest priority), alarms last (monitoring)
        self.modules["healer"] = Healer(ctx=self.ctx, bus=self.bus, resolver=self.resolver)
        self.modules["auto_food"] = AutoFood(ctx=self.ctx, bus=self.bus, resolver=self.resolver)
        self.modules["cavebot"] = Cavebot(ctx=self.ctx, bus=self.bus, resolver=self.resolver)
        self.modules["auto_target"] = AutoTarget(ctx=self.ctx, bus=self.bus, resolver=self.resolver)
        self.modules["auto_catch"] = AutoCatch(ctx=self.ctx, bus=self.bus, resolver=self.resolver)
        self.modules["alarms"] = Alarms(ctx=self.ctx, bus=self.bus, resolver=self.resolver)

    def start(self):
        self.bus.start()
        self.ctx.stop_event.clear()
        for name, mod in self.modules.items():
            mod.start()
        log.info("Engine started with %d modules", len(self.modules))

    def stop(self):
        log.info("Stopping engine...")
        self.ctx.stop()
        for name, mod in self.modules.items():
            mod.stop()
        shutdown_bus()
        log.info("Engine stopped")

    def pause(self):
        self.ctx.pause()
        log.info("Engine paused")

    def resume(self):
        self.ctx.resume()
        log.info("Engine resumed")

    def reload_config(self):
        self.ctx.reload_config()
        for mod in self.modules.values():
            mod.on_config_change()
        log.info("Config reloaded")

    def get_module(self, name: str) -> Optional[Module]:
        return self.modules.get(name)

    def get_status(self) -> dict:
        return {
            "running": not self.ctx.is_stopped(),
            "paused": self.ctx.is_paused(),
            "modules": {name: mod.enabled for name, mod in self.modules.items()},
            "stats": self.ctx.get_stats(),
            "navigator": self.navigator.get_progress(),
        }


def create_engine(config_path: str = None, resolver=None) -> Engine:
    return Engine(config_path=config_path, resolver=resolver)