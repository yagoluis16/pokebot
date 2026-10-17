"""Leitura somente consulta da pokébar publicada na telemetria local.

Este adaptador depende do produtor de telemetria do PKA Tools.
Não injeta código, não escreve IPC e não executa habilidades.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import time

MAX_TELEMETRY_BYTES = 1024 * 1024


class RosterError(ValueError):
    """Telemetria ausente, incompatível ou desatualizada."""


@dataclass(frozen=True)
class PokemonMove:
    spellword: str
    remaining_ms: int
    total_ms: int


@dataclass(frozen=True)
class Pokemon:
    uuid: str
    name: str
    slot: int
    hp_percent: int
    moves: tuple[PokemonMove, ...]


@dataclass(frozen=True)
class PokemonRoster:
    pid: int
    pokemon: tuple[Pokemon, ...]
    active_uuid: str | None

    def find(self, uuid: str) -> Pokemon | None:
        return next((pokemon for pokemon in self.pokemon if pokemon.uuid == uuid), None)


def _integer(value, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise RosterError("valor inteiro fora do contrato da telemetria")
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise RosterError("identidade do Pokémon inválida")
    if any(ord(character) < 32 for character in value):
        raise RosterError("identidade contém caracteres de controle")
    return value.strip()


def decode_roster(data, pid):
    if not isinstance(data, dict) or data.get("nativeVerified") is not True:
        raise RosterError("telemetria nativa não verificada")
    if _integer(data.get("clientPid"), 1, 0xFFFFFFFF) != pid:
        raise RosterError("PID da telemetria difere do processo escolhido")
    if type(data.get("pulseVersion")) is not int or data["pulseVersion"] != 3:
        raise RosterError("versão de telemetria incompatível")
    rows = data.get("roster")
    if not isinstance(rows, list) or len(rows) > 6:
        raise RosterError("pokébar inválida")
    pokemon = []
    identities = set()
    slots = set()
    for row in rows:
        if not isinstance(row, dict):
            raise RosterError("entrada da pokébar inválida")
        uuid = _text(row.get("uuid"))
        name = _text(row.get("name"))
        slot = _integer(row.get("slot"), 1, 6)
        hp_percent = _integer(row.get("healthPercent"), 0, 100)
        if uuid in identities or slot in slots:
            raise RosterError("UUID ou slot duplicado na pokébar")
        identities.add(uuid)
        slots.add(slot)
        raw_moves = row.get("moves", [])
        if not isinstance(raw_moves, list) or len(raw_moves) > 64:
            raise RosterError("lista de habilidades inválida")
        moves = []
        seen_moves = set()
        for move in raw_moves:
            if not isinstance(move, dict):
                raise RosterError("habilidade inválida")
            word = move.get("spellword")
            if not isinstance(word, str) or not re.fullmatch(r"m[1-9][0-9]?", word):
                continue
            if word in seen_moves:
                raise RosterError("skill duplicada")
            seen_moves.add(word)
            remaining = _integer(move.get("remainingMs"), 0, 0xFFFFFFFF)
            total = _integer(move.get("totalMs"), 0, 0xFFFFFFFF)
            moves.append(PokemonMove(word, remaining, total))
        moves.sort(key=lambda move: int(move.spellword[1:]))
        pokemon.append(Pokemon(uuid, name, slot, hp_percent, tuple(moves)))
    pokemon.sort(key=lambda item: item.slot)
    active_slot = _integer(data.get("activeSlot", 0), 0, 6)
    active_name = data.get("pokemonName", "")
    active = next((item.uuid for item in pokemon
                   if item.slot == active_slot and item.name == active_name), None)
    return PokemonRoster(pid, tuple(pokemon), active)


class PokemonRosterReader:
    def __init__(self, directory=None, max_age=1.0):
        if not math.isfinite(max_age) or max_age <= 0:
            raise ValueError("max_age deve ser positivo e finito")
        root = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        self.directory = Path(directory) if directory else Path(root) / "OTPbot"
        self.max_age = max_age

    def read(self, pid, now=None):
        _integer(pid, 1, 0xFFFFFFFF)
        path = self.directory / f"telemetry_{pid}.json"
        try:
            with path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                raw = stream.read(MAX_TELEMETRY_BYTES + 1)
                after = os.fstat(stream.fileno())
            if len(raw) > MAX_TELEMETRY_BYTES:
                raise RosterError("telemetria excede 1 MB")
            if before.st_mtime_ns != after.st_mtime_ns or before.st_size != after.st_size:
                raise RosterError("telemetria em atualização; tente novamente")
            age = (time.time() if now is None else now) - after.st_mtime
            if not -1 <= age <= self.max_age:
                raise RosterError("telemetria desatualizada")
            data = json.loads(raw.decode("utf-8-sig"))
            return decode_roster(data, pid)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RosterError(f"não foi possível ler a pokébar: {exc}") from exc


def selection_values(roster, uuid, spellword):
    pokemon = roster.find(uuid)
    if pokemon is None:
        raise RosterError("Pokémon escolhido não está na pokébar atual")
    if not any(move.spellword == spellword for move in pokemon.moves):
        raise RosterError("skill escolhida não está disponível nesse Pokémon")
    return {"heal_pokemon_uuid": pokemon.uuid, "heal_pokemon_name": pokemon.name,
            "heal_move": spellword}
