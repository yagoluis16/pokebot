# pokebot/inputbus.py
"""Serialized input bus with safety limits and per-module queue."""

from __future__ import annotations
import logging
import queue
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

import win32api
import win32con
import win32gui

from context import get_context
from wininput import send_scancode, vk_to_scancode, send_mouse_button, sendinput_selftest

log = logging.getLogger("pokebot.inputbus")


class InputType(Enum):
    KEY_DOWN = "key_down"
    KEY_UP = "key_up"
    KEY_PRESS = "key_press"  # down + up with delay
    MOUSE_CLICK = "mouse_click"
    MOUSE_MOVE = "mouse_move"


@dataclass
class InputRequest:
    type: InputType
    # key press: vk or scancode
    code: int = 0
    # mouse: x, y (client-relative)
    x: int = 0
    y: int = 0
    # key_press hold time
    hold_ms: int = 50
    # priority: lower = higher priority
    priority: int = 10
    # callback on completion
    callback: Optional[Callable[[], None]] = None
    # module name for debugging
    module: str = "unknown"


class InputBus:
    """
    Single-threaded input serializer. All modules submit requests;
    a worker thread executes them with enforced minimum interval.
    """

    def __init__(self):
        self._ctx = get_context()
        self._queue: queue.PriorityQueue[tuple[int, int, InputRequest]] = queue.PriorityQueue()
        self._worker: threading.Thread | None = None
        self._running = False
        self._seq = 0
        self._lock = threading.Lock()
        self._last_input_time = 0.0
        self._hwnd = None
        self._hwnd_lock = threading.Lock()

    def start(self):
        if self._running:
            return
        self._running = True
        self._worker = threading.Thread(target=self._run, name="InputBus", daemon=True)
        self._worker.start()
        log.info("InputBus started")

    def stop(self):
        self._running = False
        if self._worker:
            self._worker.join(timeout=2.0)
            self._worker = None
        log.info("InputBus stopped")

    def submit(self, req: InputRequest) -> bool:
        """Enqueue an input request. Returns False if queue full."""
        max_q = self._ctx.get("safety_limits", "input_bus_queue_max", default=32)
        if self._queue.qsize() >= max_q:
            log.warning("InputBus queue full (%d), dropping request from %s", max_q, req.module)
            return False
        with self._lock:
            self._seq += 1
            seq = self._seq
        self._queue.put((req.priority, seq, req))
        return True

    def press_key(self, code: int, hold_ms: int = 50, priority: int = 10, module: str = "unknown") -> bool:
        return self.submit(InputRequest(
            type=InputType.KEY_PRESS,
            code=code,
            hold_ms=hold_ms,
            priority=priority,
            module=module,
        ))

    def key_down(self, code: int, priority: int = 10, module: str = "unknown") -> bool:
        return self.submit(InputRequest(
            type=InputType.KEY_DOWN,
            code=code,
            priority=priority,
            module=module,
        ))

    def key_up(self, code: int, priority: int = 10, module: str = "unknown") -> bool:
        return self.submit(InputRequest(
            type=InputType.KEY_UP,
            code=code,
            priority=priority,
            module=module,
        ))

    def click(self, x: int, y: int, priority: int = 10, module: str = "unknown") -> bool:
        return self.submit(InputRequest(
            type=InputType.MOUSE_CLICK,
            x=x,
            y=y,
            priority=priority,
            module=module,
        ))

    def _get_hwnd(self):
        with self._hwnd_lock:
            if self._hwnd and win32gui.IsWindow(self._hwnd):
                return self._hwnd
            pattern = self._ctx.get("client", "window_title_pattern", default="PokeAlliance")
            def enum_cb(hwnd, _):
                if win32gui.IsWindowVisible(hwnd):
                    title = win32gui.GetWindowText(hwnd)
                    if pattern.lower() in title.lower():
                        return hwnd
                return None
            result = []
            win32gui.EnumWindows(lambda h, _: result.append(h) if enum_cb(h, _) else None, None)
            if result:
                self._hwnd = result[0]
            return self._hwnd

    def _focus_client(self):
        if not self._ctx.get("client", "focus_before_input", default=True):
            return
        hwnd = self._get_hwnd()
        if hwnd:
            try:
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(self._ctx.get("client", "refocus_delay_ms", default=120) / 1000.0)
            except Exception as exc:
                log.debug("focus failed: %s", exc)

    def _send_scancode(self, scancode: int, down: bool):
        """SendInput with KEYEVENTF_SCANCODE."""
        send_scancode(scancode, down)

    def _vk_to_scancode(self, vk: int) -> int:
        return vk_to_scancode(vk)

    def _execute(self, req: InputRequest):
        min_interval = self._ctx.get("safety_limits", "min_interval_between_inputs_ms", default=25) / 1000.0
        now = time.monotonic()
        wait = self._last_input_time + min_interval - now
        if wait > 0:
            time.sleep(wait)

        self._focus_client()

        try:
            if req.type == InputType.KEY_PRESS:
                sc = req.code if req.code > 255 else self._vk_to_scancode(req.code)
                self._send_scancode(sc, True)
                try:
                    time.sleep(req.hold_ms / 1000.0)
                finally:
                    self._send_scancode(sc, False)
            elif req.type == InputType.KEY_DOWN:
                sc = req.code if req.code > 255 else self._vk_to_scancode(req.code)
                self._send_scancode(sc, True)
            elif req.type == InputType.KEY_UP:
                sc = req.code if req.code > 255 else self._vk_to_scancode(req.code)
                self._send_scancode(sc, False)
            elif req.type == InputType.MOUSE_CLICK:
                hwnd = self._get_hwnd()
                if hwnd:
                    # Convert client-relative to screen
                    rect = win32gui.GetClientRect(hwnd)
                    client_x, client_y = win32gui.ClientToScreen(hwnd, (req.x, req.y))
                    win32api.SetCursorPos((client_x, client_y))
                    time.sleep(0.01)
                    send_mouse_button(True)
                    try:
                        time.sleep(0.02)
                    finally:
                        send_mouse_button(False)
            else:
                log.warning("unknown input type: %s", req.type)
        except Exception as exc:
            log.error("input execution failed: %s", exc)
        finally:
            self._last_input_time = time.monotonic()
            if req.callback:
                try:
                    req.callback()
                except Exception:
                    pass

    def _run(self):
        while self._running:
            try:
                _, _, req = self._queue.get(timeout=0.1)
                if self._ctx.is_stopped():
                    break
                self._execute(req)
            except queue.Empty:
                continue
            except Exception as exc:
                log.exception("InputBus worker error: %s", exc)


# Singleton
_BUS: InputBus | None = None


def get_bus() -> InputBus:
    global _BUS
    if _BUS is None:
        _BUS = InputBus()
    return _BUS


def shutdown_bus():
    global _BUS
    if _BUS:
        _BUS.stop()
        _BUS = None
