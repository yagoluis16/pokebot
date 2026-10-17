import argparse
from array import array
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.tools import scan_pokemon as scanner


def memory_image(values):
    def read(address, size):
        return bytes(values.get(address + offset, 0xFF) for offset in range(size))
    return SimpleNamespace(read_bytes=Mock(side_effect=read))


@pytest.mark.parametrize("text", ["1,2,3,1", "2,3,1,2", "1,4,2,3,1"])
def test_sequence_accepts_return_to_initial_slot(text):
    assert scanner.parse_sequence(text)[0] == scanner.parse_sequence(text)[-1]


@pytest.mark.parametrize("text", ["1,2,3", "1,2,1,1", "0,2,3,0", "1,2,7,1", "a,b,c,a", "1,2,3,4"])
def test_sequence_rejects_invalid_cases(text):
    with pytest.raises(argparse.ArgumentTypeError):
        scanner.parse_sequence(text)


def test_initial_scan_matches_exact_aligned_values_and_chunk_boundary():
    raw = bytes([0xFF]) + (1).to_bytes(4, "little") + bytes([0xFF]) * 3
    raw += (1).to_bytes(4, "little") + (2).to_bytes(4, "little")
    memory = memory_image({0x1000 + offset: value for offset, value in enumerate(raw)})
    hits, coverage = scanner.initial_scan(memory, {"slot": 1}, {"slot": "<i"},
                                          regions=[(0x1000, 16)], chunk_size=8)
    assert list(hits["slot"]) == [0x1008]
    assert coverage == {"read_bytes": 16, "unreadable_bytes": 0}


def test_initial_scan_can_test_two_index_bases():
    memory = memory_image({0x1000: 1, 0x1001: 2})
    hits, _ = scanner.initial_scan(memory, {"zero": 1, "one": 2},
                                   {"zero": "<B", "one": "<B"}, regions=[(0x1000, 2)])
    assert list(hits["zero"]) == [0x1000]
    assert list(hits["one"]) == [0x1001]


def test_large_failed_read_retries_pages_and_reports_unreadable_bytes():
    def read(address, size):
        if size > 4096 or address == 0x2000:
            return None
        return bytes([1]) * size
    memory = SimpleNamespace(read_bytes=Mock(side_effect=read))
    pieces = list(scanner.readable_chunks(memory, [(0x1000, 8192)]))
    assert pieces == [(0x1000, bytes([1]) * 4096, 0), (0x2000, b"", 4096)]


def test_candidate_budget_fails_explicitly_instead_of_truncating():
    memory = SimpleNamespace(read_bytes=Mock(return_value=bytes(16)))
    with pytest.raises(RuntimeError, match="não foi truncado"):
        scanner.initial_scan(memory, {"slot": 0}, {"slot": "<i"},
                             max_candidates=2, regions=[(0x1000, 16)])


def test_refine_drops_wrong_values_and_reads_only_candidate_pages():
    memory = memory_image({0x1000: 2, 0x1001: 0, 0x1002: 0, 0x1003: 0,
                           0x1004: 1, 0x1005: 0, 0x1006: 0, 0x1007: 0})
    result = scanner.refine_scan(memory, {"slot": array("Q", [0x1000, 0x1004])},
                                 {"slot": 2}, {"slot": "<i"})
    assert list(result["slot"]) == [0x1000]
    memory.read_bytes.assert_called_once_with(0x1000, 4096)


def test_refine_falls_back_to_scalar_read_when_page_is_unreadable():
    memory = SimpleNamespace(read_bytes=Mock(side_effect=lambda address, size:
                             (3).to_bytes(4, "little") if size == 4 else None))
    result = scanner.refine_scan(memory, {"slot": array("Q", [0x1000])},
                                 {"slot": 3}, {"slot": "<i"})
    assert list(result["slot"]) == [0x1000]


def test_stage_requests_real_hp_and_does_not_guess_hotkeys(monkeypatch):
    responses = iter(["", "1234 4000"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))
    expected, formats = scanner.stage_values(2, "both", True, "<B")
    assert expected == {"pokemon.active_slot_0_based": 1, "pokemon.active_slot_1_based": 2,
                        "pokemon.hp": 1234, "pokemon.hp_max": 4000}
    assert formats["pokemon.hp"] == "<i"
    assert formats["pokemon.active_slot_0_based"] == "<B"


@pytest.mark.parametrize("text", ["100% 100%", "201 200", "-1 200", "0 0", "10", "1 2147483648"])
def test_stage_rejects_invalid_hp(monkeypatch, text):
    responses = iter(["", text])
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))
    with pytest.raises(ValueError):
        scanner.stage_values(1, "0", True, "<i")


def test_pointer_candidates_are_revalidated_but_not_marked_verified(monkeypatch):
    monkeypatch.setattr(scanner, "ensure_alive", Mock())
    build = Mock(return_value=[{"module": "game.exe", "rva": 0x20, "steps": [0], "terminal": 0}])
    monkeypatch.setattr(scanner, "build_chains", build)
    memory = SimpleNamespace(resolve_entry_address=Mock(return_value=0x1000),
                             read_bytes=Mock(return_value=(1).to_bytes(4, "little")))
    result = scanner.candidate_chains(memory, {"slot": array("Q", [0x1000])},
                                      {"slot": 1}, {"slot": "<i"}, 0x2000, 3)
    record = result["slot"][0]
    assert record["entry"]["base_rva"] == 0x20
    assert record["entry"]["deref"] is False
    assert record["entry"]["verified"] is False
    assert record["validated_in_current_session"] is True
    memory.resolve_entry_address.return_value = 0x2000
    result = scanner.candidate_chains(memory, {"slot": array("Q", [0x1000])},
                                      {"slot": 1}, {"slot": "<i"}, 0x2000, 3)
    assert result["slot"][0]["validated_in_current_session"] is False


def test_no_pointer_scan_for_zero_or_fifty_candidates(monkeypatch):
    build = Mock()
    monkeypatch.setattr(scanner, "build_chains", build)
    result = scanner.candidate_chains(None, {"none": [], "many": list(range(50))}, {}, {}, 0x2000, 3)
    assert result == {"none": [], "many": []}
    build.assert_not_called()


def test_interactive_cli_full_cycle_without_real_process(monkeypatch, tmp_path):
    memory = SimpleNamespace(is_attached=True, pid=123, pointer_size=8, main_module_base=0x140000000)
    backend = Mock()
    backend.__enter__ = Mock(return_value=memory)
    backend.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(scanner, "MemoryReader", Mock(return_value=backend))
    monkeypatch.setattr(scanner, "ensure_alive", Mock())
    monkeypatch.setattr(scanner, "stage_values", lambda slot, *args:
                        ({"slot": slot - 1}, {"slot": "<i"}))
    monkeypatch.setattr(scanner, "initial_scan", Mock(return_value=({"slot": array("Q", [0x1000])}, {})))
    refine = Mock(side_effect=lambda memory, candidates, *args: candidates)
    monkeypatch.setattr(scanner, "refine_scan", refine)
    path = tmp_path / "result.json"
    assert scanner.main(["123", "--skip-chains", "--save", str(path)]) == 0
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["pid"] == 123
    assert [stage["slot"] for stage in report["history"]] == [2, 3, 1, 2]
    assert report["verified"] is False
    assert refine.call_count == 3


def test_help_requires_no_process(capsys):
    with pytest.raises(SystemExit) as exc:
        scanner.main(["--help"])
    assert exc.value.code == 0
    assert "--hp" in capsys.readouterr().out


def test_full_value_cycle_eliminates_transient_candidate():
    state = {0x1000: 1, 0x1004: 1}
    memory = memory_image({})

    def read(address, size):
        raw = bytearray([0xFF] * size)
        for location, value in state.items():
            if address <= location and location + 4 <= address + size:
                raw[location - address:location - address + 4] = value.to_bytes(4, "little")
        return bytes(raw)

    memory.read_bytes.side_effect = read
    candidates, _ = scanner.initial_scan(memory, {"slot": 1}, {"slot": "<i"},
                                         regions=[(0x1000, 8)])
    for expected in [2, 0, 1]:
        state[0x1000] = expected
        state[0x1004] = expected if expected != 0 else 4
        candidates = scanner.refine_scan(memory, candidates, {"slot": expected}, {"slot": "<i"})
    assert list(candidates["slot"]) == [0x1000]


@pytest.mark.parametrize("success,exit_code", [(True, 0), (False, 259)])
def test_process_exit_or_handle_error_stops_scan(monkeypatch, success, exit_code):
    def get_exit(handle, output):
        output._obj.value = exit_code
        return success

    kernel = SimpleNamespace(GetExitCodeProcess=Mock(side_effect=get_exit))
    monkeypatch.setattr(scanner.ctypes, "WinDLL", Mock(return_value=kernel))
    with pytest.raises(RuntimeError, match="processo terminou"):
        scanner.ensure_alive(SimpleNamespace(handle=123))
