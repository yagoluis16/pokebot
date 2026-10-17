"""Extract printable ASCII and optional UTF-16LE strings from a binary.

UTF-16 mode extracts the printable ASCII subset encoded as UTF-16LE,
including strings at odd file offsets. Offsets are file offsets, not RVAs.
No binary is executed or modified.
"""
import argparse
import heapq
import mmap
from pathlib import Path
import re
import sys


def iter_strings(data, min_len=5, utf16=False):
    if min_len < 1:
        raise ValueError("min_len must be positive")
    ascii_pattern = re.compile(rb"[\x20-\x7e]{%d,}" % min_len)
    streams = [((m.start(), "ASCII", m.group().decode("ascii"))
                for m in ascii_pattern.finditer(data))]
    if utf16:
        wide_pattern = re.compile(rb"(?:[\x20-\x7e]\x00){%d,}" % min_len)
        streams.append((m.start(), "UTF16LE", m.group().decode("utf-16le"))
                       for m in wide_pattern.finditer(data))
    yield from heapq.merge(*streams, key=lambda row: row[0])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("--min-len", type=int, default=5)
    parser.add_argument("--utf16", action="store_true")
    parser.add_argument("--filter", help="Case-insensitive regular expression")
    args = parser.parse_args(argv)
    if args.min_len < 1:
        parser.error("--min-len must be positive")
    try:
        pattern = re.compile(args.filter, re.IGNORECASE) if args.filter else None
    except re.error as exc:
        parser.error(f"Invalid --filter: {exc}")
    try:
        with args.binary.open("rb") as stream:
            if not stream.seek(0, 2):
                return 0
            stream.seek(0)
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
                for offset, encoding, value in iter_strings(data, args.min_len, args.utf16):
                    if pattern is None or pattern.search(value):
                        print(f"0x{offset:08X} [{encoding}] {value}")
    except (OSError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
