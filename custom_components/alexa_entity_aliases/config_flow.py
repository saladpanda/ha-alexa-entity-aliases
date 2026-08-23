"""Config flow to set up Alexa Entity Aliases."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .const import DOMAIN


class AlexaEntityAliasesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Alexa Entity Aliases."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initiated by the user."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is None:
            return self.async_show_form(step_id="user")

        return self.async_create_entry(title="Alexa Entity Aliases", data={})
