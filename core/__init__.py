"""
core - Subsistema de baixo nível do PokeBot.

Exports públicos:
    MemoryReader   — leitor/escritor de memória Win32.
    OffsetEntry    — entrada tipada de offset.
    OffsetRegistry — registry carregado a partir de offsets.json.
    load_offsets   — loader principal.
    OffsetError    — erro de validação/parsing.
"""

from .memory import MemoryReader
from .offsets import (
    OffsetEntry,
    OffsetError,
    OffsetRegistry,
    load_offsets,
)

__all__ = [
    "MemoryReader",
    "OffsetEntry",
    "OffsetError",
    "OffsetRegistry",
    "load_offsets",
]