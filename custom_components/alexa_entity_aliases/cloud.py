"""Cloud-specific alias lifecycle reconciliation."""

from __future__ import annotations

from collections.abc import Collection
from contextlib import suppress
import logging
from typing import Any

from homeassistant.components.alexa.errors import NoTokenAvailable
from homeassistant.helpers import entity_registry as er

from .const import DATA_ALIAS_CACHE, DOMAIN
from .model import get_alias_alexa_ids, get_entity_aliases, normalize_aliases
from .patches import async_send_delete_endpoint_ids, core_already_supports_aliases

_LOGGER = logging.getLogger(__name__)


def build_alias_cache(hass: Any) -> dict[str, list[str]]:
    """Snapshot normalized aliases so removals can delete stale Alexa endpoints."""
    cache: dict[str, list[str]] = {}
    registry = er.async_get(hass)
    for entry in registry.entities.values():
        aliases = normalize_aliases(entry.entity_id, entry.aliases)
        if aliases:
            cache[entry.entity_id] = aliases
    return cache


async def _get_cloud_alexa_config(hass: Any) -> Any | None:
    try:
        from homeassistant.components.cloud.const import DATA_CLOUD

        cloud = hass.data.get(DATA_CLOUD)
        if cloud is None or not cloud.is_logged_in:
            return None
        return await cloud.client.get_alexa_config()
    except (ImportError, AttributeError, KeyError):
        return None


async def handle_registry_update(hass: Any, event: Any) -> None:
    """Reconcile added/removed aliases while keeping existing endpoint IDs stable."""
    # When the old Core patch is still installed, its Cloud listener already
    # performs this job. Doing it twice is unnecessary and can duplicate reports.
    if core_already_supports_aliases():
        return

    data = event.data
    entity_id = data["entity_id"]
    action = data["action"]
    cache: dict[str, list[str]] = hass.data[DOMAIN][DATA_ALIAS_CACHE]

    old_entity_id = data.get("old_entity_id")
    previous_aliases = cache.get(old_entity_id or entity_id, [])

    changes = data.get("changes") or {}
    old_aliases_from_event: Collection[Any] | None = None
    if isinstance(changes, dict) and "aliases" in changes:
        old_aliases_from_event = changes.get("aliases")
        if old_aliases_from_event is not None:
            previous_aliases = normalize_aliases(
                old_entity_id or entity_id, old_aliases_from_event
            )

    if action == "remove":
        current_aliases: list[str] = []
    else:
        current_aliases = get_entity_aliases(hass, entity_id)
        if current_aliases:
            cache[entity_id] = current_aliases
        else:
            cache.pop(entity_id, None)

    if old_entity_id:
        cache.pop(old_entity_id, None)

    aliases_changed = previous_aliases != current_aliases or bool(old_entity_id)
    if not aliases_changed:
        return

    config = await _get_cloud_alexa_config(hass)
    if config is None or not getattr(config, "enabled", True):
        return

    # Do not leak aliases for entities not exposed to Alexa.
    if action != "remove" and not config.should_expose(entity_id):
        return

    stale_ids: list[str] = []
    if old_entity_id:
        stale_ids.extend(get_alias_alexa_ids(hass, old_entity_id, previous_aliases))
    else:
        old_ids = set(get_alias_alexa_ids(hass, entity_id, previous_aliases))
        new_ids = set(get_alias_alexa_ids(hass, entity_id, current_aliases))
        stale_ids.extend(sorted(old_ids - new_ids))

    # Syncing additions and deleting stale endpoints are deliberately
    # independent: a failure in the private Cloud sync API must not also
    # skip removal of endpoints that Alexa should no longer see.
    if action != "remove":
        try:
            # Add/update current aliases first. This mirrors the old patch and
            # avoids a gap when an alias is changed or an entity is renamed.
            await config._sync_helper([entity_id], [])
        except NoTokenAvailable:
            return
        except Exception:
            _LOGGER.exception("Failed to sync Alexa aliases for %s", entity_id)

    if not stale_ids:
        return

    try:
        await async_send_delete_endpoint_ids(hass, config, stale_ids)
    except NoTokenAvailable:
        return
    except Exception:
        _LOGGER.exception(
            "Failed to delete stale Alexa alias endpoints for %s", entity_id
        )
