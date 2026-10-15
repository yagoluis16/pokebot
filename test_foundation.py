import json
from pathlib import Path
import struct
import tempfile
import unittest
import threading
import ctypes
import wininput
from unittest.mock import patch

import memory
from pe_arch import inspect_pe
from offset_contract import validate_offsets, TYPE_FORMATS
from types import SimpleNamespace


class ArchitectureTests(unittest.TestCase):
    def make_pe(self, machine, magic, name=b".text", flags=0x60000020, payload=None):
        optional_size = 224 if magic == 0x10B else 240
        data = bytearray(1024)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 128)
        data[128:132] = b"PE\0\0"
        struct.pack_into("<HH", data, 132, machine, 1)
        struct.pack_into("<H", data, 148, optional_size)
        struct.pack_into("<H", data, 152, magic)
        struct.pack_into("<H", data, 220, 2)
        section = 152 + optional_size
        data[section:section + 8] = name.ljust(8, b"\0")
        struct.pack_into("<I", data, section + 36, flags)
        if payload:
            struct.pack_into("<II", data, section + 16, len(payload), len(data))
            data.extend(payload)
        return data

    def inspect(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "client.exe"
            path.write_bytes(data)
            return inspect_pe(path)

    def test_machine_and_subsystem(self):
        for machine, magic, size in [(0x14C, 0x10B, 4), (0x8664, 0x20B, 8), (0xAA64, 0x20B, 8)]:
            with self.subTest(machine=machine):
                info = self.inspect(self.make_pe(machine, magic))
                self.assertEqual((info.machine, info.pointer_size, info.subsystem_name), (machine, size, "GUI"))
                self.assertFalse(info.packed)
        data = self.make_pe(0x14C, 0x10B)
        struct.pack_into("<H", data, 220, 3)
        self.assertEqual(self.inspect(data).subsystem_name, "console")

    def test_packing_heuristics(self):
        for kwargs in [dict(name=b"UPX0"), dict(flags=0xE0000020), dict(payload=bytes(range(256)) * 8)]:
            self.assertTrue(self.inspect(self.make_pe(0x14C, 0x10B, **kwargs)).packed)

    def test_invalid_pe(self):
        for data in [b"MZ", self.make_pe(0x14C, 0x20B), self.make_pe(0x1234, 0x10B)]:
            with self.assertRaises(ValueError):
                self.inspect(data)

    def test_pointer_read_width(self):
        proc = memory.Process("test.exe")
        with patch.object(proc, "read", side_effect=lambda addr, size: b"\x01" * size) as read:
            for width in (4, 8):
                proc.pointer_size = width
                self.assertEqual(proc.read_ptr(0x123456), int.from_bytes(b"\x01" * width, "little"))
                read.assert_called_with(0x123456, width)

    def test_attach_derives_architecture(self):
        for width, machine in [(4, 0x14C), (8, 0x8664)]:
            fake_pm = SimpleNamespace(
                process_base=SimpleNamespace(lpBaseOfDll=0x100000, SizeOfImage=0x10000),
                list_modules=lambda: [], close_process=lambda: None)
            info = SimpleNamespace(pointer_size=width, machine=machine, packed=False)
            with patch.object(memory, "PYMEM_AVAILABLE", True), \
                 patch.object(memory, "pymem", SimpleNamespace(Pymem=lambda name: fake_pm)), \
                 patch.object(memory, "process_executable", return_value="client.exe"), \
                 patch.object(memory, "inspect_pe", return_value=info), \
                 patch.object(memory, "log_arch") as log:
                proc = memory.Process("client.exe")
                self.assertTrue(proc.attach())
                self.assertEqual(proc.pointer_size, width)
                self.assertEqual(memory.POINTER_SIZE, width)
                log.assert_called_once_with("client.exe", info)
                proc.detach()
                self.assertIsNone(memory.POINTER_SIZE)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.entry = dict(module="client.exe", base_rva=0, steps=[0, 16],
                          terminal=4, type="uint32", verified=True, source="assumed", note="synthetic test")
        self.data = {"$schema": "offsets.schema.json", "schema_version": 2,
                     "entries": {"player.x": self.entry}}

    def resolver(self, pointer_size=4):
        resolver = memory.Resolver.__new__(memory.Resolver)
        resolver.entries = validate_offsets(self.data)["entries"]
        resolver._assumed_warned = set()
        resolver._warning_lock = threading.Lock()
        resolver.proc = memory.Process("client.exe")
        resolver.proc.pointer_size = pointer_size
        resolver.proc.modules = {"client.exe": {"base": 0x100000, "size": 0x10000}}
        return resolver

    def test_chain_order_zero_offset_and_terminal(self):
        for width in (4, 8):
            resolver = self.resolver(width)
            raw = {0x100000: (0x200000).to_bytes(width, "little"),
                   0x200000: (0x300000).to_bytes(width, "little"),
                   0x300014: struct.pack("<I", 123456)}
            with patch.object(resolver.proc, "read", side_effect=lambda addr, size: raw.get(addr)) as read, \
                 patch.object(resolver.proc, "is_valid_addr", return_value=True):
                self.assertEqual(resolver.read_field("player", "x"), 123456)
                self.assertEqual([call.args for call in read.call_args_list],
                                 [(0x100000, width), (0x200000, width), (0x300014, 4)])

    def test_all_scalar_types_and_direct_zero_terminal(self):
        self.entry.update(steps=[], terminal=0)
        for name, fmt in TYPE_FORMATS.items():
            self.entry["type"] = name
            value = -2 if name.startswith("int") else 2.5 if name.startswith("float") else 2
            resolver = self.resolver()
            with patch.object(resolver.proc, "read", return_value=struct.pack("<" + fmt, value)), \
                 patch.object(resolver.proc, "is_valid_addr", return_value=True):
                self.assertEqual(resolver.read_entry("player.x"), value)

    def test_unverified_never_reads(self):
        self.entry["verified"] = False
        resolver = self.resolver()
        with patch.object(resolver.proc, "read") as read:
            self.assertIsNone(resolver.read_entry("player.x"))
            read.assert_not_called()

    def test_null_missing_module_and_short_read(self):
        resolver = self.resolver()
        with patch.object(resolver.proc, "read_ptr", return_value=0):
            self.assertIsNone(resolver.resolve_entry("player.x"))
        self.entry.update(steps=[], terminal=0)
        with patch.object(resolver.proc, "is_valid_addr", return_value=True), \
             patch.object(resolver.proc, "read", return_value=b"\x01"):
            self.assertIsNone(resolver.read_entry("player.x"))
        resolver.proc.modules.clear()
        self.assertIsNone(resolver.resolve_entry("player.x"))

    def test_address_overflow(self):
        self.entry.update(steps=[], terminal=1 << 32)
        self.assertIsNone(self.resolver().resolve_entry("player.x"))

    def test_invalid_contract(self):
        for key, value in [("base_rva", "0x123"), ("base_rva", True), ("base_rva", 0.0),
                           ("terminal", None), ("steps", [False]), ("steps", [0] * 17),
                           ("type", "ptr"), ("verified", 1), ("module", "C:/client.exe")]:
            previous = self.entry[key]
            self.entry[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_offsets(self.data)
            self.entry[key] = previous
        del self.entry["terminal"]
        with self.assertRaises(ValueError):
            validate_offsets(self.data)

    def test_remaining_offsets_are_unverified(self):
        path = Path(__file__).with_name("offsets.json")
        entries = validate_offsets(json.loads(path.read_text(encoding="utf-8")))["entries"]
        entries = {name: entry for name, entry in entries.items()
                   if name not in {"player.x", "player.y", "player.z", "player.hp", "player.hp_max", "pokemon.hp_percent"}}
        self.assertTrue(entries)
        self.assertTrue(all(not entry["verified"] for entry in entries.values()))
        self.assertTrue(all(entry["base_rva"] is None and entry["steps"] is None
                            and entry["terminal"] is None for entry in entries.values()))

    def test_null_offsets_block_reads_and_warn_once(self):
        self.entry.update(verified=False, source="assumed", base_rva=None, steps=None, terminal=None)
        resolver = self.resolver()
        with patch.object(resolver.proc, "read") as read, patch.object(memory.log, "warning") as warning:
            self.assertIsNone(resolver.read_entry("player.x"))
            self.assertIsNone(resolver.read_entry("player.x"))
            read.assert_not_called()
            warning.assert_called_once_with("[warn] reading ASSUMED field %s — value may be wrong", "player.x")

    def test_partial_null_steps(self):
        self.entry.update(verified=False, steps=[0, None])
        resolver = self.resolver()
        with patch.object(resolver.proc, "read_ptr") as read:
            self.assertIsNone(resolver.resolve_entry("player.x"))
            read.assert_not_called()
        self.entry["verified"] = True
        with self.assertRaises(ValueError):
            validate_offsets(self.data)

    def test_unknown_source_rejected(self):
        self.entry["source"] = "guessed"
        with self.assertRaises(ValueError):
            validate_offsets(self.data)


class SendInputTests(unittest.TestCase):
    def test_native_layout(self):
        actual = wininput.validate_layout()
        self.assertEqual(actual, (40, 24, 32, 8) if ctypes.sizeof(ctypes.c_void_p) == 8 else (28, 16, 24, 4))

    def test_extended_key_down_up(self):
        with patch.object(wininput, "send_inputs") as send:
            wininput.send_scancode(0xE048, True)
            event = send.call_args.args[0][0]
            self.assertEqual((event.type, event.ki.wVk, event.ki.wScan, event.ki.dwFlags), (1, 0, 0x48, 9))
            wininput.send_scancode(0xE048, False)
            self.assertEqual(send.call_args.args[0][0].ki.dwFlags, 11)

    def test_mouse_button_struct(self):
        with patch.object(wininput, "send_inputs") as send:
            wininput.send_mouse_button(True)
            self.assertEqual((send.call_args.args[0][0].type, send.call_args.args[0][0].mi.dwFlags), (0, 2))
            wininput.send_mouse_button(False)
            self.assertEqual(send.call_args.args[0][0].mi.dwFlags, 4)

    def test_sendinput_count_and_size(self):
        from unittest.mock import Mock
        fake = SimpleNamespace(SendInput=Mock(return_value=1))
        with patch.object(wininput, "_user32", return_value=fake):
            wininput.send_inputs([wininput.keyboard_event(vk=0x87)])
        count, events, size = fake.SendInput.call_args.args
        self.assertEqual((count, events[0].ki.wVk, size), (1, 0x87, ctypes.sizeof(wininput.INPUT)))
        fake.SendInput.return_value = 0
        with patch.object(wininput, "_user32", return_value=fake), self.assertRaises(OSError):
            wininput.send_inputs([wininput.keyboard_event(vk=0x87)])

    def test_selftest_mock_only(self):
        with patch.object(wininput, "send_inputs") as send:
            self.assertTrue(wininput.sendinput_selftest())
            events = send.call_args.args[0]
            self.assertEqual([(e.ki.wVk, e.ki.dwFlags) for e in events], [(0x87, 0), (0x87, 2)])


if __name__ == "__main__":
    unittest.main()
