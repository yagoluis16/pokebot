# pokebot/__main__.py
"""Entry point for the PKA Bot."""

from __future__ import annotations
import sys
import argparse

from gui.main import main as gui_main
from context import get_context
from engine import create_engine
from memory import Process, Resolver


def run_bot(config_path: str = None):
    """Run the bot headless (no GUI)."""
    ctx = get_context(config_path)

    proc_name = ctx.get("client", "process_name", default="PokeAlliance_dx.exe")
    proc = Process(proc_name, config=ctx.config.get("safety", {}))
    if not proc.attach():
        print("Failed to attach to process")
        return 1

    resolver = Resolver(proc, offsets_path="offsets.json", config_path=config_path)
    engine = create_engine(config_path=config_path, resolver=resolver)

    print("Starting PKA Bot (headless)... Press Ctrl+C to stop.")
    engine.start()

    try:
        import time
        while not ctx.is_stopped():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        engine.stop()
        proc.detach()
    return 0


def run_gui(config_path: str = None):
    """Run the bot with GUI."""
    return gui_main(config_path)


def main():
    parser = argparse.ArgumentParser(description="PKA Bot - PokeAlliance Assistant")
    parser.add_argument("--config", default="config.json", help="Config file path")
    parser.add_argument("--headless", action="store_true", help="Run without GUI")
    parser.add_argument("--check", action="store_true", help="Run memory check and exit")
    args = parser.parse_args()

    if args.check:
        from memory import main as mem_main
        return mem_main(["--check", "--config", args.config])

    if args.headless:
        return run_bot(args.config)
    else:
        return run_gui(args.config)


if __name__ == "__main__":
    sys.exit(main())