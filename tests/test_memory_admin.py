import ctypes.wintypes as wt
from unittest.mock import patch

import pytest

from core.memory import MemoryReader


@pytest.mark.parametrize("admin_result, expected", [(0, False), (1, True)])
def test_require_admin_returns_bool(admin_result, expected):
    with patch("core.memory.ctypes.windll.shell32.IsUserAnAdmin", return_value=admin_result) as check:
        assert MemoryReader.require_admin() is expected
        check.assert_called_once_with()
        assert check.argtypes == []
        assert check.restype is wt.BOOL


@pytest.mark.parametrize("errors", [(5, 5), (5, 87), (87, 5)])
def test_attach_preserves_access_denied_message(errors):
    with patch("core.memory.kernel32.OpenProcess", return_value=None) as open_process, \
         patch("core.memory.ctypes.get_last_error", side_effect=errors):
        reader = MemoryReader(123)
        assert reader.attach() is False
        assert reader.last_error == "acesso negado — execute o bot como Administrador"
        assert reader.is_attached is False
        assert open_process.call_count == 2


def test_attach_preserves_other_error_details():
    with patch("core.memory.kernel32.OpenProcess", return_value=None), \
         patch("core.memory.ctypes.get_last_error", return_value=87):
        reader = MemoryReader(123)
        assert reader.attach() is False
        assert reader.last_error == "OpenProcess failed for PID 123 (error code: 87)"


def test_attach_read_only_fallback_clears_previous_error():
    def enumerate_modules(reader):
        reader.main_module_base = 0x100000

    with patch("core.memory.kernel32.OpenProcess", side_effect=[None, 123]), \
         patch("core.memory.ctypes.get_last_error", return_value=5), \
         patch("core.memory.kernel32.CloseHandle"), \
         patch.object(MemoryReader, "_detect_architecture"), \
         patch.object(MemoryReader, "_enumerate_modules", enumerate_modules):
        reader = MemoryReader(123)
        reader.last_error = "erro anterior"
        try:
            assert reader.attach() is True
            assert reader.last_error is None
        finally:
            reader.detach()
