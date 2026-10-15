"""Position contract and reader tests; no live process or input events."""
import copy
import io
import json
from pathlib import Path
import struct
import unittest
from unittest.mock import Mock, patch
from contextlib import redirect_stdout, redirect_stderr

import memory
from offset_contract import validate_offsets
import position_reader
import validate_position

ROOT = Path(__file__).resolve().parent


class PositionResolverTests(unittest.TestCase):
    def setUp(self):
        # Synthetic module load address; RVA and fields come from the real JSON.
        self.module_base = 0x140000000
        self.player_pointer = 0x16C524F0590
        self.proc = memory.Process("PokeAlliance_dx.exe")
        self.proc.pointer_size = 8
        self.proc.modules = {"pokealliance_dx.exe": {
            "base": self.module_base, "size": 0x4000000}}
        self.proc.is_valid_addr = Mock(return_value=True)
        self.proc.read_ptr = Mock(return_value=self.player_pointer)
        self.proc.read_value = Mock()
        self.resolver = memory.Resolver(self.proc, str(ROOT / "offsets.json"), str(ROOT / "config.json"))

    def test_resolve_xyz_offsets(self):
        for axis, terminal in (("x", 0x28), ("y", 0x2C), ("z", 0x30)):
            with self.subTest(axis=axis):
                entry = self.resolver.entries["player." + axis]
                self.assertEqual(entry["module"], "PokeAlliance_dx.exe")
                self.assertEqual(entry["base_rva"], 0x3917F80)
                self.assertEqual(entry["terminal"], terminal)
                self.assertEqual(entry["type"], "int32")
                self.assertEqual(entry["source"], "verified_ce")
                self.assertTrue(entry["verified"])
                self.assertEqual(entry["steps"], [0])
                self.proc.read_ptr.reset_mock()
                self.assertEqual(self.resolver.resolve_entry("player." + axis), self.player_pointer + terminal)
                self.proc.read_ptr.assert_called_once_with(self.module_base + entry["base_rva"])

    def test_resolve_empty_steps(self):
        for axis in "xyz":
            entry = self.resolver.entries["player." + axis]
            # Exercise direct-address support on an in-memory fixture, not the calibrated JSON.
            entry["steps"] = []
            self.assertEqual(entry["steps"], [])
            self.assertEqual(self.resolver.resolve_entry("player." + axis),
                             self.module_base + entry["base_rva"] + entry["terminal"])
        self.proc.read_ptr.assert_not_called()

    def test_z_mask(self):
        address = self.player_pointer + 0x30
        for raw, expected in ((0x0B220007, 7), (0x0B220008, 8), (0x0B220006, 6)):
            with self.subTest(raw=raw):
                self.proc.read_value.return_value = raw
                self.assertEqual(self.resolver.read_entry("player.z"), expected)
                self.proc.read_value.assert_called_with(address, "int32")

    def test_xy_unmasked(self):
        for axis, expected in (("y", 2307), ("x", 2972)):
            self.assertNotIn("mask", self.resolver.entries["player." + axis])
            self.proc.read_value.return_value = expected
            self.assertEqual(self.resolver.read_entry("player." + axis), expected)

    def test_offset_delta(self):
        offsets = [self.resolver.entries["player." + axis]["terminal"] for axis in "xyz"]
        self.assertEqual([b - a for a, b in zip(offsets, offsets[1:])], [4, 4])

    def test_shift_default_and_nonzero(self):
        entry = self.resolver.entries["player.z"]
        entry.pop("shift")
        self.proc.read_value.return_value = 0x0B220007
        self.assertEqual(self.resolver.read_entry("player.z"), 7)
        entry.update(mask=0xFF00, shift=8)
        self.assertEqual(self.resolver.read_entry("player.z"), 0x00)
        self.proc.read_value.return_value = 0x0B220700
        self.assertEqual(self.resolver.read_entry("player.z"), 7)

    def test_signed_int32_decoding_before_mask(self):
        proc = memory.Process("test.exe")
        with patch.object(proc, "read", return_value=struct.pack("<i", -1)):
            self.assertEqual(proc.read_value(0x100000, "int32"), -1)
        self.proc.read_value.return_value = -1
        self.assertEqual(self.resolver.read_entry("player.x"), -1)
        self.assertEqual(self.resolver.read_entry("player.z"), 255)

    def test_failed_read_is_not_masked(self):
        self.proc.read_value.return_value = None
        self.assertIsNone(self.resolver.read_entry("player.z"))

    def test_invalid_mask_configuration(self):
        for changes in ({"mask": -1}, {"mask": True}, {"mask": None}, {"mask": 1 << 32},
                        {"shift": -1}, {"shift": 32}, {"shift": True}, {"type": "float32"}):
            data = copy.deepcopy(self.resolver.data)
            data["entries"]["player.z"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_offsets(data)
        data = copy.deepcopy(self.resolver.data)
        del data["entries"]["player.z"]["mask"]
        with self.assertRaises(ValueError):
            validate_offsets(data)

    def test_module_relocation(self):
        for module_base in (0x140000000, 0x7FF600000000):
            self.proc.modules["pokealliance_dx.exe"]["base"] = module_base
            self.proc.read_ptr.reset_mock()
            self.assertEqual(self.resolver.resolve_entry("player.y"), self.player_pointer + 0x2C)
            self.proc.read_ptr.assert_called_once_with(module_base + 0x3917F80)


class PositionCLITests(unittest.TestCase):
    def test_validation_ok(self):
        session = Mock()
        session.read_position.return_value = (2972, 2307, 7)
        session.resolver.read_entry.side_effect = [179, 200, 87]
        output = io.StringIO()
        with patch.object(validate_position, "PositionSession", return_value=session), redirect_stdout(output):
            self.assertEqual(validate_position.main([]), 0)
        self.assertEqual(output.getvalue(), "X=2972 Y=2307 Z=7 HP=179/200 POKEMON_HP=87%\nOK\n")
        session.close.assert_called_once()

    def test_validation_fail(self):
        session = Mock()
        session.read_position.side_effect = OSError("client closed")
        error = io.StringIO()
        with patch.object(validate_position, "PositionSession", return_value=session), redirect_stderr(error):
            self.assertEqual(validate_position.main([]), 1)
        self.assertEqual(error.getvalue(), "FAIL: client closed\n")
        session.close.assert_called_once()

    def test_validation_bad_config(self):
        error = io.StringIO()
        with patch.object(validate_position, "PositionSession", side_effect=ValueError("bad config")), redirect_stderr(error):
            self.assertEqual(validate_position.main([]), 1)
        self.assertEqual(error.getvalue(), "FAIL: bad config\n")

    def test_poll_recovers_after_closed_client(self):
        session = Mock()
        session.read_position.side_effect = [OSError("client closed"), (2972, 2307, 7)]
        output, error = io.StringIO(), io.StringIO()
        with patch.object(position_reader.time, "sleep", side_effect=[None, KeyboardInterrupt]), \
             redirect_stdout(output), redirect_stderr(error):
            self.assertEqual(position_reader.poll_positions(session), 0)
        self.assertEqual(session.read_position.call_count, 2)
        self.assertEqual(error.getvalue(), "Position unavailable: client closed\n")
        self.assertEqual(output.getvalue(), "X=2972 Y=2307 Z=7\n")
        self.assertEqual(session.close.call_count, 2)

    def test_session_reads_xyz_and_reports_unavailable(self):
        session = position_reader.PositionSession()
        session.proc.pm = object()  # mock attached state; never open a process
        session.proc.modules = {"pokealliance_dx.exe": {"base": 0x140000000, "size": 0x4000000}}
        with patch.object(session.resolver, "read_entry", side_effect=[2972, 2307, 7]) as read:
            self.assertEqual(session.read_position(), (2972, 2307, 7))
            self.assertEqual([call.args for call in read.call_args_list], [("player.x",), ("player.y",), ("player.z",)])
        with patch.object(session.resolver, "read_entry", return_value=None):
            with self.assertRaisesRegex(position_reader.PositionReadError, "player.x"):
                session.read_position()

    def test_missing_module(self):
        session = position_reader.PositionSession()
        session.proc.pm = object()
        with self.assertRaisesRegex(position_reader.PositionReadError, "not loaded"):
            session.read_position()

    def test_attach_failure_reason(self):
        session = position_reader.PositionSession()
        session.proc.last_error = "access denied"
        with patch.object(session.proc, "attach", return_value=False):
            with self.assertRaisesRegex(position_reader.PositionReadError, "access denied"):
                session.read_position()


if __name__ == "__main__":
    unittest.main()
