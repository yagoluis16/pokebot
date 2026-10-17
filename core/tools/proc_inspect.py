"""Inspect matching processes without writing to their memory."""
import argparse
import sys
from core.memory import MemoryReader


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("keyword", nargs="?", default="PokeAlliance")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args(argv)
    try:
        processes = MemoryReader.list_candidate_processes(args.keyword)
    except OSError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if not processes:
        print(f"Nenhum processo encontrado para: {args.keyword}")
        return 0
    failed = False
    for process in processes:
        print(f"PID         : {process['pid']}")
        print(f"Nome        : {process['name']}")
        print(f"Título      : {process['title'] or '(sem título)'}")
        print(f"Caminho     : {process['path'] or '(indisponível)'}")
        with MemoryReader(process["pid"]) as memory:
            if not memory.is_attached:
                print(f"Módulos/Base: indisponíveis: {memory.last_error}")
                failed = True
            else:
                names = list(memory.modules)
                print(f"Módulos     : {len(names)}")
                for name in names if args.full else names[:5]:
                    print(f"  {name}")
                print(f"Base        : 0x{memory.main_module_base:X}")
        print()
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
