# Shadows Desktop

A compact visual-novel desktop companion for **Pi on Linux**. Characters speak
when the corresponding agent speaks, move into the foreground, and remain
attached to an explicit Pi instance—even with several terminals open.

**v0.1: local desktop only.** Tested with Pi 0.85.1 on Omarchy/Wayland. GTK4
normal-window fallback is included; Windows, macOS and remote Pi connections
are not supported in this release.

## Install from GitHub

Install Pi first and ensure your system Python can import **PyGObject, GTK4
and pycairo**. Install **gtk4-layer-shell** for an overlay; without it the app
uses a normal window. On Arch/Omarchy the relevant package names are `gtk4`,
`gtk4-layer-shell`, `python-gobject`, and `python-cairo`. Other distributions
must provide the same libraries through their system package manager.

Then:

```sh
pi install git:github.com/septiannugraha/shadows-desktop@v0.1.0
```

In Pi:

```text
/reload
/shadows doctor
/shadows
```

`/shadows` opens the desktop and pins it to **that exact running Pi instance**.
It starts with a neutral code-drawn companion and leaves your persona alone.
No npm publication, API key entry, copy-to-bin step, or modifications to your
other extensions are required. Pi itself may run its package-manager step
when installing a Git package; this package has no npm runtime dependencies
or install scripts.

> Already using the original personal Alpha/Shadows installation? Read
> [migration](docs/migration.md) first. Do not load both bridge versions in the
> same Pi process: they register the same slash commands.

## Character packs and dialogue

```text
/shadows-mode shadow
/shadows-mode commander
/shadows-mode neutral
```

- **Master Shadow:** Alpha hosts; Beta, Gamma, Delta, Epsilon, Zeta and Eta can join.
- **Supreme Commander:** Tenka hosts, Kyouka implements/debugs, Ren independently reviews.
- **Neutral:** no character persona is injected.

Pack selection belongs to the Pi session and is restored from its session
history. Wait for the current turn and delegated work to finish before
changing it. The footer updates with the host and pack name. Characters keep
their own identities; Beta is never renamed Tenka.

Ask Pi: **“Use shadows_delegate to ask Ren to review this plan.”**
The bundled `shadows_delegate` tool reads agents from the active pack,
inherits your current model, and streams public child-agent text to the
stage. Up to four simultaneous calls are supported. Each call is one task;
chain stages by passing the previous result explicitly. Delegated processes
are isolated conversations, not persistent chat partners.

Existing third-party subagent tools can coexist, but their character streams
are **not automatically visible**. Use the provided tool or integrate the
[event adapter](docs/protocol.md#other-subagent-runners). The desktop still
shows main-agent activity without a subagent adapter.

The optional character sheets are generated fan art. See [ARTWORK.md](ARTWORK.md)
for provenance and the distinction from the code license.

## Controls

- **⋯:** sessions, pack selection, run roster, quiet motion and text visibility.
- **↩:** whisper to the selected Pi session; Enter sends, Escape closes.
- **Roster:** inspect a specific run and bring its character forward.
- **Drag the character stage:** reposition the Wayland overlay.
- **Scroll on the stage:** zoom.
- **− / ×:** collapse the stage / dismiss the desktop.

Whispers go to Pi, not directly to whichever portrait is selected. Name the
character in the message when requesting delegation. Focusing the input pins
the destination; an expired/disconnected pin never silently changes recipient.

The bubble and foreground use the same speaker decision. A returning host
comes forward after the delegate's reply. Speaking frames respond to new text,
including fast final responses; they are illustrative, not audio lip sync.
There is no TTS in v0.1. Quiet motion disables animation.

## Multiple Pi instances

The bridge publishes an atomic snapshot under a **unique process-instance UUID**.
The saved Pi session ID is separate, so two windows resuming one conversation
do not overwrite each other. The UI displays the session name, PID and working
directory. Automatic selection stays with a busy instance; otherwise it picks
the most recently active instance. Heartbeats do not steal selection.

A pin stays disconnected if its instance exits. After Pi reloads, restarts or
changes branch, run `/shadows` from the desired instance to pin its new identity.
This deliberate reconnect step prevents queued input reaching a different
conversation. Two separate desktop instances on different machines cannot
connect through this local transport.

See [the protocol](docs/protocol.md) for message expiry, delivery acknowledgements,
instance validation and adapter events.

## Configuration and diagnostics

Files use XDG paths:

| Data | Default |
|---|---|
| Settings | `~/.config/shadows-desktop/config.json` |
| Log | `~/.local/state/shadows-desktop/desktop.log` |
| Live sessions/inbox | `$XDG_RUNTIME_DIR/shadows-desktop-v1/sessions/` |
| Runtime fallback | `~/.cache/shadows-desktop-v1/sessions/` |

Settings are separate from the Git checkout, so package updates do not replace
them. Example (all keys are optional):

```json
{"pack":"neutral","persona":true,"delegation":true,"quiet":false,"scale":0.9}
```

`persona:false` leaves the Pi system prompt unchanged even in a character pack.
`delegation:false` blocks new bundled delegate invocations. Pack changes through
`/shadows-mode` take precedence over the default pack for that saved session.

`/shadows doctor` checks Python/GTK, pack metadata, protocol compatibility and
live-instance discovery. From a checkout, the same command is:

```sh
python3 desktop/cli.py doctor
python3 desktop/cli.py launch --windowed
python3 desktop/cli.py configure --pack commander --persona on
```

Diagnostic/test overrides: `SHADOWS_STATE_DIR`, `SHADOWS_CONFIG`, and
`SHADOWS_PI_BINARY` (an executable path, not a shell command). Both Pi and the
desktop must use the same runtime path. The launcher passes inherited overrides.

Text is stored locally in bounded runtime snapshots (including when “Hide text”
is enabled). Model credentials stay with Pi. Same-user processes can read/write
this local transport; it is not an isolation boundary against malicious software
running as your user. Nothing listens on a network port.

## Update and remove

A tagged Git installation is pinned. To move to a future published version,
install that exact tag rather than assuming `pi update` advances it. Restart
the companion and `/reload` Pi after updating; the protocol version must match.

```sh
pi remove git:github.com/septiannugraha/shadows-desktop@v0.1.0
```

Then `/reload` Pi and close the desktop. Removal unregisters the package and
preserves settings/logs. It does not delete your agents or credentials. Config
and logs can be removed manually if you no longer want them. Do not edit a
Pi-managed Git checkout: Pi may reset it during updates. Use your own clone or
fork for pack/code changes.

## Development and verification

```sh
git clone https://github.com/septiannugraha/shadows-desktop.git
cd shadows-desktop
pi install "$PWD"
npm test
python3 tests/pi_smoke.py
python3 tests/gtk_session_switch.py
```

Tests require Node 22.18+ and Python 3.10+. The main test suite has no third-party
npm dependencies and makes no provider calls. The Pi smoke test requires Pi on
PATH and installs/removes the package only in a temporary agent directory.
The GTK regression requires a graphical session and uses its own application ID.

Project layout:

```text
extensions/index.ts    self-contained Pi bridge and commands
lib/                  protocol state, inbox, paths
adapters/             bundled delegate runner and text extraction
desktop/              GTK/Cairo app, CLI, session/foreground logic
packs/                neutral + optional character/persona/agent packs
tests/                unit, fake-child, real Pi and GTK regression checks
```

[MIT](LICENSE) for code and original documentation; character artwork is excluded.
