import path from 'node:path';
import os from 'node:os';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const runtimeRoot = () => process.env.SHADOWS_STATE_DIR || path.join(process.env.XDG_RUNTIME_DIR || path.join(os.homedir(), '.cache'), 'shadows-desktop-v1', 'sessions');
export const configPath = () => process.env.SHADOWS_CONFIG || path.join(process.env.XDG_CONFIG_HOME || path.join(os.homedir(), '.config'), 'shadows-desktop', 'config.json');
export function config(): any {
  try { const c = JSON.parse(fs.readFileSync(configPath(), 'utf8')); return c && typeof c === 'object' && !Array.isArray(c) ? c : {}; } catch { return {}; }
}
export function packs(): Record<string, any> {
  const result: Record<string, any> = {};
  for (const name of fs.readdirSync(path.join(ROOT, 'packs'))) {
    if (!/^[a-z][a-z0-9-]*$/.test(name)) continue;
    const file = path.join(ROOT, 'packs', name, 'pack.json');
    if (!fs.existsSync(file)) continue;
    const pack = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (pack.schema !== 1 || pack.id !== name || typeof pack.host !== 'string') throw Error(`Invalid pack: ${name}`);
    result[name] = pack;
  }
  return result;
}
