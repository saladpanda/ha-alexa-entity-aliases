"""Directive endpoint validation tests.

Run directly (no pytest required): python tests/test_directive_resolution.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "custom_components"))

from homeassistant.components.alexa import entities as alexa_entities
from homeassistant.components.alexa import state_report as alexa_state_report

import alexa_entity_aliases.patches as patches
from alexa_entity_aliases.model import generate_alexa_id_for


class FakeStates:
    def __init__(self, entity):
        self.entity = entity

    def get(self, entity_id):
        return self.entity if entity_id == self.entity.entity_id else None


class FakeConfig:
    def __init__(self, exposed=True):
        self.exposed = exposed

    def should_expose(self, entity_id):
        return self.exposed


def directive(endpoint_id):
    return SimpleNamespace(
        _directive={"endpoint": {"endpointId": endpoint_id}, "header": {}}
    )


def assert_invalid(load_entity, hass, config, endpoint_id) -> None:
    try:
        load_entity(directive(endpoint_id), hass, config)
    except alexa_state_report.AlexaInvalidEndpointError:
        return
    raise AssertionError(f"accepted invalid endpoint {endpoint_id}")


def test_directive_resolution() -> None:
    entity = SimpleNamespace(entity_id="test.device", domain="test")
    hass = SimpleNamespace(states=FakeStates(entity))
    config = FakeConfig()
    canonical_id = generate_alexa_id_for(entity.entity_id)
    alias_id = generate_alexa_id_for(entity.entity_id, "Desk Device")

    original_aliases = patches.get_alias_alexa_ids
    original_adapter = alexa_entities.ENTITY_ADAPTERS.get("test")
    patches.get_alias_alexa_ids = lambda hass, entity_id: [alias_id]
    alexa_entities.ENTITY_ADAPTERS["test"] = lambda hass, config, state: state
    try:
        patches.install()
        load_entity = alexa_state_report.AlexaDirective.load_entity

        canonical = directive(canonical_id)
        load_entity(canonical, hass, config)
        assert canonical.entity is entity

        alias = directive(alias_id)
        load_entity(alias, hass, config)
        assert alias.entity_id == entity.entity_id

        assert_invalid(load_entity, hass, config, f"{canonical_id}::alias::deleted")
        assert_invalid(load_entity, hass, config, f"{alias_id}::alias::malformed")
        assert_invalid(load_entity, hass, FakeConfig(exposed=False), canonical_id)
        assert_invalid(load_entity, hass, config, "test#missing")
    finally:
        patches.uninstall()
        patches.get_alias_alexa_ids = original_aliases
        if original_adapter is None:
            del alexa_entities.ENTITY_ADAPTERS["test"]
        else:
            alexa_entities.ENTITY_ADAPTERS["test"] = original_adapter


def main() -> int:
    test_directive_resolution()
    print("ALL DIRECTIVE RESOLUTION TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
