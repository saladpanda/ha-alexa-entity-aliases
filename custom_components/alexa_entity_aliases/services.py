"""Home Assistant actions exposed by Alexa Entity Aliases."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, SERVICE_LIST_ALIASES
from .model import get_alias_alexa_ids, normalize_aliases


LIST_ALIASES_SCHEMA = vol.Schema(
    {
        vol.Optional("include_computed", default=False): bool,
    }
)


def _literal_aliases(entry: Any) -> list[str]:
    """Return user-defined literal aliases, excluding COMPUTED_NAME."""
    computed_name = getattr(er, "COMPUTED_NAME", object())
    return [
        alias
        for alias in entry.aliases
        if isinstance(alias, str) and alias is not computed_name and alias.strip()
    ]


def _resolved_aliases(hass: HomeAssistant, entry: Any) -> list[str]:
    """Return aliases with COMPUTED_NAME resolved when supported by Core."""
    helper = getattr(er, "async_get_entity_aliases", None)
    if callable(helper):
        return helper(hass, entry)
    return _literal_aliases(entry)


async def async_list_aliases(
    hass: HomeAssistant, call: ServiceCall
) -> dict[str, Any]:
    """Return all entity aliases and their effective Alexa endpoint IDs."""
    include_computed = call.data["include_computed"]
    registry = er.async_get(hass)

    entities: list[dict[str, Any]] = []
    literal_alias_count = 0
    alexa_alias_count = 0

    for entry in sorted(registry.entities.values(), key=lambda item: item.entity_id):
        literal_aliases = _literal_aliases(entry)
        alexa_aliases = normalize_aliases(entry.entity_id, entry.aliases)

        # By default this is a concise inventory of aliases explicitly configured
        # by the user. On newer HA versions most entries contain COMPUTED_NAME,
        # which would otherwise make this action return nearly every entity.
        if not literal_aliases and not (include_computed and entry.aliases):
            continue

        item: dict[str, Any] = {
            "entity_id": entry.entity_id,
            "aliases": literal_aliases,
            "alexa_aliases": alexa_aliases,
            "alexa_endpoint_ids": get_alias_alexa_ids(
                hass, entry.entity_id, entry.aliases
            ),
        }
        if include_computed:
            item["resolved_aliases"] = _resolved_aliases(hass, entry)

        entities.append(item)
        literal_alias_count += len(literal_aliases)
        alexa_alias_count += len(alexa_aliases)

    return {
        "entity_count": len(entities),
        "alias_count": literal_alias_count,
        "alexa_alias_count": alexa_alias_count,
        "entities": entities,
    }


def async_register_services(hass: HomeAssistant) -> None:
    """Register integration actions."""
    if hass.services.has_service(DOMAIN, SERVICE_LIST_ALIASES):
        return

    async def _handle_list_aliases(call: ServiceCall) -> dict[str, Any]:
        return await async_list_aliases(hass, call)

    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_ALIASES,
        _handle_list_aliases,
        schema=LIST_ALIASES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
