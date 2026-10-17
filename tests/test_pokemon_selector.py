from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from core.pokemon_roster import Pokemon, PokemonMove, PokemonRoster, RosterError
from gui.pokemon_selector import PokemonHealerSelector


@pytest.fixture
def selector(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    config = {"healer": {"hp_hotkey": "F1"}}

    def get(*keys, default=None):
        value = config
        for key in keys:
            if not isinstance(value, dict) or key not in value:
                return default
            value = value[key]
        return value

    def set_value(value, section, key):
        config.setdefault(section, {})[key] = value

    ctx = SimpleNamespace(get=get, set=set_value)
    pokemon = Pokemon("identity", "Togepi", 2, 100, (PokemonMove("m1", 0, 1000),))
    reader = SimpleNamespace(read=Mock(return_value=PokemonRoster(123, (pokemon,), None)))
    widget = PokemonHealerSelector(ctx, reader=reader, process_provider=lambda: [123])
    widget.timer.stop()
    yield widget, config, reader
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_user_selects_pokemon_and_available_skill(selector):
    widget, config, _ = selector
    widget.pokemon_combo.setCurrentIndex(1)
    widget.skill_combo.setCurrentIndex(1)
    assert config["healer"]["heal_pokemon_uuid"] == "identity"
    assert config["healer"]["heal_pokemon_name"] == "Togepi"
    assert config["healer"]["heal_move"] == "m1"
    assert config["healer"]["hp_hotkey"] == "F1"


def test_refresh_preserves_identity_when_order_changes(selector):
    widget, config, reader = selector
    widget.pokemon_combo.setCurrentIndex(1)
    widget.skill_combo.setCurrentIndex(1)
    pokemon = Pokemon("identity", "Togepi", 1, 100, (PokemonMove("m1", 0, 1000),))
    reader.read.return_value = PokemonRoster(123, (pokemon,), "identity")
    widget.refresh()
    assert widget.pokemon_combo.currentData() == "identity"
    assert widget.skill_combo.currentData() == "m1"


def test_stale_telemetry_disables_selection_without_erasing_config(selector):
    widget, config, reader = selector
    widget.pokemon_combo.setCurrentIndex(1)
    reader.read.side_effect = RosterError("telemetria desatualizada")
    widget.refresh()
    assert not widget.pokemon_combo.isEnabled()
    assert not widget.skill_combo.isEnabled()
    assert config["healer"]["heal_pokemon_uuid"] == "identity"
