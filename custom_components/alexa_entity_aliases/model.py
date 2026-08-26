"""Stable alias endpoint model.

Endpoint IDs are stable: the same entity and alias always produce the same
Alexa endpoint ID. Changing the format would cause Alexa to see aliases as
different devices.
"""

from __future__ import annotations

from collections.abc import Collection
from copy import deepcopy
from hashlib import sha256
import logging
from typing import Any

from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .const import ALEXA_ALIAS_DELIMITER

_LOGGER = logging.getLogger(__name__)

MAX_ENDPOINT_ID_LENGTH = 256
MAX_CUSTOM_IDENTIFIER_LENGTH = 256
MAX_DESCRIPTION_LENGTH = 128
MAX_FRIENDLY_NAME_LENGTH = 256


def _translation_table() -> dict[int, None]:
    # Import lazily so this module remains independent from Alexa load order.
    from homeassistant.components.alexa.entities import TRANSLATION_TABLE

    return TRANSLATION_TABLE


def generate_alexa_id_for(entity_id: str, alias: str | None = None) -> str:
    """Generate the canonical Alexa endpoint ID for an entity or alias."""
    alexa_id = entity_id.replace(".", "#").translate(_translation_table())
    if alias is None:
        return alexa_id

    identity = normalize_alias_identity(alias)
    if identity is None:
        raise ValueError("Alias has no valid Alexa identity")

    legacy_id = f"{alexa_id}{ALEXA_ALIAS_DELIMITER}{identity[1]}"
    if len(legacy_id) <= MAX_ENDPOINT_ID_LENGTH:
        return legacy_id

    digest = sha256(f"{entity_id}\0{identity[1]}".encode()).hexdigest()[:12]
    available_slug_length = (
        MAX_ENDPOINT_ID_LENGTH - len(alexa_id) - len(ALEXA_ALIAS_DELIMITER) - len(digest) - 1
    )
    if available_slug_length < 1:
        raise ValueError("Canonical endpoint ID leaves no room for an alias")
    return (
        f"{alexa_id}{ALEXA_ALIAS_DELIMITER}{identity[1][:available_slug_length]}-{digest}"
    )


def resolve_entity_id(endpoint_id: str) -> str:
    """Resolve canonical or alias Alexa endpoint ID to a HA entity ID."""
    entity_endpoint_id = endpoint_id.split(ALEXA_ALIAS_DELIMITER, 1)[0]
    return entity_endpoint_id.replace("#", ".")


def normalize_alias_identity(alias: str) -> tuple[str, str] | None:
    """Return the Alexa-safe display value and stable slug for an alias."""
    display_name = alias.translate(_translation_table()).strip()
    alias_slug = slugify(display_name)
    if (
        not display_name
        or not any(character.isalnum() for character in display_name)
        or not alias_slug
        or not alias_slug.isascii()
        or not all(character.isalnum() or character == "_" for character in alias_slug)
        or not any(character.isalnum() for character in alias_slug)
    ):
        return None
    return display_name, alias_slug


def generate_custom_identifier(user_identifier: str, entity_id: str, alias: str) -> str:
    """Generate a stable Alexa custom identifier for an alias endpoint."""
    identity = normalize_alias_identity(alias)
    if identity is None:
        raise ValueError("Alias has no valid Alexa identity")

    identifier = f"{user_identifier}-{entity_id}-alias-{identity[1]}"
    if len(identifier) <= MAX_CUSTOM_IDENTIFIER_LENGTH:
        return identifier

    digest = sha256(identifier.encode()).hexdigest()[:12]
    return f"{identifier[: MAX_CUSTOM_IDENTIFIER_LENGTH - len(digest) - 1]}-{digest}"


def normalize_aliases(entity_id: str, aliases: Collection[Any]) -> list[str]:
    """Normalize aliases into their display form, deduplicated and sorted."""
    try:
        computed_name = er.COMPUTED_NAME
    except AttributeError:
        computed_name = None

    unique_aliases: list[str] = []
    seen_alexa_ids: set[str] = set()

    for alias in aliases:
        if alias is None or alias is computed_name or not isinstance(alias, str):
            continue
        identity = normalize_alias_identity(alias)
        if identity is None:
            continue
        translated_alias, _ = identity
        try:
            alias_id = generate_alexa_id_for(entity_id, translated_alias)
        except ValueError:
            _LOGGER.warning("Skipping alias for %s: endpoint ID exceeds Alexa limits", entity_id)
            continue
        if alias_id in seen_alexa_ids:
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
        identity = normalize_alias_identity(self.alias)
        if identity is None:
            raise ValueError("Alias has no valid Alexa identity")
        return identity[0][:MAX_FRIENDLY_NAME_LENGTH]

    def description(self) -> str:
        description = (self.entity_conf.get("description") or self.entity_id).translate(
            _translation_table()
        )
        suffix_start = " (alias: "
        suffix_end = ") via Home Assistant"
        alias_limit = MAX_DESCRIPTION_LENGTH - len(suffix_start) - len(suffix_end)
        suffix = f"{suffix_start}{self.friendly_name()[:alias_limit]}{suffix_end}"
        return f"{description[: MAX_DESCRIPTION_LENGTH - len(suffix)]}{suffix}"

    def alexa_id(self) -> str:
        return generate_alexa_id_for(self.entity_id, self.alias)

    def custom_identifier(self) -> str:
        return generate_custom_identifier(
            self.config.user_identifier(), self.entity_id, self.alias
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
        # Never forward protocol/dunder lookups (copy, iteration, etc.) to the
        # wrapped entity; the proxy must not silently adopt its behavior.
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return getattr(self._wrapped, name)
