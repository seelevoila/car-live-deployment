const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../app.js'), 'utf8');
const definitions = source.slice(0, source.indexOf("document.querySelectorAll('nav button').forEach(button => {"));
const deferred = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return {promise, resolve};
};
const response = data => ({ok: true, headers: {get: () => 'application/json'}, json: async () => data});

function harness() {
  const nodes = {};
  const node = (value = '') => ({
    value, textContent: '', innerHTML: '', isConnected: true, disabled: false,
    dataset: {}, style:{}, options: [], selectedOptions: [{dataset: {}, value: 'browser-default'}],
    setAttribute() {}, addEventListener() {}, classList: {toggle() {}}, querySelector: () => null,
  });
  for (const id of ['app', 'script', 'question', 'vehicle', 'voice', 'speed', 'volume', 'pitch',
    'play', 'pause', 'stop', 'revise', 'playstate', 'playunit', 'version', 'ask', 'answer', 'speakAnswer', 'status','ttsLatency']) {
    nodes['#' + id] = node();
  }
  nodes['#script'].value = 'Hello. New sentence.';
  nodes['#question'].value = 'How far?';
  nodes['#voice'].value = 'browser-default';
  nodes['#speed'].value = nodes['#volume'].value = '1';
  nodes['#pitch'].value = '0';
  const storage = new Map();
  const requests = [];
  const speech = [];
  let fetchHandler = async () => response({});
  const context = vm.createContext({
    document: {querySelector: selector => nodes[selector] || null, querySelectorAll: () => []},
    console: {log() {}, info() {}, warn() {}, error() {}}, performance, AbortController, DOMException,
    setTimeout: () => 1, clearTimeout() {}, setInterval: () => 2, clearInterval() {},
    addEventListener() {},
    sessionStorage: {getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value)},
    localStorage: {getItem: () => null, setItem() {}},
    SpeechLipSync: {Timeline: class {clear() {} resetMouth() {}}},
    AvatarPerformer: {Performer: class {}},
    SpeechSynthesisUtterance: class {constructor(text) { this.text = text; }},
    speechSynthesis: {cancel() {}, pause() {}, resume() {}, speak: utterance => speech.push(utterance)},
    fetch: (url, options) => { requests.push({url, options}); return fetchHandler(url, options); },
  });
  context.window = context;
  vm.runInContext(definitions, context);
  const run = code => vm.runInContext(code, context);
  run("currentView = 'studio'; activeViewLoading = Symbol('studio');");
  return {nodes, requests, speech, storage, context, run, fetch: handler => { fetchHandler = handler; }};
}

test('leaving a view invalidates loading and pending audio but retains health polling', () => {
  const h = harness();
  h.run('healthTimer = 42; playPending = ++audioIntent; stopCurrentView();');
  assert.equal(h.run('healthTimer'), 42);
  assert.equal(h.run('activeViewLoading'), null);
  assert.equal(h.run('playPending'), 0);
});

test('a slow studio response cannot replace a newer page', async () => {
  const h = harness();
  const pending = deferred();
  h.fetch(() => pending.promise);
  const load = h.run('studio()');
  h.run("stopCurrentView(); currentView = 'analytics'; beginViewLoad('analytics');");
  h.nodes['#app'].innerHTML = 'Analytics';
  pending.resolve(response({vehicles: []}));
  await load;
  assert.equal(h.nodes['#app'].innerHTML, 'Analytics');
});

test('stale question responses cannot become the spoken answer or unlock a newer request', async () => {
  const h = harness();
  const first = deferred();
  const second = deferred();
  let calls = 0;
  h.fetch(() => (++calls === 1 ? first : second).promise);
  const old = h.run('ask()');
  h.run('clearAnswer()');
  h.nodes['#question'].value = 'New question';
  const latest = h.run('ask()');
  first.resolve(response({answer: 'Old answer', sources: []}));
  await old;
  assert.equal(h.run('currentAnswer'), '');
  assert.equal(h.nodes['#ask'].disabled, true);
  second.resolve(response({answer: 'New answer', sources: []}));
  await latest;
  assert.equal(h.run('currentAnswer'), 'New answer');
  assert.equal(h.nodes['#speakAnswer'].disabled, false);
});

test('stopping during session creation prevents delayed browser speech', async () => {
  const h = harness();
  const pending = deferred();
  h.fetch(() => pending.promise);
  const playback = h.run('play()');
  h.run('stop()');
  pending.resolve(response({id: 'session-1'}));
  await playback;
  assert.equal(h.speech.length, 0);
  assert.equal(h.nodes['#play'].disabled, false);
  assert.equal(h.run('liveRun'), null);
});

test('repeat play clicks create one session and one speech run', async () => {
  const h = harness();
  const pending = deferred();
  h.fetch(() => pending.promise);
  const first = h.run('play()');
  await h.run('play()');
  assert.equal(h.requests.length, 1);
  pending.resolve(response({id: 'session-1'}));
  await first;
  assert.equal(h.speech.length, 1);
  assert.equal(h.nodes['#play'].disabled, true);
  h.run('pause()');
  assert.equal(h.nodes['#play'].disabled, false);
  assert.equal(h.nodes['#pause'].disabled, true);
});

test('leaving during session creation does not attach the old session to the next view', async () => {
  const h = harness();
  const pending = deferred();
  h.fetch(() => pending.promise);
  const creating = h.run('ensure()');
  h.run('stopCurrentView()');
  pending.resolve(response({id: 'old-session'}));
  await assert.rejects(creating, {name: 'AbortError'});
  assert.equal(h.run('session'), null);
});

test('volume changes affect audio already scheduled for playback', () => {
  const h = harness();
  const changes = [];
  h.context.volumeChanges = changes;
  h.run('audioCtx = {currentTime: 12}; gainNode = {gain: {setTargetAtTime: (...args) => volumeChanges.push(args)}};');
  h.nodes['#volume'].value = '0';
  h.run('updateOutputs()');
  assert.equal(changes[0][0], 0);
  assert.equal(changes[0][1], 12);
});

test('draft storage retains empty scripts and controls across view changes', () => {
  const h = harness();
  h.nodes['#script'].value = '';
  h.nodes['#speed'].value = '1.25';
  h.run('saveStudioDraft()');
  h.nodes['#script'].value = 'Default script';
  h.nodes['#speed'].value = '1';
  h.run('initializeStudioDraft()');
  assert.equal(h.nodes['#script'].value, '');
  assert.equal(h.nodes['#speed'].value, '1.25');
  assert.equal(h.nodes['#play'].disabled, true);
});

test('failed revision keeps the current audio queue and restores the save button', async () => {
  const h = harness();
  h.run("session = {id: 'session-1'}; liveRun = createLiveRun('browser', ['Original']);");
  h.fetch(async () => { throw new Error('Offline'); });
  await h.run('revise()');
  assert.equal(h.run('liveRun.q[0]'), 'Original');
  assert.equal(h.run('liveRun.stopped'), false);
  assert.equal(h.nodes['#revise'].disabled, false);
  assert.match(h.nodes['#playstate'].textContent, /改稿保存失败/);
});

test('completed playback restores transport controls', () => {
  const h = harness();
  h.run("liveRun = createLiveRun('browser', ['Hello']); liveRun.nextIndex = 1; finishRunIfDrained(liveRun);");
  assert.equal(h.run('liveRun'), null);
  assert.equal(h.nodes['#play'].disabled, false);
  assert.equal(h.nodes['#stop'].disabled, true);
});

test('stopping during model readiness does not restart TTS when the check returns', async () => {
  const h = harness();
  h.nodes['#voice'].selectedOptions[0].value = 'steady';
  const ready = deferred();
  h.fetch(() => ready.promise);
  h.run('ensureAudio = async () => {};');
  const speaking = h.run('speakText("Hello")');
  await Promise.resolve();
  h.run('stop()');
  ready.resolve(response({provider: 'gpt-sovits', ready: true}));
  await speaking;
  assert.equal(h.run('liveRun'), null);
  assert.ok(h.requests.every(request => !request.url.endsWith('/tts/stream')));
  assert.equal(h.run('playPending'), 0);
});

test('health polling avoids overlapping checks during a slow response', async () => {
  const h = harness();
  const pending = deferred();
  h.fetch(() => pending.promise);
  const first = h.run('pollHealth()');
  await h.run('pollHealth()');
  assert.equal(h.requests.length, 1);
  pending.resolve(response({status: 'ok'}));
  await first;
  assert.equal(h.run('healthChecking'), false);
});

test('a stream chunk that arrives after stop cannot schedule audio', async () => {
  const h = harness();
  const chunk = deferred();
  const enteredRead = deferred();
  h.fetch(async () => ({ok: true, body: {getReader: () => ({
    read: () => { enteredRead.resolve(); return chunk.promise; }, cancel: async () => {},
  })}}));
  h.context.scheduled = [];
  h.run("liveRun = createLiveRun('gpt-sovits', ['Hello']); consumeStreamBytes = (...args) => scheduled.push(args);");
  const streaming = h.run('streamGptUnit(liveRun)');
  await enteredRead.promise;
  h.run('stop()');
  chunk.resolve({done: false, value: new Uint8Array([1, 2])});
  await streaming;
  assert.equal(h.context.scheduled.length, 0);
});

test('the first GPT stream request contains only the first phrase', async () => {
  const h = harness();
  h.fetch(async () => ({ok: true, body: {getReader: () => ({
    read: async () => ({done: true}), cancel: async () => {},
  })}}));
  h.run("liveRun = createLiveRun('gpt-sovits', ['第一句。', '第二句。', '第三句。']);");
  await h.run('streamGptUnit(liveRun)');
  assert.equal(h.requests.length, 1);
  const body = JSON.parse(h.requests[0].options.body);
  assert.equal(body.text, '第一句。');
  assert.equal(body.stream_batch, true);
});

test('script and answer timers stop on failures, stop and navigation', async () => {
  const h=harness();
  h.run('startLatencyTimer()');
  assert.match(h.nodes['#ttsLatency'].textContent,/0.0s/);
  h.run('stopCurrentView()');
  assert.equal(h.run('ttsLatencyTimer'),null);
  assert.equal(h.nodes['#ttsLatency'].textContent,'');
  h.run("selectedVoiceWantsGpt=()=>true;ensureAudio=async()=>{};waitForGptReady=async()=>false;");
  await h.run("speakText('回答内容。')");
  assert.equal(h.run('ttsLatencyTimer'),null);
  assert.equal(h.nodes['#ttsLatency'].textContent,'');
  h.run('startLatencyTimer();stopLatencyTimer(1234)');
  assert.equal(h.nodes['#ttsLatency'].textContent,'✓ 首音频 1.23s');
  h.run('stop()');
  assert.equal(h.nodes['#ttsLatency'].textContent,'');
});

test('ready answer starts its timer at the click and retains that timestamp',async()=>{
  const h=harness(),waiting=deferred();
  h.context.readiness=waiting.promise;
  h.run('selectedVoiceWantsGpt=()=>true;ttsStatus={provider:"gpt-sovits",ready:true,live_path_warmed:true};ensureAudio=async()=>{};waitForGptReady=()=>readiness;');
  const task=h.run("speakText('回答内容。')");
  const clicked=h.run('audioRequestedAt');
  assert.match(h.nodes['#ttsLatency'].textContent,/0.0s/);
  h.run('startGptRun=async()=>{liveRun=createLiveRun("gpt-sovits",["回答内容。"]);liveRun.requestedAt=audioRequestedAt;};');
  waiting.resolve(true);await task;
  assert.equal(h.run('liveRun.requestedAt'),clicked);
  h.run('stop()');
});

test('playback is disabled until live readiness, and direct calls cannot start a waiting timer', async()=>{
  const h=harness();
  h.run('selectedVoiceWantsGpt=()=>true;currentAnswer="已生成回答";ttsStatus={provider:"gpt-sovits",ready:true,live_path_warmed:false};updatePlaybackControls();');
  assert.equal(h.nodes['#play'].disabled,true);
  assert.equal(h.nodes['#speakAnswer'].disabled,true);
  await h.run('play()');
  await h.run('speakText("测试");');
  assert.equal(h.run('ttsLatencyTimer'),null);
  assert.equal(h.requests.length,0);
  h.run('ttsStatus.live_path_warmed=true;updatePlaybackControls();');
  assert.equal(h.nodes['#play'].disabled,false);
  assert.equal(h.nodes['#speakAnswer'].disabled,false);
  h.run('voicePrimeInFlight=true;updatePlaybackControls();');
  assert.equal(h.nodes['#play'].disabled,true);
});

test('end-to-end metric includes readiness delay and ignores leading silent PCM',()=>{
  const h=harness();
  h.run('audioCtx={currentTime:4,baseLatency:.01,outputLatency:.02};');
  assert.ok(h.run('firstAudioLatency({requestedAt:performance.now()-8000},4.08)')>=8110);
  h.context.silentBuffer={sampleRate:1000,getChannelData:()=>new Float32Array(200)};
  h.context.speechBuffer={sampleRate:1000,getChannelData:()=>Float32Array.from({length:200},(_,i)=>i<100?0:.1)};
  assert.equal(h.run('firstSpeechOffset(silentBuffer)'),null);
  assert.equal(h.run('firstSpeechOffset(speechBuffer)'),.1);
});

test('missing live readiness cannot pass a status refresh or leave playback enabled', async()=>{
  const h=harness();
  h.run('selectedVoiceWantsGpt=()=>true;currentAnswer="回答";ttsStatus={provider:"gpt-sovits",ready:true,live_path_warmed:true};ttsCheckedAt=-10000;updatePlaybackControls();');
  assert.equal(h.nodes['#play'].disabled,false);
  h.fetch(async()=>response({provider:'gpt-sovits',ready:true}));
  assert.equal(await h.run('waitForGptReady()'),false);
  assert.equal(h.nodes['#play'].disabled,true);
  assert.equal(h.nodes['#speakAnswer'].disabled,true);
  assert.equal(h.run('ttsLatencyTimer'),null);
});

test('stream failure clears running timer',async()=>{
  const h=harness();
  h.run('startLatencyTimer();liveRun=createLiveRun("gpt-sovits",["测试"]);');
  h.fetch(async()=>{throw new Error('disconnected');});
  await h.run('streamGptUnit(liveRun)');
  assert.equal(h.run('ttsLatencyTimer'),null);
  assert.equal(h.nodes['#ttsLatency'].textContent,'');
});

test('an all-silent GPT response fails without retaining a timer or reporting completion',()=>{
  const h=harness();
  h.run('startLatencyTimer();liveRun=createLiveRun("gpt-sovits",["测试"]);liveRun.nextIndex=1;finishRunIfDrained(liveRun);');
  assert.equal(h.run('liveRun'),null);
  assert.equal(h.run('ttsLatencyTimer'),null);
  assert.equal(h.nodes['#ttsLatency'].textContent,'');
  assert.match(h.nodes['#playstate'].textContent,/未检测到有效人声/);
});

function pcmHeader(declaredBytes) {
  const bytes = Buffer.alloc(44);
  bytes.write('RIFF'); bytes.writeUInt32LE(0x7fffffff, 4); bytes.write('WAVEfmt ', 8);
  bytes.writeUInt32LE(16, 16); bytes.writeUInt16LE(1, 20); bytes.writeUInt16LE(1, 22);
  bytes.writeUInt32LE(32000, 24); bytes.writeUInt32LE(64000, 28);
  bytes.writeUInt16LE(2, 32); bytes.writeUInt16LE(16, 34);
  bytes.write('data', 36); bytes.writeUInt32LE(declaredBytes, 40);
  return bytes;
}

test('WAV stream releases PCM before the declared data length has arrived', () => {
  for (const declaredBytes of [0, 64000, 0x7fffffff - 36, 0xffffffff]) {
    const h = harness();
    const header = pcmHeader(declaredBytes);
    const pcm = Buffer.from([0x00, 0x10, 0x00, 0xf0]);
    h.context.chunks = [header.subarray(0, 21), header.subarray(21, 43),
      Buffer.concat([header.subarray(43), pcm.subarray(0, 2)]), pcm.subarray(2)];
    h.context.received = [];
    h.run('schedulePcm = (run, bytes) => { received.push(...bytes); return () => {}; }; liveRun = createLiveRun("gpt-sovits", ["测试"]);');
    assert.equal(h.run('consumeStreamBytes(liveRun, chunks[0], 0)'), null);
    assert.equal(h.run('consumeStreamBytes(liveRun, chunks[1], 0)'), null);
    assert.equal(typeof h.run('consumeStreamBytes(liveRun, chunks[2], 0)'), 'function');
    h.run('consumeStreamBytes(liveRun, chunks[3], 0)');
    assert.deepEqual(h.context.received, [...pcm]);
    assert.equal(h.run('liveRun.format.sampleRate'), 32000);
  }
});

test('WAV parser waits for complete metadata including odd chunk padding', () => {
  const h = harness();
  const header = pcmHeader(0x7fffffff - 36);
  const metadata = Buffer.from([0x4a, 0x55, 0x4e, 0x4b, 3, 0, 0, 0, 1, 2, 3, 0]);
  h.context.wav = Buffer.concat([header.subarray(0, 12), metadata, header.subarray(12)]);
  for (let end = 0; end < 56; end++) {
    h.context.end = end;
    assert.equal(h.run('parseWavHeader(wav.subarray(0, end))'), null);
  }
  assert.equal(h.run('parseWavHeader(wav).dataOffset'), 56);
});
