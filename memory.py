# pokebot/memory.py
"""Read-only process access and validated scalar pointer chains (offsets v2)."""
from __future__ import annotations

import json
import logging
import os
import sys
import struct
import threading
from offset_contract import TYPE_FORMATS, validate_offsets
from pe_arch import inspect_pe, log_arch, process_executable
from logging.handlers import RotatingFileHandler
from pathlib import Path

try:
    import pymem
    import pymem.process
    PYMEM_AVAILABLE = True
except ImportError:
    pymem = None
    PYMEM_AVAILABLE = False

_HERE = Path(__file__).resolve().parent
DEFAULT_OFFSETS_PATH = os.path.join(_HERE, "offsets.json")
DEFAULT_CONFIG_PATH = os.path.join(_HERE, "config.json")

# Top-level offset blocks. Add new ones here when offsets.json grows.
BLOCK_KEYS = ("player", "creature_list", "tile_map", "game_state", "minimap")

# Hard ceiling on string reads. Independent of offsets.json safety.max_read_bytes
# so a corrupted config cannot turn a read into a multi-megabyte pull.
MAX_STRING_READ = 512

# Pointer-chain walk depth. Guards a corrupted loop of steps.
MAX_CHAIN_DEPTH = 16

log = logging.getLogger("pokebot.memory")
POINTER_SIZE = None  # Set only after inspecting the actual client PE.


# ---------------------------------------------------------------- parse_hex
def parse_hex(value):
    """offsets.json carries hex strings; accept those AND bare JSON numbers.

    "0x1a4" / "1a4" / "1A4" -> 162 (underscores tolerated, case-insensitive)
    "42"                    -> 42  (no 0x and no hex digits -> decimal)
    40 / 40.0               -> 40  (bare JSON numbers pass through)
    Anything else raises ValueError -- the caller decides to treat it as
    an unresolved field, never as a silent 0.
    """
    if isinstance(value, bool):
        raise ValueError(f"boolean is not an offset: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        s = value.strip().replace("_", "")
        if not s:
            raise ValueError("empty string is not an offset")
        try:
            return int(s, 16)
        except ValueError:
            pass
        try:
            return int(s, 10)
        except ValueError:
            raise ValueError(f"cannot parse offset: {value!r}") from None
    raise ValueError(f"unsupported offset type: {type(value).__name__}")


# ----------------------------------------------------------------- logging
def setup_logging(config_path=DEFAULT_CONFIG_PATH, force=False):
    """Log level/file/rotation come from config.json runtime section."""
    cfg = {}
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh).get("runtime", {})
    except Exception:
        cfg = {}

    level = str(cfg.get("log_level", "INFO")).upper()
    log_file = cfg.get("log_file", "pokebot.log")
    max_bytes = int(cfg.get("log_max_bytes", 2 * 1024 * 1024))
    backups = int(cfg.get("log_backup_count", 3))

    if log_file and not os.path.isabs(log_file):
        log_file = os.path.join(_HERE, log_file)

    root = logging.getLogger("pokebot")
    root.setLevel(getattr(logging, level, logging.INFO))
    if force or not root.handlers:
        for h in list(root.handlers):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        root.addHandler(sh)
        if log_file:
            try:
                fh = RotatingFileHandler(
                    log_file, maxBytes=max_bytes, backupCount=backups,
                    encoding="utf-8",
                )
                fh.setFormatter(fmt)
                root.addHandler(fh)
            except Exception as exc:
                root.warning("log file unavailable (%s); console only", exc)
    return log


def _normalize_cfg_path(path):
    if not path:
        return DEFAULT_CONFIG_PATH
    p = Path(str(path))
    if not p.is_absolute() and not p.exists():
        p = _HERE / p
    return str(p)


# ------------------------------------------------------------------ Process
class Process:
    """Attach + bounded, validated reads against a live process."""

    def __init__(self, process_name: str, config=None):
        if not process_name:
            raise ValueError("process_name required")
        self.process_name = process_name
        self.pm = None
        self.base = None
        self.base_size = 0
        self.modules = {}
        self._regions = []
        self._bounds = config or {}
        self.pointer_size = None
        self.executable_path = None
        self.architecture = None
        self.last_error = None

    # -- lifecycle ---------------------------------------------------------
    def attach(self) -> bool:
        global POINTER_SIZE
        self.detach()
        self.last_error = None
        POINTER_SIZE = None
        self.pointer_size = None
        if not PYMEM_AVAILABLE:
            self.last_error = "pymem not installed; run py -m pip install pymem"
            log.error("pymem not installed -- pip install pymem")
            return False
        try:
            self.pm = pymem.Pymem(self.process_name)
        except Exception as exc:
            self.last_error = f"attach to {self.process_name} failed: {exc}"
            log.error("attach failed for %s: %s", self.process_name, exc)
            return False
        try:
            self.executable_path = process_executable(self.pm)
            self.architecture = inspect_pe(self.executable_path)
            self.pointer_size = self.architecture.pointer_size
            POINTER_SIZE = self.pointer_size
            log_arch(self.executable_path, self.architecture)
            main = self.pm.process_base
            self.base = int(main.lpBaseOfDll)
            self.base_size = int(main.SizeOfImage)
            log.info("attached to %s base=0x%X size=0x%X",
                     self.process_name, self.base, self.base_size)
        except Exception as exc:
            self.last_error = f"client architecture/main module validation failed: {exc}"
            log.error("cannot validate client architecture/main module: %s", exc)
            self.detach()
            return False
        self.modules = {}
        self.modules[Path(self.executable_path).name.lower()] = {
            "base": self.base, "size": self.base_size}
        try:
            for mod in self.pm.list_modules():
                try:
                    self.modules[mod.name.lower()] = {
                        "base": int(mod.lpBaseOfDll),
                        "size": int(mod.SizeOfImage),
                    }
                except Exception:
                    continue
            log.info("enumerated %d modules", len(self.modules))
        except Exception as exc:
            log.warning("module enumeration failed (main module still usable): %s", exc)
        return True

    def detach(self):
        global POINTER_SIZE
        POINTER_SIZE = None
        self.pointer_size = None
        if self.pm is not None:
            try:
                self.pm.close_process()
            except Exception:
                pass
            self.pm = None
        self._regions = []
        self.modules = {}
        self.base = None
        self.base_size = 0

    # -- validation --------------------------------------------------------
    def is_valid_addr(self, addr) -> bool:
        """True only if the page is genuinely readable (VirtualQuery probe)."""
        if addr is None:
            return False
        try:
            addr = int(addr)
        except (TypeError, ValueError):
            return False
        if addr <= 0x10000:
            return False
        regions = self._memory_regions()
        if regions:
            for base, size, readable in regions:
                if base <= addr < base + size:
                    return readable
            return False
        # Region walk unavailable -> probe directly.
        try:
            self.pm.read_bytes(addr, 1)
            return True
        except Exception:
            return False

    def _memory_regions(self):
        if self._regions:
            return self._regions
        if self.pm is None:
            return []
        try:
            import ctypes
            import ctypes.wintypes as wt
        except Exception:
            return []
        try:
            PROCESS_QUERY_INFORMATION = 0x0400
            PROCESS_VM_READ = 0x0010
            MEM_COMMIT = 0x1000
            PAGE_GUARD = 0x100
            PAGE_NOACCESS = 0x01
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            h = k32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ,
                                False, int(self.pm.process_id))
            if not h:
                return []
            try:
                class MBI(ctypes.Structure):
                    _fields_ = [
                        ("BaseAddress", ctypes.c_void_p),
                        ("AllocationBase", ctypes.c_void_p),
                        ("AllocationProtect", wt.DWORD),
                        ("PartitionId", wt.WORD),
                        ("RegionSize", ctypes.c_size_t),
                        ("State", wt.DWORD),
                        ("Protect", wt.DWORD),
                        ("Type", wt.DWORD),
                    ]
                info = MBI()
                addr = 0
                limit = 0x00007FFFFFFFFFFF  # user-mode ceiling on x64
                out = []
                while addr < limit:
                    if not k32.VirtualQueryEx(
                            ctypes.c_void_p(h),
                            ctypes.c_void_p(addr),
                            ctypes.byref(info),
                            ctypes.sizeof(info)):
                        break
                    size = int(info.RegionSize or 0)
                    if size <= 0:
                        break
                    if info.State == MEM_COMMIT:
                        prot = int(info.Protect)
                        readable = not (prot & PAGE_GUARD) and prot not in (
                            0, PAGE_NOACCESS)
                        out.append((int(info.BaseAddress or addr), size, readable))
                    addr = int(info.BaseAddress or addr) + size
                self._regions = out
                return out
            finally:
                try:
                    k32.CloseHandle(ctypes.c_void_p(h))
                except Exception:
                    pass
        except Exception as exc:
            log.debug("VirtualQueryEx walk unavailable: %s", exc)
            return []

    def _module_range(self, module=None):
        if module:
            m = self.modules.get(str(module).lower())
            if not m:
                return None
            return m["base"], m["base"] + m["size"]
        if self.base:
            return self.base, self.base + self.base_size
        return None

    # -- raw reads ---------------------------------------------------------
    def read(self, addr, size) -> bytes | None:
        """Bounded, validated raw read. None on any failure. No partial bytes."""
        self.last_error = None
        if self.pm is None:
            self.last_error = "process is not attached"
            return None
        if addr is None:
            return None
        try:
            addr = int(addr)
            size = int(size)
        except (TypeError, ValueError):
            return None
        if size <= 0:
            log.warning("read: non-positive size %r refused", size)
            return None
        cap = self._bounds.get("max_read_bytes", 4096)
        try:
            cap = int(cap)
        except (TypeError, ValueError):
            cap = 4096
        if size > cap:
            log.warning("read: size %d exceeds safety.max_read_bytes=%d -- truncated",
                        size, cap)
            size = cap
        if not self.is_valid_addr(addr):
            self.last_error = f"invalid/unreadable address 0x{addr:X}; client may have closed"
            log.debug("read: refusing invalid/unreadable addr 0x%X", addr)
            return None
        try:
            return self.pm.read_bytes(addr, size)
        except Exception as exc:
            self.last_error = f"read at 0x{addr:X} ({size} bytes) failed: {exc}"
            log.debug("read failed at 0x%X (%d bytes): %s", addr, size, exc)
            return None

    def read_u8(self, addr) -> int | None:
        data = self.read(addr, 1)
        return data[0] if data else None

    def read_u16(self, addr) -> int | None:
        data = self.read(addr, 2)
        return int.from_bytes(data, "little") if data and len(data) >= 2 else None

    def read_u32(self, addr) -> int | None:
        data = self.read(addr, 4)
        return int.from_bytes(data, "little") if data and len(data) >= 4 else None

    def read_u64(self, addr) -> int | None:
        data = self.read(addr, 8)
        return int.from_bytes(data, "little") if data and len(data) >= 8 else None

    def read_ptr(self, addr) -> int | None:
        if self.pointer_size == 4:
            return self.read_u32(addr)
        if self.pointer_size == 8:
            return self.read_u64(addr)
        log.error("pointer_size desconhecido; leitura de ponteiro recusada")
        return None

    def read_value(self, addr, value_type):
        """Read one unmasked scalar. None on incomplete or failed reads."""
        fmt = "<" + TYPE_FORMATS[value_type]
        width = struct.calcsize(fmt)
        data = self.read(addr, width)
        if data is None or len(data) != width:
            if self.last_error is None:
                self.last_error = f"incomplete {value_type} read at 0x{addr:X}"
            return None
        return struct.unpack(fmt, data)[0]

    def read_i32(self, addr) -> int | None:
        data = self.read(addr, 4)
        if not data or len(data) < 4:
            return None
        return int.from_bytes(data, "little", signed=True)

    def read_bool(self, addr) -> bool | None:
        v = self.read_u8(addr)
        return None if v is None else bool(v)

    def read_string(self, addr, max_len: int = 32) -> str | None:
        """NUL-terminated ASCII read, bounded by config and MAX_STRING_READ."""
        try:
            max_len = int(max_len)
        except (TypeError, ValueError):
            max_len = 32
        if max_len <= 0:
            max_len = 32
        limit = int(self._bounds.get("max_string_len", 256))
        if max_len > limit:
            log.warning("read_string: max_len %d clamped to safety.max_string_len=%d",
                        max_len, limit)
            max_len = limit
        if max_len > MAX_STRING_READ:
            max_len = MAX_STRING_READ
        data = self.read(addr, max_len)
        if not data:
            return None
        nul = data.find(b"\x00")
        raw = data[:nul] if nul >= 0 else data
        try:
            return raw.decode("ascii", errors="replace")
        except Exception:
            return None


# ----------------------------------------------------------------- Resolver
class Resolver:
    """Every scalar owns a complete module-relative pointer chain."""

    def __init__(self, process, offsets_path=DEFAULT_OFFSETS_PATH,
                 config_path=DEFAULT_CONFIG_PATH):
        self.proc = process
        self.offsets_path = _normalize_cfg_path(offsets_path)
        self.cfg = self._load_config(config_path)
        with open(self.offsets_path, encoding="utf-8") as fh:
            self.data = validate_offsets(json.load(fh))
        self.entries = self.data["entries"]
        self._assumed_warned = set()
        self._warning_lock = threading.Lock()
        log.info("loaded %d offset entries (schema v2)", len(self.entries))

    @staticmethod
    def _load_config(path):
        with open(_normalize_cfg_path(path), encoding="utf-8") as fh:
            return json.load(fh)

    def resolve_entry(self, name):
        """Walk steps, optionally dereference, then add terminal; never cache targets."""
        entry = self.entries.get(name)
        if not entry or not entry["verified"] or self.proc is None:
            return None
        if (entry["base_rva"] is None or entry["steps"] is None
                or entry["terminal"] is None or any(v is None for v in entry["steps"])):
            return None
        if self.proc.pointer_size not in (4, 8):
            return None
        module = self.proc.modules.get(entry["module"].lower())
        if module is None or entry["base_rva"] >= module["size"]:
            return None
        ceiling = (1 << (8 * self.proc.pointer_size)) - 1
        addr = module["base"] + entry["base_rva"]
        for step in entry["steps"]:
            if not 0 < addr <= ceiling - self.proc.pointer_size + 1:
                return None
            pointer = self.proc.read_ptr(addr)
            if pointer is None or pointer == 0:
                return None
            addr = pointer + step
        if entry.get("deref", False):
            if not 0 < addr <= ceiling - self.proc.pointer_size + 1:
                return None
            pointer = self.proc.read_ptr(addr)
            if pointer is None or pointer == 0:
                return None
            addr = pointer
        addr += entry["terminal"]
        log.info(
            "[resolve] %s base=0x%X rva=0x%X steps=%s terminal=0x%X final=0x%X",
            name, module["base"], entry["base_rva"], entry["steps"],
            entry["terminal"], addr,
        )
        width = struct.calcsize("<" + TYPE_FORMATS[entry["type"]])
        if not 0 < addr <= ceiling - width + 1:
            return None
        return addr if self.proc.is_valid_addr(addr) else None

    def read_entry(self, name):
        self.warn_if_assumed(name)
        addr = self.resolve_entry(name)
        if addr is None:
            return None
        entry = self.entries[name]
        raw = self.proc.read_value(addr, entry["type"])
        if raw is None:
            return None
        if "mask" in entry:
            raw = (raw & entry["mask"]) >> entry.get("shift", 0)
        return raw

    def warn_if_assumed(self, name):
        """Warn once per field/resolver, even if null offsets block the read."""
        entry = self.entries.get(name)
        if entry and not entry["verified"] and entry["source"] == "assumed":
            with self._warning_lock:
                if name in self._assumed_warned:
                    return
                self._assumed_warned.add(name)
            log.warning("[warn] reading ASSUMED field %s — value may be wrong", name)

    def read_field(self, block_name, field_name, base_addr=None):
        # Existing consumers keep their block/field API. No bypass of verification.
        if base_addr is not None:
            raise ValueError("offsets v2 requires a complete per-field chain")
        return self.read_entry(f"{block_name}.{field_name}")

    def read_fields(self, block_name, field_names=None, base_addr=None):
        if base_addr is not None:
            raise ValueError("offsets v2 requires a complete per-field chain")
        names = field_names if field_names is not None else [
            name.split(".", 1)[1] for name in self.entries if name.startswith(block_name + ".")]
        return {name: self.read_field(block_name, name) for name in names}

    def resolve_block(self, name):
        # PLACEHOLDER — needs entity list offsets, not yet reversed
        # TODO: define a validated entity-container contract before returning a common block root.
        # No common struct address can be inferred from independent scalar chains.
        # Legacy creature enumeration is still unimplemented and must stay inactive.
        return None


# --------------------------------------------------------------------- CLI
USAGE = """usage:
  python memory.py --check                      validate blocks against live client
  python memory.py --field player hp            typed field read
  python memory.py --read 0x7FF6A4000000 64     raw hexdump
  options: --config PATH --offsets PATH --log-level DEBUG --json --quiet
"""


def _fmt(v):
    if isinstance(v, int) and not isinstance(v, bool):
        return f"0x{v:X} ({v})"
    return repr(v)


def test_blocks(resolver, as_json=False):
    names = list(resolver.entries.keys())
    resolved = {}
    for n in names:
        addr = resolver.resolve_entry(n)
        resolved[n] = addr
        if not as_json:
            print(f"[{'OK ' if addr else 'OFF'}] {n:<14} "
                  f"{('-> 0x%X' % addr) if addr else 'desligado (nao calibrado)'}")
    if as_json:
        print(json.dumps({n: (None if a is None else hex(a))
                          for n, a in resolved.items()}, indent=2))
    return any(resolved.values())


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="PokeAlliance memory layer",
                                 usage=USAGE)
    ap.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    ap.add_argument("--offsets", default=DEFAULT_OFFSETS_PATH)
    ap.add_argument("--log-level", default=None)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--field", nargs=2, metavar=("BLOCK", "FIELD"))
    ap.add_argument("--read", nargs=2, metavar=("ADDR", "SIZE"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    log = setup_logging(args.config)
    if args.log_level:
        logging.getLogger("pokebot").setLevel(args.log_level.upper())

    resolver = Resolver(None, offsets_path=args.offsets, config_path=args.config)
    if args.log_level and args.quiet:
        logging.getLogger("pokebot").setLevel(logging.CRITICAL)

    proc_name = (resolver.cfg.get("client", {}) or {}).get(
        "process_name", "PokeAlliance_dx.exe")
    proc = Process(proc_name, config=resolver.cfg.get("safety", {}))
    resolver.proc = proc
    if not proc.attach():
        return 1
    if not args.quiet:
        print(f"attached base=0x{proc.base:X} modules={len(proc.modules)}")

    try:
        if args.check:
            ok = test_blocks(resolver, as_json=args.json)
            return 0 if ok else 2
        if args.field:
            v = resolver.read_field(args.field[0], args.field[1])
            if v is None:
                print("None (bloco/campo nao calibrado ou leitura falhou)")
                return 2
            print(_fmt(v))
            return 0
        if args.read:
            addr = parse_hex(args.read[0])
            size = parse_hex(args.read[1])
            data = proc.read(addr, size)
            if data is None:
                print("None (endereco invalido ou nao legivel)")
                return 2
            for i in range(0, len(data), 16):
                chunk = data[i:i + 16]
                hexpart = " ".join(f"{b:02X}" for b in chunk)
                asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                print(f"0x{addr + i:012X}  {hexpart:<47}  {asc}")
            return 0
        ok = test_blocks(resolver, as_json=args.json)
        return 0 if ok else 2
    except Exception:
        log.exception("run failed")
        return 1
    finally:
        proc.detach()


if __name__ == "__main__":
    sys.exit(main())
