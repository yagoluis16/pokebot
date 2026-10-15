"""One-shot read validation: py validate_position.py."""
import argparse
import logging
from pathlib import Path
import sys

from position_reader import CONFIG_PATH, OFFSETS_PATH, PositionSession, format_position


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offsets", type=Path, default=OFFSETS_PATH)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s")
    session = None
    try:
        session = PositionSession(args.offsets, args.config)
        position = session.read_position()
        session.proc.last_error = None
        hp = session.resolver.read_entry("player.hp")
        if hp is None:
            raise RuntimeError("player.hp: " + (session.proc.last_error or "address resolution or memory read failed"))
        session.proc.last_error = None
        hp_max = session.resolver.read_entry("player.hp_max")
        if hp_max is None:
            raise RuntimeError("player.hp_max: " + (session.proc.last_error or "address resolution or memory read failed"))
        session.proc.last_error = None
        pokemon_hp = session.resolver.read_entry("pokemon.hp_percent")
        if pokemon_hp is None:
            raise RuntimeError("pokemon.hp_percent: " + (session.proc.last_error or "active Pokemon pointer or value unavailable"))
        if not 0 <= pokemon_hp <= 100:
            raise RuntimeError(f"pokemon.hp_percent: out of range: {pokemon_hp}")
        print(f"{format_position(position)} HP={hp}/{hp_max} POKEMON_HP={pokemon_hp}%")
        print("OK")
        return 0
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    finally:
        if session is not None:
            session.close()


if __name__ == "__main__":
    raise SystemExit(main())
