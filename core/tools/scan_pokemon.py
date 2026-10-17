"""Scan diferencial guiado de slots e HP de pokémons, sem enviar input.

Os índices 0-based e 1-based são hipóteses testadas separadamente.
Use --hp para informar HP absoluto e máximo em cada etapa.
"""

from __future__ import annotations

import argparse
from array import array
import ctypes
from ctypes import wintypes
from itertools import groupby
import json
import logging
from pathlib import Path
import struct
import sys

from core import MemoryReader
from core.tools.scan_value import iter_regions
from core.tools.pointer_scan import build_chains

CHUNK_SIZE = 4 * 1024 * 1024
PAGE_SIZE = 4096


def parse_sequence(text):
    try:
        slots = [int(part.strip()) for part in text.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use slots separados por vírgula") from exc
    if len(slots) < 4 or any(slot not in range(1, 7) for slot in slots):
        raise argparse.ArgumentTypeError("informe ao menos quatro slots entre 1 e 6")
    if slots[0] != slots[-1] or len(set(slots)) < 3:
        raise argparse.ArgumentTypeError("visite três slots e termine no slot inicial")
    return slots


def ensure_alive(memory):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    code = wintypes.DWORD()
    if not kernel.GetExitCodeProcess(memory.handle, ctypes.byref(code)) or code.value != 259:
        raise RuntimeError("o processo terminou; descarte os candidatos e reinicie o scan")


def readable_chunks(memory, regions, chunk_size=CHUNK_SIZE):
    """Tenta novamente por página quando um bloco grande não pode ser lido."""
    for base, size in regions:
        for offset in range(0, size, chunk_size):
            address = base + offset
            count = min(chunk_size, size - offset)
            raw = memory.read_bytes(address, count)
            if raw is not None and len(raw) == count:
                yield address, raw, 0
                continue
            for page_offset in range(0, count, PAGE_SIZE):
                page_address = address + page_offset
                page_count = min(PAGE_SIZE, count - page_offset)
                raw = memory.read_bytes(page_address, page_count)
                if raw is not None and len(raw) == page_count:
                    yield page_address, raw, 0
                else:
                    yield page_address, b"", page_count


def initial_scan(memory, expected, formats, max_candidates=10_000_000, regions=None,
                 chunk_size=CHUNK_SIZE):
    candidates = {field: array("Q") for field in expected}
    needles = {field: struct.pack(formats[field], value) for field, value in expected.items()}
    scanned = failed = total = 0
    warned = False
    regions = iter_regions(memory) if regions is None else regions
    for base, raw, missing in readable_chunks(memory, regions, chunk_size):
        scanned += len(raw)
        failed += missing
        for field, needle in needles.items():
            width = len(needle)
            position = raw.find(needle)
            while position >= 0:
                address = base + position
                if address % width == 0:
                    if total >= max_candidates:
                        raise RuntimeError(
                            f"limite de {max_candidates} candidatos atingido; scan incompleto, "
                            "não foi truncado. Comece em outro slot ou aumente --max-candidates"
                        )
                    candidates[field].append(address)
                    total += 1
                    if total > 100_000 and not warned:
                        print("AVISO: mais de 100.000 candidatos; continuando com armazenamento compacto.")
                        warned = True
                position = raw.find(needle, position + 1)
    return candidates, {"read_bytes": scanned, "unreadable_bytes": failed}


def refine_scan(memory, candidates, expected, formats):
    """Relê só páginas com candidatos, nunca varre novamente todo o processo."""
    result = {}
    for field, addresses in candidates.items():
        kept = array("Q")
        needle = struct.pack(formats[field], expected[field])
        width = len(needle)
        for page, group in groupby(addresses, key=lambda address: address // PAGE_SIZE):
            base = page * PAGE_SIZE
            raw = memory.read_bytes(base, PAGE_SIZE)
            for address in group:
                offset = address - base
                value = (raw[offset:offset + width] if raw is not None and offset + width <= len(raw)
                         else memory.read_bytes(address, width))
                if value == needle:
                    kept.append(address)
        result[field] = kept
    return result


def stage_values(slot, index_base, scan_hp, slot_format):
    input(f"Ative o Pokémon do SLOT {slot} pelo controle real do jogo e pressione ENTER aqui: ")
    expected = {}
    formats = {}
    for origin in ([0, 1] if index_base == "both" else [int(index_base)]):
        field = f"pokemon.active_slot_{origin}_based"
        expected[field] = slot - 1 + origin
        formats[field] = slot_format
    if scan_hp:
        text = input("HP ABSOLUTO e HP MÁXIMO desse Pokémon (ex.: 177 200, não percentual): ")
        try:
            hp, hp_max = map(int, text.split())
        except ValueError as exc:
            raise ValueError("informe exatamente dois inteiros: HP e máximo") from exc
        if not 0 <= hp <= hp_max <= 0x7FFFFFFF or hp_max == 0:
            raise ValueError("HP inválido: necessário 0 <= HP <= máximo positivo int32")
        expected.update({"pokemon.hp": hp, "pokemon.hp_max": hp_max})
        formats.update({"pokemon.hp": "<i", "pokemon.hp_max": "<i"})
    return expected, formats


def candidate_chains(memory, candidates, expected, formats, max_offset, max_depth):
    result = {}
    cache = {}
    for field, addresses in candidates.items():
        result[field] = []
        if not 0 < len(addresses) < 50:
            print(f"{field}: pointer scan não executado ({len(addresses)} candidatos).")
            continue
        for number, address in enumerate(addresses, 1):
            print(f"Pointer scan {field}: {number}/{len(addresses)}, alvo 0x{address:X}; pode demorar.")
            if address not in cache:
                ensure_alive(memory)
                cache[address] = build_chains(memory, address, max_offset, max_depth)
            for chain in cache[address]:
                entry = {
                    "module": chain["module"], "base_rva": chain["rva"],
                    "steps": chain["steps"], "terminal": chain["terminal"],
                    "deref": False, "type": "uint8" if formats[field] == "<B" else "int32",
                    "verified": False,
                }
                resolved = memory.resolve_entry_address(entry)
                raw = memory.read_bytes(address, struct.calcsize(formats[field]))
                valid = resolved == address and raw == struct.pack(formats[field], expected[field])
                record = {"address": address, "entry": entry,
                          "validated_in_current_session": valid}
                result[field].append(record)
                print(json.dumps({field: record}, ensure_ascii=False))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("process", help="nome ou PID do processo")
    parser.add_argument("--sequence", type=parse_sequence, default=parse_sequence("2,3,1,2"),
                        help="slots físicos; padrão 2,3,1,2 evita iniciar procurando zero")
    parser.add_argument("--index-base", choices=["0", "1", "both"], default="both")
    parser.add_argument("--slot-type", choices=["int32", "uint8"], default="int32")
    parser.add_argument("--hp", action="store_true", help="pedir HP absoluto/máximo em cada etapa")
    parser.add_argument("--max-candidates", type=int, default=10_000_000)
    parser.add_argument("--max-offset", type=lambda text: int(text, 0), default=0x2000)
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--skip-chains", action="store_true")
    parser.add_argument("--save", type=Path, default=Path("pokemon_candidates.json"))
    args = parser.parse_args(argv)
    if args.max_candidates <= 0 or args.max_depth <= 0 or args.max_offset < 0:
        parser.error("limites/profundidade devem ser positivos; max-offset deve ser não negativo")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    target = int(args.process) if args.process.isdecimal() else args.process
    try:
        with MemoryReader(target) as memory:
            if not memory.is_attached:
                print(f"FALHA: {memory.last_error}", file=sys.stderr)
                return 2
            if memory.pointer_size != 8:
                raise ValueError("esta ferramenta requer processo alvo x64")
            print(f"PID fixo desta sessão: {memory.pid}. Nenhuma tecla será enviada ao jogo.")
            print("As bases de índice são hipóteses; candidatos não provam a identidade do campo.")
            candidates = None
            history = []
            coverage = {}
            formats = {}
            expected = {}
            for stage, slot in enumerate(args.sequence, 1):
                print(f"\nEtapa {stage}/{len(args.sequence)}")
                expected, formats = stage_values(slot, args.index_base, args.hp,
                                                "<i" if args.slot_type == "int32" else "<B")
                ensure_alive(memory)
                if candidates is None:
                    candidates, coverage = initial_scan(memory, expected, formats, args.max_candidates)
                    print(f"Cobertura: {coverage}")
                else:
                    candidates = refine_scan(memory, candidates, expected, formats)
                ensure_alive(memory)
                history.append({"slot": slot, "expected": expected.copy(),
                                "counts": {field: len(addresses) for field, addresses in candidates.items()}})
                for field, addresses in candidates.items():
                    print(f"{field}: {len(addresses)} candidatos")
            for field, addresses in candidates.items():
                preview = ", ".join(f"0x{address:X}" for address in addresses[:20])
                print(f"Possíveis {field}: [{preview}] (total {len(addresses)})")
            chains = {} if args.skip_chains else candidate_chains(
                memory, candidates, expected, formats, args.max_offset, args.max_depth)
            report = {"pid": memory.pid, "module_base": memory.main_module_base,
                      "history": history, "coverage": coverage,
                      "addresses": {field: list(addresses) for field, addresses in candidates.items()},
                      "chains": chains, "verified": False,
                      "note": "Candidatos; validar comportamento e reinícios antes de usar no healer."}
            args.save.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"Salvo em {args.save}. offsets.json não foi alterado.")
            if args.hp:
                print("HP constante ou igual ao máximo não distingue campos; repita com dano/HP diferentes.")
            return 0
    except (OSError, ValueError, RuntimeError, EOFError) as exc:
        print(f"FALHA: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Scan interrompido; nenhum offset foi aplicado.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
