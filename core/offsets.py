"""
core/offsets.py - Loader tipado para offsets.json, validado contra offsets.schema.json v2.

Expõe:
    - OffsetEntry     : entrada imutável (RVA, pointer chain, tipo, mask/shift, status de validação).
    - OffsetSection   : container genérico (dict de OffsetEntry por nome).
    - PlayerOffsets   : seção "player" com atributos nomeados.
    - PokemonOffsets  : seção "pokemon".
    - CreatureOffsets : seção "creature_list".
    - TileMapOffsets  : seção "tile_map".
    - GameStateOffsets: seção "game_state".
    - MinimapOffsets  : seção "minimap".
    - WorldOffsets    : seção "world".
    - BattleOffsets   : seção "battle".
    - OffsetRegistry  : facade — busca por chave "section.key",
                        read()/write() delegando ao MemoryReader.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

log = logging.getLogger("pokebot.core.offsets")

SUPPORTED_TYPES = frozenset(
    {
        "int8",
        "uint8",
        "int16",
        "uint16",
        "int32",
        "uint32",
        "int64",
        "uint64",
        "float32",
        "float64",
    }
)

# Chaves estritas do schema v2
REQUIRED_ENTRY_KEYS = (
    "module",
    "base_rva",
    "steps",
    "terminal",
    "type",
    "verified",
    "note",
    "source",
)
ALLOWED_ENTRY_KEYS = frozenset(
    {
        "module",
        "base_rva",
        "steps",
        "terminal",
        "deref",
        "type",
        "mask",
        "shift",
        "verified",
        "note",
        "source",
        "description",
    }
)


class OffsetError(Exception):
    """Erro de parsing/validação de offsets.json."""


# ---------------------------------------------------------------------------
# OffsetEntry — entrada imutável consumida pelo MemoryReader
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class OffsetEntry:
    name: str
    base_rva: Optional[int]
    module: Optional[str] = None
    steps: Tuple[Optional[int], ...] = ()
    terminal: Optional[int] = 0
    deref: bool = False
    type: str = "int32"
    verified: bool = False
    note: str = ""
    source: str = "assumed"
    mask: Optional[int] = None
    shift: Optional[int] = None
    description: Optional[str] = None

    @property
    def is_resolved(self) -> bool:
        """Indica se os ponteiros estão definidos e verificados para leitura."""
        return self.verified and self.base_rva is not None and self.terminal is not None

    def to_reader_dict(self) -> Dict[str, Any]:
        """
        Repassa a entrada no formato aceito por MemoryReader.
        """
        return {
            "module": self.module,
            "base_rva": self.base_rva,
            "steps": list(self.steps) if self.steps is not None else None,
            "terminal": self.terminal if self.terminal is not None else 0,
            "deref": self.deref,
            "type": self.type,
            "mask": self.mask,
            "shift": self.shift,
            "verified": self.verified,
        }

    def __repr__(self) -> str:
        chain = " -> ".join(f"0x{s:X}" if isinstance(s, int) else "null" for s in self.steps) if self.steps else "-"
        rva_str = f"0x{self.base_rva:X}" if self.base_rva is not None else "null"
        term_str = f"+0x{self.terminal:X}" if self.terminal is not None else "null"
        return (
            f"OffsetEntry(name={self.name!r}, verified={self.verified}, module={self.module!r}, "
            f"base_rva={rva_str}, steps=[{chain}], terminal={term_str}, type={self.type})"
        )


# ---------------------------------------------------------------------------
# OffsetSection — container genérico; subclasses nomeiam atributos
# ---------------------------------------------------------------------------
@dataclass
class OffsetSection:
    name: str
    entries: Dict[str, OffsetEntry] = field(default_factory=dict)

    def __getitem__(self, key: str) -> OffsetEntry:
        return self.entries[key]

    def __contains__(self, key: str) -> bool:
        return key in self.entries

    def __iter__(self) -> Iterator[OffsetEntry]:
        return iter(self.entries.values())

    def __len__(self) -> int:
        return len(self.entries)

    def get(self, key: str, default: Optional[OffsetEntry] = None) -> Optional[OffsetEntry]:
        return self.entries.get(key, default)

    def names(self) -> List[str]:
        return list(self.entries.keys())


@dataclass
class PlayerOffsets(OffsetSection):
    id: Optional[OffsetEntry] = None
    hp: Optional[OffsetEntry] = None
    hp_max: Optional[OffsetEntry] = None
    mp: Optional[OffsetEntry] = None
    mp_max: Optional[OffsetEntry] = None
    level: Optional[OffsetEntry] = None
    x: Optional[OffsetEntry] = None
    y: Optional[OffsetEntry] = None
    z: Optional[OffsetEntry] = None
    direction: Optional[OffsetEntry] = None
    cap: Optional[OffsetEntry] = None
    soul: Optional[OffsetEntry] = None
    stamina: Optional[OffsetEntry] = None
    is_online: Optional[OffsetEntry] = None
    is_dead: Optional[OffsetEntry] = None


@dataclass
class PokemonOffsets(OffsetSection):
    hp_percent: Optional[OffsetEntry] = None
    hp: Optional[OffsetEntry] = None
    hp_max: Optional[OffsetEntry] = None
    level: Optional[OffsetEntry] = None
    status: Optional[OffsetEntry] = None


@dataclass
class CreatureOffsets(OffsetSection):
    creature_id: Optional[OffsetEntry] = None
    hp_percent: Optional[OffsetEntry] = None
    x: Optional[OffsetEntry] = None
    y: Optional[OffsetEntry] = None
    z: Optional[OffsetEntry] = None
    is_npc: Optional[OffsetEntry] = None
    is_player: Optional[OffsetEntry] = None
    is_dead: Optional[OffsetEntry] = None
    speed: Optional[OffsetEntry] = None


@dataclass
class GameStateOffsets(OffsetSection):
    is_online: Optional[OffsetEntry] = None
    is_dead: Optional[OffsetEntry] = None
    is_trade_open: Optional[OffsetEntry] = None
    dialog_open: Optional[OffsetEntry] = None
    ping: Optional[OffsetEntry] = None


@dataclass
class MinimapOffsets(OffsetSection):
    center_x: Optional[OffsetEntry] = None
    center_y: Optional[OffsetEntry] = None
    center_z: Optional[OffsetEntry] = None


@dataclass
class TileMapOffsets(OffsetSection):
    flags: Optional[OffsetEntry] = None


@dataclass
class WorldOffsets(OffsetSection):
    local_player_ptr: Optional[OffsetEntry] = None
    entity_list_ptr: Optional[OffsetEntry] = None
    entity_count: Optional[OffsetEntry] = None


@dataclass
class BattleOffsets(OffsetSection):
    in_battle: Optional[OffsetEntry] = None
    target_id: Optional[OffsetEntry] = None


SECTION_CLASSES: Dict[str, type] = {
    "player": PlayerOffsets,
    "pokemon": PokemonOffsets,
    "creature_list": CreatureOffsets,
    "game_state": GameStateOffsets,
    "minimap": MinimapOffsets,
    "tile_map": TileMapOffsets,
    "world": WorldOffsets,
    "battle": BattleOffsets,
}


def _split_key(key: str) -> Tuple[str, str]:
    if "." not in key:
        return ("_global", key)
    section, _, rest = key.partition(".")
    return (section.strip(), rest.strip())


def _parse_entry(name: str, raw: Any, *, source: str) -> OffsetEntry:
    if not isinstance(raw, dict):
        raise OffsetError(f"[{source}] entrada '{name}' deve ser objeto JSON, veio {type(raw).__name__}")

    unknown = set(raw.keys()) - ALLOWED_ENTRY_KEYS
    if unknown:
        raise OffsetError(f"[{source}] entrada '{name}' contém chaves desconhecidas: {sorted(unknown)}")

    base_rva = raw.get("base_rva")
    if base_rva is not None and (not isinstance(base_rva, int) or base_rva < 0):
        raise OffsetError(f"[{source}] '{name}'.base_rva inválido: {base_rva!r}")

    steps_raw = raw.get("steps")
    steps: List[Optional[int]] = []
    if steps_raw is not None:
        if not isinstance(steps_raw, list):
            raise OffsetError(f"[{source}] '{name}'.steps deve ser lista ou null")
        for i, s in enumerate(steps_raw):
            if s is None or isinstance(s, int):
                steps.append(s)
            else:
                raise OffsetError(f"[{source}] '{name}'.steps[{i}] não inteiro: {s!r}")

    terminal = raw.get("terminal")
    if terminal is not None and not isinstance(terminal, int):
        raise OffsetError(f"[{source}] '{name}'.terminal deve ser inteiro ou null: {terminal!r}")

    type_name = raw.get("type", "int32")
    if type_name not in SUPPORTED_TYPES:
        raise OffsetError(f"[{source}] '{name}'.type '{type_name}' não suportado.")

    mask = raw.get("mask")
    if mask is not None and not isinstance(mask, int):
        raise OffsetError(f"[{source}] '{name}'.mask deve ser inteiro ou null")

    shift = raw.get("shift")
    if shift is not None and not isinstance(shift, int):
        raise OffsetError(f"[{source}] '{name}'.shift deve ser inteiro ou null")

    module = raw.get("module")
    if module is not None and not isinstance(module, str):
        raise OffsetError(f"[{source}] '{name}'.module deve ser string ou null")

    verified = bool(raw.get("verified", False))
    note = str(raw.get("note", ""))
    entry_source = str(raw.get("source", "assumed"))

    return OffsetEntry(
        name=name,
        base_rva=base_rva,
        module=module,
        steps=tuple(steps),
        terminal=terminal,
        deref=bool(raw.get("deref", False)),
        type=type_name,
        verified=verified,
        note=note,
        source=entry_source,
        mask=mask,
        shift=shift,
        description=raw.get("description"),
    )


def _build_section(name: str, entries: Dict[str, OffsetEntry]) -> OffsetSection:
    cls = SECTION_CLASSES.get(name, OffsetSection)
    section = cls(name=name, entries=entries)

    for f in fields(cls):
        if f.name in ("name", "entries"):
            continue
        if f.name in entries:
            setattr(section, f.name, entries[f.name])

    return section


# ---------------------------------------------------------------------------
# Validação contra JSON Schema (utiliza jsonschema se disponível ou fallback)
# ---------------------------------------------------------------------------
def _validate_against_schema(data: Any, schema_path: Path) -> None:
    if not schema_path.exists():
        log.warning("Schema não encontrado em %s — pulando validação", schema_path)
        return

    try:
        import jsonschema
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(instance=data, schema=schema)
    except ImportError:
        # Fallback usando validador nativo sem dependências do repositório
        try:
            root_dir = Path(__file__).resolve().parent.parent
            if str(root_dir) not in sys.path:
                sys.path.insert(0, str(root_dir))
            from offset_contract import validate_offsets
            validate_offsets(data)
        except Exception as exc:
            raise OffsetError(f"Validação de contrato falhou: {exc}") from exc
    except Exception as e:
        raise OffsetError(f"offsets.json viola schema ({schema_path}): {e}") from e


# ---------------------------------------------------------------------------
# OffsetRegistry — facade principal
# ---------------------------------------------------------------------------
class OffsetRegistry:
    """
    Dicionário tipado de seções + acesso por chave "section.key".
    Consumido diretamente pelos módulos de automação.
    """

    def __init__(
        self,
        sections: Dict[str, OffsetSection],
        *,
        version: Optional[int],
        raw: Dict[str, Any],
        source: Path,
    ) -> None:
        self.sections = sections
        self.version = version
        self.raw = raw
        self.source = source
        self._flat: Dict[str, OffsetEntry] = {}
        for sec in sections.values():
            for key, entry in sec.entries.items():
                self._flat[f"{sec.name}.{key}"] = entry

    def __getitem__(self, section: str) -> OffsetSection:
        return self.sections[section]

    def __contains__(self, section: str) -> bool:
        return section in self.sections

    def __iter__(self) -> Iterator[OffsetSection]:
        return iter(self.sections.values())

    def section_names(self) -> List[str]:
        return list(self.sections.keys())

    def get_section(self, name: str) -> Optional[OffsetSection]:
        return self.sections.get(name)

    def find(self, key: str) -> Optional[OffsetEntry]:
        if key in self._flat:
            return self._flat[key]
        section, sub = _split_key(key)
        sec = self.sections.get(section)
        if sec is None:
            return None
        return sec.entries.get(sub)

    def require(self, key: str) -> OffsetEntry:
        entry = self.find(key)
        if entry is None:
            raise KeyError(f"Offset não encontrado: '{key}' em {self.source}")
        return entry

    def iter_entries(self) -> Iterator[Tuple[str, OffsetEntry]]:
        for full_key, entry in self._flat.items():
            yield full_key, entry

    def read(self, reader: Any, key: str) -> Optional[Any]:
        entry = self.find(key)
        if entry is None or not entry.is_resolved:
            return None
        return reader.read_entry(entry.to_reader_dict())

    def write(self, reader: Any, key: str, value: Any) -> bool:
        entry = self.find(key)
        if entry is None or not entry.is_resolved:
            return False
        return reader.write_entry(entry.to_reader_dict(), value)

    def summary(self) -> str:
        lines = [
            f"OffsetRegistry — source={self.source}",
            f"  schema_version: {self.version if self.version is not None else 'unknown'}",
            f"  total de seções: {len(self.sections)}",
            f"  total de entradas: {len(self._flat)}",
        ]
        for name, sec in sorted(self.sections.items()):
            verified_count = sum(1 for e in sec if e.verified)
            lines.append(f"    [{name}] {len(sec)} entradas ({verified_count} verificadas)")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Loader principal
# ---------------------------------------------------------------------------
def load_offsets(
    offsets_path: Union[str, Path] = "offsets.json",
    schema_path: Optional[Union[str, Path]] = "offsets.schema.json",
    *,
    validate: bool = True,
) -> OffsetRegistry:
    src = Path(offsets_path)
    if not src.exists():
        raise OffsetError(f"Arquivo de offsets não encontrado: {src}")

    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise OffsetError(f"offsets.json inválido em {src}: {e}") from e

    if not isinstance(data, dict):
        raise OffsetError(f"{src} deve ser um objeto JSON na raiz")

    if validate and schema_path:
        _validate_against_schema(data, Path(schema_path))

    version = data.get("schema_version") or data.get("version")

    if "entries" in data and isinstance(data["entries"], dict):
        entries_raw: Dict[str, Any] = data["entries"]
    else:
        entries_raw = {
            k: v for k, v in data.items() if isinstance(v, dict) and ("base_rva" in v or "verified" in v)
        }

    if not entries_raw:
        raise OffsetError(f"{src}: nenhuma entrada encontrada")

    grouped: Dict[str, Dict[str, OffsetEntry]] = {}
    for full_key, raw_entry in entries_raw.items():
        section_name, sub_key = _split_key(full_key)
        entry = _parse_entry(full_key, raw_entry, source=str(src))
        grouped.setdefault(section_name, {})[sub_key] = entry

    sections: Dict[str, OffsetSection] = {
        name: _build_section(name, entries) for name, entries in grouped.items()
    }

    registry = OffsetRegistry(
        sections,
        version=version,
        raw=data,
        source=src,
    )
    return registry


# ---------------------------------------------------------------------------
# CLI de diagnóstico
# ---------------------------------------------------------------------------
def _cli() -> int:
    parser = argparse.ArgumentParser(
        prog="offsets",
        description="Valida e inspeciona offsets.json do PokeBot.",
    )
    parser.add_argument("--file", default="offsets.json", help="Caminho de offsets.json")
    parser.add_argument(
        "--schema",
        default="offsets.schema.json",
        help="Caminho de offsets.schema.json (use '' para pular)",
    )
    parser.add_argument("--summary", action="store_true", help="Imprime resumo por seção")
    parser.add_argument("--list", action="store_true", help="Lista todas as entradas")
    parser.add_argument("--show", metavar="KEY", help="Mostra uma entrada (ex: player.hp)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log DEBUG")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    schema_arg: Optional[str] = args.schema if args.schema else None

    try:
        registry = load_offsets(args.file, schema_arg, validate=schema_arg is not None)
    except OffsetError as e:
        print(f"ERRO: {e}", file=sys.stderr)
        return 2

    if args.summary or (not args.list and not args.show):
        print(registry.summary())

    if args.list:
        for key, entry in registry.iter_entries():
            print(f"{key}\n    {entry}")

    if args.show:
        entry = registry.find(args.show)
        if entry is None:
            print(f"Não encontrado: {args.show}", file=sys.stderr)
            return 3
        print(entry)

    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())