"""Active Pokemon percentage tests, without connecting to a process."""
import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from memory import Process, Resolver
import validate_position

ROOT = Path(__file__).resolve().parent


class PokemonHPTests(unittest.TestCase):
    def setUp(self):
        self.base = 0x140000000  # Synthetic module base.
        self.target = 0x1F606E2B5F0
        self.proc = Process("PokeAlliance_dx.exe")
        self.proc.pointer_size = 8
        self.proc.modules = {"pokealliance_dx.exe": {"base": self.base, "size": 0x4000000}}
        self.proc.is_valid_addr = Mock(return_value=True)
        self.proc.read_ptr = Mock(return_value=self.target)
        self.proc.read_value = Mock(return_value=87)
        self.resolver = Resolver(self.proc, str(ROOT / "offsets.json"), str(ROOT / "config.json"))

    def test_pointer_and_int32_field(self):
        entry = self.resolver.entries["pokemon.hp_percent"]
        self.assertEqual(entry["base_rva"], 0x3921B48)
        self.assertEqual(entry["steps"], [])
        self.assertTrue(entry["deref"])
        self.assertEqual(entry["terminal"], 0x3C8)
        self.assertEqual(entry["source"], "verified_ce")
        self.assertTrue(entry["verified"])
        self.assertEqual(self.resolver.read_field("pokemon", "hp_percent"), 87)
        self.proc.read_ptr.assert_called_once_with(self.base + 0x3921B48)
        self.proc.read_value.assert_called_once_with(self.target + 0x3C8, "int32")

    def test_switch_refreshes_target(self):
        other = self.target + 0x10000
        self.proc.read_ptr.side_effect = [self.target, other, self.target]
        self.proc.read_value.side_effect = [87, 100, 87]
        self.assertEqual([self.resolver.read_entry("pokemon.hp_percent") for _ in range(3)], [87, 100, 87])
        self.assertEqual([c.args for c in self.proc.read_value.call_args_list],
                         [(self.target + 0x3C8, "int32"), (other + 0x3C8, "int32"),
                          (self.target + 0x3C8, "int32")])
        self.assertEqual(self.proc.read_ptr.call_count, 3)

    def test_null_target(self):
        self.proc.read_ptr.return_value = 0
        self.assertIsNone(self.resolver.read_entry("pokemon.hp_percent"))
        self.proc.read_value.assert_not_called()

    def test_aslr(self):
        relocated = 0x7FF700000000
        self.proc.modules["pokealliance_dx.exe"]["base"] = relocated
        self.assertEqual(self.resolver.resolve_entry("pokemon.hp_percent"), self.target + 0x3C8)
        self.proc.read_ptr.assert_called_once_with(relocated + 0x3921B48)

    def test_validation_missing_or_invalid_percentage(self):
        for percentage in (None, -1, 101):
            session = Mock()
            session.read_position.return_value = (2985, 2304, 6)
            session.resolver.read_entry.side_effect = [179, 200, percentage]
            output, error = io.StringIO(), io.StringIO()
            with self.subTest(value=percentage), \
                 patch.object(validate_position, "PositionSession", return_value=session), \
                 redirect_stdout(output), redirect_stderr(error):
                self.assertEqual(validate_position.main([]), 1)
            self.assertEqual(output.getvalue(), "")
            self.assertIn("FAIL: pokemon.hp_percent:", error.getvalue())
            session.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
