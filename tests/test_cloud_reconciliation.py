"""Cloud alias reconciliation tests.

Run directly (no pytest required): python tests/test_cloud_reconciliation.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "custom_components"))

import alexa_entity_aliases.cloud as cloud
from alexa_entity_aliases.const import DATA_ALIAS_CACHE, DOMAIN


class FakeConfig:
    enabled = True

    def __init__(self, exposed=True, with_sync_helper=True):
        self.exposed = exposed
        self.synced = []
        if with_sync_helper:
            self._sync_helper = self.sync

    def should_expose(self, entity_id):
        return self.exposed

    async def sync(self, added, removed):
        self.synced.append((added, removed))


async def test_rename_and_missing_sync_helper() -> None:
    config = FakeConfig()
    hass = SimpleNamespace(data={DOMAIN: {DATA_ALIAS_CACHE: {"test.old": ["Desk"]}}})
    deleted = []

    original_config = cloud._get_cloud_alexa_config
    original_aliases = cloud.get_entity_aliases
    original_ids = cloud.get_alias_alexa_ids
    original_delete = cloud.async_send_delete_endpoint_ids
    cloud._get_cloud_alexa_config = lambda hass: _return(config)
    cloud.get_entity_aliases = lambda hass, entity_id: ["Desk"]
    cloud.get_alias_alexa_ids = lambda hass, entity_id, aliases=None: [
        f"{entity_id}:{alias}" for alias in aliases or []
    ]

    async def delete(hass, config, endpoint_ids):
        deleted.extend(endpoint_ids)

    cloud.async_send_delete_endpoint_ids = delete
    try:
        await cloud.handle_registry_update(
            hass,
            SimpleNamespace(
                data={"entity_id": "test.new", "old_entity_id": "test.old", "action": "update"}
            ),
        )
        assert config.synced == [(["test.new"], [])]
        assert deleted == ["test.old:Desk"]

        config_without_sync = FakeConfig(with_sync_helper=False)
        deleted.clear()
        hass.data[DOMAIN][DATA_ALIAS_CACHE] = {"test.new": ["Desk"]}
        cloud._get_cloud_alexa_config = lambda hass: _return(config_without_sync)
        await cloud.handle_registry_update(
            hass,
            SimpleNamespace(data={"entity_id": "test.new", "action": "remove"}),
        )
        assert deleted == ["test.new:Desk"]
    finally:
        cloud._get_cloud_alexa_config = original_config
        cloud.get_entity_aliases = original_aliases
        cloud.get_alias_alexa_ids = original_ids
        cloud.async_send_delete_endpoint_ids = original_delete


async def _return(value):
    return value


def main() -> int:
    asyncio.run(test_rename_and_missing_sync_helper())
    print("ALL CLOUD RECONCILIATION TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
