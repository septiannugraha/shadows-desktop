# Local protocol v1

This is a same-user, same-host filesystem bridge. No HTTP server, remote endpoint,
model credential or authentication token is part of the protocol.

## Snapshot

Default root: `$XDG_RUNTIME_DIR/shadows-desktop-v1/sessions` (fallback
`~/.cache/shadows-desktop-v1/sessions`). Override with `SHADOWS_STATE_DIR` on
both sides. Each bridge instance writes `<pid>-<uuid>.json` using a private
mode-600 temporary file and atomic rename in a mode-700 directory.

Required ownership: `schema:1`, `protocol:"shadows-desktop/1"`, `instanceId`,
`sessionId`, `pid`. State includes `name`, `cwd`, `mode`, `host`, `phase`,
`heartbeatAt`, `activityAt`, `seq`, `message`, `tools`, `agents`, `history`.
All timestamps are milliseconds since the Unix epoch. `seq` increments per write.

Heartbeats: 5 seconds. Readers reject schema/protocol mismatches, symlinks,
malformed/oversized snapshots, dead PIDs and heartbeats aged 20 seconds or more.
Heartbeat writes do not change activity time. Clean shutdown removes its snapshot
and inbox. Crashed-instance files expire by TTL; unrelated files are not removed.
`doctor` reports incompatible protocol files rather than treating them as sessions.

New process, extension reload, or branch navigation rotates the instance UUID.
Inputs addressed to the previous instance do not carry over. Pins deliberately
require re-selection; `/shadows` provides that re-selection from the correct Pi.

## Input and mode requests

Write a fresh UUID file atomically under `inbox/<instanceId>/<uuid>.json`:

```json
{"schema":1,"id":"UUID","instanceId":"PID-UUID","sessionId":"PI-SESSION-ID","at":0,"text":"Hello"}
```

Use a current timestamp, not the illustrative zero. Mode requests replace text
with `"type":"mode","mode":"commander"` (or another known bundled pack).

The bridge polls every 500 ms and validates schema, filename/id agreement, exact
session+instance and expiry (30 seconds). It claims/removes before dispatch,
remembers the last 256 claimed request IDs for duplicate rejection, and writes
`delivery:{id,status}`. Status is `queued`, `failed`, `mode-changed` or `mode-busy`.
Modes are refused while a turn/delegate is active. No automatic replay to another
instance or after a reconnect occurs.

`queued` means handed to Pi as a follow-up, not a completed model response. This
is at-most-once dispatch, not exactly-once delivery: a crash after claim but
before dispatch can lose input. Check the terminal before retrying an unacknowledged
message. Queue work is bounded per poll. Expired valid requests are removed;
malformed or oversized files are ignored. No remote transport is supported.

## Other subagent runners

The bundled `shadows_delegate` captures parent ownership at invocation and emits
on Pi's **process-local event bus**:

```ts
pi.events.emit('shadows-desktop:agent:v1', {
  instanceId, sessionId, runId, agent: 'beta', task: 'Inspect this file',
  phase: 'progress', dialogue: 'Public assistant text so far'
});
```

Phases: `running`, `progress`, `success`, `error`, `cancelled`. Start with running;
use a unique run ID for every invocation. Never send chain-of-thought, raw tool
arguments, secrets, or whole provider payloads. Snapshot ownership can be read
from the live snapshot matching the parent's PID and session ID at dispatch;
do not recalculate it after a session switch. The bridge rejects wrong instance
or session and late updates after terminal completion. Observer failures must
not interrupt the underlying task.

For custom runners, set `SHADOWS_CHILD=1` on delegated Pi processes to suppress
bridge publication there. The bundled runner also disables child extensions,
skills and prompt templates and uses the chosen pack's explicit agent prompt/tools.
It inherits the parent's model and Pi's normal credential resolution. Project
instructions are still governed by Pi. The runner supports four concurrent calls;
there is no extra autonomous scheduler.

## Bounds and privacy

Main assistant text: 600 characters. Delegated text: 4,000 characters. Task:
280 characters. Up to 24 completed runs and 24 history items are retained; up to
32 concurrent externally observed runs are accepted. The bundled tool returns
the captured, bounded text; it is not a full transcript transport. “Hide text”
is presentation-only. No private reasoning blocks are copied.
