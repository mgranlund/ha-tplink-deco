# Temporary client connection preference discovery

This is a diagnostic experiment, not a confirmed connection preference API.
It does not change the inventory service, entities, polling, node topology,
manifest version or MQTT behavior. No new release is required.

## Requests

Both requests use the integration's existing authenticated `/admin/client`
endpoint, encryption, transport, operation lock and retry helper:

| Form | Decrypted payload | Evidence |
| --- | --- | --- |
| `client_list` | `{"operation":"read","params":{"device_mac":"default"}}` | Already used by this integration; inspect the full envelope before model filtering. |
| `client_access` | `{"operation":"read"}` | Read operation listed in https://github.com/oliver006/deco/blob/main/admin_client.go; preference semantics and required parameters are unknown. |

No guessed write operations, per-client sweep or new login is performed.
The retry helper is reused with zero timeout retries. Its potential auth retry
rechecks existing authentication and cannot call login. If the transport clears
authentication, the probe skips further requests; normal integration polling
remains responsible for its usual authentication recovery.

The total budget is 15 seconds, including lock acquisition. Failed forms do not
prevent the next form from being attempted within that budget. Outer transport
errors are recorded as exception types only; decrypted API errors remain in the
raw response. External task cancellation is propagated normally.

## Install and test in Home Assistant

1. Back up `/homeassistant/custom_components/tplink_deco/api.py` and
   `/homeassistant/custom_components/tplink_deco/diagnostics.py` outside the
   integration folder. These instructions assume the installed `v3.10.1-home.2`.
2. From the probe commit on GitHub, download those two files using **Raw** then
   save the raw Python, not the GitHub HTML page. Replace the two files in the
   folder above using your File Editor/Studio Code Server or existing file access.
   Do not install an old tagged release through HACS: it will omit this probe.
3. Restart Home Assistant through **Settings → System → Restart Home Assistant**
   (restart Home Assistant itself, not only the integration).
4. Wait for Deco entities to update successfully. Keep at least one client with
   an already known Specified Connection online, plus an automatic client as a
   comparison. Record their MACs and the expected preferred/current Decos from
   your existing knowledge or HA entities. Do not open another owner login or
   change a preference for this test.
5. Go to **Settings → Devices & services → TP-Link Deco**. In the integration
   entry's three-dot menu choose **Download diagnostics**. Allow up to 15 seconds
   of additional time for the probe.
6. In the JSON, find `data.client_connection_preference_probe` (or search for
   `client_connection_preference_probe` if HA wraps the document differently).
   Inspect `probes.client_list.response` and `probes.client_access.response`.
   Each entry includes `request`, `form`, `endpoint`, and `status`.

`response_received` means a response was decrypted, not necessarily API success.
Check `error_code`/`errorcode` and `result`. An `error` entry includes `error_type`;
`probe_budget_exhausted` means the budget expired, possibly while waiting for
polling. Missing preference fields or an unsupported form are inconclusive.

Raw client identifiers, names and IP addresses are intentionally retained for
correlation. Credential keys use the existing diagnostics redaction set. Treat
this experimental diagnostic download as private network data.

Do not assume `client_mesh` (roaming enablement), a current association field, or
node `topology` is a configured client preference. The actual response must first
be compared with known automatic and specified clients.

## Remove

Restore the backed-up two files and restart Home Assistant, or reinstall
`v3.10.1-home.2`. The version remains `3.10.1-home.2` during this experiment;
presence of the diagnostic probe key identifies the temporary build.

## Checks

`python -m unittest discover -s tests` exercises actual probe/retry methods with
mocked transport and crypto without requiring HA. These are isolated checks,
not a live firmware or full Home Assistant integration test.
