"""
core/tools/pointer_scan.py - Scanner de pointer chains.

Dado um endereço-alvo dinâmico (ex: HP do player), encontra cadeias
de ponteiros estáveis até o módulo principal.

Algoritmo:
  1. Escaneia todas as regiões legíveis buscando valores u64 V tais
     que V + small_offset == target, para small_offset em [0, max_offset].
  2. Cada match (ponteiro_addr, offset) é candidato nível 1.
  3. Se ponteiro_addr já está dentro de um módulo → chain estática:
     [module+rva, steps=[offset], terminal=0].
  4. Senão, recursivamente busca QUEM aponta pro ponteiro_addr, até
     max_depth, e acumula os offsets na chain.

Formato da chain no schema:
    base+rva -> (read_ptr, +step1) -> (read_ptr, +step2) -> ... -> alvo
    steps = [step1, step2, ..., stepN]  (na ordem de resolução)
    terminal = 0  (o último offset já está dentro do último step)
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import logging
import struct
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from core import MemoryReader

log = logging.getLogger("pokebot.tools.pointer_scan")

MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100

READABLE_PROTECTIONS = 0x02 | 0x04 | 0x20 | 0x40
WRITABLE_PROTECTIONS = 0x04 | 0x08 | 0x40 | 0x80

MIN_VALID_PTR = 0x10000
MAX_VALID_PTR = 0x7FFFFFFFFFFF


class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
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
kernel32.VirtualQueryEx.argtypes = [
    wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t
]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t


def iter_regions(mem: MemoryReader, *, writable_only: bool = False) -> Iterator[Tuple[int, int]]:
    """Itera regiões legíveis (ou graváveis) via VirtualQueryEx."""
    addr = 0
    while addr < MAX_VALID_PTR:
        mbi = MEMORY_BASIC_INFORMATION64()
        res = kernel32.VirtualQueryEx(
            mem.handle,
            ctypes.c_void_p(addr),
            ctypes.byref(mbi),
            ctypes.sizeof(mbi),
        )
        if res == 0:
            addr += 0x1000
            continue

        base = mbi.BaseAddress
        size = mbi.RegionSize
        if size == 0:
            addr += 0x1000
            continue

        # FIX #3: avança pela região inteira, não 4 KB por consulta.
        # Regiões enormes são comuns; pulamos usando o próximo base.

        if (mbi.State == MEM_COMMIT
                and not (mbi.Protect & PAGE_GUARD)
                and not (mbi.Protect & PAGE_NOACCESS)):
            prot = mbi.Protect & 0xFF
            allowed = WRITABLE_PROTECTIONS if writable_only else READABLE_PROTECTIONS
            if prot & allowed:
                yield (base, size)

        addr = base + size


def find_containing_module(mem: MemoryReader, address: int) -> Optional[Tuple[str, int]]:
    """Retorna (nome_módulo, rva) se o endereço pertence a um módulo mapeado."""
    for name, info in mem.modules.items():
        base = info["base"]
        size = info["size"]
        if base <= address < base + size:
            return (name, address - base)
    return None


def scan_level1(
    mem: MemoryReader,
    target: int,
    max_offset: int,
    chunk_size: int = 4 * 1024 * 1024,
) -> List[Tuple[int, int]]:
    """Encontra (ponteiro_addr, offset) com read_u64(addr) + offset == target."""
    hits: List[Tuple[int, int]] = []
    struct_u64 = struct.Struct("<Q")
    low_bound = target - max_offset if target > max_offset else 0
    high_bound = target

    t0 = time.time()
    total_scanned = 0

    for (base, size) in iter_regions(mem, writable_only=False):
        offset_in_region = 0
        while offset_in_region < size:
            to_read = min(chunk_size, size - offset_in_region)
            chunk = mem.read_bytes(base + offset_in_region, to_read)
            if not chunk or len(chunk) < 8:
                offset_in_region += to_read
                continue

            total_scanned += len(chunk)
            idx = 0
            end = len(chunk) - 7
            while idx < end:
                value = struct_u64.unpack_from(chunk, idx)[0]
                if low_bound <= value <= high_bound:
                    diff = target - value
                    hits.append((base + offset_in_region + idx, diff))
                idx += 8

            offset_in_region += to_read

    log.info(
        "level1: %d candidatos em %.2fs (%.1f MB varridos)",
        len(hits), time.time() - t0, total_scanned / 1e6,
    )
    return hits


def scan_for_parents(
    mem: MemoryReader,
    children: List[int],
    max_offset: int,
    chunk_size: int = 4 * 1024 * 1024,
) -> List[Tuple[int, int, int]]:
    """Para cada child, acha (parent_addr, offset) com read_u64(parent)+offset==child."""
    children_set = set(children)
    children_sorted = sorted(children_set)
    if not children_sorted:
        return []
    min_child = children_sorted[0]
    max_child = children_sorted[-1]
    low_bound = min_child - max_offset if min_child > max_offset else 0
    high_bound = max_child

    # Só testamos children "próximos" do value encontrado, então:
    # para cada u64 V em [low_bound, high_bound], testamos se V + off = algum child
    # com off em [0, max_offset]. Como children_sorted é ordenado, dá pra binsearch.

    import bisect

    hits: List[Tuple[int, int, int]] = []
    struct_u64 = struct.Struct("<Q")

    for (base, size) in iter_regions(mem, writable_only=False):
        offset_in_region = 0
        while offset_in_region < size:
            to_read = min(chunk_size, size - offset_in_region)
            chunk = mem.read_bytes(base + offset_in_region, to_read)
            if not chunk or len(chunk) < 8:
                offset_in_region += to_read
                continue

            idx = 0
            end = len(chunk) - 7
            while idx < end:
                value = struct_u64.unpack_from(chunk, idx)[0]
                if low_bound <= value <= high_bound:
                    # Queremos child c com c >= value e c - value <= max_offset
                    lo = bisect.bisect_left(children_sorted, value)
                    if lo < len(children_sorted):
                        c = children_sorted[lo]
                        if c - value <= max_offset:
                            hits.append((
                                base + offset_in_region + idx,
                                c - value,
                                c,
                            ))
                idx += 8

            offset_in_region += to_read

    return hits


def format_static_chain(
    mem: MemoryReader,
    chain: List[Tuple[int, int]],
) -> Optional[Dict[str, Any]]:
    """
    Se chain[0][0] (o ponteiro mais externo) está em um módulo, retorna
    o dicionário pronto pro schema.

    chain = [(addr_0, off_0), (addr_1, off_1), ..., (addr_n, off_n)]
      onde read_u64(addr_i) + off_i = addr_{i+1} para i<n, e
      read_u64(addr_n) + off_n = target.

    FIX #2: steps recebe TODOS os offsets na ordem da chain.
    terminal = 0 (não sobra offset depois do último deref).
    """
    if not chain:
        return None
    outermost_addr = chain[0][0]
    mod_info = find_containing_module(mem, outermost_addr)
    if mod_info is None:
        return None
    module_name, rva = mod_info
    steps = [off for (_, off) in chain]
    return {
        "module": module_name,
        "rva": rva,
        "steps": steps,
        "terminal": 0,
        "level": len(chain),
    }


def build_chains(
    mem: MemoryReader,
    target: int,
    max_offset: int,
    max_depth: int,
) -> List[Dict[str, Any]]:
    print(f"[1/{max_depth}] Escaneando ponteiros nível 1 para 0x{target:X}...")
    level1 = scan_level1(mem, target, max_offset)
    print(f"          {len(level1)} ponteiros nível 1")

    static_chains: List[Dict[str, Any]] = []
    entries: List[Dict[str, Any]] = []

    # FIX #1: verifica static já no nível 1.
    for (ptr_addr, offset) in level1:
        chain = [(ptr_addr, offset)]
        static = format_static_chain(mem, chain)
        if static is not None:
            static_chains.append(static)
        else:
            entries.append({"addr": ptr_addr, "chain": chain})

    print(f"          {len(static_chains)} chains estáticas nível 1; "
          f"{len(entries)} entradas para recursão")

    if not entries:
        return static_chains

    visited_addrs: set = set()

    for depth in range(2, max_depth + 1):
        if not entries:
            break

        current_addrs = list({e["addr"] for e in entries} - visited_addrs)
        if not current_addrs:
            break
        visited_addrs.update(current_addrs)

        print(f"[{depth}/{max_depth}] Escaneando pais de {len(current_addrs)} endereços...")
        parents = scan_for_parents(mem, current_addrs, max_offset)
        print(f"          {len(parents)} ponteiros pais encontrados")

        if not parents:
            break

        addr_to_chains: Dict[int, List[List[Tuple[int, int]]]] = {}
        for e in entries:
            addr_to_chains.setdefault(e["addr"], []).append(e["chain"])

        next_entries: List[Dict[str, Any]] = []
        seen: set = set()

        for (parent_addr, offset, child_addr) in parents:
            for chain in addr_to_chains.get(child_addr, []):
                new_chain = [(parent_addr, offset)] + chain
                static = format_static_chain(mem, new_chain)
                if static is not None:
                    static_chains.append(static)
                else:
                    key = (parent_addr, tuple(new_chain))
                    if key in seen:
                        continue
                    seen.add(key)
                    next_entries.append({"addr": parent_addr, "chain": new_chain})

        print(f"          {len(static_chains)} chains estáticas acumuladas; "
              f"{len(next_entries)} entradas para próximo nível")
        entries = next_entries

        if len(static_chains) > 50000:
            print("      limite de 50k chains estáticas atingido, parando")
            break

    return static_chains


def _parse_hex(value: str) -> int:
    try:
        return int(value, 0)
    except ValueError:
        return int(value)


def main() -> int:
    p = argparse.ArgumentParser(prog="pointer_scan")
    p.add_argument("process", help="Nome ou PID do processo")
    p.add_argument("--target", required=True, type=_parse_hex,
                   help="Endereço-alvo em hex")
    p.add_argument("--max-offset", type=_parse_hex, default=0x2000,
                   help="Offset máximo por passo (padrão 0x2000)")
    p.add_argument("--max-depth", type=int, default=4,
                   help="Profundidade máxima da chain (padrão 4)")
    p.add_argument("--save", help="Salvar chains em JSON")
    p.add_argument("--top", type=int, default=20,
                   help="Chains a imprimir (padrão 20)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        target_proc: Any = int(args.process)
    except ValueError:
        target_proc = args.process

    print(f"Anexando a {args.process}...")
    with MemoryReader(target_proc) as mem:
        if not mem.is_attached:
            print(f"FALHA: {mem.last_error}", file=sys.stderr)
            return 2

        print(f"Base do módulo principal: 0x{mem.main_module_base:X}")
        print(f"Alvo: 0x{args.target:X}")
        print(f"Max offset: 0x{args.max_offset:X}, Max depth: {args.max_depth}")

        chains = build_chains(
            mem,
            target=args.target,
            max_offset=args.max_offset,
            max_depth=args.max_depth,
        )

    print(f"\n=== {len(chains)} chains estáticas encontradas ===")

    chains_sorted = sorted(chains, key=lambda c: (c["level"], c["terminal"], c["rva"]))

    for i, c in enumerate(chains_sorted[:args.top]):
        steps_str = " -> ".join(f"+0x{s:X}" for s in c["steps"]) if c["steps"] else "-"
        print(
            f"[{i+1}] level={c['level']} "
            f"{c['module']}+0x{c['rva']:X} | steps=[{steps_str}] | terminal=+0x{c['terminal']:X}"
        )

    if args.save:
        Path(args.save).write_text(json.dumps(chains_sorted, indent=2))
        print(f"\nSalvo em {args.save}")

    if not chains:
        print(
            "\nNenhuma chain. Tente:\n"
            "  - Aumentar --max-offset (0x4000, 0x8000)\n"
            "  - Aumentar --max-depth (5, 6)\n"
            "  - Verificar se o alvo ainda é o HP atual (o endereço muda)\n"
        )
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
