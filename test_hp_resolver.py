"""Final dereference contract regressions; no live process required."""
import copy
from pathlib import Path
import unittest
from unittest.mock import Mock
from memory import Process, Resolver
from offset_contract import validate_offsets

ROOT = Path(__file__).resolve().parent
BASE = 0x7FF7092F0000
TARGET = 0x16C0E200000

class HPResolverTests(unittest.TestCase):
    def setUp(self):
        self.proc = Process('PokeAlliance_dx.exe')
        self.proc.pointer_size = 8
        self.proc.modules = {'pokealliance_dx.exe': {'base': BASE, 'size': 0x4000000}}
        self.proc.is_valid_addr = Mock(return_value=True)
        self.proc.read_ptr = Mock(return_value=TARGET)
        self.proc.read_value = Mock(return_value=179)
        self.resolver = Resolver(self.proc, str(ROOT/'offsets.json'), str(ROOT/'config.json'))

    def test_x_no_deref(self):
        # Direct-address fixture; calibrated XYZ chains remain unchanged.
        self.resolver.entries['player.x']['steps'] = []
        self.assertEqual(self.resolver.resolve_entry('player.x'), BASE + 0x3917F80 + 0x28)
        self.proc.read_ptr.assert_not_called()

    def test_hp_with_deref(self):
        self.assertEqual(self.resolver.entries['player.hp']['steps'], [])
        self.assertTrue(self.resolver.entries['player.hp']['deref'])
        self.assertEqual(self.resolver.resolve_entry('player.hp'), TARGET)
        self.proc.read_ptr.assert_called_once_with(BASE + 0x3922220)

    def test_hp_reads_correct_value(self):
        self.assertEqual(self.resolver.read_entry('player.hp'), 179)
        self.proc.read_value.assert_called_once_with(TARGET, 'int32')

    def test_xz_unaffected_by_deref_change(self):
        for axis, terminal in [('x', 0x28), ('y', 0x2c), ('z', 0x30)]:
            with self.subTest(axis=axis):
                self.proc.read_ptr.reset_mock()
                entry = self.resolver.entries['player.'+axis]
                self.assertFalse(entry.get('deref', False))
                self.assertEqual(self.resolver.resolve_entry('player.'+axis), TARGET+terminal)
                self.proc.read_ptr.assert_called_once_with(BASE+0x3917F80)
        self.proc.read_value.return_value = 0x0b220006
        self.assertEqual(self.resolver.read_entry('player.z'), 6)

    def test_hp_pointer_refreshed_between_reads(self):
        self.proc.read_ptr.side_effect = [TARGET, TARGET+0x1000]
        self.resolver.read_entry('player.hp')
        self.resolver.read_entry('player.hp')
        self.assertEqual([c.args for c in self.proc.read_value.call_args_list], [(TARGET, 'int32'), (TARGET+0x1000, 'int32')])

    def test_deref_after_chain_before_terminal(self):
        self.resolver.entries['player.hp'].update(steps=[0], terminal=4)
        self.proc.read_ptr.side_effect = [TARGET, TARGET+0x1000]
        self.assertEqual(self.resolver.resolve_entry('player.hp'), TARGET+0x1004)
        self.assertEqual([c.args for c in self.proc.read_ptr.call_args_list], [(BASE+0x3922220,), (TARGET,)])

    def test_final_null_or_failed_pointer_blocks_value_read(self):
        for result in (0, None):
            self.proc.read_ptr.return_value = result
            self.assertIsNone(self.resolver.read_entry('player.hp'))
        self.proc.read_value.assert_not_called()

    def test_final_deref_overflow_blocks_pointer_read(self):
        self.resolver.entries['player.hp']['terminal'] = 1 << 64
        self.assertIsNone(self.resolver.resolve_entry('player.hp'))
        self.proc.read_ptr.assert_called_once_with(BASE+0x3922220)

    def test_hp_max_shares_base_with_hp(self):
        target = 0x21700020000
        slot = BASE + 0x3922220
        def read_pointer(address):
            self.assertEqual(address, slot)
            return target
        self.proc.read_ptr.side_effect = read_pointer
        hp = self.resolver.entries['player.hp']
        hp_max = self.resolver.entries['player.hp_max']
        self.assertEqual(hp['base_rva'], hp_max['base_rva'])
        self.assertEqual(hp['deref'], hp_max['deref'])
        self.assertTrue(hp_max['deref'])
        self.assertEqual(hp_max['steps'], [])
        self.assertEqual(hp_max['terminal'], 4)
        self.assertEqual(self.resolver.resolve_entry('player.hp'), target)
        self.assertEqual(self.resolver.resolve_entry('player.hp_max'), target+4)
        self.assertEqual([c.args for c in self.proc.read_ptr.call_args_list], [(slot,), (slot,)])

    def test_hp_max_reads_int32(self):
        self.proc.read_value.return_value = 185
        self.assertEqual(self.resolver.read_entry('player.hp_max'), 185)
        self.proc.read_value.assert_called_once_with(TARGET+4, 'int32')

    def test_hp_max_reallocation(self):
        self.proc.read_ptr.side_effect = [TARGET, TARGET+0x1000]
        self.assertEqual(self.resolver.resolve_entry('player.hp_max'), TARGET+4)
        self.assertEqual(self.resolver.resolve_entry('player.hp_max'), TARGET+0x1004)

    def test_deref_requires_boolean(self):
        for value in (0, 1, 'true', None):
            data = copy.deepcopy(self.resolver.data)
            data['entries']['player.hp']['deref'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_offsets(data)

if __name__ == '__main__':
    unittest.main()
