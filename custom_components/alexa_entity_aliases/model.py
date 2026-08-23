"""Stable alias endpoint model.

The endpoint format deliberately matches the Home Assistant Core Alexa-alias
patch. Changing it would cause Alexa to see aliases as different devices.
"""

from __future__ import annotations

from collections.abc import Collection
from copy import deepcopy
from typing import Any

from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .const import ALEXA_ALIAS_DELIMITER


def _translation_table() -> dict[int, None]:
    # Import lazily so this module remains independent from Alexa load order.
    from homeassistant.components.alexa.entities import TRANSLATION_TABLE

    return TRANSLATION_TABLE


def generate_alexa_id_for(entity_id: str, alias: str | None = None) -> str:
    """Generate the exact endpoint ID used by the old Core patch."""
    alexa_id = entity_id.replace(".", "#").translate(_translation_table())
    if alias is None:
        return alexa_id
    return f"{alexa_id}{ALEXA_ALIAS_DELIMITER}{slugify(alias)}"


def resolve_entity_id(endpoint_id: str) -> str:
    """Resolve canonical or alias Alexa endpoint ID to a HA entity ID."""
    entity_endpoint_id = endpoint_id.split(ALEXA_ALIAS_DELIMITER, 1)[0]
    return entity_endpoint_id.replace("#", ".")


def normalize_aliases(entity_id: str, aliases: Collection[Any]) -> list[str]:
    """Normalize aliases exactly like the old Core patch."""
    try:
        computed_name = er.COMPUTED_NAME
    except AttributeError:
        computed_name = None

    unique_aliases: list[str] = []
    seen_alexa_ids: set[str] = set()

    for alias in aliases:
        if alias is None or alias is computed_name or not isinstance(alias, str):
            continue
        translated_alias = alias.translate(_translation_table()).strip()
        alias_id = generate_alexa_id_for(entity_id, translated_alias)
        if not translated_alias or alias_id in seen_alexa_ids:
            continue
        seen_alexa_ids.add(alias_id)
        unique_aliases.append(translated_alias)

    return sorted(unique_aliases, key=str.casefold)


def get_entity_aliases(hass: Any, entity_id: str) -> list[str]:
    """Return literal registry aliases for an entity."""
    entity_registry = er.async_get(hass)
    if not (entity_entry := entity_registry.async_get(entity_id)):
        return []
    return normalize_aliases(entity_id, entity_entry.aliases)


def get_alias_alexa_ids(
    hass: Any, entity_id: str, aliases: Collection[Any] | None = None
) -> list[str]:
    """Return alias endpoint IDs."""
    normalized = (
        get_entity_aliases(hass, entity_id)
        if aliases is None
        else normalize_aliases(entity_id, aliases)
    )
    return [generate_alexa_id_for(entity_id, alias) for alias in normalized]


def get_entity_alexa_ids(hass: Any, entity_id: str) -> list[str]:
    """Return canonical endpoint followed by alias endpoints."""
    return [generate_alexa_id_for(entity_id), *get_alias_alexa_ids(hass, entity_id)]


class AliasAlexaEntity:
    """Proxy an AlexaEntity as an alias endpoint without modifying Core classes."""

    def __init__(self, wrapped: Any, alias: str) -> None:
        self._wrapped = wrapped
        self.alias = alias
        self.hass = wrapped.hass
        self.config = wrapped.config
        self.entity = wrapped.entity
        self.entity_conf = wrapped.entity_conf

    @property
    def entity_id(self) -> str:
        return self._wrapped.entity_id

    def friendly_name(self) -> str:
        return self.alias.translate(_translation_table())

    def description(self) -> str:
        description = (self.entity_conf.get("description") or self.entity_id).translate(
            _translation_table()
        )
        return f"{description} (alias: {self.alias}) via Home Assistant"

    def alexa_id(self) -> str:
        return generate_alexa_id_for(self.entity_id, self.alias)

    def custom_identifier(self) -> str:
        return (
            f"{self.config.user_identifier()}-{self.entity_id}"
            f"-alias-{slugify(self.alias)}"
        )

    def serialize_discovery(self) -> dict[str, Any]:
        # Start from Core's current serialization so new capabilities/metadata
        # are inherited automatically, then replace only alias-specific fields.
        result = deepcopy(self._wrapped.serialize_discovery())
        result["endpointId"] = self.alexa_id()
        result["friendlyName"] = self.friendly_name()
        result["description"] = self.description()
        additional = result.setdefault("additionalAttributes", {})
        additional["customIdentifier"] = self.custom_identifier()
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)
