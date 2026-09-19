from pathlib import Path
import ast
root=Path(__file__).resolve().parents[1]
p=root/'backend/app/main.py'
s=p.read_text(encoding='utf-8');lines=s.splitlines(keepends=True)
targets={'_voice_aux_reference_paths','_voice_sampling_seed','_voice_sampling_profile','_voice_model_profile'}
inserts=[]
for node in ast.parse(s).body:
    if isinstance(node,ast.FunctionDef) and node.name in targets:
        first=node.body[0]
        line=first.end_lineno if isinstance(first,ast.Expr) and isinstance(first.value,ast.Constant) and isinstance(first.value.value,str) else node.lineno
        inserts.append(line)
for index in sorted(inserts,reverse=True):lines.insert(index,'    voice_id=_effective_voice_id(voice_id)\n')
p.write_text(''.join(lines),encoding='utf-8')
p=root/'frontend/app.js';s=p.read_text(encoding='utf-8')
s=s.replace('''      lipSync.cancel(source);
''','''      lipSync.cancel(source);
      window.CarLiveFeatures?.cancelAudio(source);
''')
start=s.index('async function tests() {');end=s.index("document.querySelectorAll('nav button')",start)
s=s[:start]+'''async function tests() {
  layout('性能与验收', '按自然问句测试检索与本地回答；模型首包和客户端实际播放分别统计。', '<div id="testResult">测试中…</div>');
  try {
    const [rag,qa]=await Promise.all([api('/tests/retrieval',{method:'POST'}),api('/tests/qa',{method:'POST'})]);
    const tts=await api('/tests/tts',{method:'POST'});
    const stats=await api('/analytics');
    document.querySelector('#testResult').innerHTML=`<div class="metrics"><div class="metric"><b>${rag.accuracy}%</b><span>完整依据命中 ${rag.passed}/${rag.total}</span></div><div class="metric"><b>${qa.accuracy}%</b><span>本地回答命中 ${qa.passed}/${qa.total}</span></div><div class="metric"><b>${tts.average_first_audio_ms ?? '-'} ms</b><span>模型首包平均延迟</span></div><div class="metric"><b>${tts.meets_target?'本次通过':'需优化'}</b><span>全部首包样本 ≤3秒</span></div></div><p class="notice">模型首包不包含浏览器等待。客户端近期 ${stats.first_audio.count} 次记录，最大首音频排程延迟 ${stats.first_audio.max_ms==null?'暂无':Math.round(stats.first_audio.max_ms)+' ms'}。</p><pre>${esc(JSON.stringify({retrieval:rag,local_qa:qa,model_first_audio:tts},null,2))}</pre><a class="btn secondary" href="${API}/reports/export" download>导出运行与听测报告</a>`;
  } catch(error) {document.querySelector('#testResult').innerHTML=`<p class="notice error">${esc(error.message)}</p><button class="btn" id="retryTests">重试</button>`;document.querySelector('#retryTests').onclick=tests;}
}

'''+s[end:]
p.write_text(s,encoding='utf-8')
