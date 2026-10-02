import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {EventEmitter} from 'node:events';
import bridge from '../extensions/index.ts';
import {registerDelegate,agentDefinition} from '../adapters/delegate.ts';
function harness() {
 const hooks:any={},commands:any={},tools:any={},entries:any[]=[],statuses=new Map();
 const pi:any={events:new EventEmitter(),on:(n:string,f:any)=>hooks[n]=f,registerCommand:(n:string,c:any)=>commands[n]=c,registerTool:(t:any)=>tools[t.name]=t,getSessionName:()=> 'Test',appendEntry:(type:string,data:any)=>entries.push({type:'custom',customType:type,data}),sendUserMessage:()=>{},exec:async()=>({code:0,stdout:'doctor'})};
 const ctx:any={cwd:'/tmp',sessionManager:{getSessionId:()=> 'same',getBranch:()=>entries},ui:{notify:()=>{},setStatus:(k:string,v:any)=>statuses.set(k,v)}};
 return {pi,hooks,commands,tools,ctx,entries,statuses};
}
test('bridge isolates instances, restores packs, rotates branches and cleans up',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'shadows-bridge-'));
 const old=process.env.SHADOWS_STATE_DIR,oldConfig=process.env.SHADOWS_CONFIG;
 process.env.SHADOWS_STATE_DIR=dir;process.env.SHADOWS_CONFIG=path.join(dir,'missing');
 const a=harness(),b=harness();bridge(a.pi);bridge(b.pi);
 try{
  a.hooks.session_start({},a.ctx);b.hooks.session_start({},b.ctx);
  const snapshots=()=>fs.readdirSync(dir).filter(n=>n.endsWith('.json')).map(n=>JSON.parse(fs.readFileSync(path.join(dir,n),'utf8')));
  assert.equal(snapshots().length,2);assert.ok(snapshots().every(s=>s.mode==='neutral'));
  assert.equal(a.hooks.before_agent_start({systemPrompt:'base'}),undefined);
  await a.commands['shadows-mode'].handler('commander',a.ctx);
  assert.equal(snapshots().filter(s=>s.mode==='commander').length,1);
  assert.match(a.hooks.before_agent_start({systemPrompt:'base'}).systemPrompt,/Tenka/);
  const prior=snapshots().find(s=>s.mode==='commander');
  a.hooks.agent_start();await a.commands['shadows-mode'].handler('shadow',a.ctx);
  assert.equal(snapshots().filter(s=>s.mode==='commander').length,1);
  a.hooks.agent_end();a.hooks.session_tree({},a.ctx);
  assert.ok(!snapshots().some(s=>s.instanceId===prior.instanceId));
  a.pi.events.emit('shadows-desktop:agent:v1',{instanceId:prior.instanceId,sessionId:'same',runId:'late',agent:'ren',phase:'running'});
  assert.ok(snapshots().every(s=>!s.agents.late));
  a.hooks.session_shutdown();a.hooks.session_start({},a.ctx);
  assert.equal(snapshots().filter(s=>s.mode==='commander').length,1);
 }finally{
  a.hooks.session_shutdown();b.hooks.session_shutdown();
  assert.equal(fs.readdirSync(dir).filter(n=>n.endsWith('.json')).length,0);
  if(old===undefined)delete process.env.SHADOWS_STATE_DIR;else process.env.SHADOWS_STATE_DIR=old;
  if(oldConfig===undefined)delete process.env.SHADOWS_CONFIG;else process.env.SHADOWS_CONFIG=oldConfig;
  fs.rmSync(dir,{recursive:true});
 }
});
test('adapter streams public text and handles failure/cancellation without a provider',async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'shadows-adapter-')),binary=path.join(dir,'fake-pi'),old=process.env.SHADOWS_PI_BINARY;
 process.env.SHADOWS_PI_BINARY=binary;
 const h=harness(),events:any[]=[];h.pi.events.on('shadows-desktop:agent:v1',e=>events.push(e));
 registerDelegate(h.pi,()=>({instanceId:'instance',sessionId:'session',pack:'commander'}));
 const write=(body:string)=>{fs.writeFileSync(binary,'#!/usr/bin/env node\n'+body);fs.chmodSync(binary,0o700);};
 try{
  write(`console.log(JSON.stringify({type:'message_start'}));
console.log(JSON.stringify({type:'message_update',assistantMessageEvent:{type:'thinking_delta',contentIndex:0,delta:'PRIVATE'}}));
console.log(JSON.stringify({type:'message_update',assistantMessageEvent:{type:'text_delta',contentIndex:1,delta:'Hello'}}));
console.log(JSON.stringify({type:'message_end',message:{role:'assistant',stopReason:'stop',content:[{type:'text',text:'Hello Commander'}]}}));`);
  const result=await h.tools.shadows_delegate.execute('x',{agent:'ren',task:'test'},undefined,()=>{},h.ctx);
  assert.equal(result.isError,false);assert.equal(result.content[0].text,'Hello Commander');
  assert.ok(events.some(e=>e.phase==='progress'&&e.dialogue==='Hello'));
  assert.equal(events.at(-1).phase,'success');assert.ok(!JSON.stringify(events).includes('PRIVATE'));
  assert.ok(events.every(e=>e.instanceId==='instance'));
  write('process.exit(1)');events.length=0;
  assert.equal((await h.tools.shadows_delegate.execute('x',{agent:'ren',task:'test'},undefined,undefined,h.ctx)).isError,true);
  assert.equal(events.at(-1).phase,'error');
  write('setInterval(()=>{},1000)');events.length=0;
  const controller=new AbortController();setTimeout(()=>controller.abort(),100);
  await h.tools.shadows_delegate.execute('x',{agent:'kyouka',task:'test'},controller.signal,undefined,h.ctx);
  assert.equal(events.at(-1).phase,'cancelled');
  assert.throws(()=>agentDefinition('commander','../../secrets'));
  assert.ok(!agentDefinition('commander','ren').tools.includes('write'));
 }finally{
  if(old===undefined)delete process.env.SHADOWS_PI_BINARY;else process.env.SHADOWS_PI_BINARY=old;
  fs.rmSync(dir,{recursive:true});
 }
});
