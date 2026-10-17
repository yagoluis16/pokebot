from core.tools.dump_strings import iter_strings, main


def test_ascii_and_unaligned_utf16():
    data = b"player_hp\x00!" + "creature".encode("utf-16le") + b"\x00\x00"
    assert list(iter_strings(data, 5, True)) == [
        (0, "ASCII", "player_hp"), (11, "UTF16LE", "creature")]


def test_filter_and_empty_file(tmp_path, capsys):
    binary = tmp_path / "sample.bin"
    binary.write_bytes(b"player_hp\x00unrelated\x00")
    assert main([str(binary), "--filter", "HP|tile"]) == 0
    output = capsys.readouterr().out
    assert "player_hp" in output and "unrelated" not in output
    binary.write_bytes(b"")
    assert main([str(binary)]) == 0
    assert capsys.readouterr().out == ""


def test_missing_file(tmp_path, capsys):
    assert main([str(tmp_path / "missing")]) == 1
    assert "FAIL:" in capsys.readouterr().err
