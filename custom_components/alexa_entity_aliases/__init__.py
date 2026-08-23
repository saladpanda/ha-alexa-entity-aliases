"""Alexa Entity Aliases custom integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .cloud import build_alias_cache, handle_registry_update
from .const import DATA_ALIAS_CACHE, DATA_UNSUB, DOMAIN
from .patches import install, uninstall
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Alexa Entity Aliases from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    try:
        installed = install()
    except Exception:
        _LOGGER.exception(
            "Alexa Entity Aliases is incompatible with this Home Assistant version; "
            "no runtime patches were installed"
        )
        return False

    async_register_services(hass)
    hass.data[DOMAIN][DATA_ALIAS_CACHE] = build_alias_cache(hass)

    if not installed:
        # Seamless migration mode: while the old amitfin/Core patch is present,
        # leave it fully in charge. After that patch is removed and HA restarts,
        # this component automatically becomes active.
        return True

    async def _listener(event: Any) -> None:
        await handle_registry_update(hass, event)

    hass.data[DOMAIN][DATA_UNSUB] = hass.bus.async_listen(
        er.EVENT_ENTITY_REGISTRY_UPDATED, _listener
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and restore patched Core behavior."""
    data = hass.data.get(DOMAIN, {})
    unsub = data.pop(DATA_UNSUB, None)
    if unsub is not None:
        unsub()
    data.pop(DATA_ALIAS_CACHE, None)

    async_unregister_services(hass)
    uninstall()
    return True
