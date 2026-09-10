# Temporary client preference probe, version 3

Diagnostic discovery only. No inventory schema, entities, MQTT, node topology,
manifest version or releases are changed. The probe uses the existing HA API
object, operation lock, encryption/decryption, transport and retry helper. It
never calls login. Do not create another owner-authenticated session to test it.

## Evidence and limits

Live version-2 diagnostics returned successful `client_list` and `client_access`
responses without an identifiable configured client preference. The repeated
`client_access.device_id` must not be treated as the preferred Deco, and
`client_mesh` does not identify a preferred node.

The next experiment tests MAC selectors on those established read forms.
These selectors are hypotheses, not a verified per-client API schema.

- Read-operation source: https://github.com/oliver006/deco/blob/main/admin_client.go
- Feature description: https://www.tp-link.com/us/support/faq/3480/

No substantiated dedicated preference/binding form was found in the sources
checked. A successful response can mean the firmware ignored an unknown selector.
Do not infer a preference from `device_id`, `client_mesh`, or current association.

## Exact requests

All requests go to `/admin/client` through the existing authenticated URL.
For each selected client MAC `M`:

| Result key suffix | Form | Decrypted payload |
| --- | --- | --- |
| `client_list_mac` | `client_list` | `{"operation":"read","params":{"device_mac":"default","mac":"M"}}` |
| `client_access_mac` | `client_access` | `{"operation":"read","params":{"mac":"M"}}` |
| `client_access_client_mac` | `client_access` | `{"operation":"read","params":{"client_mac":"M"}}` |

`device_mac` selects a Deco in the established client-list call, so it remains
`default`; it is not replaced with a client MAC. The `mac` hypothesis follows
client record naming; `client_mac` tests an explicit client identifier.

MACs are normalized to uppercase hyphen notation. At most two selections and six
requests are allowed. Invalid and duplicate selections are recorded and skipped.
No selection means no requests. Each request has three seconds, including waiting
for the lock, inside a 20-second overall diagnostics timeout. Timeout retries are
disabled. The shared retry helper cannot initiate login through this probe.

## Install and select a known client

1. Back up the installed `api.py` and `diagnostics.py` outside the integration
   folder. Start from the existing `v3.10.1-home.2` installation with its probe.
2. Download **Raw** `custom_components/tplink_deco/api.py` and `diagnostics.py`
   from this probe commit. Replace the corresponding files in
   `/homeassistant/custom_components/tplink_deco/`. Do not save GitHub HTML.
3. In the installed `diagnostics.py`, find:

   ```python
   CLIENT_PREFERENCE_PROBE_MACS: tuple[str, ...] = ()
   ```

   Change it locally to the MAC of a client whose specified setting you know:

   ```python
   CLIENT_PREFERENCE_PROBE_MACS: tuple[str, ...] = (
       "AA-BB-CC-DD-EE-FF",  # Replace this example with your actual client MAC.
   )
   ```

   Optionally add a second MAC for a known automatic client. Use the client MAC
   in HA, not the Deco MAC. Keep private MACs out of commits to the public fork.
4. Restart Home Assistant itself through **Settings → System → Restart Home
   Assistant**. Wait for Deco entities to update successfully and keep the
   selected clients online. No preference change or owner login is necessary.
5. Open **Settings → Devices & services → TP-Link Deco → integration entry's
   three-dot menu → Download diagnostics**. Allow up to 20 additional seconds.

The manifest still reports `3.10.1-home.2`; the marker below identifies the probe.

## Inspect

Search for `client_connection_preference_probe`, normally under `data`.
Expect `probe_version: 3`, `diagnostics_module`, `selected_client_macs`,
`max_clients: 2`, `request_timeout_seconds: 3`, `budget_seconds: 20`,
`selector_support: "unconfirmed"`, `status`, and `probes`.

For selection 1, the `probes` object contains these literal keys (the dot is part
of each key, not an additional JSON nesting level):

- `client_1.client_list_mac`
- `client_1.client_access_mac`
- `client_1.client_access_client_mac`

Selection 2 uses the prefix `client_2`. Each valid selection's entries are
initialized before network calls. Inspect `request`, `client_mac`, `response`,
`attempted`, `status`, and any `error_code`, `error_type` or `reason`.

States are `not_attempted`, `response_received`, `api_error`, `timeout`, and
`unexpected_exception`. Top-level `completed` means orchestration finished, not
that the preference was found. Empty selection produces `not_attempted` with
`reason: "configure_CLIENT_PREFERENCE_PROBE_MACS_in_diagnostics_py"` and empty
`probes`. A missing/mismatched API method produces a boundary error while keeping
the version marker. External cancellation still cancels a download normally.

Compare returned client MACs and envelopes across the three requests and against
version 2. Responses containing unrelated clients may indicate ignored filters.
Even a single-client response needs comparison with the known app setting before
any field can be called a configured preference.

Raw client identifiers are retained for correlation; existing credential-key
redaction is applied. Exception types, not potentially credential-bearing
exception strings, are serialized. Keep downloaded diagnostics private.

## Remove and checks

Restore the backed-up files and restart HA, or reinstall `v3.10.1-home.2`.
To change test clients, edit the local tuple and restart HA again.

Run `python -m unittest discover -s tests`. The focused checks compile actual
probe/retry and diagnostics hook functions with mocked transport/HA context;
they do not contact a Deco or constitute a full HA/firmware test.
