"""Runtime compatibility patches for Home Assistant Alexa internals."""

from __future__ import annotations

from asyncio import timeout
from collections.abc import Collection
from http import HTTPStatus
import inspect
import json
import logging
from typing import Any, cast

import aiohttp

from homeassistant.components.alexa import config as alexa_config
from homeassistant.components.alexa import entities as alexa_entities
from homeassistant.components.alexa import handlers as alexa_handlers
from homeassistant.components.alexa import state_report as alexa_state_report
from homeassistant.components.alexa.const import API_CHANGE, Cause, DATE_FORMAT
from homeassistant.components.alexa.diagnostics import async_redact_auth_data
from homeassistant.components.alexa.errors import NoTokenAvailable, RequireRelink
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
from homeassistant.util.json import JsonObjectType, json_loads_object

from .model import (
    AliasAlexaEntity,
    generate_alexa_id_for,
    get_alias_alexa_ids,
    get_entity_alexa_ids,
    get_entity_aliases,
    normalize_aliases,
    resolve_entity_id,
)

_LOGGER = logging.getLogger(__name__)
_PATCH_MARKER = "__alexa_entity_aliases_patch__"

# (owner, attribute name, pre-patch value) for every installed patch, in
# install order. Used by uninstall() to fully restore Core modules.
_ORIGINALS: list[tuple[Any, str, Any]] = []


def _mark(obj: Any) -> Any:
    setattr(obj, _PATCH_MARKER, True)
    return obj


def _is_marked(obj: Any) -> bool:
    return bool(getattr(obj, _PATCH_MARKER, False))


# Sentinel recorded when a patched attribute did not exist before installation.
_MISSING = object()


def _set_patched(owner: Any, name: str, value: Any) -> None:
    _ORIGINALS.append((owner, name, getattr(owner, name, _MISSING)))
    setattr(owner, name, value)


def _parameter_names(func: Any) -> set[str]:
    """Return a callable's parameter names, tolerating unresolvable annotations."""
    try:
        return set(inspect.signature(func).parameters)
    except Exception:
        # Python 3.14 evaluates annotations during signature introspection,
        # and Core annotations may reference names that are not importable in
        # their module (e.g. AbstractConfig in state_report). Only the names
        # are needed here, and those remain available on the code object.
        code = getattr(func, "__code__", None)
        if code is None:
            raise
        count = code.co_argcount + code.co_kwonlyargcount
        return set(code.co_varnames[:count])


def validate_core_shape() -> None:
    """Fail closed if the Core internals we depend on have materially changed."""
    required = {
        "AbstractConfig.generate_alexa_id": alexa_config.AbstractConfig.generate_alexa_id,
        "AlexaDirective.load_entity": alexa_state_report.AlexaDirective.load_entity,
        "handlers.async_get_entities": alexa_handlers.async_get_entities,
        "state_report.async_send_add_or_update_message": alexa_state_report.async_send_add_or_update_message,
        "state_report.async_send_delete_message": alexa_state_report.async_send_delete_message,
        "state_report.async_send_changereport_message": alexa_state_report.async_send_changereport_message,
        "state_report.async_send_doorbell_event_message": alexa_state_report.async_send_doorbell_event_message,
    }
    for name, value in required.items():
        if not callable(value):
            raise RuntimeError(f"Unsupported Home Assistant Alexa internals: {name} missing")

    # We intentionally allow additive signature changes, but these parameters
    # must remain available for the wrappers below.
    required_params = {
        "AlexaDirective.load_entity": (
            alexa_state_report.AlexaDirective.load_entity,
            {"self", "hass", "config"},
        ),
        "async_send_add_or_update_message": (
            alexa_state_report.async_send_add_or_update_message,
            {"hass", "config", "entity_ids"},
        ),
    }
    for name, (func, params) in required_params.items():
        present = _parameter_names(func)
        if not params <= present:
            raise RuntimeError(
                f"Unsupported Home Assistant Alexa internals: {name} signature changed"
            )


def install() -> None:
    """Install alias behavior into unmodified Core modules."""
    validate_core_shape()
    try:
        _install_config_api()
        _install_directive_resolution()
        _install_discovery()
        _install_state_reporting()
    except Exception:
        uninstall()
        raise
    _LOGGER.info("Installed Alexa alias compatibility shim")


def uninstall() -> None:
    """Restore Core modules to their pre-install state."""
    if not _ORIGINALS:
        return
    while _ORIGINALS:
        owner, name, original = _ORIGINALS.pop()
        try:
            if original is _MISSING:
                delattr(owner, name)
            else:
                setattr(owner, name, original)
        except Exception:
            _LOGGER.exception("Unable to restore patched Alexa attribute %s", name)
    _LOGGER.info("Removed Alexa alias compatibility shim")


def _install_config_api() -> None:
    cls = alexa_config.AbstractConfig

    def generate_alexa_id_for_method(
        self: Any, entity_id: str, alias: str | None = None
    ) -> str:
        return generate_alexa_id_for(entity_id, alias)

    def get_entity_aliases_method(self: Any, entity_id: str) -> list[str]:
        return get_entity_aliases(self.hass, entity_id)

    def normalize_aliases_method(
        self: Any, entity_id: str, aliases: Collection[Any]
    ) -> list[str]:
        return normalize_aliases(entity_id, aliases)

    def get_alias_alexa_ids_method(
        self: Any, entity_id: str, aliases: Collection[Any] | None = None
    ) -> list[str]:
        return get_alias_alexa_ids(self.hass, entity_id, aliases)

    def get_entity_alexa_ids_method(self: Any, entity_id: str) -> list[str]:
        return get_entity_alexa_ids(self.hass, entity_id)

    def resolve_entity_id_method(self: Any, endpoint_id: str) -> str:
        return resolve_entity_id(endpoint_id)

    _set_patched(cls, "generate_alexa_id_for", generate_alexa_id_for_method)
    _set_patched(cls, "get_entity_aliases", get_entity_aliases_method)
    _set_patched(cls, "normalize_aliases", normalize_aliases_method)
    _set_patched(cls, "get_alias_alexa_ids", get_alias_alexa_ids_method)
    _set_patched(cls, "get_entity_alexa_ids", get_entity_alexa_ids_method)
    _set_patched(cls, "resolve_entity_id", resolve_entity_id_method)


def _install_directive_resolution() -> None:
    old = alexa_state_report.AlexaDirective.load_entity
    if _is_marked(old):
        return

    @_mark
    def load_entity(self: Any, hass: Any, config: Any) -> None:
        endpoint_id = self._directive["endpoint"]["endpointId"]
        self.entity_id = resolve_entity_id(endpoint_id)
        entity = hass.states.get(self.entity_id)
        if not entity or not config.should_expose(self.entity_id):
            raise alexa_state_report.AlexaInvalidEndpointError(endpoint_id)
        self.entity = entity
        self.endpoint = alexa_entities.ENTITY_ADAPTERS[self.entity.domain](
            hass, config, self.entity
        )
        if "instance" in self._directive["header"]:
            self.instance = self._directive["header"]["instance"]

    _set_patched(alexa_state_report.AlexaDirective, "load_entity", load_entity)


def _entities_with_aliases(hass: Any, config: Any) -> list[Any]:
    canonical = alexa_entities.async_get_entities(hass, config)
    result: list[Any] = []
    for entity in canonical:
        result.append(entity)
        for alias in get_entity_aliases(hass, entity.entity_id):
            try:
                result.append(AliasAlexaEntity(entity, alias))
            except Exception:
                _LOGGER.exception(
                    "Unable to build %s alias %s for discovery",
                    entity.entity_id,
                    alias,
                )
    return result


def _install_discovery() -> None:
    # handlers.py imports async_get_entities directly. Replacing this reference
    # affects Alexa discovery without changing Cloud's entity-listing UI or its
    # canonical entity iteration.
    if not _is_marked(alexa_handlers.async_get_entities):
        _set_patched(
            alexa_handlers, "async_get_entities", _mark(_entities_with_aliases)
        )


async def _post_response(hass: Any, config: Any, message: Any, token: str) -> Any:
    session = async_get_clientsession(hass)
    assert config.endpoint is not None
    return await session.post(
        config.endpoint,
        headers={"Authorization": f"Bearer {token}"},
        json=message.serialize(),
        allow_redirects=True,
    )


async def _async_send_add_or_update_message(
    hass: Any, config: Any, entity_ids: list[str]
) -> aiohttp.ClientResponse:
    token = await config.async_get_access_token()
    endpoints: list[dict[str, Any]] = []

    for entity_id in entity_ids:
        domain = entity_id.split(".", 1)[0]
        if domain not in alexa_entities.ENTITY_ADAPTERS:
            continue
        state = hass.states.get(entity_id)
        if state is None:
            continue
        canonical = alexa_entities.ENTITY_ADAPTERS[domain](hass, config, state)
        endpoints.append(canonical.serialize_discovery())
        for alias in get_entity_aliases(hass, entity_id):
            try:
                endpoints.append(AliasAlexaEntity(canonical, alias).serialize_discovery())
            except Exception:
                _LOGGER.exception(
                    "Unable to serialize %s alias %s for AddOrUpdateReport",
                    entity_id,
                    alias,
                )

    payload = {
        "endpoints": endpoints,
        "scope": {"type": "BearerToken", "token": token},
    }
    message = alexa_state_report.AlexaResponse(
        name="AddOrUpdateReport", namespace="Alexa.Discovery", payload=payload
    )
    return await _post_response(hass, config, message, token)


async def async_send_delete_endpoint_ids(
    hass: Any, config: Any, endpoint_ids: list[str]
) -> aiohttp.ClientResponse:
    token = await config.async_get_access_token()
    payload = {
        "endpoints": [{"endpointId": endpoint_id} for endpoint_id in endpoint_ids],
        "scope": {"type": "BearerToken", "token": token},
    }
    message = alexa_state_report.AlexaResponse(
        name="DeleteReport", namespace="Alexa.Discovery", payload=payload
    )
    return await _post_response(hass, config, message, token)


async def _async_send_delete_message(
    hass: Any, config: Any, entity_ids: list[str]
) -> aiohttp.ClientResponse:
    endpoint_ids: list[str] = []
    for entity_id in entity_ids:
        domain = entity_id.split(".", 1)[0]
        if domain not in alexa_entities.ENTITY_ADAPTERS:
            continue
        endpoint_ids.extend(get_entity_alexa_ids(hass, entity_id))
    return await async_send_delete_endpoint_ids(
        hass, config, list(dict.fromkeys(endpoint_ids))
    )


async def _async_send_changereport_message(
    hass: Any,
    config: Any,
    alexa_entity: Any,
    alexa_properties: list[dict[str, Any]],
    *,
    invalidate_access_token: bool = True,
) -> None:
    try:
        token = await config.async_get_access_token()
    except (RequireRelink, NoTokenAvailable):
        await config.set_authorized(False)
        _LOGGER.error(
            "Error when sending ChangeReport to Alexa, could not get access token"
        )
        return

    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        API_CHANGE: {
            "cause": {"type": Cause.APP_INTERACTION},
            "properties": alexa_properties,
        }
    }
    session = async_get_clientsession(hass)
    assert config.endpoint is not None

    for endpoint in get_entity_alexa_ids(hass, alexa_entity.entity_id):
        message = alexa_state_report.AlexaResponse(
            name="ChangeReport", namespace="Alexa", payload=payload
        )
        message.set_endpoint_full(token, endpoint)
        serialized = message.serialize()
        try:
            async with timeout(alexa_state_report.DEFAULT_TIMEOUT):
                response = await session.post(
                    config.endpoint,
                    headers=headers,
                    json=serialized,
                    allow_redirects=True,
                )
        except (TimeoutError, aiohttp.ClientError):
            _LOGGER.error(
                "Timeout sending report to Alexa for %s", alexa_entity.entity_id
            )
            continue

        response_text = await response.text()
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Sent: %s", json.dumps(async_redact_auth_data(serialized))
            )
            _LOGGER.debug("Received (%s): %s", response.status, response_text)
        if response.status == HTTPStatus.ACCEPTED:
            continue

        response_json = json_loads_object(response_text)
        response_payload = cast(JsonObjectType, response_json["payload"])
        if response_payload["code"] == "INVALID_ACCESS_TOKEN_EXCEPTION":
            if invalidate_access_token:
                config.async_invalidate_access_token()
                await _async_send_changereport_message(
                    hass,
                    config,
                    alexa_entity,
                    alexa_properties,
                    invalidate_access_token=False,
                )
                return
            await config.set_authorized(False)
        _LOGGER.error(
            "Error when sending ChangeReport for %s to Alexa: %s: %s",
            alexa_entity.entity_id,
            response_payload["code"],
            response_payload["description"],
        )


async def _async_send_doorbell_event_message(
    hass: Any, config: Any, alexa_entity: Any
) -> None:
    token = await config.async_get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    session = async_get_clientsession(hass)
    assert config.endpoint is not None

    for endpoint in get_entity_alexa_ids(hass, alexa_entity.entity_id):
        message = alexa_state_report.AlexaResponse(
            name="DoorbellPress",
            namespace="Alexa.DoorbellEventSource",
            payload={
                "cause": {"type": Cause.PHYSICAL_INTERACTION},
                "timestamp": dt_util.utcnow().strftime(DATE_FORMAT),
            },
        )
        message.set_endpoint_full(token, endpoint)
        serialized = message.serialize()
        try:
            async with timeout(alexa_state_report.DEFAULT_TIMEOUT):
                response = await session.post(
                    config.endpoint,
                    headers=headers,
                    json=serialized,
                    allow_redirects=True,
                )
        except (TimeoutError, aiohttp.ClientError):
            _LOGGER.error(
                "Timeout sending report to Alexa for %s", alexa_entity.entity_id
            )
            continue

        response_text = await response.text()
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "Sent: %s", json.dumps(async_redact_auth_data(serialized))
            )
            _LOGGER.debug("Received (%s): %s", response.status, response_text)
        if response.status == HTTPStatus.ACCEPTED:
            continue
        response_json = json_loads_object(response_text)
        response_payload = cast(JsonObjectType, response_json["payload"])
        _LOGGER.error(
            "Error when sending DoorbellPress event for %s to Alexa: %s: %s",
            alexa_entity.entity_id,
            response_payload["code"],
            response_payload["description"],
        )


def _install_state_reporting() -> None:
    replacements = {
        "async_send_add_or_update_message": _async_send_add_or_update_message,
        "async_send_delete_message": _async_send_delete_message,
        "async_send_changereport_message": _async_send_changereport_message,
        "async_send_doorbell_event_message": _async_send_doorbell_event_message,
    }
    for name, replacement in replacements.items():
        _mark(replacement)
        _set_patched(alexa_state_report, name, replacement)
