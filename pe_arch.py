"""PE architecture inspection; packing detection is heuristic, not proof."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import logging
import math
from pathlib import Path
import struct

MACHINES = {0x014C: ("x86", 4, 0x10B), 0x8664: ("x64", 8, 0x20B),
            0xAA64: ("ARM64", 8, 0x20B)}


@dataclass(frozen=True)
class PEInfo:
    machine: int
    architecture: str
    pointer_size: int
    subsystem: int
    subsystem_name: str
    packed: bool
    packing_reasons: tuple[str, ...]


def inspect_pe(path: str | Path) -> PEInfo:
    """Read DOS, NT/COFF, optional and section headers with bounds checks."""
    with open(path, "rb") as f:
        size = f.seek(0, 2)

        def read_at(offset, length):
            if offset < 0 or offset + length > size:
                raise ValueError("PE truncado: cabeçalho ou seção fora do arquivo")
            f.seek(offset)
            data = f.read(length)
            if len(data) != length:
                raise ValueError("Leitura incompleta do PE")
            return data

        dos = read_at(0, 64)
        if dos[:2] != b"MZ":
            raise ValueError("Assinatura DOS MZ ausente")
        nt = struct.unpack_from("<I", dos, 0x3C)[0]
        header = read_at(nt, 24)
        if header[:4] != b"PE\0\0":
            raise ValueError("Assinatura NT PE ausente")
        machine, sections = struct.unpack_from("<HH", header, 4)
        optional_size = struct.unpack_from("<H", header, 20)[0]
        if machine not in MACHINES:
            raise ValueError(f"Machine não suportado: 0x{machine:04X}")
        arch, pointers, expected_magic = MACHINES[machine]
        optional = read_at(nt + 24, optional_size)
        minimum = 96 if pointers == 4 else 112
        if len(optional) < minimum:
            raise ValueError("Optional Header truncado")
        if struct.unpack_from("<H", optional)[0] != expected_magic:
            raise ValueError("Machine e Optional Header Magic incompatíveis")
        subsystem = struct.unpack_from("<H", optional, 68)[0]
        reasons = []
        if not 1 <= sections <= 96:
            raise ValueError("Quantidade de seções PE inválida")
        for i in range(sections):
            section = read_at(nt + 24 + optional_size + i * 40, 40)
            name = section[:8].rstrip(b"\0").decode("ascii", "replace")
            raw_size, raw_ptr = struct.unpack_from("<II", section, 16)
            flags = struct.unpack_from("<I", section, 36)[0]
            executable = bool(flags & 0x20000000)
            if raw_size and raw_ptr + raw_size > size:
                raise ValueError(f"Seção {name} truncada")
            if name.lower().startswith(("upx", ".upx", ".vmp", ".themida", "aspack", ".aspack")):
                reasons.append(f"{name}: nome associado a empacotador")
            if executable and flags & 0x80000000:
                reasons.append(f"{name}: seção executável e gravável")
            if executable and raw_size >= 1024:
                # Bounded sample from the beginning, middle and end of the section.
                length = min(raw_size, 65536)
                starts = sorted({0, (raw_size - length) // 2, raw_size - length})
                sample = b"".join(read_at(raw_ptr + start, length) for start in starts)
                counts = Counter(sample)
                entropy = -sum((n / len(sample)) * math.log2(n / len(sample))
                               for n in counts.values())
                if entropy >= 7.2:
                    reasons.append(f"{name}: entropia executável alta ({entropy:.3f} bits/byte)")
        return PEInfo(machine, arch, pointers, subsystem,
                      {2: "GUI", 3: "console"}.get(subsystem, f"other({subsystem})"),
                      bool(reasons), tuple(reasons))


def log_arch(path, info):
    log = logging.getLogger("pokebot.arch")
    log.info("[arch] client=%s machine=0x%04X pointer_size=%d packed=%s",
             Path(path).name, info.machine, info.pointer_size, "YES" if info.packed else "NO")
    if info.packed:
        log.warning("[arch] Empacotamento SUSPEITO (heurística): %s", "; ".join(info.packing_reasons))


def process_executable(pm):
    """Resolve the executable belonging to the opened process, not a guessed path."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    query = kernel.QueryFullProcessImageNameW
    query.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                      ctypes.POINTER(wintypes.DWORD)]
    query.restype = wintypes.BOOL
    buffer = ctypes.create_unicode_buffer(32768)
    length = wintypes.DWORD(len(buffer))
    if not query(pm.process_handle, 0, buffer, ctypes.byref(length)):
        raise ctypes.WinError(ctypes.get_last_error())
    return buffer.value


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    info = inspect_pe(args.executable)
    log_arch(args.executable, info)
    print(f"subsystem={info.subsystem} ({info.subsystem_name})")
