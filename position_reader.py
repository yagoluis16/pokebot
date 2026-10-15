"""Read configured XYZ without starting GUI, engine or input automation."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
import time

from memory import Process, Resolver

# CONFIG: module/RVA/offset/type/mask values live only in offsets.json.
PROJECT_DIR = Path(__file__).resolve().parent
OFFSETS_PATH = PROJECT_DIR / "offsets.json"
CONFIG_PATH = PROJECT_DIR / "config.json"
POLL_INTERVAL_SECONDS = 0.1


class PositionReadError(RuntimeError):
    pass


class PositionSession:
    def __init__(self, offsets_path=OFFSETS_PATH, config_path=CONFIG_PATH):
        with open(config_path, encoding="utf-8") as fh:
            config = json.load(fh)
        process_name = config.get("client", {}).get("process_name")
        if not isinstance(process_name, str) or not process_name.strip():
            raise ValueError("config.json: client.process_name is required")
        self.proc = Process(process_name, config=config.get("safety", {}))
        self.resolver = Resolver(self.proc, offsets_path=str(offsets_path), config_path=str(config_path))
        for axis in "xyz":
            name = "player." + axis
            entry = self.resolver.entries.get(name)
            if not entry or not entry["verified"]:
                raise ValueError(f"{name}: missing or not verified in offsets.json")

    def attach(self):
        if not self.proc.attach():
            raise PositionReadError(self.proc.last_error or f"cannot attach to {self.proc.process_name}")

    def close(self):
        self.proc.detach()

    def read_position(self):
        if self.proc.pm is None:
            self.attach()
        values = []
        for axis in "xyz":
            name = "player." + axis
            entry = self.resolver.entries[name]
            module = self.proc.modules.get(entry["module"].lower())
            if module is None:
                raise PositionReadError(f"{name}: module {entry['module']!r} is not loaded")
            if entry["base_rva"] >= module["size"]:
                raise PositionReadError(f"{name}: base_rva is outside module {entry['module']}")
            self.proc.last_error = None
            try:
                value = self.resolver.read_entry(name)
            except Exception as exc:
                raise PositionReadError(f"{name}: {exc}") from exc
            if value is None:
                reason = self.proc.last_error or "address resolution or memory read failed; client may have closed"
                raise PositionReadError(f"{name}: {reason}")
            values.append(value)
        return tuple(values)


def format_position(position):
    x, y, z = position
    return f"X={x} Y={y} Z={z}"


def poll_positions(session, interval=POLL_INTERVAL_SECONDS):
    if interval <= 0:
        raise ValueError("poll interval must be positive")
    try:
        while True:
            started = time.monotonic()
            try:
                print(format_position(session.read_position()), flush=True)
            except Exception as exc:
                print(f"Position unavailable: {exc}", file=sys.stderr, flush=True)
                # Reopen by name on the next iteration; refresh module base after ASLR/restart.
                session.close()
            time.sleep(max(0.0, interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        return 0
    finally:
        session.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offsets", type=Path, default=OFFSETS_PATH)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s")
    try:
        session = PositionSession(args.offsets, args.config)
    except Exception as exc:
        print(f"Position unavailable: {exc}", file=sys.stderr)
        return 1
    return poll_positions(session)


if __name__ == "__main__":
    raise SystemExit(main())
