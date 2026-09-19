const test = require('node:test');
const assert = require('node:assert/strict');
const {Timeline, outputTime} = require('../lip-sync.js');

function audio(duration, amplitudeAt) {
  const sampleRate = 32000;
  const data = Float32Array.from({length: Math.round(duration * sampleRate)}, (_, i) =>
    amplitudeAt(i / sampleRate) * Math.sin(2 * Math.PI * 180 * i / sampleRate));
  return {sampleRate, length: data.length, duration, numberOfChannels: 1, getChannelData: () => data};
}
function advance(timeline, start, end) {
  const levels = [];
  for (let t = start; t < end; t += 1 / 60) levels.push(timeline.sample(t));
  return levels;
}

test('future generated audio and lead-in silence do not move the mouth', () => {
  const timeline = new Timeline();
  timeline.schedule({}, audio(1, t => t < 0.3 ? 0 : 0.2), 5);
  assert.equal(Math.max(...advance(timeline, 0, 5.3)), 0);
  assert.ok(Math.max(...advance(timeline, 5.3, 5.5)) > 0.4);
});

test('pausing/muting closes the mouth and resuming follows the same audio position', () => {
  const timeline = new Timeline();
  timeline.schedule({}, audio(2, () => 0.2), 0);
  advance(timeline, 0, 0.5);
  assert.equal(timeline.sample(0.5, false), 0);
  assert.ok(Math.max(...advance(timeline, 0.5, 0.7)) > 0.4);
  assert.equal(timeline.sample(0.7, true, 0), 0);
  timeline.clear();
  assert.equal(timeline.sample(0.8), 0);
});

test('playback rate changes mouth timing together with the sound', () => {
  const timeline = new Timeline();
  timeline.schedule({}, audio(2, t => t >= 1 ? 0.2 : 0), 10, 2);
  assert.equal(Math.max(...advance(timeline, 10, 10.48)), 0);
  assert.ok(Math.max(...advance(timeline, 10.52, 10.8)) > 0.4);
});

test('dynamic revisions remove cancelled future audio without cancelling the active phrase', () => {
  const timeline = new Timeline();
  const first = {}, replaced = {}, newPhrase = {};
  timeline.schedule(first, audio(0.5, () => 0.2), 0);
  timeline.schedule(replaced, audio(0.5, () => 0.3), 0.5);
  timeline.cancel(replaced);
  timeline.schedule(newPhrase, audio(0.5, () => 0), 0.5);
  assert.ok(Math.max(...advance(timeline, 0, 0.4)) > 0.4);
  advance(timeline, 0.4, 0.95);
  assert.ok(timeline.sample(0.99) < 0.01);
});

test('rapid amplitude changes are smoothed while sentence gaps close the mouth', () => {
  const timeline = new Timeline();
  timeline.schedule({}, audio(2, t => t < 1 ? (Math.floor(t / 0.02) % 2 ? 0.03 : 0.3) : 0), 0);
  const levels = advance(timeline, 0, 1.6);
  const steps = levels.slice(1).map((level, i) => Math.abs(level - levels[i]));
  assert.ok(Math.max(...steps) < 0.25);
  assert.equal(levels.at(-1), 0);
});

test('mouth uses speaker output time, including output latency and the final audio tail', () => {
  const context = {currentTime: 8.2, getOutputTimestamp: () => ({contextTime: 8, performanceTime: 1000})};
  assert.equal(outputTime(context, 1050), 8.05);
  assert.equal(outputTime(context, 1400), 8.2);
  assert.ok(Math.abs(outputTime({currentTime: 8.2, baseLatency: 0.05, outputLatency: 0.1}, 1050) - 8.05) < 1e-9);
  const timeline = new Timeline();
  timeline.schedule({}, audio(0.2, () => 0.2), 8);
  advance(timeline, 8, 8.1);
  assert.ok(timeline.sample(8.15) > 0.4, 'render onended must not clear the still audible tail');
});

test('device offset shifts the mouth with the same PCM, preserving explicit pauses', () => {
  const timeline=new Timeline();
  timeline.offsetMs=150;
  timeline.schedule({},audio(1,t=>t>.2&&t<.7?.2:0),5);
  assert.equal(Math.max(...advance(timeline,5,5.34)),0);
  assert.ok(Math.max(...advance(timeline,5.36,5.6))>.4);
  assert.equal(timeline.sample(5.6,false),0);
});

test('ordinary listening volume does not shrink articulation; mute still closes', () => {
  const normal=new Timeline(),quiet=new Timeline();
  normal.schedule({},audio(1,()=>.2),0);quiet.schedule({},audio(1,()=>.2),0);
  for(let t=0;t<.5;t+=1/60){normal.sample(t,true,1);quiet.sample(t,true,.1);}
  assert.equal(normal.level,quiet.level);
  assert.equal(quiet.sample(.5,true,0),0);
});
