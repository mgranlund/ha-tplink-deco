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

Version 2 adds a diagnostics-owned `probe_version: 2` marker and a boundary
error handler. Each form has a seven-second limit, including lock acquisition,
inside an overall 15-second diagnostics budget. Failed forms do not
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

Expected keys are `probe_version` (2), `diagnostics_module`, `temporary`,
`budget_seconds`, `status`, and `probes.client_list` / `probes.client_access`.
The section is initialized by diagnostics itself even if the API method is missing.
Boundary failures include `error_type`; partial per-form results are preserved.
Exception types are serialized rather than exception strings that may contain
credentials or authenticated URLs.

Per-form states:

- `not_attempted`: no call made (for example, authentication unavailable).
- `response_received`: decrypted response without a nonzero API error code.
- `api_error`: decrypted nonzero error (`error_code` and raw `response` retained),
  or an API exception raised by the existing transport (`error_type`).
- `timeout`: per-form timeout, including time waiting for the lock.
- `unexpected_exception`: other exception, with `error_type`.

`attempted` identifies whether the API read was invoked. Top-level `completed`
means orchestration finished, even if both forms failed. Boundary `timeout` or
`unexpected_exception` leaves unattempted entries present. External cancellation
still cancels the download normally; unrelated failures in normal diagnostics
can still fail the download.

If the marker is absent from a successful fresh download, this patched hook did
not supply that section (or the downloaded JSON was subsequently transformed).
The original v1 hook also unconditionally included the key: an awaited exception
would fail the download, not silently omit the key. Check the downloaded file's
integration domain and the module loaded by the running HA instance. Confirming
files on disk alone cannot prove which code handled a download.

Missing preference fields or an unsupported form are inconclusive.

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
