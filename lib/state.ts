import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

export const textOnly = (message: any): string =>
  (Array.isArray(message?.content) ? message.content.filter((c: any) => c.type === "text").map((c: any) => c.text).join("\n") :
    typeof message?.content === "string" ? message.content : "").slice(0, 600);

export class SessionState {
  data: any;
  file: string;
  closed = false;
  directory: string;
  now: () => number;
  claimed = new Set<string>();
  constructor(directory: string, sessionId: string, cwd: string, name: string, now = Date.now) {
    this.directory = directory;
    this.now = now;
    const instanceId = `${process.pid}-${randomUUID()}`;
    this.file = path.join(directory, `${instanceId}.json`);
    this.data = { schema: 1, protocol: "shadows-desktop/1", instanceId, sessionId, pid: process.pid, cwd, name,
      mode: "neutral", host: "companion", modeSwitch: true, startedAt: now(), activityAt: now(), heartbeatAt: now(), seq: 0, phase: "idle",
      message: "Connected to Pi.", agents: {}, history: [], tools: {} };
  }
  activity(phase: string, message?: string) {
    if (this.closed) return;
    this.data.phase = phase;
    if (message !== undefined) this.data.message = message.slice(0, 600);
    this.data.activityAt = this.now();
    this.write();
  }
  agent(event: any) {
    if (!event || this.closed || event.sessionId !== this.data.sessionId || typeof event.runId !== "string") return;
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$/.test(event.runId) || ["__proto__", "constructor", "prototype"].includes(event.runId)) return;
    if (!this.data.agents[event.runId] && Object.values(this.data.agents).filter((a: any) => a.phase === "running").length >= 32) return;
    if (!["running", "progress", "success", "error", "cancelled"].includes(event.phase)) return;
    const prior = this.data.agents[event.runId];
    if (prior && prior.phase !== "running") return; // late progress cannot resurrect a completed run
    if (!prior && event.phase === "progress") return;
    const time = this.now();
    const phase = event.phase === "progress" ? "running" : event.phase;
    const name = String(event.agent).slice(0, 80);
    this.data.agents[event.runId] = { runId: event.runId, agent: name, task: String(event.task || "").slice(0, 280),
      startedAt: prior?.startedAt ?? time, updatedAt: time, phase,
      dialogue: typeof event.dialogue === "string" ? event.dialogue.slice(0,4000) : prior?.dialogue || "" };
    if (event.phase !== "progress") {
      this.data.history.push({ at: time, agent: name, phase, text: String(event.task || "").slice(0, 280) });
      this.data.history = this.data.history.slice(-24);
      this.data.activityAt = time;
    }
    const finished = Object.values(this.data.agents).filter((a: any) => a.phase !== "running") as any[];
    finished.sort((a, b) => b.updatedAt - a.updatedAt).slice(24).forEach(a => delete this.data.agents[a.runId]);
    this.write();
  }
  write() {
    if (this.closed) return;
    this.data.heartbeatAt = this.now();
    this.data.seq++;
    fs.mkdirSync(this.directory, { recursive: true, mode: 0o700 });
    const tmp = this.file + ".tmp";
    fs.writeFileSync(tmp, JSON.stringify(this.data), { mode: 0o600 });
    fs.renameSync(tmp, this.file);
  }
  close() {
    this.closed = true;
    try { fs.unlinkSync(this.file); } catch { /* already removed */ }
    try { fs.rmSync(path.join(this.directory, "inbox", this.data.instanceId), {recursive:true, force:true}); } catch { /* best effort */ }
  }
}

export function deliverInbox(state: SessionState, send: (text: string) => void, switchMode?: (mode: string) => boolean) {
  if (state.closed) return;
  const dir = path.join(state.directory, "inbox", state.data.instanceId);
  if (!fs.existsSync(dir)) return;
  for (const name of fs.readdirSync(dir).filter(n => /^[a-f0-9-]+\.json$/.test(n)).slice(0, 8)) {
    const file = path.join(dir, name);
    try {
      const stat = fs.lstatSync(file);
      if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 20000) continue;
      const request = JSON.parse(fs.readFileSync(file, "utf8"));
      // Claim before dispatch: never duplicate user input on the next poll.
      fs.unlinkSync(file);
      if (!request || request.schema !== 1 || typeof request.id !== "string" || request.id + ".json" !== name || state.claimed.has(request.id)) continue;
      if (request.instanceId !== state.data.instanceId || request.sessionId !== state.data.sessionId ||
          !Number.isFinite(request.at) || Math.abs(state.now() - request.at) > 30000) continue;
      state.claimed.add(request.id);
      if (state.claimed.size > 256) state.claimed.delete(state.claimed.values().next().value!);
      if (request.type === "mode") {
        const valid = typeof request.mode === "string";
        const accepted = valid && switchMode?.(request.mode);
        state.data.delivery = { id: request.id, status: accepted ? "mode-changed" : "mode-busy" };
        state.write(); continue;
      }
      if (typeof request.text !== "string" || !request.text.trim() || request.text.length > 4000) continue;
      try {
        send(request.text);
        state.data.delivery = { id: request.id, status: "queued" };
      } catch {
        state.data.delivery = { id: request.id, status: "failed" };
      }
      state.write();
    } catch { /* malformed requests do not stop Pi */ }
  }
}
