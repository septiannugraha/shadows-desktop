"""Session arbitration and sprite selection. No GTK dependency."""
import json
import os
import time
import math
import tempfile
from pathlib import Path

CHARACTERS = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "tenka", "kyouka", "ren")
BUSY = {"thinking", "working", "speaking"}


def runtime_root():
    return Path(os.environ.get("SHADOWS_STATE_DIR", str(Path(os.environ.get("XDG_RUNTIME_DIR", str(Path.home() / ".cache"))) / "shadows-desktop-v1" / "sessions")))


def read_sessions(directory, now=None):
    now = time.time() * 1000 if now is None else now
    result = {}
    for file in Path(directory).glob("*.json"):
        try:
            if file.is_symlink() or file.stat().st_size > 262144:
                continue
            data = json.loads(file.read_text())
            if not isinstance(data, dict) or data.get("schema") != 1 or data.get("protocol") != "shadows-desktop/1" or file.stem != data.get("instanceId"):
                continue
            if not 0 <= now - data["heartbeatAt"] < 20000:
                continue
            if not isinstance(data.get("agents"), dict) or not isinstance(data.get("pid"), int) or data['pid'] <= 0:
                continue
            if not all(isinstance(data.get(k), str) for k in ('sessionId', 'name', 'cwd', 'phase')):
                continue
            if not isinstance(data.get('activityAt'), (float, int)) or not math.isfinite(data['activityAt']):
                continue
            if any(not isinstance(a, dict) or not all(isinstance(a.get(k), str) for k in ('agent', 'runId', 'task', 'phase')) or
                   not all(isinstance(a.get(k), (int, float)) for k in ('startedAt', 'updatedAt')) or not isinstance(a.get('dialogue', ''), str) for a in data['agents'].values()):
                continue
            if not isinstance(data.get('message', ''), str) or not isinstance(data.get('delivery', {}), dict):
                continue
            history = data.get('history', [])
            if not isinstance(history, list) or any(not isinstance(h, dict) or
                not all(isinstance(h.get(k), str) for k in ('agent', 'phase', 'text')) for h in history):
                continue
            os.kill(data["pid"], 0)
            result[data["instanceId"]] = data
        except (ValueError, KeyError, TypeError, OSError):
            continue
    return result


class Selection:
    def __init__(self):
        self.pinned = None
        self.current = None

    def choose(self, sessions):
        if self.pinned:
            self.current = self.pinned
            return sessions.get(self.pinned)  # Never silently send to another session.
        current = sessions.get(self.current)
        if current and (current.get("phase") in BUSY or any(a["phase"] == "running" for a in current["agents"].values())):
            return current
        chosen = max(sessions.values(), key=lambda s: (s.get("activityAt", 0), s["instanceId"]), default=None)
        self.current = chosen["instanceId"] if chosen else None
        return chosen


def cast_for(session, selected_run=None, now=None):
    if not session:
        return [{"agent": "companion", "phase": "offline", "runId": "__host__", "task": ""}]
    now = time.time() * 1000 if now is None else now
    runs = list(session["agents"].values())
    active = sorted((a for a in runs if a["phase"] == "running"), key=lambda a: a["startedAt"], reverse=True)
    recent = sorted((a for a in runs if a["phase"] != "running" and a["updatedAt"] >= session.get("modeChangedAt", 0) and now - a["updatedAt"] < (45000 if a.get('dialogue') else 7000)), key=lambda a: a["updatedAt"], reverse=True)
    agents = active + recent
    if selected_run:
        selected = next((a for a in runs if a["runId"] == selected_run), None)
        if selected:
            agents = [selected] + [a for a in agents if a["runId"] != selected_run]
    # Alpha anchors the stage. Separate run IDs remain visible in the roster.
    unique = []
    host = session.get("host", "companion")
    seen = {host}
    for a in agents:
        if a["agent"] not in seen:
            seen.add(a["agent"])
            unique.append(a)
    alpha = {"agent": host, "phase": session["phase"], "runId": "__host__", "task": session.get("message", "")}
    return [alpha] + unique[:2]


def expression(phase):
    return {"running": "thinking-up", "thinking": "thinking-up", "working": "thinking-side",
            "speaking": "speaking-small", "success": "success", "error": "error",
            "cancelled": "needs-input", "offline": "sleepy"}.get(phase, "resting-smile")


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(data, handle)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


class SpeechClock:
    """Animate new dialogue independently of the worker's completion timing."""
    def __init__(self):
        self.entries = {}

    def update(self, key, text, now):
        previous, until = self.entries.get(key, ('', 0))
        if text and text != previous:
            added = len(text) - len(previous) if text.startswith(previous) else len(text)
            until = now + min(8.0, max(2.0, added / 24.0))
            self.entries[key] = (text, until)
            if len(self.entries) > 128:
                del self.entries[next(iter(self.entries))]
        return bool(text) and now < until


def speaker_for(session, selected_run=None, now=None):
    """One speaker decision shared by the dialogue and foreground portrait."""
    cast = cast_for(session, selected_run, now)
    host = cast[0]
    if not session or selected_run == '__host__':
        return host
    selected = session['agents'].get(selected_run)
    if selected:
        return selected
    if len(cast) == 1:
        return host
    latest_reply = max((a['updatedAt'] for a in cast[1:]), default=0)
    if session['phase'] in ('speaking', 'idle') and session.get('activityAt', 0) > latest_reply:
        return host
    return cast[1]
