const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// Exercise the production functions without starting audio or rendering a page.
const source = fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
const values={'#voice':{value:'friendly'},'#speed':{value:'1'}};
const context = vm.createContext({document:{querySelector:selector=>values[selector]}});
vm.runInContext(source.slice(source.indexOf('const SPEECH_MAX_CHARS'),source.indexOf('function layout(')),context);
vm.runInContext(source.slice(source.indexOf('function ttsBody('),source.indexOf('async function startQualityPreview(')),context);
const cases=JSON.parse(fs.readFileSync(path.join(__dirname,'../../data/testset/speech_normalization.json'),'utf8'));
for (const item of cases) {
  test(`spoken copy: ${item.input}`,()=>{
    assert.equal(context.normalizeSpeechText(item.input),item.expected);
    assert.equal(context.normalizeSpeechText(item.expected),item.expected);
    assert.equal(JSON.parse(context.ttsBody(item.input)).text,item.expected);
  });
}
test('percent prefix and value cannot split across live phrases',()=>{
  const text='这段说明需要保持连贯接下来介绍电池电量范围从百分之三十到百分之八十然后继续介绍配置。';
  for (const token of ['百分之三十','百分之八十']) {
    const start=text.indexOf(token);
    for (let limit=start+1;limit<start+token.length;limit++) {
      const cut=context.safeSpeechCut(text,limit);
      assert.ok(cut<=start || cut>=start+token.length);
    }
  }
  context.speechInput='从30%充到80%需要0.33小时[2]。';
  assert.equal(vm.runInContext('sentenceList(normalizeSpeechText(speechInput)).join("")',context),'从百分之三十充到百分之八十需要零点三三小时。');
});

for (const token of ['CLTC','WLTC','150kW','120km/h']) {
  test(`atomic boundary preserves ${token}`,()=>{
    const text='前文'+token+'后文';
    for(let limit=3;limit<2+token.length;limit++) assert.equal(context.safeSpeechCut(text,limit),2);
  });
}
