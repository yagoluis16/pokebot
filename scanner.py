# pokebot/scanner.py
"""AOB pattern scanner + signature resolver for PokeAlliance (FASE 1 / 05).

Reuses Process and Resolver from memory.py -- no class duplication.

Pattern scanning reads the PE file on disk (bounded chunks, overlap of
len(pattern)-1) instead of ReadProcessMemory: cheaper, no transient
ERROR_PARTIAL_COPY on pages the client is actively touching.

Subcommands:
  aob <pattern>          scan a raw AOB pattern, print every hit
  aob-list               run every aob_signatures entry from offsets.json
  resolve <aob_key>      first hit + declared resolve method -> final VA
  chain <aob_key> <term> walk a pointer chain from a resolved address
  read <addr> <size>     hexdump live memory via memory.Process.read
  sections               PE sections of the main module (where to scan)

Fail-closed: 0 hits -> clear message, no resolve. Any chain level that is
0, None or unreadable aborts the walk -- no zero-filled continuation.
"""
from __future__ import annotations

import argparse
import json
import logging
import struct
import sys
from pathlib import Path

from memory import Process, Resolver, parse_hex, setup_logging, _normalize_cfg_path

log = logging.getLogger("pokebot.scanner")

# Default section for AOB scans. Signatures may override with "section".
DEFAULT_SECTION = ".text"

# PE/COFF structures (x86 / x64, PE32 / PE32+).
_IMAGE_SECTION_HEADER = struct.Struct("<8sIIIIIIHHI")


# ---------------------------------------------------------------- helpers
def hex_num(s):
    """CLI hex arg: '0x1A4', '1A4', '1a4' -> int. Bare digits parse base-16
    first, so pass 0x-prefixed values when you mean decimal-looking hex."""
    if isinstance(s, int):
        return s
    s = str(s).strip()
    try:
        return int(s, 16)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a hex number: {s!r}") from None


def parse_aob_pattern(pattern: str):
    """Space-separated hex bytes; '??' (or '?') is a wildcard.

    Returns (bytes, bytearray mask) where mask[i] == 0xFF means "must match".
    Raises ValueError on a bad token -- never silently drops a byte.
    """
    pat = bytearray()
    mask = bytearray()
    for tok in pattern.split():
        t = tok.strip().lower()
        if t in ("??", "?"):
            pat.append(0)
            mask.append(0x00)
            continue
        if len(t) != 2:
            raise ValueError(f"bad pattern token {tok!r} (want 2 hex chars or ??)")
        try:
            pat.append(int(t, 16))
        except ValueError:
            raise ValueError(f"bad pattern token {tok!r} (not hex)") from None
        mask.append(0xFF)
    if not pat:
        raise ValueError("empty pattern")
    return bytes(pat), bytes(mask)


def find_displacement(pattern: str):
    """First run of >=4 consecutive '??' = the disp32 of a RIP-relative
    instruction. Returns (start_index, length) or (None, 0)."""
    tokens = pattern.split()
    run_start = None
    run = 0
    for i, tok in enumerate(tokens):
        if tok.strip().lower() in ("??", "?"):
            if run_start is None:
                run_start = i
            run += 1
            if run >= 4:
                return run_start, run
        else:
            run_start = None
            run = 0
    return None, 0


# ---------------------------------------------------------------- sections
class SectionScanner:
    """Parse the PE section table of a file on disk and scan raw bytes."""

    def __init__(self, path, module_base):
        self.path = str(path)
        # module_base may arrive as a pymem MODULEINFO, an int, or a hex
        # string. Normalize to int without ever calling int() on a ctypes
        # struct -- prefer an explicit attribute if present.
        if hasattr(module_base, "lpBaseOfDll"):
            module_base = module_base.lpBaseOfDll
        self.module_base = int(module_base)
        self.sections = []
        self._load()

    def _load(self):
        with open(self.path, "rb") as fh:
            dos = fh.read(64)
            if len(dos) < 64:
                raise ValueError("file too small for DOS header")
            if dos[:2] != b"MZ":
                raise ValueError("not a PE file (no MZ)")
            e_lfanew = struct.unpack_from("<I", dos, 0x3C)[0]
            fh.seek(e_lfanew)
            sig = fh.read(4)
            if sig != b"PE\0\0":
                raise ValueError("not a PE file (no PE signature)")
            coff = fh.read(20)  # entire COFF header (20 bytes)
            if len(coff) < 20:
                raise ValueError("truncated COFF header")
            (_, n_sections, _, _, _,
             size_of_optional_header, _) = struct.unpack("<HHIIIHH", coff)
            # fh is now positioned at the start of the optional header.
            fh.seek(size_of_optional_header, 1)  # skip by the real size
            for _ in range(n_sections):
                raw = fh.read(_IMAGE_SECTION_HEADER.size)
                if len(raw) < _IMAGE_SECTION_HEADER.size:
                    break
                (name, vsize, rva, raw_size, raw_ptr, *_) = \
                    _IMAGE_SECTION_HEADER.unpack(raw)
                name = name.rstrip(b"\x00").decode("ascii", errors="replace")
                self.sections.append({
                    "name": name,
                    "rva": rva,
                    "vsize": vsize,
                    "raw_size": raw_size,
                    "raw_ptr": raw_ptr,
                })

    def list(self):
        return list(self.sections)

    def get(self, name):
        for s in self.sections:
            if s["name"] == name:
                return s
        return None

    def scan(self, section_name, pattern, mask):
        """All hits of pattern in section. Returns [(va, rva, raw_off)].

        Chunked read with (len(pattern)-1)-byte overlap so a pattern that
        straddles a chunk boundary is found exactly once.
        """
        sec = self.get(section_name)
        if not sec:
            raise ValueError(
                f"section {section_name!r} not found; sections: "
                + ", ".join(s["name"] for s in self.sections))
        p_len = len(pattern)
        chunk_size = max(65536, p_len)
        hits = []
        carry = b""
        section_offset = 0
        with open(self.path, "rb") as fh:
            fh.seek(sec["raw_ptr"])
            remaining = sec["raw_size"]
            while remaining > 0:
                want = min(chunk_size, remaining)
                chunk = fh.read(want)
                if not chunk:
                    break
                remaining -= len(chunk)
                buf = carry + chunk
                pos = 0
                while True:
                    idx = buf.find(pattern, pos)
                    if idx < 0:
                        break
                    hit_raw = idx - len(carry)
                    if hit_raw >= 0:
                        actual_offset = section_offset + hit_raw
                        if actual_offset + p_len <= sec["raw_size"]:
                            rva = sec["rva"] + actual_offset
                            va = self.module_base + rva
                            hits.append((va, rva, sec["raw_ptr"] + actual_offset))
                    pos = idx + 1
                carry = buf[-(p_len - 1):] if p_len > 1 else b""
                section_offset += len(chunk)
        # Second pass: re-read each candidate and apply the mask properly.
        # find() matched on the concrete pattern bytes (wildcards stored as
        # 0x00), so a real 0x00 byte in a wildcard slot would falsely match.
        filtered = []
        with open(self.path, "rb") as fh:
            for va, rva, raw_off in hits:
                fh.seek(raw_off)
                got = fh.read(p_len)
                if len(got) == p_len and all(
                        (got[i] & mask[i]) == (pattern[i] & mask[i])
                        for i in range(p_len)):
                    filtered.append((va, rva, raw_off))
        return filtered


# ---------------------------------------------------------------- resolver
def load_signatures(offsets_path):
    path = _normalize_cfg_path(offsets_path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh).get("aob_signatures", {})
    except Exception as exc:
        log.error("cannot read aob_signatures from %s: %s", path, exc)
        return {}


def resolve_hit(sig, hit_va, proc, pattern):
    """Apply the resolve method declared in the signature.

    relative32: read disp32 from hit_va + disp_start, add to the address
                AFTER the displacement (rip-relative semantics).
    direct:     the hit VA is the answer.
    ptr:        dereference a client-sized pointer at the hit VA.
    Returns (resolved_addr, method, note). None on unreadable/zero.
    """
    method = str(sig.get("resolve", "direct")).lower()
    note = ""
    if method == "relative32":
        disp_start, disp_len = find_displacement(pattern)
        if disp_start is None:
            note = ("no 4-byte wildcard run in pattern -- disp32 not located; "
                    "returning hit VA as fallback. Adjust the pattern or add "
                    "a 'disp_start' key to the signature.")
            return hit_va, method, note
        disp_addr = hit_va + disp_start
        disp = proc.read_u32(disp_addr)
        if disp is None:
            log.error("relative32: cannot read disp32 at 0x%X", disp_addr)
            return None, method, "disp32 unreadable"
        if disp >= 0x80000000:
            disp -= 0x100000000  # sign-extend
        next_ip = hit_va + disp_start + disp_len
        return next_ip + disp, method, note
    if method == "direct":
        return hit_va, method, note
    if method == "ptr":
        val = proc.read_ptr(hit_va)
        if val is None or val == 0:
            log.error("ptr: no readable pointer at 0x%X", hit_va)
            return None, method, "pointer unreadable or null"
        return val, method, note
    log.error("unknown resolve method %r -- treating as direct", method)
    return hit_va, method, "unknown method, fell back to direct"


def walk_chain(start_addr, terminal, proc, label="chain"):
    """Walk a pointer chain: [deref]*n then +terminal. Aborts on any
    zero/unreadable level. Returns the final address or None."""
    if start_addr is None:
        return None
    addr = start_addr
    print(f"[{label}] start 0x{addr:X}")
    if terminal == 0:
        print(f"[{label}] terminal=0 -> final 0x{addr:X}")
        return addr
    nxt = proc.read_ptr(addr)
    if nxt is None or nxt == 0:
        print(f"[{label}] ABORT at 0x{addr:X} -> read_ptr gave "
              f"{'unreadable' if nxt is None else '0 (null pointer)'}")
        return None
    print(f"[{label}] 0x{addr:X} -> 0x{nxt:X} (deref)")
    addr = nxt
    final = addr + terminal
    if not proc.is_valid_addr(final):
        print(f"[{label}] ABORT: final 0x{final:X} not readable")
        return None
    print(f"[{label}] + terminal 0x{terminal:X} -> final 0x{final:X}")
    return final


def dump_hex(proc, addr, size):
    data = proc.read(addr, size)
    if data is None:
        print(f"read failed / address invalid: 0x{addr:X}")
        return 1
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hexpart = " ".join(f"{b:02X}" for b in chunk)
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"0x{addr + i:012X}  {hexpart:<47}  {asc}")
    return 0


# ------------------------------------------------------------------- CLI
def _print_hits(hits, section, pat_str, va_only=False):
    if not hits:
        print(f"0 hits in {section} for: {pat_str}")
        return
    print(f"{len(hits)} hit(s) in {section}:")
    for va, rva, raw in hits[:5]:
        print(f"  VA=0x{va:X}  RVA=0x{rva:X}  raw=0x{raw:X}"
              + ("  (module-relative)" if va_only else ""))
    if len(hits) > 5:
        print(f"  ... and {len(hits) - 5} more")
    if len(hits) > 1:
        print("AMBIGUOUS: multiple hits -- narrow the pattern or pick "
              "by RVA/VA against a known disassembly")


def _resolve_main_module_path(proc):
    """Return the on-disk path of the main module for the attached process.

    psutil by PID is preferred: the handle opened by memory.py may lack
    PROCESS_QUERY_INFORMATION, which QueryFullProcessImageNameW requires.
    """
    # Preferred: psutil by PID. Independent of the handle's access rights.
    try:
        import psutil
        pid = getattr(proc.pm, "process_id", None)
        if pid:
            path = psutil.Process(pid).exe()
            if path:
                return path
    except Exception as exc:
        log.warning("psutil exe lookup failed: %s", exc)

    # Fallback: kernel API on the existing handle (may fail on restricted
    # handles; that's why psutil comes first).
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        buf = ctypes.create_unicode_buffer(32768)
        size = ctypes.wintypes.DWORD(32768)
        handle = getattr(proc.pm, "process_handle", None) \
            or getattr(proc, "handle", None)
        if handle:
            n = k32.QueryFullProcessImageNameW(
                ctypes.c_void_p(handle), 0, buf, ctypes.byref(size))
            if n:
                return buf.value
    except Exception as exc:
        log.warning("QueryFullProcessImageNameW fallback failed: %s", exc)

    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="PokeAlliance AOB scanner")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_aob = sub.add_parser("aob", help="scan a raw AOB pattern")
    p_aob.add_argument("pattern")
    p_aob.add_argument("--section", default=DEFAULT_SECTION)

    sub.add_parser("aob-list", help="run every aob_signatures entry")

    p_res = sub.add_parser("resolve", help="resolve a signature to an address")
    p_res.add_argument("aob_key")

    p_chain = sub.add_parser("chain", help="walk a chain from a resolved addr")
    p_chain.add_argument("aob_key")
    p_chain.add_argument("terminal", type=hex_num)

    p_read = sub.add_parser("read", help="hexdump memory")
    p_read.add_argument("addr", type=hex_num)
    p_read.add_argument("size", type=hex_num)

    sub.add_parser("sections", help="list PE sections of the main module")

    ap.add_argument("--offsets", default="offsets.json")
    ap.add_argument("--signatures", default="signatures.json")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--log-level", default=None)
    args = ap.parse_args(argv)

    log = setup_logging(args.config)
    if args.log_level:
        logging.getLogger("pokebot").setLevel(args.log_level.upper())

    with open(_normalize_cfg_path(args.offsets), "r", encoding="utf-8") as fh:
        cfg_off = json.load(fh)
    with open(_normalize_cfg_path(args.config), "r", encoding="utf-8") as fh:
        cfg = json.load(fh)

    proc_name = (cfg.get("client", {}) or {}).get(
        "process_name", "PokeAlliance_dx.exe")
    proc = Process(proc_name, config=cfg.get("safety", {}))
    if not proc.attach():
        return 1

    exe_path = proc.executable_path
    if not exe_path or not Path(exe_path).exists():
        print("cannot resolve main module file path from the live process")
        return 1
    log.info("main module: %s", exe_path)

    scanner = SectionScanner(exe_path, module_base=proc.base)

    if args.cmd == "sections":
        print(f"module: {exe_path}")
        print(f"module_base: 0x{proc.base:X}")
        print(f"{'name':<10} {'RVA':>10} {'VSize':>10} "
              f"{'RawPtr':>10} {'RawSize':>10}")
        for s in scanner.list():
            print(f"{s['name']:<10} 0x{s['rva']:08X} 0x{s['vsize']:08X} "
                  f"0x{s['raw_ptr']:08X} 0x{s['raw_size']:08X}")
        return 0

    if args.cmd == "aob":
        pat, mask = parse_aob_pattern(args.pattern)
        hits = scanner.scan(args.section, pat, mask)
        _print_hits(hits, args.section, args.pattern, va_only=True)
        return 0 if hits else 2

    if args.cmd == "aob-list":
        sigs = load_signatures(args.signatures)
        if not sigs:
            print("no aob_signatures in offsets.json")
            return 2
        for key, sig in sigs.items():
            pattern = sig.get("pattern", "")
            section = sig.get("section", DEFAULT_SECTION)
            module = sig.get("module", "client")
            try:
                pat, mask = parse_aob_pattern(pattern)
            except ValueError as exc:
                print(f"{key}: BAD PATTERN ({exc})")
                continue
            if module != "client":
                print(f"{key}: module {module!r} not wired -- "
                      f"only 'client' (main module) is scannable for now")
                continue
            hits = scanner.scan(section, pat, mask)
            print(f"{key}: {len(hits)} hit(s)  module={module}  section={section}")
            if hits:
                va, rva, raw = hits[0]
                print(f"  first VA=0x{va:X}  first RVA=0x{rva:X}")
                if len(hits) > 1:
                    print("  AMBIGUOUS: >1 hit, narrow the pattern")
        return 0

    if args.cmd == "resolve":
        sigs = load_signatures(args.signatures)
        sig = sigs.get(args.aob_key)
        if not sig:
            print(f"signature {args.aob_key!r} not found in offsets.json")
            return 2
        pattern = sig.get("pattern", "")
        section = sig.get("section", DEFAULT_SECTION)
        try:
            pat, mask = parse_aob_pattern(pattern)
        except ValueError as exc:
            print(f"bad pattern for {args.aob_key}: {exc}")
            return 2
        hits = scanner.scan(section, pat, mask)
        if not hits:
            print(f"0 hits -- {args.aob_key} not found in {section}")
            return 2
        va, rva, raw = hits[0]
        resolved, method, note = resolve_hit(sig, va, proc, pattern)
        print(f"{args.aob_key}: hit VA=0x{va:X} RVA=0x{rva:X} "
              f"({len(hits)} hit(s), using first)")
        if resolved is None:
            print(f"  resolve FAILED: {note}")
            return 2
        print(f"  method={method}  resolved=0x{resolved:X}")
        if note:
            print(f"  note: {note}")
        if len(hits) > 1:
            print("  AMBIGUOUS: >1 hit, verify against disassembly")
        return 0

    if args.cmd == "chain":
        sigs = load_signatures(args.signatures)
        sig = sigs.get(args.aob_key)
        if not sig:
            print(f"signature {args.aob_key!r} not found in offsets.json")
            return 2
        pattern = sig.get("pattern", "")
        section = sig.get("section", DEFAULT_SECTION)
        try:
            pat, mask = parse_aob_pattern(pattern)
        except ValueError as exc:
            print(f"bad pattern for {args.aob_key}: {exc}")
            return 2
        hits = scanner.scan(section, pat, mask)
        if not hits:
            print(f"0 hits -- {args.aob_key} not found")
            return 2
        va = hits[0][0]
        start, method, note = resolve_hit(sig, va, proc, pattern)
        if start is None:
            print(f"resolve failed: {note}")
            return 2
        print(f"{args.aob_key}: resolved start 0x{start:X} (method={method})")
        final = walk_chain(start, args.terminal, proc, label=args.aob_key)
        return 0 if final is not None else 2

    if args.cmd == "read":
        return dump_hex(proc, args.addr, args.size)

    return 2


if __name__ == "__main__":
    sys.exit(main())
