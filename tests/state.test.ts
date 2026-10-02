import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { SessionState, textOnly, deliverInbox } from "../lib/state.ts";
import { observeRun, DialogueStream } from "../adapters/lifecycle.ts";

test("simultaneous instances of the same resumed session never overwrite each other", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "shadows-test-"));
  try {
    const a = new SessionState(dir, "same", "/a", "a"), b = new SessionState(dir, "same", "/b", "b");
    a.activity("thinking"); b.activity("speaking");
    assert.notEqual(a.file, b.file);
    assert.equal(JSON.parse(fs.readFileSync(a.file, "utf8")).phase, "thinking");
    a.close(); a.write(); assert.ok(!fs.existsSync(a.file)); assert.ok(fs.existsSync(b.file));
  } finally { fs.rmSync(dir, { recursive: true }); }
});
test("out of order progress and another session's events cannot resurrect or contaminate runs", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "shadows-test-"));
  try {
    const s = new SessionState(dir, "one", "/a", "a");
    const event = { sessionId: "one", runId: "r", agent: "beta", task: "inspect" };
    s.agent({ ...event, phase: "running" }); s.agent({ ...event, phase: "success" });
    s.agent({ ...event, phase: "progress" });
    s.agent({ ...event, sessionId: "two", runId: "other", phase: "running" });
    assert.equal(s.data.agents.r.phase, "success"); assert.equal(Object.keys(s.data.agents).length, 1);
    assert.equal(s.data.history.length, 2);
  } finally { fs.rmSync(dir, { recursive: true }); }
});
test("actual concurrent lifecycle handles repeated names, failure and cancellation", async () => {
  const events: any[] = []; const emit = (e: any) => events.push(e);
  const controller = new AbortController();
  await Promise.all([
    observeRun("beta", "one", undefined, emit, async progress => { progress(); return { exitCode: 0 }; }),
    observeRun("beta", "two", undefined, emit, async () => ({ exitCode: 1 })),
    observeRun("delta", "three", controller.signal, emit, async () => { controller.abort(); return { exitCode: 0 }; }),
  ]);
  assert.equal(new Set(events.map(e => e.runId)).size, 3);
  assert.deepEqual(events.filter(e => ["success", "error", "cancelled"].includes(e.phase)).map(e => e.phase).sort(), ["cancelled", "error", "success"]);
  assert.equal((await observeRun("eta", "", undefined, () => { throw Error(); }, async () => ({ exitCode: 0 }))).exitCode, 0);
});
test("thinking and tool payloads are never copied as dialogue", () => {
  assert.equal(textOnly({content: [{type:"thinking",thinking:"private"},{type:"toolCall",arguments:{password:"private"}},{type:"text",text:"hello"}]}), "hello");
});
test("whispers are claimed once and reject wrong instance, wrong session and expired requests", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "shadows-test-"));
  try {
    const s = new SessionState(dir, "one", "/a", "a", () => 100000);
    const inbox = path.join(dir, "inbox", s.data.instanceId); fs.mkdirSync(inbox, { recursive:true });
    const good = {schema:1, id:"0", instanceId:s.data.instanceId, sessionId:"one", at:100000, text:"hello"};
    const requests = [good, {...good,instanceId:"other"}, {...good,sessionId:"two"}, {...good,at:0}];
    requests.forEach((r,i)=>fs.writeFileSync(path.join(inbox, `${i}.json`),JSON.stringify({...r,id:String(i)})));
    const sent: string[] = [];
    deliverInbox(s, text=>sent.push(text)); deliverInbox(s, text=>sent.push(text));
    assert.deepEqual(sent,["hello"]); assert.equal(s.data.delivery.status,"queued");
  } finally { fs.rmSync(dir,{recursive:true}); }
});

test('delegated dialogue reaches its own run and survives completion and late progress', async () => {
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'shadows-dialogue-'));
  try {
    const s=new SessionState(dir,'one','/a','a');
    await observeRun('beta','TASK NOT DIALOGUE',undefined,e=>s.agent({...e,sessionId:'one'}),async progress=>{
      progress('Hello'); progress('Hello Shadow'); return {exitCode:0};
    });
    const run:any=Object.values(s.data.agents)[0];
    assert.equal(run.dialogue,'Hello Shadow');
    s.agent({sessionId:'one',runId:run.runId,phase:'progress',dialogue:'late'});
    assert.equal(run.dialogue,'Hello Shadow');
  } finally {fs.rmSync(dir,{recursive:true});}
});


test('dialogue stream accepts deltas and final snapshots without thinking or tools', () => {
 const stream=new DialogueStream();
 const delta=(type:string, fields:any={})=>stream.accept({type:'message_update',assistantMessageEvent:{type,contentIndex:0,...fields}});
 assert.equal(delta('text_delta',{delta:'Hi '}),'Hi ');
 assert.equal(delta('thinking_delta',{delta:'secret'}),undefined);
 assert.equal(delta('toolcall_delta',{delta:'private args'}),undefined);
 assert.equal(delta('text_delta',{delta:'Shadow'}),'Hi Shadow');
 assert.equal(stream.accept({type:'message_end',message:{role:'assistant',content:[{type:'thinking',thinking:'secret'},{type:'text',text:'Hello Shadow!'}]}}),'Hello Shadow!');
 stream.accept({type:'message_start'});
 assert.equal(delta('text_delta',{delta:'New turn'}),'New turn');
});

test('mode requests target one instance and never become chat messages', () => {
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'shadows-mode-'));
 try {
  const s=new SessionState(dir,'one','/a','a',()=>100000);
  const inbox=path.join(dir,'inbox',s.data.instanceId);fs.mkdirSync(inbox,{recursive:true});
  const request={schema:1,id:'a',type:'mode',mode:'commander',instanceId:s.data.instanceId,sessionId:'one',at:100000};
  fs.writeFileSync(path.join(inbox,'a.json'),JSON.stringify(request));
  const modes:string[]=[];
  deliverInbox(s,()=>assert.fail('mode is not user text'),mode=>{modes.push(mode);return true;});
  assert.deepEqual(modes,['commander']);assert.equal(s.data.delivery.status,'mode-changed');
  fs.writeFileSync(path.join(inbox,'b.json'),JSON.stringify({...request,id:'b',instanceId:'other'}));
  deliverInbox(s,()=>assert.fail(),()=>{assert.fail('wrong instance');return true;});
  fs.writeFileSync(path.join(inbox,'c.json'),JSON.stringify({...request,id:'c'}));
  deliverInbox(s,()=>assert.fail(),()=>false);
  assert.equal(s.data.delivery.status,'mode-busy');
 } finally {fs.rmSync(dir,{recursive:true});}
});

test('replayed request IDs cannot send a second message in the same instance', () => {
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'shadows-replay-'));
 try {
  const s=new SessionState(dir,'one','/a','a',()=>100000);
  const inbox=path.join(dir,'inbox',s.data.instanceId);fs.mkdirSync(inbox,{recursive:true});
  const file=path.join(inbox,'a.json'),request={schema:1,id:'a',instanceId:s.data.instanceId,sessionId:'one',at:100000,text:'hello'};
  let count=0;
  for(let i=0;i<2;i++){fs.writeFileSync(file,JSON.stringify(request));deliverInbox(s,()=>count++);}
  assert.equal(count,1);
 }finally{fs.rmSync(dir,{recursive:true});}
});
