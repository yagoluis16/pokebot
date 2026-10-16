"""Run a lifecycle-only demo: python -m modules._example.

--process opts into real read-only HP polling via the existing core API.
The default demo neither opens a process nor sends input events.
"""
from __future__ import annotations

import argparse
import logging
import math
from pathlib import Path
import sys
import time

from modules.base import AutomationModule, ModuleState


class ExampleModule(AutomationModule):
    def __init__(self, memory, offsets, *, interval=1.0, log_payload=False):
        self.log_payload = log_payload
        self._local_counter = 0
        super().__init__(memory, offsets, name="example", interval=interval)

    def setup(self):
        self._local_counter = 0
        self.log.info("setup()")

    def tick(self):
        self._local_counter += 1
        self.log.info("tick #%d (uptime=%.1fs)", self._local_counter, self.stats["uptime_s"])
        if self.log_payload:
            hp = self.read("player.hp")
            if hp is not None:
                self.log.info("player.hp=%s", hp)
            else:
                self.log.warning("player.hp unavailable")

    def teardown(self):
        self.log.info("teardown() - local ticks=%d", self._local_counter)


class _NullMemory:
    def read_entry(self, entry):
        return None

    def write_entry(self, entry, value):
        return False


class _NullOffsets:
    def read(self, memory, key):
        return None

    def write(self, memory, key, value):
        return False

    def find(self, key):
        return None


def _demo_run(seconds, interval):
    mod = ExampleModule(_NullMemory(), _NullOffsets(), interval=interval)
    print(f"--- start (seconds={seconds:g}, interval={interval:g}s) ---", flush=True)
    if not mod.start():
        return 1
    started = time.monotonic()
    phase = 0
    try:
        while not mod.stop_event.is_set():
            elapsed = time.monotonic() - started
            if elapsed >= seconds:
                break
            if phase == 0 and elapsed >= seconds / 3:
                mod.disable()
                phase = 1
            if phase == 1 and elapsed >= 2 * seconds / 3:
                mod.enable()
                phase = 2
            mod.stop_event.wait(min(0.05, seconds - elapsed))
    except KeyboardInterrupt:
        pass
    finally:
        print(f"--- stop --- stats before: {mod.stats}", flush=True)
        ok = mod.stop(timeout=5.0)
        print(f"stop() -> {ok}", flush=True)
        print(f"stats final: {mod.stats}", flush=True)
    return 0 if ok and mod.state != ModuleState.ERROR else 2


def _real_run(process_name, offsets_path, seconds, interval):
    from core import MemoryReader, load_offsets
    offsets = load_offsets(offsets_path, Path(offsets_path).with_name("offsets.schema.json"))
    with MemoryReader(process_name) as memory:
        if not memory.is_attached:
            print(f"attach failed: {memory.last_error}", flush=True)
            return 3
        mod = ExampleModule(memory, offsets, interval=interval, log_payload=True)
        if not mod.start():
            return 1
        try:
            mod.stop_event.wait(seconds)
        except KeyboardInterrupt:
            pass
        finally:
            ok = mod.stop(timeout=5.0)
            print(f"stats final: {mod.stats}", flush=True)
        return 0 if ok and mod.state != ModuleState.ERROR else 2


def _cli():
    parser = argparse.ArgumentParser(prog="modules._example", description=__doc__)
    parser.add_argument("--process", default=None)
    parser.add_argument("--offsets", default=str(Path(__file__).resolve().parents[1] / "offsets.json"))
    parser.add_argument("--seconds", type=float, default=6.0)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    if not math.isfinite(args.seconds) or args.seconds <= 0:
        parser.error("--seconds must be finite and > 0")
    if not math.isfinite(args.interval) or args.interval <= 0:
        parser.error("--interval must be finite and > 0")
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    if args.process:
        return _real_run(args.process, args.offsets, args.seconds, args.interval)
    return _demo_run(args.seconds, args.interval)


if __name__ == "__main__":
    raise SystemExit(_cli())
