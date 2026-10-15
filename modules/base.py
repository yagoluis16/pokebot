# pokebot/modules/base.py
"""Base class for all bot modules."""

from __future__ import annotations
import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

from context import get_context
from inputbus import get_bus, InputRequest, InputType

log = logging.getLogger("pokebot.modules")


@dataclass
class ModuleConfig:
    enabled: bool = True
    tick_ms: int = 200


class Module(ABC):
    """Base module with lifecycle, config, and tick loop."""

    name: str = "base"
    config_key: str = "base"
    default_config: ModuleConfig = ModuleConfig()

    def __init__(self, ctx=None, bus=None):
        self.ctx = ctx or get_context()
        self.bus = bus or get_bus()
        self._cfg = self.default_config
        self._thread: threading.Thread | None = None
        self._running = False
        self._reload_config()

    def _reload_config(self):
        mod_cfg = self.ctx.config.get("modules", {}).get(self.config_key, {})
        self._cfg = ModuleConfig(
            enabled=mod_cfg.get("enabled", self.default_config.enabled),
            tick_ms=mod_cfg.get("tick_ms", self.default_config.tick_ms),
        )

    @property
    def enabled(self) -> bool:
        return self._cfg.enabled and self.ctx.get("modules", self.config_key, "enabled", default=True)

    @property
    def tick_ms(self) -> int:
        return self._cfg.tick_ms

    def start(self):
        if self._running:
            return
        if not self.enabled:
            log.info("Module %s disabled, not starting", self.name)
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name=f"Module-{self.name}", daemon=True)
        self._thread.start()
        log.info("Module %s started (tick=%dms)", self.name, self.tick_ms)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        log.info("Module %s stopped", self.name)

    def _run(self):
        while self._running and not self.ctx.is_stopped():
            try:
                if not self.ctx.wait_if_paused(timeout=0.1):
                    break
                if self.enabled:
                    self.tick()
            except Exception as exc:
                log.exception("Module %s tick error: %s", self.name, exc)
            time.sleep(self.tick_ms / 1000.0)

    @abstractmethod
    def tick(self):
        """Single tick - implement in subclass."""
        pass

    def press(self, vk: int, hold_ms: int = 50, priority: int = 10) -> bool:
        return self.bus.press_key(vk, hold_ms, priority, module=self.name)

    def key_down(self, vk: int, priority: int = 10) -> bool:
        return self.bus.key_down(vk, priority, module=self.name)

    def key_up(self, vk: int, priority: int = 10) -> bool:
        return self.bus.key_up(vk, priority, module=self.name)

    def click(self, x: int, y: int, priority: int = 10) -> bool:
        return self.bus.click(x, y, priority, module=self.name)

    def on_config_change(self):
        """Called when config is reloaded."""
        self._reload_config()