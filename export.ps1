# export.ps1 — PokeAlliance bot file exporter (FASE 1)
# Writes every project file to the VM in one shot. No manual copy/paste.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File export.ps1                    # write all files
#   powershell -ExecutionPolicy Bypass -File export.ps1 -Verify            # write + SHA256 check
#   powershell -ExecutionPolicy Bypass -File export.ps1 -Destino D:\pokebot
#
# Adding a new file: append one entry to $Files with Name / Content / Sha256.
# Content MUST be a single-quoted here-string (@' ... '@). The closing '@
# must be at column 0 with no leading whitespace. Scan for delimiter
# collisions (lines that are exactly '@ or '@) before embedding — none of
# the current three files have any.
#
# -Verify normalizes both sides (strips UTF-8 BOM, converts CRLF -> LF)
# before hashing, so it passes identically on Windows PowerShell 5.1
# (Set-Content writes BOM + CRLF) and PowerShell 7 (no BOM, LF).

param(
    [string]$Destino = "C:\pokebot",
    [switch]$Verify
)

$ErrorActionPreference = "Stop"

# ─────────────────────────── embedded file contents ───────────────────────────

$offsets_json = @'
{
  "_meta": {
    "client_path": "C:\\PokeAlliance Games\\PokeAlliance\\PokeAlliance_dx.exe",
    "client_process": "PokeAlliance_dx.exe",
    "target": "PokeAlliance (OTClientV8 fork, build 2026-09-15)",
    "engine": "OTClientV8",
    "scanned_on": null,
    "client_build": "2026-09-15",
    "notes": [
      "All values start at 0x0 on purpose. memory.py treats any chain containing 0x0 as unresolved and returns None (fail-closed).",
      "Calibrate with scanner.py + diagnostico.py against the running client BEFORE enabling any module.",
      "Pointer chain format: [base_selector, step1, step2, ..., terminal_offset]. base_selector is a key into base_modules.",
      "AOB entries are {'pattern': hex string with ?? wildcards, 'module': base selector or null, 'resolve': how to turn the hit into an address: 'direct' | 'relative32' | 'ptr'}.",
      "Offsets are stored as hex STRINGS ('0x0') because JSON has no hex literal. memory.py parses them with int(value, 16); '0x0' / empty steps / null = unresolved = fail-closed."
    ]
  },

  "base_modules": {
    "client": {
      "name": "PokeAlliance_dx.exe",
      "resolve": "main_module",
      "note": "Main executable module. Base acquired at runtime by pymem."
    },
    "lua_engine": {
      "name": "lua51.dll",
      "resolve": "module",
      "optional": true,
      "note": "Present in most OTClientV8 builds. Game objects reachable through the Lua registry if direct structs are unresolvable."
    },
    "kernel32": {
      "name": "kernel32.dll",
      "resolve": "module",
      "note": "Used only for telemetry checks (QueryFullProcessImageNameW import), never for game state."
    }
  },

  "player": {
    "ptr_chain": {
      "base": "client",
      "steps": [],
      "terminal": "0x0",
      "aob_hint": null,
      "note": "Static pointer to the local player object, e.g. g_game -> LocalPlayer. Fill via AOB scan for the vtable or the 'Player' type string, then verify the pointer resolves to a heap object with sane coordinates."
    },
    "struct": {
      "size": "0x0",
      "fields": {
        "name":            { "offset": "0x0", "type": "string8",  "max_len": 32 },
        "id":              { "offset": "0x0", "type": "u32" },
        "hp":              { "offset": "0x0", "type": "u32" },
        "hp_max":          { "offset": "0x0", "type": "u32" },
        "mp":              { "offset": "0x0", "type": "u32" },
        "mp_max":          { "offset": "0x0", "type": "u32" },
        "level":           { "offset": "0x0", "type": "u32" },
        "x":               { "offset": "0x0", "type": "u16" },
        "y":               { "offset": "0x0", "type": "u16" },
        "z":               { "offset": "0x0", "type": "u8"  },
        "direction":       { "offset": "0x0", "type": "u8",  "enum": { "0": "north", "1": "east", "2": "south", "3": "west" } },
        "cap":             { "offset": "0x0", "type": "u32" },
        "soul":            { "offset": "0x0", "type": "u8",  "note": "In Pokemon forks often repurposed as a secondary resource; verify in diagnostico." },
        "stamina":         { "offset": "0x0", "type": "u8" },
        "is_online":       { "offset": "0x0", "type": "bool" },
        "is_dead":         { "offset": "0x0", "type": "bool" }
      }
    }
  },

  "creature_list": {
    "ptr_chain": {
      "base": "client",
      "steps": [],
      "terminal": "0x0",
      "note": "Pointer to the CreaturesMap / CreatureVector owned by g_game. OTClientV8 keeps an id->Creature map plus a vector of visible creatures."
    },
    "iter": {
      "size": "0x0",
      "id_stride": "0x0",
      "fields": {
        "creature_id":   { "offset": "0x0", "type": "u32" },
        "creature_ptr":  { "offset": "0x0", "type": "ptr" },
        "name":          { "offset": "0x0", "type": "string8", "max_len": 32 },
        "hp_percent":    { "offset": "0x0", "type": "u8", "note": "OTClient stores 0-100 percent, not raw HP, for non-self creatures." },
        "x":             { "offset": "0x0", "type": "u16" },
        "y":             { "offset": "0x0", "type": "u16" },
        "z":             { "offset": "0x0", "type": "u8" },
        "is_npc":        { "offset": "0x0", "type": "bool" },
        "is_player":     { "offset": "0x0", "type": "bool" },
        "is_dead":       { "offset": "0x0", "type": "bool" },
        "speed":         { "offset": "0x0", "type": "u32" }
      }
    },
    "aob_hint": null,
    "note": "Vector layout differs between OTClientV8 builds (map vs vector vs flat array). Calibrate iter.size and id_stride from a live creature count before trusting iteration."
  },

  "tile_map": {
    "ptr_chain": {
      "base": "client",
      "steps": [],
      "terminal": "0x0",
      "note": "g_map -> tile storage. Needed only if cavebot wants walkability checks; waypoint walking itself works off player coords alone."
    },
    "struct": {
      "size": "0x0",
      "fields": {
        "flags":       { "offset": "0x0", "type": "u32" },
        "walkable":    { "offset": "0x0", "type": "bit", "bit": 0, "note": "Bit position unverified; calibrate against a known wall/floor pair." },
        "has_creature":{ "offset": "0x0", "type": "bit", "bit": 1 }
      }
    }
  },

  "game_state": {
    "ptr_chain": {
      "base": "client",
      "steps": [],
      "terminal": "0x0",
      "note": "g_game itself. exposes isOnline, isDead, isTrading, whether a modal dialog is open."
    },
    "struct": {
      "size": "0x0",
      "fields": {
        "is_online":        { "offset": "0x0", "type": "bool" },
        "is_dead":          { "offset": "0x0", "type": "bool" },
        "is_trade_open":    { "offset": "0x0", "type": "bool" },
        "dialog_open":      { "offset": "0x0", "type": "bool" },
        "ping":             { "offset": "0x0", "type": "u32" },
        "server_name":      { "offset": "0x0", "type": "string8", "max_len": 64 }
      }
    }
  },

  "minimap": {
    "ptr_chain": { "base": "client", "steps": [], "terminal": "0x0", "note": "Optional. Used for position sanity checks only." },
    "struct": {
      "size": "0x0",
      "fields": {
        "center_x": { "offset": "0x0", "type": "u16" },
        "center_y": { "offset": "0x0", "type": "u16" },
        "center_z": { "offset": "0x0", "type": "u8"  }
      }
    }
  },

  "aob_signatures": {
    "g_game_static": {
      "module": "client",
      "_comment": {
        "origin": "Herdado de offsets.json/export.ps1; autor e fonte externa nao registrados; geracao pelo scanner nao comprovada",
        "status": "ASSUMPTION — not validated in memory",
        "intended_target": "ponteiro global g_game",
        "evidence": "Nenhuma confirmacao CE ao vivo registrada; buscas do scanner usam o arquivo em disco"
      },
      "pattern": "48 8B 0D ?? ?? ?? ?? 48 85 C9 74 ?? E8 ?? ?? ?? ??",
      "resolve": "relative32",
      "note": "RIP-relative load of the global g_game pointer. Classic MSVC pattern; adjust displacement position once you see the first hit."
    },
    "g_map_static": {
      "module": "client",
      "_comment": {
        "origin": "Herdado de offsets.json/export.ps1; autor e fonte externa nao registrados; geracao pelo scanner nao comprovada",
        "status": "ASSUMPTION — not validated in memory",
        "intended_target": "ponteiro global g_map",
        "evidence": "Nenhuma confirmacao CE ao vivo registrada; buscas do scanner usam o arquivo em disco"
      },
      "pattern": "48 8B 0D ?? ?? ?? ?? 48 8B 01 FF 50 ?? 48 8B",
      "resolve": "relative32",
      "note": "Same shape as g_game; distinguish by the call target after the null check."
    },
    "creature_vector": {
      "module": "client",
      "_comment": {
        "origin": "Herdado de offsets.json/export.ps1; autor e fonte externa nao registrados; geracao pelo scanner nao comprovada",
        "status": "ASSUMPTION — not validated in memory",
        "intended_target": "container/lista de criaturas",
        "evidence": "Nenhuma confirmacao CE ao vivo registrada; buscas do scanner usam o arquivo em disco"
      },
      "pattern": "48 8D 0D ?? ?? ?? ?? E8 ?? ?? ?? ?? 8B 0D ?? ?? ?? ??",
      "resolve": "relative32",
      "note": "lea rcx, [rip+disp] feeding a container clear/fill call."
    },
    "local_player_vtable": {
      "module": "client",
      "_comment": {
        "origin": "Herdado de offsets.json/export.ps1; autor e fonte externa nao registrados; geracao pelo scanner nao comprovada",
        "status": "ASSUMPTION — not validated in memory",
        "intended_target": "referencias de vtable de Player/LocalPlayer",
        "evidence": "Nenhuma confirmacao CE ao vivo registrada; buscas do scanner usam o arquivo em disco"
      },
      "pattern": "48 89 05 ?? ?? ?? ?? 48 89 05 ?? ?? ?? ?? C3",
      "resolve": "relative32",
      "note": "vtable stores for Player/LocalPlayer objects. Use the vtable address to locate constructor calls and walk back to the object pointer."
    },
    "name_string_ref": {
      "module": "client",
      "_comment": {
        "origin": "Herdado de offsets.json/export.ps1; autor e fonte externa nao registrados; geracao pelo scanner nao comprovada",
        "status": "ASSUMPTION — not validated in memory",
        "intended_target": "literal Player e referencias para investigar objetos Player",
        "evidence": "Nenhuma confirmacao CE ao vivo registrada; buscas do scanner usam o arquivo em disco"
      },
      "pattern": "?? ?? ?? ?? 50 6C 61 79 65 72 00",
      "resolve": "direct",
      "note": "'Player\\0' literal in .rdata. Follow xrefs from IDA/Ghidra or a runtime scan to find the code that writes to the name field; the field offset falls out of that."
    }
  },

  "telemetry_notes": {
    "build_2026_09_15": {
      "imports": ["NtQuerySystemInformation (dynamic, GetProcAddress)", "QueryFullProcessImageNameW (direct import)"],
      "interpretation": "Enumerates running processes and image paths. Consistent with logging or a soft ban list, not with an injection gate. External RPM via pymem remains unaffected.",
      "countermeasure": "None needed for read-only external access. Do not inject, do not create remote threads, do not load foreign DLLs into the client."
    }
  },

  "safety": {
    "max_read_bytes": 4096,
    "max_string_len": 256,
    "read_retries": 2,
    "invalid_addr_behavior": "return_none",
    "notes": [
      "memory.py clamps every read to max_read_bytes and validates the pointer before dereferencing.",
      "A zero step, a null pointer, or an address outside the module/heap range yields None, never a partial read.",
      "Modules treat None as 'unknown' and go idle rather than acting on stale state."
    ]
  }
}
'@

$config_json = @'
{
  "_meta": {
    "version": 1,
    "last_calibrated": null,
    "notes": [
      "Hotkeys are sent to the CLIENT WINDOW, not handled globally, unless 'global_hotkeys' is true.",
      "SendInput uses scancodes (KEYEVENTF_SCANCODE) to survive clients that ignore virtual-key events.",
      "Every module honors 'stop_on_death' and the shared stop event from context.py."
    ]
  },

  "client": {
    "window_title_pattern": "PokeAlliance",
    "window_class": null,
    "process_name": "PokeAlliance_dx.exe",
    "focus_before_input": true,
    "refocus_delay_ms": 120,
    "click_delay_ms": 45,
    "key_delay_ms": 30
  },

  "modules": {
    "healer":      { "enabled": true,  "tick_ms": 400 },
    "auto_food":   { "enabled": true,  "tick_ms": 1000 },
    "cavebot":     { "enabled": false, "tick_ms": 200 },
    "auto_target": { "enabled": false, "tick_ms": 300 },
    "auto_catch":  { "enabled": false, "tick_ms": 250 },
    "alarms":      { "enabled": true,  "tick_ms": 250 }
  },

  "healer": {
    "hp_percent_threshold": 60,
    "hp_above_percent": 85,
    "mp_percent_threshold": 40,
    "mp_above_percent": 90,
    "hp_hotkey": "F1",
    "mp_hotkey": "F2",
    "delay_between_heals_ms": 650,
    "panic_hp_percent": 25,
    "panic_hotkey": "F3",
    "panic_delay_ms": 250,
    "note": "Hysteresis pair: heal below threshold, stop at above_threshold, prevents hotkey spam oscillation."
  },

  "auto_food": {
    "interval_seconds": 60,
    "jitter_seconds": 8,
    "food_hotkey": "F4",
    "pause_when_hp_below_percent": 30,
    "note": "Jitter prevents a metronomic eating pattern. Pause while critical so healer gets the input bus."
  },

  "cavebot": {
    "waypoints_file": "waypoints.json",
    "walk_mode": "key_hold",
    "key_hold_ms": 90,
    "arrive_tolerance_tiles": 1,
    "max_seconds_per_leg": 6,
    "stuck_retry_count": 3,
    "stuck_threshold_ms": 1500,
    "pause_on_creature_within_tiles": 2,
    "resume_after_combat_seconds": 4,
    "walk_keys": { "north": "Up", "south": "Down", "east": "Right", "west": "Left" },
    "note": "walk_mode 'key_hold' sends direction scancodes for key_hold_ms and re-checks position from memory. 'click_tile' needs calibrated tile_map and stays off until offsets land."
  },

  "auto_target": {
    "attack_range_tiles": 7,
    "attack_cooldown_ms": 900,
    "attack_hotkey": "F5",
    "target_mode": "attack_hotkey",
    "prioritize": "lowest_hp_percent",
    "ignore_players": true,
    "ignore_npcs": true,
    "ignore_dead": true,
    "name_whitelist": [],
    "name_blacklist": ["Gary"],
    "min_level": 1,
    "chase_enabled": false,
    "note": "target_mode 'attack_hotkey' presses the client's attack key on a selected creature. 'click_creature' needs calibrated screen projection, added later."
  },

  "auto_catch": {
    "enabled_creature_names": ["Pikachu", "Charmander", "Bulbasaur", "Squirtle"],
    "catch_ball_hotkey": "F6",
    "throw_count": 3,
    "throw_delay_ms": 750,
    "only_after_kill": true,
    "stop_when_hp_above_percent": 60,
    "note": "Waits for target death flag in memory, then fires the configured ball hotkey throw_count times with jittered delay."
  },

  "alarms": {
    "check_interval_ms": 250,
    "beep_on": ["death", "disconnect", "gm_detected"],
    "beep_pattern": { "count": 5, "interval_ms": 180 },
    "webhook_on": ["death", "disconnect", "gm_detected", "low_hp"],
    "low_hp_percent": 20,
    "gm_name_patterns": [".*[Gg]amemaster.*", ".*[Gg]od[Aa]ccess.*", ".*[Ss]erver.*[Aa]dmin.*"],
    "gm_scan_radius_tiles": 12,
    "disconnect_grace_seconds": 8,
    "note": "disconnect grace avoids false positives during normal loading screens."
  },

  "notify": {
    "webhook_enabled": false,
    "webhook_url": "",
    "webhook_username": "PokeAlliance Bot",
    "mention_on_critical": false,
    "mention_string": "",
    "timeout_seconds": 8,
    "rate_limit_per_minute": 20,
    "note": "Left disabled by default. Fill the URL and flip enabled when you want Discord pings."
  },

  "hotkeys": {
    "global_hotkeys": false,
    "panic_stop": "F12",
    "panic_stop_mode": "keyboard_hook",
    "note": "panic_stop works even when the client doesn't have focus. F12 immediately sets the shared stop event and releases all held keys."
  },

  "runtime": {
    "log_level": "INFO",
    "log_file": "pokebot.log",
    "log_max_bytes": 2097152,
    "log_backup_count": 3,
    "state_dump_seconds": 30,
    "fail_closed_default": true,
    "stop_on_death": true,
    "stop_on_disconnect": true
  },

  "safety_limits": {
    "max_threads": 8,
    "input_bus_queue_max": 32,
    "memory_read_interval_ms": 150,
    "min_interval_between_inputs_ms": 25,
    "notes": [
      "input_bus_queue_max is a hard cap; overflow drops the request and logs, never blocks a module thread.",
      "min_interval_between_inputs_ms is enforced inside inputbus so two modules can't stroke the client even if a priority bug slips through."
    ]
  }
}
'@

$memory_py = @'
# pokebot/memory.py
"""PokeAlliance external memory layer (FASE 1 / 03).

Read-only external access via pymem. No injection, no DLL load, no remote
threads -- the client's telemetry build (NtQuerySystemInformation +
QueryFullProcessImageNameW) enumerates processes/paths, which does not
interfere with OpenProcess + ReadProcessMemory.

Fail-closed contract:
  * every public method returns None (bool False for is_valid_addr) on
    failure -- no exceptions cross the public surface
  * "unresolved" is decided on the PARSED value (parse_hex(...) == 0),
    never on the raw string
  * offsets.json values arrive as hex strings ("0x0", "0x1a4") or bare
    JSON numbers; both are accepted
  * no partial reads, no zero-filled structs, no garbage returns

Offset blocks in offsets.json sit at the TOP LEVEL of the file
(player, creature_list, tile_map, game_state, minimap) -- they are NOT
nested under a "blocks" key. BLOCK_KEYS below is the single source of
truth for which top-level keys are treated as addressable blocks.
"""
from __future__ import annotations

import json
import logging
import os
import sys
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

    # -- lifecycle ---------------------------------------------------------
    def attach(self) -> bool:
        if not PYMEM_AVAILABLE:
            log.error("pymem not installed -- pip install pymem")
            return False
        try:
            self.pm = pymem.Pymem(self.process_name)
        except Exception as exc:
            log.error("attach failed for %s: %s", self.process_name, exc)
            return False
        try:
            main = self.pm.process_base
            self.base = int(main.lpBaseOfDll)
            self.base_size = int(main.SizeOfImage)
            log.info("attached to %s base=0x%X size=0x%X",
                     self.process_name, self.base, self.base_size)
        except Exception as exc:
            log.error("cannot read main module info: %s", exc)
            return False
        self.modules = {}
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
        if self.pm is not None:
            try:
                self.pm.close_process()
            except Exception:
                pass
            self.pm = None
        self._regions = []

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
            log.debug("read: refusing invalid/unreadable addr 0x%X", addr)
            return None
        try:
            return self.pm.read_bytes(addr, size)
        except Exception as exc:
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
    """Turns offsets.json into resolved struct addresses and typed fields."""

    def __init__(self, process: Process, offsets_path=DEFAULT_OFFSETS_PATH,
                 config_path=DEFAULT_CONFIG_PATH):
        self.proc = process
        self.offsets_path = _normalize_cfg_path(offsets_path)
        self.cfg = self._load_config(config_path)
        self.data = self._load_offsets()
        # Blocks live at the TOP LEVEL of offsets.json, not under "blocks".
        self.blocks = {k: self.data[k] for k in BLOCK_KEYS if k in self.data}
        missing = [k for k in BLOCK_KEYS if k not in self.data]
        if missing:
            log.warning("offsets.json missing block keys: %s", ", ".join(missing))
        log.info("loaded %d offset blocks: %s",
                 len(self.blocks), ", ".join(self.blocks.keys()))
        self.safety = self.data.get("safety", {}) or {}
        self._module_cache = {}

    @staticmethod
    def _load_config(path):
        p = _normalize_cfg_path(path)
        try:
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:
            log.warning("config.json not loaded (%s) -- using defaults", exc)
            return {}

    def _load_offsets(self):
        try:
            with open(self.offsets_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:
            log.error("offsets.json not loadable (%s)", exc)
            return {}

    # -- module base resolution -------------------------------------------
    def resolve_module(self, selector):
        """selector -> (base, size) from base_modules. None if absent/unloaded."""
        if not selector:
            return None
        if selector in self._module_cache:
            return self._module_cache[selector]
        entry = self.data.get("base_modules", {}).get(selector)
        if not entry:
            log.warning("base module '%s' not declared in offsets.json", selector)
            return None
        name = str(entry.get("name", "")).lower()
        kind = entry.get("resolve", "module")
        if kind == "main_module":
            result = (self.proc.base, self.proc.base + self.proc.base_size) \
                if self.proc.base else None
        else:
            mod = self.proc.modules.get(name)
            if not mod:
                if entry.get("optional"):
                    log.debug("optional module '%s' not loaded", name)
                else:
                    log.warning("required module '%s' is not loaded in the client", name)
                result = None
            else:
                result = (mod["base"], mod["base"] + mod["size"])
        self._module_cache[selector] = result
        return result

    # -- pointer chains ----------------------------------------------------
    def resolve_block(self, name):
        """Follow ptr_chain for a named block. None == unresolved (fail-closed).

        steps: read u64 at (addr + step) for every element except the last;
        the last element is the terminal offset ADDED to the current address.
        Any parsed step == 0 -> 'campo X nao calibrado' -> None.
        """
        try:
            block = self.blocks.get(name)
            if not block:
                log.error("block '%s' does not exist in offsets.json", name)
                return None
            chain = block.get("ptr_chain") or {}
            base_sel = chain.get("base")
            steps = chain.get("steps") or []
            if len(steps) > MAX_CHAIN_DEPTH:
                log.error("block '%s': chain has %d steps (> %d) -- refusing",
                          name, len(steps), MAX_CHAIN_DEPTH)
                return None

            parsed = []
            for i, raw in enumerate(steps):
                try:
                    v = parse_hex(raw)
                except ValueError as exc:
                    log.warning("block '%s' step %d unreadable (%s) -- nao calibrado",
                                name, i, exc)
                    return None
                if v == 0:
                    log.warning("campo %s.step[%d] nao calibrado (0x0)", name, i)
                    return None
                parsed.append(v)
            if not parsed:
                log.warning("campo %s nao calibrado (ptr_chain.steps vazio)", name)
                return None
            terminal = parsed[-1]
            walk = parsed[:-1]

            base_range = self.resolve_module(base_sel)
            if base_range:
                addr = base_range[0]
                log.debug("block '%s': base '%s' -> 0x%X", name, base_sel, addr)
            else:
                # No declared module: last resort, the chain starts with an
                # absolute address only if that address is actually readable.
                if terminal == 0 or not self.proc.is_valid_addr(terminal):
                    log.warning("block '%s': base module '%s' unresolved "
                                "e terminal 0x%X nao e legivel -- desligado",
                                name, base_sel, terminal)
                    return None
                addr = terminal
                terminal = 0
                log.warning("block '%s': using bare-address fallback (calibrate "
                            "base_modules)", name)

            for i, step in enumerate(walk):
                nxt = self.proc.read_u64(addr + step)
                if nxt is None:
                    log.warning("block '%s': step %d leitura falhou "
                                "(0x%X + 0x%X) -- nao calibrado ou invalido",
                                name, i, addr, step)
                    return None
                if nxt == 0:
                    log.warning("block '%s': step %d devolveu ponteiro nulo "
                                "-- nao calibrado", name, i)
                    return None
                addr = nxt

            final = addr + terminal
            if not self.proc.is_valid_addr(final):
                log.warning("block '%s': endereco final 0x%X nao e legivel", name, final)
                return None
            log.info("block '%s' resolvido em 0x%X", name, final)
            return final
        except Exception:
            log.exception("resolve_block(%s) unexpected failure", name)
            return None

    def _field_def(self, name, field_name):
        block = self.blocks.get(name)
        if not block:
            return None
        struct = block.get("struct") or block.get("iter") or {}
        f = (struct.get("fields") or {}).get(field_name)
        if not f:
            log.error("field '%s' not declared in block '%s'", field_name, name)
            return None
        return f

    def read_field(self, block_name, field_name, base_addr=None):
        """Typed field read. None if block, field, offset or bytes are unusable."""
        try:
            f = self._field_def(block_name, field_name)
            if not f:
                return None
            off = parse_hex(f.get("offset", 0))
            if off == 0:
                log.warning("campo %s.%s nao calibrado (offset 0x0)",
                            block_name, field_name)
                return None
            base = base_addr if base_addr is not None else self.resolve_block(block_name)
            if base is None:
                return None
            return self._read_by_type(base + off, f)
        except Exception:
            log.exception("read_field(%s.%s) unexpected failure",
                          block_name, field_name)
            return None

    def _read_by_type(self, addr, f):
        t = str(f.get("type", "")).lower()
        if t in ("u8", "byte"):
            return self.proc.read_u8(addr)
        if t in ("u16", "word"):
            return self.proc.read_u16(addr)
        if t in ("u32", "dword", "int"):
            return self.proc.read_u32(addr)
        if t in ("i32", "signed_dword"):
            return self.proc.read_i32(addr)
        if t in ("u64", "qword"):
            return self.proc.read_u64(addr)
        if t in ("bool", "boolean"):
            return self.proc.read_bool(addr)
        if t in ("ptr", "address"):
            return self.proc.read_u64(addr)
        if t in ("string8", "string", "cstring"):
            max_len = f.get("max_len", 32)
            try:
                max_len = int(max_len)
            except (TypeError, ValueError):
                max_len = 32
            return self.proc.read_string(addr, max_len)
        if t == "bit":
            v = self.proc.read_u8(addr)
            if v is None:
                return None
            try:
                bit = int(f.get("bit", 0))
            except (TypeError, ValueError):
                bit = 0
            return bool(v & (1 << bit))
        log.error("unknown field type %r -- refusing to guess", t)
        return None

    def read_fields(self, block_name, field_names=None, base_addr=None):
        """Named fields of a block -> dict. Block unresolved -> None (fail-closed)."""
        try:
            base = base_addr if base_addr is not None else self.resolve_block(block_name)
            if base is None:
                return None
            block = self.blocks.get(block_name) or {}
            struct = block.get("struct") or block.get("iter") or {}
            names = list(field_names) if field_names else list((struct.get("fields") or {}).keys())
            out = {}
            for fn in names:
                out[fn] = self.read_field(block_name, fn, base_addr=base)
            return out
        except Exception:
            log.exception("read_fields(%s) unexpected failure", block_name)
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
    names = list(resolver.blocks.keys())
    resolved = {}
    for n in names:
        addr = resolver.resolve_block(n)
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
    proc = Process(proc_name, config=resolver.data.get("safety", {}))
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
'@

# ─────────────────────────── file manifest ───────────────────────────
# Sha256 values are LF-normalized, BOM-stripped hashes of the embedded
# content. -Verify applies the same normalization to the written file,
# so the check is stable across PowerShell 5.1 (BOM+CRLF) and 7 (no BOM).

$Files = @(
    @{ Name = "offsets.json"; Content = $offsets_json; Sha256 = "a50382aae70b66a5390206f90ff2fe75bb695902e336d642960b0df0905aeae4" },
    @{ Name = "config.json";  Content = $config_json;  Sha256 = "9a0678179fe29e2b79001c8fa3be30c91c9f72a62bcf72ff75bdb3b7122713ae" },
    @{ Name = "memory.py";    Content = $memory_py;    Sha256 = "1674a220da7d4a09115748b461843e713e2629a84c5798e0472fa0c581a5079f" }
)

# ─────────────────────────── helpers ───────────────────────────

function Get-NormHash {
    param([string]$Path)
    $bytes = [System.IO.File]::ReadAllBytes($Path)
    if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        $bytes = $bytes[3..($bytes.Length - 1)]
    }
    $text = [System.Text.Encoding]::UTF8.GetString($bytes) -replace "`r`n", "`n"
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $hash = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($text))
    return (($hash | ForEach-Object { $_.ToString("x2") }) -join "")
}

function Invoke-Export {
    if (-not (Test-Path -LiteralPath $Destino)) {
        New-Item -ItemType Directory -Path $Destino -Force | Out-Null
    }
    $enc = New-Object System.Text.UTF8Encoding($false)   # no BOM, PS5.1 + PS7
    foreach ($f in $Files) {
        $path = Join-Path $Destino $f.Name
        # A here-string loses the newline that precedes its closing '@ --
        # without this, every exported file comes back exactly 1 byte short.
        $text = $f.Content
        if (-not $text.EndsWith("`n")) { $text += "`n" }
        [System.IO.File]::WriteAllText($path, $text, $enc)
        $size = (Get-Item -LiteralPath $path).Length
        Write-Host ("{0,-14} -> {1}  ({2} bytes)" -f $f.Name, $path, $size)
    }
}

function Test-Hashes {
    $ok = $true
    foreach ($f in $Files) {
        $path = Join-Path $Destino $f.Name
        $got = Get-NormHash -Path $path
        if ($got -eq $f.Sha256) {
            Write-Host ("OK      {0}" -f $f.Name)
        } else {
            Write-Host ("MISMATCH {0}" -f $f.Name)
            Write-Host ("   esperado: {0}" -f $f.Sha256)
            Write-Host ("   obtido:   {0}" -f $got)
            $ok = $false
        }
    }
    return $ok
}

function Test-PyCompile {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        Write-Host "python nao encontrado no PATH -- py_compile pulado"
        return
    }
    # The Windows Store alias answers to 'python' but cannot execute code
    # (exit 49). Probe it for real before trusting it. EA=SilentlyContinue:
    # WinPS 5.1 turns native stderr into a terminating error under Stop.
    $eap = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    & python -c "pass" 2>$null
    $probeExit = $LASTEXITCODE
    $ErrorActionPreference = $eap
    if ($probeExit -ne 0) {
        Write-Host "python no PATH e o alias da Microsoft Store (nao executa) -- py_compile pulado"
        return
    }
    $target = Join-Path $Destino "memory.py"
    Write-Host "py_compile: $target"
    $out = & python -m py_compile $target 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "py_compile OK"
    } else {
        Write-Host "py_compile FALHOU:"
        $out | ForEach-Object { Write-Host $_ }
        exit 1
    }
}

# ─────────────────────────── main ───────────────────────────

Invoke-Export

if ($Verify) {
    if (-not (Test-Hashes)) {
        exit 1
    }
}

Test-PyCompile

# The Store-stub probe can leave $LASTEXITCODE=9009 behind even after the
# EAP restore -- pin a clean exit so callers see 0 on success.
$global:LASTEXITCODE = 0
