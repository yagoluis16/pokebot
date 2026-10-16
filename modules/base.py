# pokebot/modules/base.py
"""Base class for all bot modules."""

from __future__ import annotations
import logging
import threading
import time
import math
from enum import Enum
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.memory import MemoryReader
    from core.offsets import OffsetEntry, OffsetRegistry

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
        # Keep legacy modules compatible without loading the input backend for the dummy demo.
        from context import get_context
        from inputbus import get_bus
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


class ModuleState(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    RUNNING_DISABLED = "running_disabled"
    ERROR = "error"


class AutomationModule(ABC):
    """Threaded module contract for the new core API.

    start() launches the worker without waiting for setup(). setup/tick/teardown
    run on that worker; inspect state/stats for asynchronous setup failures.
    stop() never discards a live thread after a timeout. teardown runs exactly
    once per launched worker, including after setup failure or the error limit.
    disable() prevents new ticks once observed; an in-flight tick may finish.
    An ERROR remains visible after the worker exits, until the next start().
    Legacy Module above remains available until its consumers are migrated.
    """

    def __init__(self, memory: MemoryReader, offsets: OffsetRegistry, name: str, *,
                 interval: float = 0.1, enabled: bool = True,
                 autostart: bool = False, max_errors: int = 10) -> None:
        if type(max_errors) is not int or max_errors < 0:
            raise ValueError("max_errors must be a nonnegative integer")
        self.memory = memory
        self.offsets = offsets
        self.name = name
        self.log = logging.getLogger(f"pokebot.modules.{name}")
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread = None
        self._enabled = bool(enabled)
        self._running = False
        self._failed = False
        self._last_error = None
        self._error_count = 0
        self._ticks = 0
        self._started_at = None
        self._stopped_at = None
        self.max_errors = max_errors
        self.interval = interval
        # Subclasses opting into autostart must initialize their own fields first.
        if autostart:
            self.start()

    @property
    def interval(self) -> float:
        with self._lock:
            return self._interval

    @interval.setter
    def interval(self, value: float) -> None:
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("interval must be finite and > 0")
        with self._lock:
            self._interval = value

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def is_enabled(self) -> bool:
        with self._lock:
            return self._enabled

    @property
    def state(self) -> ModuleState:
        with self._lock:
            if self._failed:
                return ModuleState.ERROR
            if not self._running:
                return ModuleState.STOPPED
            return ModuleState.RUNNING if self._enabled else ModuleState.RUNNING_DISABLED

    @property
    def stats(self) -> dict:
        with self._lock:
            end = self._stopped_at if self._stopped_at is not None else time.monotonic()
            uptime = end - self._started_at if self._started_at is not None else 0.0
            return {"name": self.name, "state": self.state.value, "ticks": self._ticks,
                    "errors": self._error_count, "uptime_s": round(uptime, 2),
                    "interval_s": self._interval,
                    "last_error": repr(self._last_error) if self._last_error is not None else None}

    def start(self) -> bool:
        with self._lock:
            if self._running or (self._thread is not None and self._thread.is_alive()):
                return False
            self._stop_event.clear()
            self._last_error = None
            self._failed = False
            self._error_count = self._ticks = 0
            self._started_at = time.monotonic()
            self._stopped_at = None
            self._thread = threading.Thread(target=self._run_loop,
                                            name=f"pokebot.{self.name}", daemon=True)
            self._running = True
            try:
                self._thread.start()
            except Exception as exc:
                self._running = False
                self._thread = None
                self._failed = True
                self._last_error = exc
                self._stopped_at = time.monotonic()
                self.log.exception("thread start failed")
                return False
            self.log.info("module started (interval=%.3fs)", self._interval)
            return True

    def stop(self, timeout: float = 5.0) -> bool:
        if not math.isfinite(timeout) or timeout < 0:
            raise ValueError("timeout must be finite and >= 0")
        with self._lock:
            self._stop_event.set()
            thread = self._thread
        if thread is None:
            return True
        if thread is threading.current_thread():
            # Requested from a hook: let the worker's finally perform cleanup.
            return False
        thread.join(timeout)
        if thread.is_alive():
            self.log.warning("stop timeout after %.3fs; worker still running", timeout)
            return False
        return True

    def enable(self) -> None:
        with self._lock:
            if not self._enabled:
                self._enabled = True
                self.log.info("module enabled")

    def disable(self) -> None:
        with self._lock:
            if self._enabled:
                self._enabled = False
                self.log.info("module disabled")

    def toggle(self) -> bool:
        with self._lock:
            self._enabled = not self._enabled
            self.log.info("module %s", "enabled" if self._enabled else "disabled")
            return self._enabled

    def _run_loop(self) -> None:
        try:
            self.setup()
            while not self._stop_event.is_set():
                started = time.monotonic()
                if self.is_enabled:
                    try:
                        self.tick()
                    except Exception as exc:
                        with self._lock:
                            self._error_count += 1
                            self._last_error = exc
                            fatal = bool(self.max_errors and self._error_count >= self.max_errors)
                            if fatal:
                                self._failed = True
                        self.log.exception("tick failed (%d consecutive errors)", self._error_count)
                        if fatal:
                            self._stop_event.set()
                            break
                    else:
                        with self._lock:
                            self._ticks += 1
                            self._error_count = 0
                            self._last_error = None
                self._stop_event.wait(max(0.0, self.interval - (time.monotonic() - started)))
        except BaseException as exc:
            with self._lock:
                self._failed = True
                self._last_error = exc
            self.log.exception("worker/setup failed")
        finally:
            self._stop_event.set()
            try:
                self.teardown()
            except BaseException as exc:
                with self._lock:
                    self._failed = True
                    self._last_error = exc
                self.log.exception("teardown failed")
            finally:
                with self._lock:
                    self._running = False
                    self._stopped_at = time.monotonic()
                self.log.info("module stopped (ticks=%d, errors=%d)", self._ticks, self._error_count)

    def read(self, key: str) -> Optional[Any]:
        return self.offsets.read(self.memory, key)

    def write(self, key: str, value: Any) -> bool:
        return self.offsets.write(self.memory, key, value)

    def entry(self, key: str) -> Optional[OffsetEntry]:
        return self.offsets.find(key)

    def setup(self) -> None:
        """Optional initialization on the worker, once per start."""

    def teardown(self) -> None:
        """Optional cleanup on the worker, once per exit (even setup failure)."""

    @abstractmethod
    def tick(self) -> None:
        """One short cooperative tick; check stop_event during longer operations."""

    def __repr__(self) -> str:
        s = self.stats
        return (f"<{type(self).__name__} name={self.name!r} state={s['state']} "
                f"ticks={s['ticks']} interval={s['interval_s']}s>")
