const test = require('node:test');
const assert = require('node:assert/strict');
const library = require('../voice-library.js');
const esc = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const voices = [
  {id:'steady', name:'沉稳阿川', kind:'builtin', builtin:true, provider:'gpt-sovits', quality:{status:'ready'}, gender:'男声', style:'沉稳讲解', description:'配置讲解'},
  {id:'clone', name:'我的 <克隆>', kind:'clone', cloned:1, provider:'gpt-sovits', quality:{status:'ready'}},
  {id:'broken', name:'坏音色', kind:'builtin', builtin:true, provider:'gpt-sovits', quality:{status:'missing'}},
  {id:'browser-default', name:'系统默认', kind:'system', provider:'browser'},
];

test('coverage reports exact automotive tokens missing from the reference', () => {
  assert.deepEqual(library.missingCoverage('CLTC续航580km，轴距2720毫米，最大功率150千瓦。', '大家好，欢迎来到直播间。'),
    ['CLTC', '580km', '2720毫米', '150千瓦']);
  assert.deepEqual(library.missingCoverage('CLTC和EV车型。', '这款cltc与ev车型。'), []);
});

test('coverage uses the speech normalizer to recognize spoken numeric equivalents', () => {
  const normalize = text => text.replace('2720', '二千七百二十');
  assert.deepEqual(library.missingCoverage('轴距2720毫米。', '轴距二千七百二十毫米。', normalize), []);
});

test('fresh users start with a usable built-in speaker; saved choices survive navigation', () => {
  assert.equal(library.preferred(voices, null), 'steady');
  assert.equal(library.preferred(voices, 'clone'), 'clone');
  assert.equal(library.preferred(voices, 'deleted-clone'), 'steady');
  assert.equal(library.preferred(voices, 'broken'), 'steady');
  assert.equal(library.preferred(voices, 'browser-default'), 'browser-default');
});

test('speaker choices separate built-ins, clones and system audio without style suffixes', () => {
  const html = library.options(voices, esc);
  for (const label of ['内置主播', '我的克隆', '系统声音']) assert.ok(html.includes(`label="${label}"`));
  assert.ok(html.includes('我的 &lt;克隆&gt;'));
  assert.ok(html.includes('>沉稳阿川</option>'));
  assert.match(html, /value="broken"[^>]*disabled/);
  assert.ok(!html.includes('PCM') && !html.includes('预置风格'));
});

test('preset cards provide listen/use actions but cannot edit or delete a speaker', () => {
  const html = library.cards(voices, esc);
  assert.ok(html.includes('aria-label="试听沉稳阿川"'));
  assert.ok(html.includes('aria-label="使用沉稳阿川"'));
  assert.ok(!html.includes('voice-delete') && !html.includes('voice-save'));
  assert.ok(!html.includes('我的 &lt;克隆&gt;'));
});

test('a validated clone remains selectable while optional calibration runs', () => {
  const clone = {...voices[1], warmed:true, calibrating:true, calibration_pending:true, synthesis_check:{status:'ready'}};
  assert.equal(library.unavailable(clone), false);
  assert.equal(library.preferred([voices[0], clone], 'clone'), 'clone');
  assert.ok(!library.options([clone], esc).includes(' disabled'));
  assert.equal(library.unavailable({...clone, synthesis_check:{status:'pending'}}), true);
  assert.equal(library.unavailable({...clone, synthesis_check:{status:'failed'}}), true);
});
