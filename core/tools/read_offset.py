"""
core/tools/read_offset.py - Leitura avulsa de um offset para validação.

Uso:
    python -m core.tools.read_offset <processo> <chave>
    python -m core.tools.read_offset PokeAlliance_dx.exe player.hp
"""

from __future__ import annotations
import argparse
import logging
import sys

from core import MemoryReader, load_offsets


def main() -> int:
    p = argparse.ArgumentParser(prog="read_offset")
    p.add_argument("process", help="Nome ou PID do processo alvo")
    p.add_argument("key", help="Chave do offset (ex: player.hp)")
    p.add_argument("--offsets", default="offsets.json")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        target = int(args.process)
    except ValueError:
        target = args.process

    offsets = load_offsets(args.offsets)

    with MemoryReader(target) as mem:
        if not mem.is_attached:
            print(f"FALHA ao anexar: {mem.last_error}", file=sys.stderr)
            return 2

        entry = offsets.find(args.key)
        if entry is None:
            print(f"Chave não encontrada: {args.key}", file=sys.stderr)
            return 3

        addr = mem.resolve_entry_address(entry.to_reader_dict())
        print(f"Entrada: {entry}")
        print(f"Endereço resolvido: {hex(addr) if addr else 'None'}")

        value = offsets.read(mem, args.key)
        print(f"Valor de '{args.key}': {value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

