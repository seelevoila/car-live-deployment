from pathlib import Path
p=Path(__file__).resolve().parents[1]/'frontend/app.js'
s=p.read_text(encoding='utf-8')
s=s.replace("const lipSync = new SpeechLipSync.Timeline();", "const lipSync = new SpeechLipSync.Timeline();\nconst avatarPerformer = new AvatarPerformer.Performer();\nlet audioIntent = 0;")
s=s.replace("function stop() { stopLive", "function stop() { audioIntent++; stopLive")
s=s.replace("async function play() {", "async function play() {\n  const intent=++audioIntent;")
s=s.replace("  if (liveRun?.paused) { await resumeLive(liveRun); return; }", "  if (intent !== audioIntent) return;\n  if (liveRun?.paused) { await resumeLive(liveRun); return; }")
s=s.replace("async function speakText(text) {", "async function speakText(text) {\n  const intent=++audioIntent;\n  await ensureAudio();")
s=s.replace("    return startGptRun(q);", "    if (intent !== audioIntent) return;\n    return startGptRun(q);")
s=s.replace("  const mouth = lipSync.sample(", "  lipSync.offsetMs=Number(localStorage.getItem('avatarLipOffset') || 0);\n  lipSync.sensitivity=Number(localStorage.getItem('avatarLipStrength') || 1.25);\n  const mouth = lipSync.sample(")
s=s.replace("  live2dModel.internalModel.coreModel.setParameterValueById('ParamMouthOpenY', mouth);", """  const core=live2dModel.internalModel.coreModel;
  core.setParameterValueById('ParamMouthOpenY', mouth);
  core.setParameterValueById('ParamMouthForm',mouth>.02 ? lipSync.form : .15);
  avatarPerformer.update(core,performance.now()/1000,mouth,{style:document.querySelector('#delivery')?.value || 'warm',enabled:document.querySelector('#avatarMotion')?.checked !== false,paused:Boolean(liveRun?.paused)});""")
s=s.replace('resolution: Math.min(window.devicePixelRatio || 1, 2)', 'resolution: 1')
s=s.replace('    // Keep each quality-first phrase fragment intact.\n    if (!flush) return;', '''    const available=wholeFramesForQueue(run,bytesPerFrame);
    const minimum=Math.ceil(sampleRate*(run.hasScheduledAudio ? .12 : .24));
    if (!flush && available < minimum) return;''')
s=s.replace('      const frames = wholeFramesForQueue(run, bytesPerFrame);', '''      const available=wholeFramesForQueue(run,bytesPerFrame);
      if(!flush && available < Math.ceil(sampleRate*.12)) break;
      const frames = Math.min(available,Math.ceil(sampleRate*.36));''')
s=s.replace('''      source.start(when);
''','''      source.start(when);
      window.CarLiveFeatures?.audioScheduled(run,source,when);
''')
s=s.replace('''function createLiveRun(mode, q, startIndex = 0) {
  return {''','''function createLiveRun(mode, q, startIndex = 0) {
  return {
    requestedAt:performance.now(),''')
s=s.replace("  const run = liveRun;\n  if (run) {", "  const run = liveRun;\n  window.CarLiveFeatures?.flushPlayback();\n  if (run) {")
s=s.replace('''    text,
''','''    text,
''')
# ttsBody uses a one-line object; insert the delivery before JSON serialization.
start=s.index('function ttsBody(')
end=s.index('async function startQualityPreview',start)
part=s[start:end]
part=part.replace('JSON.stringify({',"JSON.stringify({delivery:document.querySelector('#delivery')?.value || 'natural',")
s=s[:start]+part+s[end:]
# Show actual evidence instead of converting an uncalibrated score to certainty.
old='''currentAnswer = r.answer; document.querySelector('#answer').innerHTML = `<div class="notice">${esc(r.answer)}</div>${r.sources.map(s => `<div class="source">${esc(s.document_name)} · 相关度 ${Math.round(s.score * 100)}% · ${esc(s.metadata.series || '')}</div>`).join('')}`;'''
new='''currentAnswer = r.answer; document.querySelector('#answer').innerHTML = `<div class="notice">${esc(r.answer)}</div><p class="hint">${r.provider==='llm-grounded-rag' ? '大模型依据回答' : '本地资料摘录'} · 依据充分度：${esc(({high:'高',medium:'中',low:'不足'})[r.confidence] || r.confidence)}</p>${r.sources.map((s,i) => `<details class="source"><summary>[${i+1}] ${esc(s.document_name)} · v${s.version||1}${s.page ? ' · 第'+s.page+'页' : ''} · 检索相关度 ${Math.round(Math.min(1,s.score)*100)}%</summary><p>${esc(s.content)}</p><small>${esc(s.metadata.series||'')} · ${esc(s.license||'来源待审核')}</small>${s.source_url && /^https?:\\/\\//.test(s.source_url) ? `<p><a href="${esc(s.source_url)}" target="_blank" rel="noopener noreferrer">查看原始来源</a></p>` : ''}</details>`).join('')}`;'''
assert old in s
s=s.replace(old,new)
s=s.replace("  document.querySelector('#version').textContent = '会话版本 v' + session.version;", "  document.querySelector('#version').textContent = '会话版本 v' + session.version;\n  window.CarLiveFeatures?.revision();")
s=s.replace('const response = await fetch(API + \'/tts/stream\',', 'const response = await fetch(API + \'/tts/stream\',')
p.write_text(s,encoding='utf-8')
