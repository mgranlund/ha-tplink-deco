# Temporary client preference discovery — version 4

This is capability discovery, not a confirmed preference getter. Production
inventory, node topology, entities, MQTT and manifest version remain unchanged.

## Findings and rejected hypotheses

Live v3 testing disproved all three selectors for this firmware:

- `/admin/client?form=client_list`, `params.mac` with `device_mac: default`.
- `/admin/client?form=client_access`, `params.mac`.
- `/admin/client?form=client_access`, `params.client_mac`.

All returned broad lists despite success codes. Version 4 removes those probes.
The repeated `client_access.device_id` is not evidence of a preferred client node.
`client_mesh` does not identify a preferred node either.

The integration code itself contains no separate client preference read. Offline
inspection of the public wrapper at commit
`939be4cab158cf88ceef63655282742b8323ac87` found a mobile-app namespace:

- `/admin/mobile_app/device?form=device_prefer_set`, operation `set` only.
- `/admin/mobile_app/iot_client_mesh?form=client_mesh`, operation `set` only.

These are naming leads, not established read interfaces or proof of semantics.
Neither is called. No guessed read operation is sent to a set-only form.
The cloud `system` bind/unbind forms concern cloud binding, not proven client
node preferences, and are excluded. Client isolation, DHCP lease and blacklist
forms are also not evidence of a preferred node getter.

Source:
https://github.com/oliver006/deco/blob/939be4cab158cf88ceef63655282742b8323ac87/admin_mobile_app.go

The wrapper and its mock tests list request paths and operations; they do not
prove support on this firmware, provide firmware handler source, or establish
which call the current app makes when opening Connection Preference.

## Proposed and implemented reads

| Result key | Endpoint | Form | Decrypted payload |
| --- | --- | --- | --- |
| `mobile_components` | `/admin/mobile_app/component_list` | `mobile` | `{"operation":"read","params":{}}` |
| `component_switches` | `/admin/component_control` | `switch_list` | `{"operation":"read","params":{}}` |

The first may reveal mobile component names/versions. The second may expose
component configuration flags. These purposes are inferred from names, not
confirmed response schemas. The paths and `read` operations are source-listed;
empty `params` support on this firmware is unconfirmed.

Sources:
- https://github.com/oliver006/deco/blob/939be4cab158cf88ceef63655282742b8323ac87/admin_mobile_app.go#L308
- https://github.com/oliver006/deco/blob/939be4cab158cf88ceef63655282742b8323ac87/admin_component_control.go
- https://github.com/oliver006/deco/blob/939be4cab158cf88ceef63655282742b8323ac87/admin_request.go

The temporary low-level helper accepts only these exact endpoint/form/payload
combinations. Both use the integration's existing API object, encryption,
transport, operation lock and retry helper. No login is initiated; unavailable
authentication is recorded and skipped. A transport auth failure may clear the
existing session as usual; normal polling remains responsible for recovery.
There are no timeout retries. Each request has four seconds including lock wait,
inside the diagnostics module's ten-second overall limit.

## Install and test

1. Back up installed `api.py` and `diagnostics.py` outside the integration folder.
2. Download **Raw** versions of both files from this commit and replace:
   `/homeassistant/custom_components/tplink_deco/api.py` and
   `/homeassistant/custom_components/tplink_deco/diagnostics.py`.
3. No client MAC tuple is needed. Replacing diagnostics removes v3's local MAC
   configuration. Do not carry that selection code into version 4.
4. Restart Home Assistant itself. Wait for successful Deco entity updates.
5. Use **Settings → Devices & services → TP-Link Deco → integration entry's
   three-dot menu → Download diagnostics**. No app owner login is needed.

Search for `data.client_connection_preference_probe` (or the probe key if the
HA wrapper differs). Expect:

- `probe_version: 4`
- `purpose: capability_discovery_not_preference_getter`
- `budget_seconds: 10`, `request_timeout_seconds: 4`
- `probes.mobile_components`
- `probes.component_switches`

Both entries include endpoint, form, request, attempted flag and status. Raw
`response` envelopes retain decrypted errors. Statuses are `not_attempted`,
`response_received`, `api_error`, `timeout` or `unexpected_exception`. Exception
types are serialized without potentially credential-bearing exception strings.
Boundary errors retain the diagnostics-owned version marker and partial results.
External cancellation still propagates normally.

Look for component names or versions mentioning client preference, steering,
binding or mesh. A feature flag is not a client's configured preference. Missing
such a flag does not prove the feature is unavailable. If the response supplies
no useful lead, the next evidence needed is a relevant firmware handler or app
request/schema reference; do not resume the disproven selector guesses.

Keep raw diagnostics private. Existing credential-key redaction is applied;
unknown response fields are retained for discovery.

## Remove and validation

Restore backups and restart HA, or reinstall `v3.10.1-home.2`. The temporary build
does not bump the manifest version or create a release.

`python -m unittest discover -s tests` checks actual API and diagnostics functions
with mocked transport/HA context. It covers exact allowed reads, rejection of
writes/unlisted paths, auth skips, independent failures, timeout cleanup and
marker persistence. It is not a live firmware or full HA test.
