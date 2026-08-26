"""Alias endpoint identity tests.

Run directly (no pytest required): python tests/test_model_identity.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "custom_components"))

import alexa_entity_aliases.model as model


def test_alias_identity() -> None:
    original_translation_table = model._translation_table
    model._translation_table = lambda: {}
    try:
        assert (
            model.generate_alexa_id_for("light.desk", "Reading Light")
            == "light#desk::alias::reading_light"
        )
        assert model.normalize_alias_identity("   ") is None
        assert model.normalize_alias_identity("!!!") is None
        assert model.normalize_alias_identity("Reading Light") == (
            "Reading Light",
            "reading_light",
        )

        normalized = model.normalize_aliases(
            "light.desk", ["Reading Light", "reading-light", "READING LIGHT", "!!!"]
        )
        assert normalized == ["Reading Light"]
    finally:
        model._translation_table = original_translation_table


def test_bounded_alias_ids() -> None:
    original_translation_table = model._translation_table
    model._translation_table = lambda: {}
    try:
        entity_id = f"light.{'e' * 100}"
        alias_one = "a" * 300
        alias_two = f"{'a' * 299}b"
        endpoint_one = model.generate_alexa_id_for(entity_id, alias_one)
        endpoint_two = model.generate_alexa_id_for(entity_id, alias_two)
        assert len(endpoint_one) == model.MAX_ENDPOINT_ID_LENGTH
        assert endpoint_one.isascii()
        assert endpoint_one == model.generate_alexa_id_for(entity_id, alias_one)
        assert endpoint_one != endpoint_two

        unicode_endpoint = model.generate_alexa_id_for(entity_id, "Lämp in the Office")
        assert unicode_endpoint.isascii()
        assert len(unicode_endpoint) <= model.MAX_ENDPOINT_ID_LENGTH

        exact_alias = "a" * (
            model.MAX_ENDPOINT_ID_LENGTH
            - len(model.generate_alexa_id_for("light.desk"))
            - len("::alias::")
        )
        assert (
            len(model.generate_alexa_id_for("light.desk", exact_alias))
            == model.MAX_ENDPOINT_ID_LENGTH
        )
    finally:
        model._translation_table = original_translation_table


def main() -> int:
    test_alias_identity()
    test_bounded_alias_ids()
    print("ALL MODEL IDENTITY TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
