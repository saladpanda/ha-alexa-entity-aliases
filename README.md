# Alexa Entity Aliases

![Alexa Entity Aliases logo](docs/logo.png)

Runtime Home Assistant custom integration that exposes entity-registry aliases as
additional Amazon Alexa endpoints, without modifying Home Assistant Core files.

It intentionally preserves the endpoint IDs and alias semantics of the existing
Home Assistant Core Alexa-alias patch, so switching away from the `amitfin/patch`
installation does not create new Alexa devices.

## Installation with HACS

This repository is laid out for installation as a HACS custom repository.

1. In HACS, open **Integrations**.
2. Open the menu and choose **Custom repositories**.
3. Add `https://github.com/saladpanda/ha-alexa-entity-aliases` with category **Integration**.
4. Search for **Alexa Entity Aliases** and install it.
5. Restart Home Assistant.
6. Go to **Settings -> Devices & Services -> Add Integration** and choose
   **Alexa Entity Aliases**, then submit the confirmation dialog.

No `configuration.yaml` changes are needed; setup happens entirely through the UI.

### Upgrading from a YAML-based version

If an earlier release was enabled with an `alexa_entity_aliases:` line in
`configuration.yaml`, delete that line after updating. The integration no longer
supports YAML setup.

For releases, tag the repository (for example `v0.2.0`). HACS can then install and update tagged versions normally.

### Manual installation

Copy `custom_components/alexa_entity_aliases/` into your Home Assistant configuration directory, restart, and set it up under **Settings -> Devices & Services -> Add Integration**.

## Seamless migration from the Core patch

Use this order:

1. Keep the existing `amitfin/patch` Alexa-alias patch installed.
2. Install this custom integration and set it up under **Settings -> Devices &
   Services -> Add Integration**.
3. Restart Home Assistant once.
4. Verify the log contains a message that Alexa alias support already exists in Core.
   In this state the custom integration deliberately does nothing.
5. Disable/remove the `amitfin/patch` modifications for the Alexa alias feature.
6. Upgrade/reinstall stock Home Assistant Core as needed so the modified Core files
   are gone.
7. Restart Home Assistant.
8. Verify the log contains `Installed Alexa alias compatibility shim`.
9. Run one Alexa sync from Home Assistant Cloud (recommended, but it does not change
   existing endpoint IDs).

Do **not** delete the Alexa devices between steps. The endpoint IDs remain exactly:

```
<entity_id with . replaced by #>::alias::<slugified alias>
```

Example:

```
switch#desk::alias::reading_light
```

The alias-specific `customIdentifier` is also kept compatible:

```
<cloud-user>-<entity_id>-alias-<slugified alias>
```

## Compatibility strategy

The integration does not fork the Alexa entity classes. Alias discovery endpoints
are proxies around Home Assistant's current Alexa entity serializer, so new Core
capabilities and metadata are inherited automatically.

It patches only these narrow seams:

- Alexa directive endpoint resolution
- discovery entity enumeration in `alexa.handlers`
- AddOrUpdateReport / DeleteReport generation
- ChangeReport / doorbell endpoint fan-out

Alias creation/removal is reconciled by a separate entity-registry listener. This
avoids depending on a Cloud callback that might already have been registered before
the custom integration loads.

The Cloud add/update path additionally relies on the Cloud Alexa config's private
`_sync_helper` API. If that API is removed by Core, sync errors are logged and
stale-endpoint deletion still runs independently.

If Core already contains an Alexa-alias patch (or a compatible upstream
implementation), the integration detects `ALEXA_ALIAS_DELIMITER` plus the alias API
on `AbstractConfig` and stays inactive. This is what makes a staged migration safe.

## Supported versions

The implementation was checked against the Alexa API shapes in Home Assistant
2026.7.1 and 2026.8.2 and uses feature/signature checks instead of a hard-coded
HA version.
Additive Core changes should normally keep working. If a required internal API is
removed or materially changed, setup fails closed and logs an incompatibility rather
than partially patching Alexa.

Because this still relies on private Home Assistant Alexa internals, it should be
regression-tested against every Home Assistant monthly release before upgrading.

## Notes

- Literal entity-registry aliases are exposed. The computed-name sentinel is not
  exposed as a second endpoint.
- Aliases that translate/slugify to the same endpoint ID are deduplicated.
- Alias ordering is case-insensitive and stable, matching the existing Core patch.
- Home Assistant Cloud is supported for alias add/remove reconciliation.
- Unloading or removing the integration's config entry restores every patched
  Core function, so disabling it takes effect without a restart.

## List all entity aliases

The integration registers a response-only Home Assistant action:

```
alexa_entity_aliases.list_aliases
```

Run it from **Developer Tools -> Actions**. With no parameters it returns only
literal aliases explicitly configured by the user, together with the aliases and
endpoint IDs that this integration will expose to Alexa.

Example response:

```yaml
entity_count: 1
alias_count: 2
alexa_alias_count: 2
entities:
  - entity_id: light.desk
    aliases:
      - Reading light
      - Desk lamp
    alexa_aliases:
      - Desk lamp
      - Reading light
    alexa_endpoint_ids:
      - light#desk::alias::desk_lamp
      - light#desk::alias::reading_light
```

Set `include_computed: true` to also return `resolved_aliases`, where Home
Assistant's `COMPUTED_NAME` sentinel is expanded to the current computed entity
name. This is off by default because recent Home Assistant versions can contain a
computed-name entry for most registry entities, which would make a literal-alias
inventory unnecessarily large.

This action is registered even while the old Core/`amitfin/patch` implementation is
still installed, so it can also be used to verify aliases before switching to the
runtime shim.
