"""HP global pointer regression tests. No live process required."""
from pathlib import Path
import unittest
from unittest.mock import Mock

from memory import Process, Resolver

ROOT = Path(__file__).resolve().parent


class HPTests(unittest.TestCase):
    def setUp(self):
        self.module_base = 0x140000000  # Synthetic module load address.
        self.hp_pointer = 0x16C0E200000
        self.proc = Process("PokeAlliance_dx.exe")
        self.proc.pointer_size = 8
        self.proc.modules = {"pokealliance_dx.exe": {
            "base": self.module_base, "size": 0x4000000}}
        self.proc.is_valid_addr = Mock(return_value=True)
        self.proc.read_ptr = Mock(return_value=self.hp_pointer)
        self.proc.read_value = Mock(return_value=179)
        self.resolver = Resolver(self.proc, str(ROOT / "offsets.json"),
                                 str(ROOT / "config.json"))

    def test_resolve_hp_global_pointer(self):
        entry = self.resolver.entries["player.hp"]
        self.assertEqual(entry["base_rva"], 0x3922260)
        self.assertEqual(entry["steps"], [0])
        self.assertFalse(entry["deref"])
        self.assertEqual(entry["terminal"], 0)
        self.assertEqual(entry["type"], "int32")
        self.assertEqual(entry["source"], "reversed_disasm")
        self.assertTrue(entry["verified"])
        self.assertEqual(self.resolver.resolve_entry("player.hp"), self.hp_pointer)
        self.proc.read_ptr.assert_called_once_with(self.module_base + 0x3922260)
        self.proc.read_value.assert_not_called()

    def test_read_hp_int32(self):
        self.assertEqual(self.resolver.read_entry("player.hp"), 179)
        self.proc.read_ptr.assert_called_once_with(self.module_base + 0x3922260)
        self.proc.read_value.assert_called_once_with(self.hp_pointer, "int32")

    def test_null_hp_pointer_blocks_value_read(self):
        self.proc.read_ptr.return_value = 0
        self.assertIsNone(self.resolver.read_entry("player.hp"))
        self.proc.read_value.assert_not_called()


if __name__ == "__main__":
    unittest.main()
