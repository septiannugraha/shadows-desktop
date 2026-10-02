import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { SessionState, textOnly, deliverInbox } from '../lib/state.ts';
import { ROOT, runtimeRoot, config, packs } from '../lib/paths.ts';
import { registerDelegate } from '../adapters/delegate.ts';

export default function bridge(pi: ExtensionAPI) {
  if (process.env.SHADOWS_CHILD === '1') return;
  const catalog = packs();
  let state: SessionState | undefined;
  let timer: ReturnType<typeof setInterval> | undefined;
  let inbox: ReturnType<typeof setInterval> | undefined;
  let busy = false;
  let context: any;
  let streamedAt = 0;
  let warned = false;
  const safe = (fn: () => void) => {
    try { fn(); } catch (error) {
      if (!warned) { context?.ui.notify(`Shadows bridge: ${String(error)}`, 'warning'); warned = true; }
    }
  };
  const footer = () => {
    if (context && state) context.ui.setStatus('shadows-desktop', `${catalog[state.data.mode].host} · ${catalog[state.data.mode].name}`);
  };
  function applyPack(id: string) {
    if (!state || !catalog[id]) return;
    state.data.mode = id; state.data.host = catalog[id].host;
    state.data.modeChangedAt = Date.now();
    state.activity('idle', catalog[id].greeting);
    footer();
  }
  function switchPack(id: string) {
    if (!state || !catalog[id] || busy || Object.values(state.data.agents).some((a: any) => a.phase === 'running')) return false;
    pi.appendEntry('shadows-desktop-pack-v1', { pack: id });
    applyPack(id); return true;
  }
  function restore(ctx: any) {
    const saved = [...ctx.sessionManager.getBranch()].reverse().find((e: any) => e.type === 'custom' && e.customType === 'shadows-desktop-pack-v1') as any;
    const requested = saved?.data?.pack || config().pack || 'neutral';
    applyPack(catalog[requested] ? requested : 'neutral');
  }
  function stop() {
    if (timer) clearInterval(timer); if (inbox) clearInterval(inbox);
    safe(() => state?.close()); state = undefined; busy = false;
  }
  pi.on('session_start', (_event, ctx) => {
    stop(); context = ctx;
    safe(() => {
      state = new SessionState(runtimeRoot(), ctx.sessionManager.getSessionId(), ctx.cwd, pi.getSessionName() || path.basename(ctx.cwd));
      restore(ctx);
      timer = setInterval(() => safe(() => state?.write()), 5000); timer.unref();
      inbox = setInterval(() => safe(() => { if (state) deliverInbox(state, text => pi.sendUserMessage(text, { deliverAs: 'followUp' }), switchPack); }), 500); inbox.unref();
    });
  });
  pi.on('session_tree', (_event, ctx) => {
    context = ctx;
    // Rotate ownership so queued input from the prior branch is never accepted.
    const id = ctx.sessionManager.getSessionId();
    safe(() => {
      state?.close(); state = new SessionState(runtimeRoot(), id, ctx.cwd, pi.getSessionName() || path.basename(ctx.cwd));
      busy = false; restore(ctx);
    });
  });
  pi.on('session_shutdown', () => { stop(); context?.ui.setStatus('shadows-desktop', undefined); });
  pi.on('session_info_changed', event => safe(() => { if (state) { state.data.name = event.name || path.basename(state.data.cwd); state.write(); } }));
  pi.on('before_agent_start', event => {
    const persona = state && catalog[state.data.mode]?.persona;
    if (persona && config().persona !== false) return { systemPrompt: event.systemPrompt + '\n\n[Selected desktop persona]\n' + persona };
  });
  pi.on('agent_start', () => { busy = true; safe(() => state?.activity('thinking', 'Considering your request…')); });
  pi.on('message_update', event => {
    if (Date.now() - streamedAt < 100) return;
    const text = textOnly(event.message);
    if (text) { streamedAt = Date.now(); safe(() => state?.activity('speaking', text)); }
  });
  pi.on('message_end', event => {
    if (event.message.role !== 'assistant') return;
    safe(() => state?.activity(event.message.stopReason === 'error' ? 'error' : event.message.stopReason === 'aborted' ? 'cancelled' : 'speaking', textOnly(event.message) || undefined));
  });
  pi.on('tool_execution_start', event => safe(() => {
    if (state) { state.data.tools[event.toolCallId] = event.toolName; state.activity('working', `Working · ${event.toolName}`); }
  }));
  pi.on('tool_execution_end', event => safe(() => {
    if (state) { delete state.data.tools[event.toolCallId]; if (event.isError) state.activity('error', `${event.toolName} reported a problem.`); else state.write(); }
  }));
  pi.on('agent_end', () => { busy = false; safe(() => { if (state) { state.data.tools = {}; state.activity(['error','cancelled'].includes(state.data.phase) ? state.data.phase : 'idle'); } }); });
  // Process-local bus: the adapter captures session AND instance at dispatch.
  pi.events.on('shadows-desktop:agent:v1', (event: any) => safe(() => {
    if (state && event?.instanceId === state.data.instanceId) state.agent(event);
  }));
  registerDelegate(pi, () => state && ({ instanceId: state.data.instanceId, sessionId: state.data.sessionId, pack: state.data.mode }));
  pi.registerCommand('shadows-mode', {
    description: 'Select this session’s character pack: neutral, shadow, commander',
    handler: async (args, ctx) => {
      const id = args.trim();
      if (!catalog[id]) { ctx.ui.notify(`Packs: ${Object.keys(catalog).join(', ')}`, 'info'); return; }
      ctx.ui.notify(switchPack(id) ? `Shadows: ${catalog[id].name}` : 'Wait for the current turn and delegates to finish.', 'info');
    },
  });
  pi.registerCommand('shadows', {
    description: 'Open/pin the desktop, or /shadows doctor',
    handler: async (args, ctx) => {
      if (args.trim() === 'doctor') {
        const result = await pi.exec('python3', [path.join(ROOT, 'desktop/cli.py'), 'doctor']);
        ctx.ui.notify(result.stdout || result.stderr, result.code ? 'warning' : 'info'); return;
      }
      if (!state) { ctx.ui.notify('Desktop bridge has no active session.', 'warning'); return; }
      safe(() => state?.write());
      const child = spawn('python3', [path.join(ROOT, 'desktop/cli.py'), 'launch', '--session', state.data.instanceId], { detached: true, stdio: 'ignore' });
      child.on('error', error => ctx.ui.notify(`Cannot launch desktop: ${error.message}`, 'error'));
      child.on('exit', code => { if (code) ctx.ui.notify('Desktop exited. Run /shadows doctor and inspect the desktop log.', 'error'); });
      child.unref();
    },
  });
}
