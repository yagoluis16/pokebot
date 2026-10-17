import ctypes
import struct
from unittest.mock import patch

import pytest

from core.memory import MemoryReader
from core.tools.pointer_scan import (
    MEM_COMMIT,
    _parse_hex,
    build_chains,
    find_containing_module,
    format_static_chain,
    iter_regions,
    scan_for_parents,
    scan_level1,
)


@pytest.fixture
def memory_image():
    reader = MemoryReader(123)
    reader.modules = {"pokealliance_dx.exe": {"base": 0x100000, "size": 0x100}}
    data = {}

    def read_bytes(address, size):
        return bytes(data.get(address + offset, 0) for offset in range(size))

    def store_pointer(address, value):
        for offset, byte in enumerate(struct.pack("<Q", value)):
            data[address + offset] = byte

    reader.read_bytes = read_bytes
    return reader, store_pointer


def test_level_one_static_chain_is_registered(memory_image):
    reader, store_pointer = memory_image
    store_pointer(0x100010, 0x300000)
    with patch("core.tools.pointer_scan.iter_regions", return_value=[(0x100000, 0x100)]):
        chains = build_chains(reader, 0x300020, 0x40, 1)
    assert chains == [{"module": "pokealliance_dx.exe", "rva": 0x10,
                       "steps": [0x20], "terminal": 0, "level": 1}]
    entry = {**chains[0], "base_rva": chains[0]["rva"]}
    assert reader.resolve_entry_address(entry) == 0x300020


def test_two_level_chain_preserves_every_dereference(memory_image):
    reader, store_pointer = memory_image
    store_pointer(0x100010, 0x200000)
    store_pointer(0x200020, 0x300000)
    with patch("core.tools.pointer_scan.iter_regions",
               return_value=[(0x100000, 0x100), (0x200000, 0x100)]):
        chains = build_chains(reader, 0x300030, 0x40, 2)
    assert len(chains) == 1
    assert chains[0]["steps"] == [0x20, 0x30]
    assert chains[0]["terminal"] == 0
    entry = {**chains[0], "base_rva": chains[0]["rva"]}
    assert reader.resolve_entry_address(entry) == 0x300030


def test_three_level_format_resolves_in_forward_order(memory_image):
    reader, store_pointer = memory_image
    store_pointer(0x100010, 0x200000)
    store_pointer(0x200020, 0x300000)
    store_pointer(0x300030, 0x400000)
    chain = format_static_chain(reader, [(0x100010, 0x20), (0x200020, 0x30), (0x300030, 0x40)])
    assert chain["steps"] == [0x20, 0x30, 0x40]
    assert reader.resolve_entry_address({**chain, "base_rva": chain["rva"]}) == 0x400040


def test_large_regions_advance_by_region_size(memory_image):
    reader, _ = memory_image
    calls = []
    large_size = 0x1000000000

    def query(handle, address, output, size):
        calls.append(address.value or 0)
        information = output._obj
        information.BaseAddress = address.value or 0
        if len(calls) == 1:
            information.RegionSize = large_size
            information.State = 0x10000
        elif len(calls) == 2:
            information.RegionSize = 0x1000
            information.State = MEM_COMMIT
            information.Protect = 0x04
        else:
            pytest.fail("Consultas inesperadas antes de avançar pela região gigante")
        return ctypes.sizeof(information)

    with patch("core.tools.pointer_scan.kernel32.VirtualQueryEx", side_effect=query):
        regions = iter_regions(reader)
        assert next(regions) == (large_size, 0x1000)
        regions.close()
    assert calls == [0, large_size]


@pytest.mark.parametrize("protection, expected", [(0x04, True), (0x104, False), (0x01, False), (0x02, False)])
def test_writable_filter_excludes_guard_and_read_only(memory_image, protection, expected):
    reader, _ = memory_image

    def query(handle, address, output, size):
        information = output._obj
        information.BaseAddress = 0
        information.RegionSize = 0x800000000000
        information.State = MEM_COMMIT
        information.Protect = protection
        return ctypes.sizeof(information)

    with patch("core.tools.pointer_scan.kernel32.VirtualQueryEx", side_effect=query):
        regions = list(iter_regions(reader, writable_only=True))
    assert bool(regions) is expected


def test_empty_parent_search_skips_memory(memory_image):
    reader, _ = memory_image
    with patch("core.tools.pointer_scan.iter_regions") as regions:
        assert scan_for_parents(reader, [], 0x40) == []
        regions.assert_not_called()


def test_parent_search_uses_sorted_child_addresses(memory_image):
    reader, store_pointer = memory_image
    store_pointer(0x100000, 0x300000)
    with patch("core.tools.pointer_scan.iter_regions", return_value=[(0x100000, 8)]):
        assert scan_for_parents(reader, [0x500000, 0x300020], 0x40) == [(0x100000, 0x20, 0x300020)]


def test_level_one_respects_maximum_offset(memory_image):
    reader, store_pointer = memory_image
    store_pointer(0x100000, 0x300000)
    with patch("core.tools.pointer_scan.iter_regions", return_value=[(0x100000, 8)]):
        assert scan_level1(reader, 0x300020, 0x1F) == []


def test_module_end_is_exclusive(memory_image):
    reader, _ = memory_image
    assert find_containing_module(reader, 0x1000FF) == ("pokealliance_dx.exe", 0xFF)
    assert find_containing_module(reader, 0x100100) is None
    assert format_static_chain(reader, []) is None
    assert format_static_chain(reader, [(0x200000, 0)]) is None


@pytest.mark.parametrize("value, expected", [("0x4000", 0x4000), ("16384", 16384), ("0010", 10)])
def test_integer_parser(value, expected):
    assert _parse_hex(value) == expected
