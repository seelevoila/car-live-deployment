const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../app.js'), 'utf8');
const waitCode = source.slice(source.indexOf('async function waitForVoiceWarmup('), source.indexOf('async function cloneVoice('));

function harness(states) {
  const messages = [];
  const state = {classList:{add(){},remove(){}}, set textContent(value){messages.push(value);}};
  let calls = 0;
  const context = vm.createContext({document:{querySelector:()=>state},
    api:async()=>[{id:'clone', ...states[Math.min(calls++, states.length-1)]}],
    setTimeout:resolve=>resolve()});
  vm.runInContext(waitCode, context);
  return {context, messages, calls:()=>calls};
}

test('a stale warmed flag cannot bypass queued training; retry warnings survive readiness', async()=>{
  const h = harness([
    {warmed:true, synthesis_check:{status:'pending'}, adaptation:{status:'queued',message:'等待训练'}},
    {warmed:true, synthesis_check:{status:'ready'}, adaptation:{status:'complete',message:'已就绪，但触发了重试'}}
  ]);
  assert.equal(await vm.runInContext("waitForVoiceWarmup('clone')", h.context), true);
  assert.equal(h.calls(),2);
  assert.deepEqual(h.messages,['等待训练','已就绪，但触发了重试']);
});

test('a training failure stops polling and surfaces the reason', async()=>{
  const h = harness([{warmed:false, synthesis_check:{status:'failed',message:'训练失败，可重试或恢复原版'}}]);
  assert.equal(await vm.runInContext("waitForVoiceWarmup('clone')",h.context),false);
  assert.equal(h.calls(),1);
  assert.deepEqual(h.messages,['训练失败，可重试或恢复原版']);
});
