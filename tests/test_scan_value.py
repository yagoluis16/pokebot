import struct
from unittest.mock import patch

import pytest

from core.tools.scan_value import _parse_value, main, scan_region


@pytest.mark.parametrize("text, expected, value_type", [
    ("487", 487, int),
    ("-487", -487, int),
    ("0x1E7", 487, int),
    ("0b111", 7, int),
    ("0o17", 15, int),
    ("487.5", 487.5, float),
    ("-1.5", -1.5, float),
    ("1e3", 1000.0, float),
    ("1E-3", 0.001, float),
])
def test_parse_value_preserves_numeric_type(text, expected, value_type):
    parsed = _parse_value(text)
    assert parsed == expected
    assert type(parsed) is value_type


def test_decimal_value_scans_int32_without_float_error():
    with patch("core.tools.scan_value.MemoryReader") as reader:
        reader.return_value.read_bytes.return_value = struct.pack("<i", 487)
        assert scan_region(reader.return_value, 0x1000, 4, "<i", _parse_value("487")) == [0x1000]


def test_cli_accepts_decimal_value_for_int32(capsys):
    with patch("sys.argv", ["scan_value", "123", "--value", "487", "--type", "int32"]), \
         patch("core.tools.scan_value.MemoryReader") as reader, \
         patch("core.tools.scan_value.iter_regions", return_value=[(0x1000, 4)]):
        backend = reader.return_value.__enter__.return_value
        backend.is_attached = True
        backend.read_bytes.return_value = struct.pack("<i", 487)
        assert main() == 0
        assert "0x1000 = 487" in capsys.readouterr().out


def test_invalid_value_is_rejected_by_cli():
    with patch("sys.argv", ["scan_value", "123", "--value", "invalid"]), \
         pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
