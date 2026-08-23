"""Alexa Entity Aliases custom integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .cloud import build_alias_cache, handle_registry_update
from .const import DATA_ALIAS_CACHE, DATA_UNSUB, DOMAIN
from .patches import core_already_supports_aliases, install
from .services import async_register_services

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up Alexa Entity Aliases."""
    hass.data.setdefault(DOMAIN, {})
    async_register_services(hass)

    try:
        install()
    except Exception:
        _LOGGER.exception(
            "Alexa Entity Aliases is incompatible with this Home Assistant version; "
            "no runtime patches were installed"
        )
        return False

    hass.data[DOMAIN][DATA_ALIAS_CACHE] = build_alias_cache(hass)

    if core_already_supports_aliases():
        # Seamless migration mode: while the old amitfin/Core patch is present,
        # leave it fully in charge. After that patch is removed and HA restarts,
        # this component automatically becomes active.
        return True

    async def _listener(event: Any) -> None:
        await handle_registry_update(hass, event)

    unsub = hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, _listener)
    hass.data[DOMAIN][DATA_UNSUB] = unsub
    return True
