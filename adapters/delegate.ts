import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { ROOT, config, packs } from '../lib/paths.ts';
import { DialogueStream } from './lifecycle.ts';

export function agentDefinition(pack: string, name: string) {
  if (!packs()[pack] || !/^[a-z][a-z0-9-]{0,63}$/.test(name)) throw Error('Unknown pack or agent');
  const file = path.join(ROOT, 'packs', pack, 'agents', `${name}.md`);
  if (!fs.existsSync(file)) throw Error(`No ${name} agent in pack ${pack}`);
  const source = fs.readFileSync(file, 'utf8');
  const match = source.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n([\s\S]*)$/);
  if (!match) throw Error('Invalid bundled agent definition');
  const tools = match[1].match(/^tools:\s*(.+)$/m)?.[1] || 'read,grep,find,ls';
  const allowed = tools.split(',').map(t => t.trim());
  if (allowed.some(t => !['read','write','edit','bash','grep','find','ls'].includes(t))) throw Error('Invalid agent tools');
  return { prompt: match[2], tools: allowed.join(',') };
}

export function piInvocation(args: string[]) {
  if (process.env.SHADOWS_PI_BINARY) return { command: process.env.SHADOWS_PI_BINARY, args };
  const script = process.argv[1];
  if (script && !script.startsWith('/$bunfs/') && /(?:cli|pi)\.(?:js|mjs|ts)$/.test(script) && fs.existsSync(script))
    return { command: process.execPath, args: [script, ...args] };
  if (!/^(node|bun)(\.exe)?$/.test(path.basename(process.execPath))) return { command: process.execPath, args };
  return { command: 'pi', args };
}

export function registerDelegate(pi: any, owner: () => any) {
  let active = 0;
  pi.registerTool({
    name: 'shadows_delegate', label: 'Delegate to a character',
    description: 'Run a named agent from the selected Shadows Desktop pack in an isolated Pi child, with live desktop dialogue. Optional tool; request character by exact name. Commander pack: tenka, kyouka, ren. Shadow pack: alpha, beta, gamma, delta, epsilon, zeta, eta. Inherit the current model. Use when delegation is useful; do not delegate simple greetings unless the user asks to speak with that character.',
    parameters: { type: 'object', properties: { agent: { type: 'string', description: 'Agent ID from the active pack' }, task: { type: 'string', description: 'Self-contained scoped task' } }, required: ['agent','task'], additionalProperties: false },
    async execute(_id: string, params: any, signal: AbortSignal | undefined, onUpdate: any, ctx: any) {
      if (config().delegation === false) throw Error('Character delegation disabled in Shadows config');
      const identity = owner();
      if (!identity) throw Error('No connected parent session');
      if (!params || typeof params.task !== 'string' || !params.task.trim() || params.task.length > 16000) throw Error('Task must be 1–16000 characters');
      const definition = agentDefinition(identity.pack, params.agent);
      if (active >= 4) throw Error('Four character delegates are already active');
      if (signal?.aborted) throw Error('Cancelled before dispatch');
      const runId = randomUUID();
      const event = (phase: string, dialogue?: string) => {
        try { pi.events.emit('shadows-desktop:agent:v1', { ...identity, runId, agent: params.agent, task: params.task, phase, dialogue }); } catch { /* optional observer */ }
      };
      active++;
      let dir: string | undefined;
      let final = '';
      event('running');
      try {
        dir = fs.mkdtempSync(path.join(os.tmpdir(), 'shadows-agent-'));
        const prompt = path.join(dir, 'persona.md'); fs.writeFileSync(prompt, definition.prompt, { mode: 0o600 });
        const args = ['--mode','json','--no-session','--no-extensions','--no-skills','--no-prompt-templates','--tools',definition.tools,'--append-system-prompt',prompt];
        if (ctx.model) args.push('--provider', ctx.model.provider, '--model', ctx.model.id);
        args.push(params.task);
        const invocation = piInvocation(args);
        let stopped = false;
        let failed = false;
        const code = await new Promise<number>((resolve, reject) => {
          const child = spawn(invocation.command, invocation.args, {cwd: ctx.cwd, env: {...process.env, SHADOWS_CHILD:'1'}, stdio:['ignore','pipe','pipe']});
          let buffer = ''; let killTimer: ReturnType<typeof setTimeout> | undefined;
          const stream = new DialogueStream(); let last = 0;
          const cancel = () => { stopped = true; child.kill('SIGTERM'); killTimer = setTimeout(() => child.kill('SIGKILL'), 2000); killTimer.unref(); };
          signal?.addEventListener('abort', cancel, {once:true});
          if (signal?.aborted) cancel();
          const clean = () => { signal?.removeEventListener('abort', cancel); if (killTimer) clearTimeout(killTimer); };
          const line = (value: string) => {
            let data: any; try { data = JSON.parse(value); } catch { return; }
            if (data.type === 'message_end' && data.message?.role === 'assistant') {
              failed ||= data.message.stopReason === 'error'; stopped ||= data.message.stopReason === 'aborted';
            }
            const text = stream.accept(data);
            if (text !== undefined) {
              final = text;
              if (data.type === 'message_end' || Date.now()-last > 100) {
                last = Date.now(); event('progress', text);
                onUpdate?.({content:[{type:'text',text:text || '(working…)'}],details:{runId,agent:params.agent}});
              }
            }
          };
          child.stdout.setEncoding('utf8'); child.stdout.on('data', (data: string) => {
            buffer += data;
            if (buffer.length > 4_000_000) { failed = true; cancel(); buffer = ''; return; }
            const lines = buffer.split('\n'); buffer = lines.pop() || ''; lines.forEach(line);
          });
          // Drain stderr without leaking provider/credential diagnostics into the UI.
          child.stderr.resume();
          child.on('error', error => { clean(); reject(error); });
          child.on('close', code => { clean(); if (buffer) line(buffer); resolve(code ?? 1); });
        });
        const phase = stopped ? 'cancelled' : code !== 0 || failed ? 'error' : 'success';
        event(phase, final);
        return {content:[{type:'text',text:final || `Delegate ${phase}; no public response captured.`}],details:{runId,agent:params.agent,phase},isError:phase!=='success'};
      } catch (error) {
        event(signal?.aborted ? 'cancelled' : 'error', final); throw error;
      } finally {
        active--; if (dir) fs.rmSync(dir, {recursive:true,force:true});
      }
    },
  });
}
