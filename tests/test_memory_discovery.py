from unittest.mock import patch
import pytest
from core.memory import MemoryReader


@pytest.fixture
def attached_backend():
    def modules(reader):
        reader.main_module_base = 0x7FF600000000
        reader.modules = {"renamed.exe": {"base": reader.main_module_base, "size": 4096}}
    with patch("core.memory.kernel32.OpenProcess", return_value=123), \
         patch("core.memory.kernel32.CloseHandle"), \
         patch.object(MemoryReader, "_detect_architecture"), \
         patch.object(MemoryReader, "_enumerate_modules", modules):
        yield


def test_list_candidate_processes_returns_list():
    with patch.object(MemoryReader, "_process_rows", return_value=[]), \
         patch("core.memory._window_titles", return_value={}):
        assert MemoryReader.list_candidate_processes("missing") == []


def test_list_matches_name_or_title():
    rows = [{"pid": 1, "name": "hash.exe"}, {"pid": 2, "name": "PokeAlliance.exe"},
            {"pid": 3, "name": "other.exe"}]
    with patch.object(MemoryReader, "_process_rows", return_value=rows), \
         patch("core.memory._window_titles", return_value={1: ["PokeAlliance - Shiba"]}), \
         patch("core.memory._process_path", return_value=None):
        assert MemoryReader.list_candidate_processes("POKEALLIANCE") == [
            {**rows[0], "title": "PokeAlliance - Shiba", "path": None},
            {**rows[1], "title": "", "path": None}]


def test_attach_with_fallback_names(attached_backend):
    with patch.object(MemoryReader, "_find_pid_by_name", side_effect=[None, None, 42]) as find, \
         patch.object(MemoryReader, "_find_pid_by_window_title") as window:
        with MemoryReader("original.exe", fallback_names=["first.exe", "second.exe"]) as reader:
            assert reader.is_attached and reader.pid == 42
            assert [call.args[0] for call in find.call_args_list] == ["original.exe", "first.exe", "second.exe"]
            window.assert_not_called()


def test_attach_with_window_title_pattern(attached_backend):
    with patch.object(MemoryReader, "_find_pid_by_name", return_value=None), \
         patch.object(MemoryReader, "_find_pid_by_window_title", return_value=43) as find:
        with MemoryReader(window_title_pattern="PokeAlliance") as reader:
            assert reader.is_attached and reader.pid == 43
            find.assert_called_once_with("PokeAlliance")


def test_attach_with_int_pid_still_works(attached_backend):
    with patch.object(MemoryReader, "_find_pid_by_name") as name, \
         patch.object(MemoryReader, "_find_pid_by_window_title") as window:
        with MemoryReader(44) as reader:
            assert reader.is_attached and reader.pid == 44
            name.assert_not_called()
            window.assert_not_called()


def test_primary_name_takes_precedence(attached_backend):
    with patch.object(MemoryReader, "_find_pid_by_name", return_value=45) as find:
        with MemoryReader(fallback_names=["other.exe"]) as reader:
            assert reader.pid == 45
            find.assert_called_once_with("PokeAlliance_dx.exe")


def test_not_found_describes_attempts():
    with patch.object(MemoryReader, "_find_pid_by_name", return_value=None), \
         patch.object(MemoryReader, "_find_pid_by_window_title", return_value=None):
        reader = MemoryReader("missing.exe", fallback_names=["renamed.exe"], window_title_pattern="Game")
        assert not reader.attach()
        assert all(value in reader.last_error for value in ["missing.exe", "renamed.exe", "Game"])


def test_window_title_substring_case_insensitive():
    with patch("core.memory._window_titles", return_value={88: ["PokeAlliance - Shiba Bots"]}):
        assert MemoryReader()._find_pid_by_window_title("pokeALLIANCE") == 88
        assert MemoryReader()._find_pid_by_window_title("absent") is None
        assert MemoryReader()._find_pid_by_window_title("") is None
