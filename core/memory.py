"""
core/memory.py - Low-level Windows process memory reader/writer.

Provides robust process attachment via Win32 API (kernel32/psapi via ctypes),
module base resolution, typed scalar reading/writing, and pointer-chain
resolution matching offsets.schema.json.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import logging
import os
import struct
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

log = logging.getLogger("pokebot.core.memory")

# ---------------------------------------------------------------------------
# Win32 Constants & Type Definitions
# ---------------------------------------------------------------------------
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008

STANDARD_RIGHTS_REQUIRED = 0x000F0000
SYNCHRONIZE = 0x00100000
PROCESS_ALL_ACCESS = STANDARD_RIGHTS_REQUIRED | SYNCHRONIZE | 0xFFFF

TH32CS_SNAPPROCESS = 0x00000002
LIST_MODULES_ALL = 0x03
MAX_PATH = 260

MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100

READABLE_PAGE_PROTECTIONS = (
    0x02,  # PAGE_READONLY
    0x04,  # PAGE_READWRITE
    0x20,  # PAGE_EXECUTE_READ
    0x40,  # PAGE_EXECUTE_READWRITE
)

WRITABLE_PAGE_PROTECTIONS = (
    0x04,  # PAGE_READWRITE
    0x08,  # PAGE_WRITECOPY
    0x40,  # PAGE_EXECUTE_READWRITE
    0x80,  # PAGE_EXECUTE_WRITECOPY
)

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
user32.EnumWindows.restype = wt.BOOL
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindowVisible.restype = wt.BOOL
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wt.BOOL


def _window_titles() -> dict[int, list[str]]:
    """Visible top-level titles grouped by PID, without opening processes."""
    titles = {}

    @WNDENUMPROC
    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            size = user32.GetWindowTextLengthW(hwnd)
            if size:
                buf = ctypes.create_unicode_buffer(size + 1)
                if user32.GetWindowTextW(hwnd, buf, size + 1):
                    pid = wt.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    titles.setdefault(pid.value, []).append(buf.value)
        return True

    if not user32.EnumWindows(visit, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return titles


def _process_path(pid: int) -> Optional[str]:
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        size = wt.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return buf.value
        return None
    finally:
        kernel32.CloseHandle(handle)


# Process Entry for Toolhelp32
class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", wt.WCHAR * MAX_PATH),
    ]

# Module Info
class MODULEINFO(ctypes.Structure):
    _fields_ = [
        ("lpBaseOfDll", ctypes.c_void_p),
        ("SizeOfImage", wt.DWORD),
        ("EntryPoint", ctypes.c_void_p),
    ]

# Memory Basic Information 64-bit
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

# Explicit Win32 function signatures for 64-bit safety
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE

kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL

kernel32.ReadProcessMemory.argtypes = [
    wt.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.ReadProcessMemory.restype = wt.BOOL

kernel32.WriteProcessMemory.argtypes = [
    wt.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
kernel32.WriteProcessMemory.restype = wt.BOOL

kernel32.VirtualQueryEx.argtypes = [
    wt.HANDLE,
    ctypes.c_void_p,
    ctypes.c_void_p,
    ctypes.c_size_t,
]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t

kernel32.IsWow64Process.argtypes = [wt.HANDLE, ctypes.POINTER(wt.BOOL)]
kernel32.IsWow64Process.restype = wt.BOOL

kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE

kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32FirstW.restype = wt.BOOL

kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.restype = wt.BOOL

psapi.EnumProcessModulesEx.argtypes = [
    wt.HANDLE,
    ctypes.POINTER(ctypes.c_void_p),
    wt.DWORD,
    ctypes.POINTER(wt.DWORD),
    wt.DWORD,
]
psapi.EnumProcessModulesEx.restype = wt.BOOL

psapi.EnumProcessModules.argtypes = [
    wt.HANDLE,
    ctypes.POINTER(ctypes.c_void_p),
    wt.DWORD,
    ctypes.POINTER(wt.DWORD),
]
psapi.EnumProcessModules.restype = wt.BOOL

psapi.GetModuleBaseNameW.argtypes = [
    wt.HANDLE,
    ctypes.c_void_p,
    wt.LPWSTR,
    wt.DWORD,
]
psapi.GetModuleBaseNameW.restype = wt.DWORD

psapi.GetModuleInformation.argtypes = [
    wt.HANDLE,
    ctypes.c_void_p,
    ctypes.POINTER(MODULEINFO),
    wt.DWORD,
]
psapi.GetModuleInformation.restype = wt.BOOL


# ---------------------------------------------------------------------------
# MemoryReader Class
# ---------------------------------------------------------------------------
class MemoryReader:
    """Manages process attachment, memory reading/writing, and pointer resolution."""

    TYPE_SPECS: Dict[str, Tuple[str, int]] = {
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

    def __init__(self, target_process: Union[str, int] = "PokeAlliance_dx.exe", *,
                 fallback_names: Optional[List[str]] = None,
                 window_title_pattern: Optional[str] = None) -> None:
        self.fallback_names = list(fallback_names or [])
        self.window_title_pattern = window_title_pattern
        self.target: Union[str, int] = target_process
        self.pid: Optional[int] = None
        self.handle: Optional[int] = None
        self.is_64bit: bool = True
        self.pointer_size: int = 8
        self.ptr_format: str = "<Q"
        self.main_module_base: int = 0
        self.main_module_size: int = 0
        self.modules: Dict[str, Dict[str, int]] = {}
        self.last_error: Optional[str] = None

    def __enter__(self) -> MemoryReader:
        self.attach()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.detach()

    # -- Lifecycle & Process Management -------------------------------------
    @staticmethod
    def require_admin() -> bool:
        """Retorna se o processo atual executa como Administrador."""
        is_user_an_admin = ctypes.windll.shell32.IsUserAnAdmin
        is_user_an_admin.argtypes = []
        is_user_an_admin.restype = wt.BOOL
        return bool(is_user_an_admin())

    def attach(self) -> bool:
        """Finds PID, opens process handle, detects arch and caches modules."""
        self.detach()
        self.last_error = None

        if isinstance(self.target, int):
            self.pid = self.target
        else:
            try:
                self.pid = self._find_pid_by_name(str(self.target))
                if not self.pid:
                    self.pid = self._find_pid_by_candidates(self.fallback_names)
                if not self.pid and self.window_title_pattern:
                    self.pid = self._find_pid_by_window_title(self.window_title_pattern)
                    if self.pid:
                        log.info("Process discovered by window title: PID=%d pattern=%r "
                                 "(possible renamed client; launcher not confirmed)",
                                 self.pid, self.window_title_pattern)
            except OSError as exc:
                self.last_error = f"Process discovery failed: {exc}"
                log.error(self.last_error)
                return False

        if not self.pid:
            self.last_error = (f"Process not found: target={self.target!r}, "
                               f"fallback_names={self.fallback_names!r}, "
                               f"window_title_pattern={self.window_title_pattern!r}")
            log.error(self.last_error)
            return False

        desired_access = (
            PROCESS_VM_READ
            | PROCESS_VM_WRITE
            | PROCESS_VM_OPERATION
            | PROCESS_QUERY_INFORMATION
        )
        h_proc = kernel32.OpenProcess(desired_access, False, self.pid)
        initial_error = ctypes.get_last_error() if not h_proc else 0
        if not h_proc:
            # Fallback to read-only access if write permission is rejected
            desired_access = PROCESS_VM_READ | PROCESS_QUERY_INFORMATION
            h_proc = kernel32.OpenProcess(desired_access, False, self.pid)

        if not h_proc:
            err = ctypes.get_last_error()
            if err == 5 or initial_error == 5:
                self.last_error = "acesso negado — execute o bot como Administrador"
            else:
                self.last_error = f"OpenProcess failed for PID {self.pid} (error code: {err})"
            log.error(self.last_error)
            return False

        self.handle = h_proc
        self._detect_architecture()
        self._enumerate_modules()

        if self.main_module_base == 0:
            self.last_error = "Could not resolve main module base address"
            log.error(self.last_error)
            self.detach()
            return False

        log.info(
            "Attached to '%s' (PID=%d, Arch=%s, Base=0x%X, Modules=%d)",
            self.target,
            self.pid,
            "x64" if self.is_64bit else "x86",
            self.main_module_base,
            len(self.modules),
        )
        return True

    def detach(self) -> None:
        """Closes open process handle and resets state."""
        if self.handle:
            try:
                kernel32.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None
        self.pid = None
        self.main_module_base = 0
        self.main_module_size = 0
        self.modules.clear()

    @property
    def is_attached(self) -> bool:
        return self.handle is not None and self.main_module_base != 0

    # -- Internal Inspection Helpers ----------------------------------------
    @staticmethod
    def _process_rows() -> list[dict]:
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snapshot in (None, 0, -1, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        rows = []
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        try:
            success = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while success:
                rows.append({"pid": int(entry.th32ProcessID), "name": entry.szExeFile})
                success = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
            error = ctypes.get_last_error()
            if error != 18:  # ERROR_NO_MORE_FILES
                raise ctypes.WinError(error)
        finally:
            kernel32.CloseHandle(snapshot)
        return rows

    def _find_pid_by_name(self, name: str) -> Optional[int]:
        name = name.strip().casefold()
        return next((row["pid"] for row in self._process_rows()
                     if row["name"].casefold() == name), None)

    def _find_pid_by_candidates(self, candidates: list[str]) -> Optional[int]:
        for name in candidates:
            pid = self._find_pid_by_name(name)
            if pid:
                return pid
        return None

    def _find_pid_by_window_title(self, pattern: str) -> Optional[int]:
        if not pattern.strip():
            return None
        pattern = pattern.casefold()
        return next((pid for pid, titles in _window_titles().items()
                     if any(pattern in title.casefold() for title in titles)), None)

    @staticmethod
    def list_candidate_processes(keyword: str) -> list[dict]:
        """Match process names or visible top-level window titles, case-insensitively.

        Protected/exited processes may have path=None. Enumeration errors raise
        OSError rather than being misreported as an empty process list.
        """
        keyword = keyword.casefold()
        titles = _window_titles()
        result = []
        for row in MemoryReader._process_rows():
            windows = titles.get(row["pid"], [])
            matches = [title for title in windows if keyword in title.casefold()]
            if keyword in row["name"].casefold() or matches:
                result.append({**row, "title": next(iter(matches or windows), ""),
                               "path": _process_path(row["pid"])})
        return result

    def _detect_architecture(self) -> None:
        """Determines if target process is 32-bit (WoW64) or native 64-bit."""
        is_wow64 = wt.BOOL(False)
        if kernel32.IsWow64Process(self.handle, ctypes.byref(is_wow64)):
            self.is_64bit = not bool(is_wow64.value)
        else:
            self.is_64bit = True

        self.pointer_size = 8 if self.is_64bit else 4
        self.ptr_format = "<Q" if self.is_64bit else "<I"

    def _enumerate_modules(self) -> None:
        """Lists all modules loaded in process and maps their bases and sizes."""
        self.modules.clear()
        max_mods = 1024
        h_mods = (ctypes.c_void_p * max_mods)()
        cb_needed = wt.DWORD()

        enum_flags = LIST_MODULES_ALL
        success = psapi.EnumProcessModulesEx(
            self.handle,
            h_mods,
            ctypes.sizeof(h_mods),
            ctypes.byref(cb_needed),
            enum_flags,
        )
        if not success:
            success = psapi.EnumProcessModules(
                self.handle,
                h_mods,
                ctypes.sizeof(h_mods),
                ctypes.byref(cb_needed),
            )
            if not success:
                return

        mod_count = cb_needed.value // ctypes.sizeof(ctypes.c_void_p)
        base_name_buf = ctypes.create_unicode_buffer(MAX_PATH)

        for i in range(min(mod_count, max_mods)):
            h_mod = h_mods[i]
            if not h_mod:
                continue

            length = psapi.GetModuleBaseNameW(
                self.handle, ctypes.c_void_p(h_mod), base_name_buf, MAX_PATH
            )
            if length == 0:
                continue

            mod_name = base_name_buf.value.lower()
            mod_info = MODULEINFO()
            if psapi.GetModuleInformation(
                self.handle,
                ctypes.c_void_p(h_mod),
                ctypes.byref(mod_info),
                ctypes.sizeof(MODULEINFO),
            ):
                base_addr = int(mod_info.lpBaseOfDll) if mod_info.lpBaseOfDll else 0
                size = int(mod_info.SizeOfImage)
                if base_addr:
                    self.modules[mod_name] = {"base": base_addr, "size": size}
                    if i == 0 or self.main_module_base == 0:
                        self.main_module_base = base_addr
                        self.main_module_size = size

    def get_module_base(self, module_name: Optional[str] = None) -> Optional[int]:
        """Returns base address for specified module or main module by default."""
        if not module_name:
            return self.main_module_base if self.main_module_base else None

        mod = self.modules.get(module_name.lower().strip())
        if mod:
            return mod["base"]
        return None

    def is_valid_address(self, address: int, write: bool = False) -> bool:
        """Probes address page state and protection flags via VirtualQueryEx."""
        if not self.handle or address <= 0x10000:
            return False

        mbi = MEMORY_BASIC_INFORMATION64()
        res = kernel32.VirtualQueryEx(
            self.handle,
            ctypes.c_void_p(address),
            ctypes.byref(mbi),
            ctypes.sizeof(mbi),
        )
        if res == 0:
            return False

        if mbi.State != MEM_COMMIT or (mbi.Protect & PAGE_GUARD) or (mbi.Protect & PAGE_NOACCESS):
            return False

        allowed = WRITABLE_PAGE_PROTECTIONS if write else READABLE_PAGE_PROTECTIONS
        return bool(mbi.Protect & sum(allowed))

    # -- Raw Reading & Writing ----------------------------------------------
    def read_bytes(self, address: int, size: int) -> Optional[bytes]:
        """Reads raw byte buffer from process memory."""
        if not self.handle or address <= 0 or size <= 0:
            return None

        buf = (ctypes.c_char * size)()
        bytes_read = ctypes.c_size_t(0)

        success = kernel32.ReadProcessMemory(
            self.handle,
            ctypes.c_void_p(address),
            ctypes.byref(buf),
            size,
            ctypes.byref(bytes_read),
        )
        if not success or bytes_read.value != size:
            return None
        return bytes(buf)

    def write_bytes(self, address: int, data: bytes) -> bool:
        """Writes raw byte buffer to process memory."""
        if not self.handle or address <= 0 or not data:
            return False

        size = len(data)
        buf = (ctypes.c_char * size).from_buffer_copy(data)
        bytes_written = ctypes.c_size_t(0)

        success = kernel32.WriteProcessMemory(
            self.handle,
            ctypes.c_void_p(address),
            ctypes.byref(buf),
            size,
            ctypes.byref(bytes_written),
        )
        return bool(success and bytes_written.value == size)

    # -- Typed Scalar Readers -----------------------------------------------
    def _read_unpack(self, address: int, fmt: str, size: int) -> Optional[Any]:
        raw = self.read_bytes(address, size)
        if raw is None or len(raw) != size:
            return None
        try:
            return struct.unpack(fmt, raw)[0]
        except struct.error:
            return None

    def read_int8(self, address: int) -> Optional[int]:
        return self._read_unpack(address, "<b", 1)

    def read_uint8(self, address: int) -> Optional[int]:
        return self._read_unpack(address, "<B", 1)

    def read_int16(self, address: int) -> Optional[int]:
        return self._read_unpack(address, "<h", 2)

    def read_uint16(self, address: int) -> Optional[int]:
        return self._read_unpack(address, "<H", 2)

    def read_int32(self, address: int) -> Optional[int]:
        return self._read_unpack(address, "<i", 4)

    def read_uint32(self, address: int) -> Optional[int]:
        return self._read_unpack(address, "<I", 4)

    def read_int64(self, address: int) -> Optional[int]:
        return self._read_unpack(address, "<q", 8)

    def read_uint64(self, address: int) -> Optional[int]:
        return self._read_unpack(address, "<Q", 8)

    def read_float(self, address: int) -> Optional[float]:
        return self._read_unpack(address, "<f", 4)

    def read_double(self, address: int) -> Optional[float]:
        return self._read_unpack(address, "<d", 8)

    def read_ptr(self, address: int) -> Optional[int]:
        """Reads pointer based on target architecture pointer width."""
        return self._read_unpack(address, self.ptr_format, self.pointer_size)

    def read_string(
        self, address: int, max_length: int = 256, encoding: str = "utf-8"
    ) -> Optional[str]:
        """Reads null-terminated ASCII/UTF-8 string from memory."""
        data = self.read_bytes(address, max_length)
        if not data:
            return None

        null_idx = data.find(b"\x00")
        if null_idx != -1:
            data = data[:null_idx]

        try:
            return data.decode(encoding, errors="replace")
        except Exception:
            return None

    # -- Typed Scalar Writers -----------------------------------------------
    def _write_pack(self, address: int, fmt: str, value: Any) -> bool:
        try:
            data = struct.pack(fmt, value)
        except (struct.error, TypeError, OverflowError):
            return False
        return self.write_bytes(address, data)

    def write_int8(self, address: int, value: int) -> bool:
        return self._write_pack(address, "<b", int(value))

    def write_uint8(self, address: int, value: int) -> bool:
        return self._write_pack(address, "<B", int(value))

    def write_int16(self, address: int, value: int) -> bool:
        return self._write_pack(address, "<h", int(value))

    def write_uint16(self, address: int, value: int) -> bool:
        return self._write_pack(address, "<H", int(value))

    def write_int32(self, address: int, value: int) -> bool:
        return self._write_pack(address, "<i", int(value))

    def write_uint32(self, address: int, value: int) -> bool:
        return self._write_pack(address, "<I", int(value))

    def write_int64(self, address: int, value: int) -> bool:
        return self._write_pack(address, "<q", int(value))

    def write_uint64(self, address: int, value: int) -> bool:
        return self._write_pack(address, "<Q", int(value))

    def write_float(self, address: int, value: float) -> bool:
        return self._write_pack(address, "<f", float(value))

    def write_double(self, address: int, value: float) -> bool:
        return self._write_pack(address, "<d", float(value))

    # -- Pointer Chain & Schema Resolvers -----------------------------------
    def resolve_pointer_chain(
        self,
        base_address: int,
        steps: Optional[List[Optional[int]]] = None,
        terminal: Optional[int] = 0,
        deref: bool = False,
    ) -> Optional[int]:
        """
        Traverses a pointer chain:
        1. Starts at base_address.
        2. For each step offset: reads pointer at curr_addr, then adds step offset.
        3. If steps is empty and deref is True: dereferences curr_addr once.
        4. Adds terminal offset.
        """
        if base_address is None or base_address <= 0x10000:
            return None

        curr = base_address

        # Step traversal
        if steps:
            for step in steps:
                if step is None:
                    return None
                val = self.read_ptr(curr)
                if not val or val <= 0x10000:
                    return None
                curr = val + step
        elif deref:
            val = self.read_ptr(curr)
            if not val or val <= 0x10000:
                return None
            curr = val

        if terminal is not None:
            curr += terminal

        return curr

    def resolve_entry_address(self, entry: Dict[str, Any]) -> Optional[int]:
        """Resolves target memory address from a validated schema entry."""
        mod_name = entry.get("module")
        base = self.get_module_base(mod_name)
        if base is None:
            return None

        rva = entry.get("base_rva")
        if rva is None:
            return None

        start_addr = base + rva
        steps = entry.get("steps")
        terminal = entry.get("terminal", 0)
        deref = entry.get("deref", False)

        return self.resolve_pointer_chain(
            start_addr, steps=steps, terminal=terminal, deref=deref
        )

    def read_entry(self, entry: Dict[str, Any]) -> Optional[Any]:
        """Resolves address and unpacks value according to entry type, mask and shift."""
        addr = self.resolve_entry_address(entry)
        if addr is None:
            return None

        type_name = entry.get("type", "int32")
        spec = self.TYPE_SPECS.get(type_name)
        if not spec:
            return None

        fmt, size = spec
        val = self._read_unpack(addr, fmt, size)
        if val is None:
            return None

        if isinstance(val, int):
            mask = entry.get("mask")
            if mask is not None:
                val &= mask
            shift = entry.get("shift")
            if shift is not None:
                val >>= shift

        return val

    def write_entry(self, entry: Dict[str, Any], value: Any) -> bool:
        """Resolves address and writes typed value."""
        addr = self.resolve_entry_address(entry)
        if addr is None:
            return False

        type_name = entry.get("type", "int32")
        spec = self.TYPE_SPECS.get(type_name)
        if not spec:
            return False

        fmt, _ = spec
        return self._write_pack(addr, fmt, value)


# ---------------------------------------------------------------------------
# CLI / Self-Test Runner
# ---------------------------------------------------------------------------
def main() -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="PokeBot Core Memory Diagnostic")
    parser.add_argument(
        "--process",
        default="PokeAlliance_dx.exe",
        help="Target process name (default: PokeAlliance_dx.exe)",
    )
    parser.add_argument(
        "--offsets",
        default="offsets.json",
        help="Path to offsets.json for validation testing",
    )
    parser.add_argument(
        "--read-addr",
        type=lambda x: int(x, 0),
        help="Hex/Dec memory address to read 4-byte int",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=" * 65)
    print(" PokeBot Core Memory Subsystem Diagnostic ")
    print("=" * 65)

    reader = MemoryReader(target_process=args.process)
    if not reader.attach():
        print(f"[-] Falha ao anexar no processo '{args.process}'.")
        print(f"    Detalhes do erro: {reader.last_error}")
        return 1

    print(f"[+] Anexado com sucesso ao PID: {reader.pid}")
    print(f"[+] Arquitetura: {'64-bit (x64)' if reader.is_64bit else '32-bit (x86)'}")
    print(f"[+] Módulo Principal Base: 0x{reader.main_module_base:X} (Tamanho: 0x{reader.main_module_size:X})")
    print(f"[+] Total de módulos carregados: {len(reader.modules)}")

    if args.read_addr:
        val = reader.read_int32(args.read_addr)
        print(f"[+] Leitura manual em 0x{args.read_addr:X} (int32): {val}")

    # Validação contra offsets.json se existir
    offsets_file = Path(args.offsets)
    if not offsets_file.exists():
        offsets_file = Path(__file__).resolve().parent.parent / "offsets.json"

    if offsets_file.exists():
        print(f"\n[+] Testando resolucao de entradas em '{offsets_file.name}':")
        try:
            with open(offsets_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            entries = data.get("entries", {})
            for key, entry in entries.items():
                verified = entry.get("verified", False)
                addr = reader.resolve_entry_address(entry)
                val = reader.read_entry(entry) if addr else None
                status = "OK" if val is not None else "FALHA"
                print(
                    f"  * [{status}] {key:<20} | Verified: {str(verified):<5} | "
                    f"Addr: {('0x%X' % addr) if addr else 'UNRESOLVED':<14} | Valor: {val}"
                )
        except Exception as exc:
            print(f"[-] Erro ao carregar offsets: {exc}")

    reader.detach()
    print("=" * 65)
    return 0


if __name__ == "__main__":
    sys.exit(main())
