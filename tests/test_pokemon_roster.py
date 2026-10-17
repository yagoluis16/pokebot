import json
import os

import pytest

from core.pokemon_roster import PokemonRosterReader, RosterError, decode_roster, selection_values


@pytest.fixture
def payload():
    return {"clientPid": 123, "nativeVerified": True, "pulseVersion": 3,
            "activeSlot": 1, "pokemonName": "Togepi", "roster": [
                {"slot": 1, "uuid": "uuid-healer", "name": "Togepi", "healthPercent": 100,
                 "moves": [{"spellword": "m2", "remainingMs": 300, "totalMs": 5000},
                           {"spellword": "m1", "remainingMs": 0, "totalMs": 1000},
                           {"spellword": "passive", "remainingMs": 0, "totalMs": 0}]},
                {"slot": 2, "uuid": "uuid-other", "name": "Togepi", "healthPercent": 87,
                 "moves": []}]}


def test_roster_preserves_duplicate_names_but_distinct_identities(payload):
    roster = decode_roster(payload, 123)
    assert [pokemon.name for pokemon in roster.pokemon] == ["Togepi", "Togepi"]
    assert roster.active_uuid == "uuid-healer"
    assert [move.spellword for move in roster.find("uuid-healer").moves] == ["m1", "m2"]
    assert roster.find("uuid-healer").moves[1].remaining_ms == 300


def test_uuid_selection_survives_pokebar_reordering(payload):
    original = selection_values(decode_roster(payload, 123), "uuid-healer", "m2")
    payload["roster"][0]["slot"] = 2
    payload["roster"][1]["slot"] = 1
    roster = decode_roster(payload, 123)
    assert roster.find("uuid-healer").slot == 2
    assert selection_values(roster, "uuid-healer", "m2") == original


@pytest.mark.parametrize("uuid,move", [("missing", "m1"), ("uuid-healer", "m9"), ("uuid-healer", "passive")])
def test_selection_rejects_unknown_pokemon_or_skill(payload, uuid, move):
    with pytest.raises(RosterError):
        selection_values(decode_roster(payload, 123), uuid, move)


@pytest.mark.parametrize("field,value", [("nativeVerified", False), ("clientPid", 124), ("clientPid", True),
                                         ("pulseVersion", 2), ("pulseVersion", True), ("roster", {}),
                                         ("activeSlot", 7)])
def test_incompatible_snapshot_is_rejected(payload, field, value):
    payload[field] = value
    with pytest.raises(RosterError):
        decode_roster(payload, 123)


@pytest.mark.parametrize("field,value", [("healthPercent", 101), ("healthPercent", True), ("slot", 0),
                                         ("name", ""), ("uuid", ""), ("name", "bad\nname"), ("moves", {})])
def test_invalid_pokemon_is_rejected(payload, field, value):
    payload["roster"][0][field] = value
    with pytest.raises(RosterError):
        decode_roster(payload, 123)


@pytest.mark.parametrize("field", ["uuid", "slot"])
def test_duplicate_identity_or_slot_is_rejected(payload, field):
    payload["roster"][1][field] = payload["roster"][0][field]
    with pytest.raises(RosterError):
        decode_roster(payload, 123)


def test_reader_checks_pid_freshness_and_utf8_bom(tmp_path, payload):
    path = tmp_path / "telemetry_123.json"
    path.write_text(json.dumps(payload), encoding="utf-8-sig")
    os.utime(path, (1000, 1000))
    reader = PokemonRosterReader(tmp_path)
    assert reader.read(123, now=1000.5).find("uuid-healer").name == "Togepi"
    with pytest.raises(RosterError, match="desatualizada"):
        reader.read(123, now=1002)
    with pytest.raises(RosterError, match="desatualizada"):
        reader.read(123, now=998)


@pytest.mark.parametrize("content", [b"{", b"\xff\xfe", b"x" * (1024 * 1024 + 1)],
                         ids=["partial", "encoding", "oversized"])
def test_reader_rejects_partial_invalid_or_oversized_file(tmp_path, content):
    (tmp_path / "telemetry_123.json").write_bytes(content)
    with pytest.raises(RosterError):
        PokemonRosterReader(tmp_path).read(123)


def test_missing_telemetry_is_explicit(tmp_path):
    with pytest.raises(RosterError):
        PokemonRosterReader(tmp_path).read(123)


def test_empty_roster_is_valid_but_has_no_selection(payload):
    payload.update(roster=[], activeSlot=0, pokemonName="")
    assert decode_roster(payload, 123).pokemon == ()


def test_name_mismatch_does_not_infer_active_identity(payload):
    payload["pokemonName"] = "Spearow"
    assert decode_roster(payload, 123).active_uuid is None
