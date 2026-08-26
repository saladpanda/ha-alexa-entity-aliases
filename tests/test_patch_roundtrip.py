"""Compatibility tests for the Alexa alias shim.

Run directly (no pytest required): python tests/test_patch_roundtrip.py

The CI matrix (.github/workflows/test-matrix.yml) executes this against
multiple Home Assistant releases to catch Core changes early.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "custom_components"))

from homeassistant.components.alexa import config as alexa_config
from homeassistant.components.alexa import handlers as alexa_handlers
from homeassistant.components.alexa import state_report as alexa_state_report

import alexa_entity_aliases.patches as patches

SNAPSHOT_ATTRS = [
    (alexa_config.AbstractConfig, name)
    for name in (
        "generate_alexa_id_for",
        "get_entity_aliases",
        "normalize_aliases",
        "get_alias_alexa_ids",
        "get_entity_alexa_ids",
        "resolve_entity_id",
    )
] + [
    (alexa_state_report.AlexaDirective, "load_entity"),
    (alexa_handlers, "async_get_entities"),
    (alexa_state_report, "async_send_add_or_update_message"),
    (alexa_state_report, "async_send_delete_message"),
    (alexa_state_report, "async_send_changereport_message"),
    (alexa_state_report, "async_send_doorbell_event_message"),
]


def snapshot() -> dict:
    return {
        (owner, name): getattr(owner, name, None) for owner, name in SNAPSHOT_ATTRS
    }


def test_parameter_names_fallback() -> None:
    """Signature introspection must survive unresolvable annotations (py3.14)."""
    def load_entity(self, hass, config):
        pass

    def async_send_add_or_update_message(hass, config, entity_ids):
        pass

    original = inspect.signature

    def raising_signature(func, *args, **kwargs):
        raise NameError("name 'AbstractConfig' is not defined")

    inspect.signature = raising_signature
    try:
        assert patches._parameter_names(load_entity) == {"self", "hass", "config"}
        assert patches._parameter_names(async_send_add_or_update_message) == {
            "hass",
            "config",
            "entity_ids",
        }
    finally:
        inspect.signature = original

    assert patches._parameter_names(load_entity) == {"self", "hass", "config"}


def test_response_error_parsing() -> None:
    assert patches._response_error('{"payload":{"code":"BAD","description":"bad"}}') == (
        "BAD",
        "bad",
    )
    for response in ("", "<html>error</html>", "{}", '{"payload":{}}'):
        assert patches._response_error(response) is None


def test_install_uninstall_roundtrip() -> None:
    before = snapshot()

    installed = patches.install()
    assert installed is None, "install() must not return a value"

    during = snapshot()
    changed = [key for key in before if before[key] != during[key]]
    assert len(changed) == len(SNAPSHOT_ATTRS), f"not all attrs patched: {changed}"

    patches.uninstall()
    after = snapshot()
    not_restored = [key for key in before if before[key] != after[key]]
    assert not not_restored, f"attributes not restored: {not_restored}"
    assert patches._ORIGINALS == [], "_ORIGINALS not drained"

    patches.uninstall()  # second call must be a no-op


def test_double_install_is_harmless() -> None:
    before = snapshot()
    patches.install()
    first = snapshot()
    originals_count = len(patches._ORIGINALS)

    patches.install()
    assert snapshot() == first, "second install changed patched attributes"
    assert len(patches._ORIGINALS) == originals_count, "second install recorded patches"

    patches.uninstall()
    assert snapshot() == before, "double install did not restore originals"


def test_uninstall_preserves_foreign_patch() -> None:
    owner, name = SNAPSHOT_ATTRS[6]
    original = getattr(owner, name)
    patches.install()

    def foreign_patch(*args, **kwargs):
        return None

    setattr(owner, name, foreign_patch)
    patches.uninstall()
    assert getattr(owner, name) is foreign_patch, "uninstall overwrote a foreign patch"
    setattr(owner, name, original)


def test_rollback_on_partial_failure() -> None:
    before = snapshot()

    original = patches._install_state_reporting

    def boom() -> None:
        raise RuntimeError("boom")

    patches._install_state_reporting = boom
    try:
        patches.install()
    except RuntimeError:
        pass
    else:
        raise AssertionError("install() should have re-raised")
    finally:
        patches._install_state_reporting = original

    leftover = snapshot()
    dirty = [key for key in before if before[key] != leftover[key]]
    assert not dirty, f"rollback left patches behind: {dirty}"
    assert patches._ORIGINALS == [], "rollback did not drain _ORIGINALS"


def main() -> int:
    test_parameter_names_fallback()
    print("parameter-name fallback OK")
    test_response_error_parsing()
    print("response-error parsing OK")
    test_install_uninstall_roundtrip()
    print("install/uninstall round-trip OK")
    test_double_install_is_harmless()
    print("double install OK")
    test_uninstall_preserves_foreign_patch()
    print("foreign patch preservation OK")
    test_rollback_on_partial_failure()
    print("rollback-on-failure OK")
    print("ALL COMPATIBILITY TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
