import { randomUUID } from "node:crypto";

/** Observer failures must never interrupt delegated work. */
export async function observeRun<T extends { exitCode: number; stopReason?: string }>(
  agent: string, task: string, signal: AbortSignal | undefined,
  emit: ((event: Record<string, unknown>) => void) | undefined,
  run: (progress: (text?: string) => void) => Promise<T>,
): Promise<T> {
  const runId = randomUUID();
  let dialogue = "";
  const send = (phase: string) => {
    try { emit?.({ runId, agent, task: task.slice(0, 280), phase, dialogue }); } catch { /* optional observer */ }
  };
  send("running");
  try {
    const result = await run(text => { if (text !== undefined) dialogue = text.slice(0, 4000); send("progress"); });
    send(signal?.aborted || result.stopReason === "aborted" ? "cancelled" :
      result.exitCode !== 0 || result.stopReason === "error" ? "error" : "success");
    return result;
  } catch (error) {
    send(signal?.aborted ? "cancelled" : "error");
    throw error;
  }
}


/** Consume only public assistant text, supporting JSON snapshots and RPC deltas. */
export class DialogueStream {
  blocks = new Map<number, string>();
  accept(event: any): string | undefined {
    if (event.type === "message_start") { this.blocks.clear(); return undefined; }
    if (!["message_update", "message_end"].includes(event.type)) return undefined;
    if (event.message?.role === "assistant" && Array.isArray(event.message.content)) {
      return event.message.content.filter((p: any) => p.type === "text" && typeof p.text === "string").map((p: any) => p.text).join("\n").slice(0, 4000);
    }
    const delta = event.assistantMessageEvent;
    if (!delta || !["text_start", "text_delta", "text_end"].includes(delta.type)) return undefined;
    const index = delta.contentIndex ?? 0;
    if (delta.type === "text_start") this.blocks.set(index, "");
    if (delta.type === "text_delta") this.blocks.set(index, ((this.blocks.get(index) || "") + (delta.delta || "")).slice(0,4000));
    if (delta.type === "text_end" && typeof delta.content === "string") this.blocks.set(index, delta.content.slice(0,4000));
    return [...this.blocks.entries()].sort((a,b)=>a[0]-b[0]).map(([,text])=>text).join("\n").slice(0,4000);
  }
}
