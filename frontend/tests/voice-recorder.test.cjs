const test = require('node:test');
const assert = require('node:assert/strict');
const recorder = require('../voice-recorder.js');

test('uploaded auxiliaries keep their own transcripts and never borrow primary text', () => {
  const nodes = new Map();
  const get = selector => {
    if (!nodes.has(selector)) nodes.set(selector, {value:'', files:[], dataset:{}});
    return nodes.get(selector);
  };
  get('#voiceFile').files=[{name:'primary.wav'}];
  get('#voicePrompt').value='主录音的原文';
  get('#voiceAuxFiles').files=[{name:'aux1.wav'}, {name:'aux2.wav'}];
  get('#voiceAuxPrompt0').value=' 辅助录音自己的原文 ';
  const capture = recorder.mount({querySelector:get});
  const sample=capture.sample();
  assert.deepEqual(sample.auxiliaryPrompts,['辅助录音自己的原文','']);
  assert.equal(sample.prompt,'主录音的原文');
  assert.deepEqual(sample.auxiliary.map(file=>file.name),['aux1.wav','aux2.wav']);
});

test('recordings become standard mono 24kHz PCM WAV accepted by existing clone API', () => {
  const samples = Float32Array.from([-2,-0.5,0,0.5,2]);
  const bytes = recorder.encodeWav(samples);
  const header = new DataView(bytes);
  assert.equal(Buffer.from(bytes).toString('ascii',0,4),'RIFF');
  assert.equal(Buffer.from(bytes).toString('ascii',8,12),'WAVE');
  assert.equal(header.getUint16(20,true),1);
  assert.equal(header.getUint16(22,true),1);
  assert.equal(header.getUint32(24,true),24000);
  assert.equal(header.getUint16(34,true),16);
  assert.equal(header.getUint32(40,true),10);
  assert.deepEqual([...new Int16Array(bytes,44)],[-32767,-16384,0,16384,32767]);
});

test('quiet recordings gain speech energy without clipping peaks or changing the input', () => {
  const input=Float32Array.from({length:24000*5},(_,i)=>.03*Math.sin(2*Math.PI*220*i/24000));
  const result=recorder.normalizeRecording(input);
  assert.equal(result.level,'偏低');
  assert.ok(Math.abs(result.after.rmsDb+20)<.01);
  assert.ok(result.after.peakDb<=-3);
  assert.ok(result.gainDb>6);
  assert.ok(Math.abs(input[24])<=.03);
  const high=recorder.normalizeRecording(Float32Array.from([1,-1,.5,-.5]));
  assert.equal(high.level,'偏高');
  assert.ok(high.after.peakDb<=-3);
  assert.deepEqual(recorder.CAPTURE_AUDIO,{channelCount:1,echoCancellation:false,noiseSuppression:false,autoGainControl:false});
  assert.equal(recorder.SCRIPTS.length,2);
  assert.notEqual(recorder.SCRIPTS[0],recorder.SCRIPTS[1]);
});

test('too-short, too-long and silent microphone recordings are rejected before cloning', () => {
  assert.throws(()=>recorder.validateRecording(new Float32Array(24000).fill(0.1),24000),/不足/);
  assert.throws(()=>recorder.validateRecording(new Float32Array(24000*11).fill(0.1),24000),/超过/);
  assert.throws(()=>recorder.validateRecording(new Float32Array(24000*5),24000),/没有检测到/);
  assert.equal(recorder.validateRecording(new Float32Array(24000*5).fill(0.1),24000),5);
});
