# pokebot/context.py
"""Shared runtime context: config, stop event, stats, logging."""

from __future__ import annotations
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memory import setup_logging, _normalize_cfg_path, DEFAULT_CONFIG_PATH

log = logging.getLogger("pokebot.context")


@dataclass
class BotContext:
    """Single source of truth for runtime state shared across all modules."""

    config_path: str = DEFAULT_CONFIG_PATH
    config: dict = field(default_factory=dict)
    stop_event: threading.Event = field(default_factory=threading.Event)
    pause_event: threading.Event = field(default_factory=threading.Event)
    stats: dict = field(default_factory=lambda: {
        "heals": 0,
        "mana_heals": 0,
        "food_eaten": 0,
        "creatures_killed": 0,
        "items_looted": 0,
        "waypoints_reached": 0,
        "stuck_recoveries": 0,
        "deaths": 0,
        "disconnects": 0,
        "uptime_start": None,
    })
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def __post_init__(self):
        self.reload_config()
        if not self.pause_event.is_set():
            self.pause_event.set()  # start unpaused

    def reload_config(self):
        with self._lock:
            p = _normalize_cfg_path(self.config_path)
            try:
                with open(p, "r", encoding="utf-8") as fh:
                    self.config = json.load(fh)
            except Exception as exc:
                log.error("failed to load config %s: %s", p, exc)
                self.config = {}

    def get(self, *keys, default=None):
        with self._lock:
            cur = self.config
            for k in keys:
                if not isinstance(cur, dict):
                    return default
                cur = cur.get(k)
                if cur is None:
                    return default
            return cur if cur is not None else default

    def set(self, value, *keys):
        with self._lock:
            cur = self.config
            for k in keys[:-1]:
                if k not in cur or not isinstance(cur[k], dict):
                    cur[k] = {}
                cur = cur[k]
            cur[keys[-1]] = value

    def save_config(self):
        with self._lock:
            p = _normalize_cfg_path(self.config_path)
            try:
                with open(p, "w", encoding="utf-8") as fh:
                    json.dump(self.config, fh, indent=2)
            except Exception as exc:
                log.error("failed to save config %s: %s", p, exc)

    def is_stopped(self) -> bool:
        return self.stop_event.is_set()

    def is_paused(self) -> bool:
        return not self.pause_event.is_set()

    def pause(self):
        self.pause_event.clear()

    def resume(self):
        self.pause_event.set()

    def stop(self):
        self.stop_event.set()
        self.pause_event.set()  # unblock any waiting threads

    def wait_if_paused(self, timeout=None):
        """Block while paused. Returns True if still running, False if stopped."""
        while not self.stop_event.is_set() and self.is_paused():
            if not self.pause_event.wait(timeout=timeout or 0.1):
                continue
        return not self.stop_event.is_set()

    def inc_stat(self, key: str, delta: int = 1):
        with self._lock:
            self.stats[key] = self.stats.get(key, 0) + delta

    def get_stats(self) -> dict:
        with self._lock:
            return dict(self.stats)


# Global singleton
_CTX: BotContext | None = None


def get_context(config_path: str = DEFAULT_CONFIG_PATH) -> BotContext:
    global _CTX
    if _CTX is None:
        _CTX = BotContext(config_path=config_path)
        setup_logging(config_path)
    return _CTX


def reset_context():
    global _CTX
    if _CTX:
        _CTX.stop()
    _CTX = None