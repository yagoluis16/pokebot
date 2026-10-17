import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from memory import Resolver
from modules.healer import Healer, _resolve_vk

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def make_healer(monkeypatch):
    monkeypatch.setitem(sys.modules, "inputbus", SimpleNamespace(get_bus=Mock()))
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr("modules.healer.time.monotonic", lambda: clock.now)

    def create(hp=110, hp_max=200, settings=None):
        config = {"healer": dict(settings or {})}

        def get(*keys, default=None):
            value = config
            for key in keys:
                if not isinstance(value, dict) or key not in value:
                    return default
                value = value[key]
            return default if value is None else value

        ctx = SimpleNamespace(config=config, get=get, inc_stat=Mock())
        bus = SimpleNamespace(press_key=Mock(return_value=True))
        values = {"hp": hp, "hp_max": hp_max}
        resolver = SimpleNamespace(read_field=Mock(side_effect=lambda block, field: values[field]))
        healer = Healer(ctx=ctx, bus=bus, resolver=resolver)
        return healer, ctx, bus, resolver, values, clock

    return create


def test_hp_heals_without_reading_mp(make_healer):
    healer, ctx, bus, resolver, _, _ = make_healer()
    healer.tick()
    assert resolver.read_field.call_args_list == [call("player", "hp"), call("player", "hp_max")]
    bus.press_key.assert_called_once_with(0x70, 50.0, 5, module="healer")
    ctx.inc_stat.assert_called_once_with("heals")
    assert healer.stats["heals_sent"] == 1


def test_normal_cooldown_is_not_key_hold(make_healer):
    healer, _, bus, _, _, clock = make_healer(settings={"cooldown_ms": 800, "hold_ms": 30})
    healer.tick()
    clock.now = 0.799
    healer.tick()
    assert bus.press_key.call_count == 1
    assert healer.last_skip_reason == "cura em cooldown"
    clock.now = 0.801
    healer.tick()
    assert bus.press_key.call_count == 2
    assert bus.press_key.call_args == call(0x70, 30.0, 5, module="healer")


def test_emergency_priority_cooldown_and_normal_reset(make_healer):
    healer, _, bus, _, values, clock = make_healer(hp=30)
    healer.tick()
    bus.press_key.assert_called_once_with(0x72, 50.0, 1, module="healer")
    clock.now = 0.399
    healer.tick()
    assert bus.press_key.call_count == 1
    clock.now = 0.401
    healer.tick()
    assert bus.press_key.call_count == 2
    values["hp"] = 100
    clock.now = 0.9
    healer.tick()
    assert bus.press_key.call_count == 2
    clock.now = 1.202
    healer.tick()
    assert bus.press_key.call_count == 3
    assert healer.stats["emergency_heals_sent"] == 2
    assert healer.stats["heals_sent"] == 1


def test_emergency_can_interrupt_normal_cooldown(make_healer):
    healer, _, bus, _, values, clock = make_healer()
    healer.tick()
    values["hp"] = 30
    clock.now = 0.1
    healer.tick()
    assert bus.press_key.call_count == 2
    assert bus.press_key.call_args.args[0] == 0x72


@pytest.mark.parametrize("hp,hp_max", [(None, 200), (100, None), (100, 0), (100, -1), (0, 200), (-1, 200), (201, 200), (120, 200)])
def test_invalid_or_sufficient_hp_does_not_press(make_healer, hp, hp_max):
    healer, _, bus, _, _, _ = make_healer(hp=hp, hp_max=hp_max)
    healer.tick()
    bus.press_key.assert_not_called()
    assert healer.last_skip_reason


def test_missing_resolver_is_noop(make_healer):
    healer, _, bus, _, _, _ = make_healer()
    healer.resolver = None
    healer.tick()
    bus.press_key.assert_not_called()
    assert healer.last_skip_reason == "resolver indisponível"


def test_threshold_boundary_is_normal_not_emergency(make_healer):
    healer, _, bus, _, _, _ = make_healer(hp=50)
    healer.tick()
    assert bus.press_key.call_args.args[0] == 0x70


@pytest.mark.parametrize("hp", [110, 30])
def test_rejected_queue_does_not_count_or_start_cooldown(make_healer, hp):
    healer, ctx, bus, _, _, _ = make_healer(hp=hp)
    bus.press_key.return_value = False
    healer.tick()
    ctx.inc_stat.assert_not_called()
    assert healer.heals_sent == healer.emergency_heals_sent == 0
    assert healer._last_heal_ts is None
    assert healer._last_emergency_ts is None
    bus.press_key.return_value = True
    healer.tick()
    ctx.inc_stat.assert_called_once_with("heals")


def test_existing_config_preserves_hotkeys_and_uses_delay_as_cooldown(make_healer):
    settings = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["healer"]
    healer, _, bus, _, _, clock = make_healer(settings=settings)
    assert healer.cooldown_ms == 650
    assert healer.hold_ms == 50
    assert healer.hp_threshold_pct == 60
    assert healer.emergency_threshold_pct == 25
    healer.tick()
    clock.now = 0.649
    healer.tick()
    assert bus.press_key.call_count == 1


def test_gui_config_updates_are_observed_next_tick(make_healer):
    healer, ctx, bus, _, _, _ = make_healer(hp=130)
    healer.tick()
    bus.press_key.assert_not_called()
    ctx.config["healer"].update(hp_percent_threshold=70, hp_hotkey="F4")
    healer.tick()
    assert bus.press_key.call_args.args[0] == 0x73


def test_alias_config_and_explicit_cooldown(make_healer):
    healer, _, bus, _, _, _ = make_healer(settings={"hotkey": "F5", "cooldown_ms": 900, "delay_between_heals_ms": 650})
    healer.tick()
    assert healer.cooldown_ms == 900
    assert bus.press_key.call_args.args[0] == 0x74


@pytest.mark.parametrize("settings", [{"hp_percent_threshold": 101}, {"panic_hp_percent": 70}, {"hold_ms": -1}, {"cooldown_ms": float("nan")}, {"emergency_cooldown_ms": -1}])
def test_invalid_settings_are_rejected(make_healer, settings):
    with pytest.raises(ValueError):
        make_healer(settings=settings)


@pytest.mark.parametrize("hotkey,expected", [("F1", 0x70), (" f12 ", 0x7B), ("1", 0x31), ("0x70", 0x70), ("112", 0x70)])
def test_hotkey_resolution(hotkey, expected):
    assert _resolve_vk(hotkey) == expected


@pytest.mark.parametrize("hotkey", ["invalid", "0x100", "-1"])
def test_invalid_hotkey(hotkey):
    with pytest.raises(ValueError):
        _resolve_vk(hotkey)


def test_legacy_resolver_returns_none_for_unknown_and_unverified_mp():
    resolver = Resolver(None, str(ROOT / "offsets.json"), str(ROOT / "config.json"))
    assert resolver.read_field("player", "mp") is None
    assert resolver.read_field("player", "mp_max") is None
    resolver.entries.pop("player.mp", None)
    assert resolver.read_field("player", "mp") is None
