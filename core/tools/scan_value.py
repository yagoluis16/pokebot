"""
core/tools/scan_value.py - Scanner diferencial de valores na memória.

Uso:
    # 1ª passada: escaneia valor inicial (ex: HP=487)
    python -m core.tools.scan_value PokeAlliance_dx.exe --value 487 --type int32 --save scan1.json

    # Depois o valor muda (tome dano). 2ª passada:
    python -m core.tools.scan_value PokeAlliance_dx.exe --value 442 --type int32 --intersect scan1.json --save scan2.json

    # Repetir conforme necessário até sobrar poucos endereços. Ver resultado:
    python -m core.tools.scan_value --list scan2.json
"""

from __future__ import annotations
import argparse
import json
import logging
import struct
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core import MemoryReader

log = logging.getLogger("pokebot.tools.scan_value")

TYPE_FMT = {
    "int8": ("<b", 1),
    "uint8": ("<B", 1),
    "int16": ("<h", 2),
    "uint16": ("<H", 2),
    "int32": ("<i", 4),
    "uint32": ("<I", 4),
    "int64": ("<q", 8),
    "uint64": ("<Q", 8),
    "float32": ("<f", 4),
    "float64": ("<d", 8),
}


def iter_regions(mem: MemoryReader):
    """Itera regiões legíveis do processo via VirtualQueryEx."""
    import ctypes
    import ctypes.wintypes as wt

    MEM_COMMIT = 0x1000
    PAGE_NOACCESS = 0x01
    PAGE_GUARD = 0x100
    READABLE = 0x02 | 0x04 | 0x20 | 0x40

    class MBI64(ctypes.Structure):
        _fields_ = [
            ("BaseAddress", ctypes.c_ulonglong),
            ("AllocationBase", ctypes.c_ulonglong),
            ("AllocationProtect", wt.DWORD),
            ("__alignment1", wt.DWORD),
            ("RegionSize", ctypes.c_ulonglong),
            ("State", wt.DWORD),
            ("Protect", wt.DWORD),
            ("Type", wt.DWORD),
            ("__alignment2", wt.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
    kernel32.VirtualQueryEx.restype = ctypes.c_size_t

    addr = 0
    MAX_ADDR = 0x7FFFFFFFFFFF

    while addr < MAX_ADDR:
        mbi = MBI64()
        res = kernel32.VirtualQueryEx(
            mem.handle, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)
        )
        if res == 0:
            addr += 0x1000
            continue

        base = mbi.BaseAddress
        size = mbi.RegionSize
        if size == 0:
            addr += 0x1000
            continue

        if (mbi.State == MEM_COMMIT
                and not (mbi.Protect & PAGE_GUARD)
                and not (mbi.Protect & PAGE_NOACCESS)
                and (mbi.Protect & READABLE)):
            yield (base, size)

        addr = base + size


def scan_region(mem: MemoryReader, base: int, size: int, fmt: str, value: Any,
                chunk_size: int = 1024 * 1024) -> List[int]:
    """Escaneia região em chunks. Retorna endereços onde o valor bate."""
    hits: List[int] = []
    packer = struct.Struct(fmt)
    needle = packer.pack(value)
    step = len(needle)
    offset = 0

    while offset < size:
        to_read = min(chunk_size, size - offset)
        chunk = mem.read_bytes(base + offset, to_read)
        if not chunk:
            offset += to_read
            continue

        idx = 0
        end = len(chunk) - step + 1
        while idx < end:
            if chunk[idx:idx + step] == needle:
                hits.append(base + offset + idx)
            idx += 1
        offset += to_read

    return hits


def _parse_value(value: str):
    try:
        return int(value, 0)
    except ValueError:
        return float(value)


def main() -> int:
    p = argparse.ArgumentParser(prog="scan_value")
    p.add_argument("process", nargs="?", help="Nome ou PID do processo")
    p.add_argument("--value", type=_parse_value,
                   help="Valor a procurar (int, 0x hex, ou float)")
    p.add_argument("--type", default="int32", choices=list(TYPE_FMT.keys()))
    p.add_argument("--save", help="Salvar resultados neste arquivo JSON")
    p.add_argument("--intersect", help="Cruzar com resultados de JSON anterior")
    p.add_argument("--list", dest="list_file", help="Listar endereços de um JSON salvo")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Modo --list
    if args.list_file:
        data = json.loads(Path(args.list_file).read_text())
        addrs = data.get("addresses", [])
        print(f"Total: {len(addrs)} endereços")
        for a in addrs:
            print(f"  0x{a:X}")
        return 0

    if not args.process or args.value is None:
        print("Precisa de <process> e --value", file=sys.stderr)
        return 2

    try:
        target: Any = int(args.process)
    except ValueError:
        target = args.process

    fmt, _ = TYPE_FMT[args.type]

    print(f"[1/3] Anexando a {args.process}...")
    with MemoryReader(target) as mem:
        if not mem.is_attached:
            print(f"FALHA: {mem.last_error}", file=sys.stderr)
            return 2

        print(f"[2/3] Escaneando {args.type} == {args.value}...")
        t0 = time.time()
        hits: List[int] = []
        scanned = 0

        for (base, size) in iter_regions(mem):
            region_hits = scan_region(mem, base, size, fmt, args.value)
            hits.extend(region_hits)
            scanned += size
            if len(hits) > 50000:
                print("  limite de 50k hits atingido, parando")
                break

        elapsed = time.time() - t0
        print(f"[3/3] {len(hits)} hits em {elapsed:.2f}s ({scanned / 1e6:.1f} MB varridos)")

        # Interseção
        if args.intersect:
            prev = json.loads(Path(args.intersect).read_text())
            prev_set = set(prev.get("addresses", []))
            hits = [a for a in hits if a in prev_set]
            print(f"  após interseção: {len(hits)} endereços")

        # Salvar
        if args.save:
            Path(args.save).write_text(json.dumps({
                "value": args.value,
                "type": args.type,
                "count": len(hits),
                "addresses": hits,
            }, indent=2))
            print(f"  salvo em {args.save}")

        # Preview
        for a in hits[:20]:
            val = mem.read_bytes(a, TYPE_FMT[args.type][1])
            if val:
                try:
                    decoded = struct.unpack(fmt, val)[0]
                    print(f"    0x{a:X} = {decoded}")
                except Exception:
                    pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
