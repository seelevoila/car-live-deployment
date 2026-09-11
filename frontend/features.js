/* Core knowledge, model connection, business statistics and listening evaluation UI. */
(function(){
  const json=(method,body)=>({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  let playbackSeconds=0,lastClock=null,scheduledIntervals=[];
  const vehicle=()=>document.querySelector('#vehicle')?.value || '';
  const sendEvent=(kind,values={})=>api('/analytics/events',json('POST',{id:crypto.randomUUID(),kind,vehicle:vehicle(),...values})).catch(()=>{});
  const countPlayback=()=>{
    if (typeof audioCtx === 'undefined' || !audioCtx) return;
    const current=audioCtx?.currentTime;
    if(current!=null && lastClock!=null && audioCtx.state==='running'){
      let end=lastClock;
      for(const interval of scheduledIntervals.filter(x=>!x.run.stopped).sort((a,b)=>a.start-b.start)){
        const start=Math.max(lastClock,interval.start,end),until=Math.min(current,interval.end);
        if(until>start){playbackSeconds+=until-start;end=until;}
      }
    }
    lastClock=current;
    scheduledIntervals=scheduledIntervals.filter(x=>!x.run.stopped&&x.end>(current||0));
  };
  const flushPlayback=()=>{countPlayback();if(playbackSeconds>0){sendEvent('playback',{seconds:Math.min(30,playbackSeconds)});playbackSeconds=0;}};
  setInterval(()=>{
    countPlayback();
    if(playbackSeconds>=5)flushPlayback();
  },500);
  window.CarLiveFeatures={
    flushPlayback,
    cancelAudio:source=>{scheduledIntervals=scheduledIntervals.filter(x=>x.source!==source);},
    revision:()=>sendEvent('revision'),
    audioScheduled(run,source,when){
      scheduledIntervals.push({run,source,start:when,end:source.liveEnd});
      if(run.measuredFirstAudio)return;
      run.measuredFirstAudio=true;
      sendEvent('first_audio',{latency_ms:Math.max(0,performance.now()-run.requestedAt+(when-audioCtx.currentTime+(audioCtx.baseLatency||0)+(audioCtx.outputLatency||0))*1000)});
    }
  };
  const selectedIds=()=>[...document.querySelectorAll('.document-select:checked')].map(n=>Number(n.value));
  const showModal=html=>{
    document.querySelector('#featureDialog')?.remove();
    const dialog=document.createElement('dialog');
    dialog.id='featureDialog';
    dialog.innerHTML=html;
    document.body.append(dialog);
    // 先添加 DOM，然后触发动画
    requestAnimationFrame(() => {
      dialog.showModal();
    });
    dialog.querySelector('[data-close]')?.addEventListener('click',()=>dialog.close());
    // 点击背景关闭
    dialog.addEventListener('click', (e) => {
      if (e.target === dialog) dialog.close();
    });
    return dialog;
  };
  function decorateKnowledge(){
    if(!document.querySelector('#upload')||document.querySelector('#batchTools'))return;
    const table=app.querySelector('.table');if(!table)return;
    const tools=document.createElement('div');tools.id='batchTools';tools.className='inline-tools feature-tools';
    tools.innerHTML='<input id="documentSearch" placeholder="搜索文件名、车型"><button class="btn secondary" id="batchEdit">批量编辑</button><button class="btn secondary" id="batchDelete">删除选中</button><button class="btn secondary" id="ragInspector">检索索引与资料检查</button><span class="hint">上传时自动脱敏手机号、身份证号和邮箱</span>';
    table.before(tools);
    const ragButton=tools.querySelector('#ragInspector');
    ragButton.onclick=async()=>{
      try{
        const [state,quality]=await Promise.all([api('/rag/status'),api('/rag/quality')]);
        const dialog=showModal(`
          <h2>检索索引与资料检查</h2>
          <p>${state.ready?'✓ 索引已就绪':'⚠ 索引待重建'} · ${state.chunks} 个子块 · ${state.dimensions} 维 · ${state.blocked_chunks} 个隔离块</p>
          <p class="hint">${esc(state.embedding)}<br>${esc(state.reranker)}<br>CPU · ${state.threads} 线程 · FAISS + BM25 → RRF → 独立重排 → 完整问答上下文</p>
          <label>检索试查<input id="ragQuestion" value="纯电版多少钱"></label>
          <div id="ragResult"></div>
          <details><summary>资料核对记录（${quality.issues.length} 组）</summary>${quality.issues.map(x=>`<p><b>${esc(x.document_name)} · ${esc(x.title)}${x.blocked?' · 已隔离':''}</b><br>${x.warnings.map(esc).join('<br>')}</p>`).join('')}</details>
          <p class="dialog-actions">
            <button class="btn" id="ragSearch">查看召回与重排</button>
            <button class="btn secondary" id="ragReindex">重建索引</button>
            <button class="btn secondary" data-close>关闭</button>
          </p>
        `);
        dialog.querySelector('#ragSearch').onclick=async()=>{
          const result=dialog.querySelector('#ragResult');result.textContent='正在检索…';
          try{
            const vehicle=(await api('/dashboard')).vehicles[0]||{};
            const data=await api('/rag/search',json('POST',{question:dialog.querySelector('#ragQuestion').value,brand:vehicle.brand||'',series:vehicle.series||'',year:vehicle.year||''}));
            result.innerHTML=`<p>向量召回 ${data.trace.dense_candidates.length} 条 · BM25召回 ${data.trace.bm25_candidates.length} 条 · 重排 ${data.trace.reranked.length} 条 · ${data.trace.latency_ms||0} ms${data.trace.cache_hit?'（缓存）':''}</p>${data.sources.map((s,i)=>`<details><summary>${i+1}. ${esc(s.metadata.title)} · 重排相关度 ${s.score.toFixed(3)}</summary><p>${esc(s.matched_text)}</p><p class="hint">文档 ${esc(s.document_name)} v${s.version} · 子块 ${s.chunk_id} · 向量分数 ${(s.retrieval_scores.dense||0).toFixed(3)} · BM25 ${(s.retrieval_scores.bm25||0).toFixed(3)} · RRF ${s.retrieval_scores.rrf.toFixed(4)}</p></details>`).join('')}<p class="hint">相关度反映匹配程度，不代表事实正确率。</p>`;
          }catch(e){result.textContent=e.message;}
        };
        dialog.querySelector('#ragReindex').onclick=async e=>{
          e.target.disabled=true;const result=dialog.querySelector('#ragResult');result.textContent='正在重建索引…';
          try{const state=await api('/rag/reindex',json('POST',{}));result.textContent=`重建完成：${state.chunks} 个子块，索引版本 ${state.index_revision}`;}catch(e){result.textContent=e.message;}finally{e.target.disabled=false;}
        };
      }catch(e){alert(e.message);}
    };
    table.querySelectorAll('tr').forEach((row,i)=>{
      const cell=document.createElement(i?'td':'th');
      const id=row.querySelector('.versions')?.dataset.id;
      cell.innerHTML=i?`<input type="checkbox" class="document-select" value="${id}" aria-label="选择资料">`:'<input id="selectAllDocuments" type="checkbox" aria-label="全选资料">';row.prepend(cell);
      if(id){const show=document.createElement('button');show.className='btn secondary';show.textContent='来源';show.onclick=async()=>{
        const data=await api(`/knowledge/${id}/content`);
        const d=data.document;
        showModal(`<h2>${esc(d.name)}</h2><p>v${d.version} · ${esc(d.license)} · 有效期：${esc(d.valid_until||'未填写')}</p><p>${esc(d.source_url||'尚未填写原始来源')}</p><div class="evidence-text">${data.chunks.map(x=>`<p>${x.page?'第'+x.page+'页 · ':''}${esc(x.content)}</p>`).join('')}</div><button class="btn" data-close>关闭</button>`);
      };row.lastElementChild.append(show);}
    });
    document.querySelector('#selectAllDocuments').onchange=e=>table.querySelectorAll('.document-select').forEach(n=>{if(!n.closest('tr').hidden)n.checked=e.target.checked;});
    document.querySelector('#documentSearch').oninput=e=>[...table.rows].slice(1).forEach(row=>row.hidden=!row.textContent.toLowerCase().includes(e.target.value.toLowerCase()));
    document.querySelector('#batchDelete').onclick=async()=>{
      const ids=selectedIds();if(!ids.length)return alert('请先选择资料');
      if(!confirm(`删除选中的 ${ids.length} 份资料及其版本记录？`))return;
      try{await api('/knowledge/batch-delete',json('POST',{ids}));await knowledge();}catch(e){alert(e.message);}
    };
    document.querySelector('#batchEdit').onclick=()=>{
      const ids=selectedIds();if(!ids.length)return alert('请先选择资料');
      const fields=[['brand','品牌'],['series','车系'],['year','年款'],['source_url','公开来源地址'],['license','资料许可/授权说明'],['valid_until','政策有效期']];
      const dialog=showModal(`
        <h2>批量编辑 ${ids.length} 份资料</h2>
        <p>仅填写需要更新的字段，保存后生成新版本。</p>
        <div class="fields">${fields.map(([id,label])=>`<label>${label}<input name="${id}" type="${id==='valid_until'?'date':'text'}"></label>`).join('')}</div>
        <p id="batchMessage"></p>
        <p class="dialog-actions">
          <button class="btn" id="saveBatch">保存新版本</button>
          <button class="btn secondary" data-close>取消</button>
        </p>
      `);
      dialog.querySelector('#saveBatch').onclick=async()=>{
        const body={ids};fields.forEach(([id])=>{const value=dialog.querySelector(`[name="${id}"]`).value.trim();if(value)body[id]=value;});
        try{await api('/knowledge/batch',json('PATCH',body));dialog.close();await knowledge();}catch(e){dialog.querySelector('#batchMessage').textContent=e.message;}
      };
    };
  }
  function decoratePlayback(){
    const controls=document.querySelector('.studio-settings');
    if(!controls||controls.dataset.playbackDecorated)return;
    controls.dataset.playbackDecorated='1';
    const isAvatar=Boolean(document.querySelector('#avatarCanvas'));
    if(isAvatar){
      const box=document.createElement('details');box.className='avatar-tuning';
      box.innerHTML='<summary>嘴型同步与动作</summary><div class="fields"><label>嘴型时差 <output id="lipOffsetOut"></output><input id="lipOffset" type="range" min="-250" max="250" step="10"></label><label>嘴型幅度 <output id="lipStrengthOut"></output><input id="lipStrength" type="range" min="0.7" max="1.8" step="0.05"></label><label><input type="checkbox" id="avatarMotion" checked>随语气点头、表情与呼吸</label></div><p class="hint">时差用于补偿音箱或耳机的输出延迟，嘴动得早向右调、嘴动得晚向左调；设置保存在本机浏览器。</p><button class="btn secondary" id="resetLip">恢复默认</button>';
      controls.after(box);
      const offset=box.querySelector('#lipOffset'),strength=box.querySelector('#lipStrength');
      offset.value=localStorage.getItem('avatarLipOffset')||0;strength.value=localStorage.getItem('avatarLipStrength')||1.25;
      const sync=()=>{localStorage.setItem('avatarLipOffset',offset.value);localStorage.setItem('avatarLipStrength',strength.value);box.querySelector('#lipOffsetOut').textContent=(Number(offset.value)>0?'+':'')+offset.value+' ms';box.querySelector('#lipStrengthOut').textContent=Number(strength.value).toFixed(2);};
      offset.oninput=sync;strength.oninput=sync;sync();box.querySelector('#resetLip').onclick=()=>{offset.value=0;strength.value=1.25;sync();};
    }
  }
  new MutationObserver(()=>{decorateKnowledge();decoratePlayback();}).observe(app,{childList:true,subtree:true});
  decorateKnowledge();decoratePlayback();
  const rank=(title,rows)=>`<section class="panel"><div class="panel-head"><h2>${title}</h2></div><div class="panel-body">${rows.length?rows.map(r=>`<p>${esc(r.name)} <b>${r.count}</b></p>`).join(''):'<p class="hint">暂无记录</p>'}</div></section>`;
  async function analyticsView(){
    const data=await api('/analytics');
    layout('直播统计','最近 7 天的实际讲解时长、观众咨询与知识库检索热点。',`<div class="metrics"><div class="metric"><b>${(data.playback_seconds/60).toFixed(1)} 分钟</b><span>实际讲解时长</span></div><div class="metric"><b>${data.question_count}</b><span>观众咨询</span></div><div class="metric"><b>${data.revision_count}</b><span>动态改稿</span></div><div class="metric"><b>${data.first_audio.max_ms==null?'暂无':(data.first_audio.max_ms/1000).toFixed(2)+' 秒'}</b><span>首音频最大延迟</span></div></div>${rank('高频咨询车型',data.popular_vehicles)}${rank('知识库检索热点',data.retrieval_hotspots)}${rank('高频问题',data.frequent_questions)}<p><a class="btn secondary" href="${API}/reports/export" download>导出运行与听测报告</a></p>`,{eyebrow:'扩展能力',tag:'近 7 天'});
  }
  async function modelView(){
    let config=await api('/llm/config');
    layout('大模型配置','接入任意 OpenAI 兼容服务，保存后立即用于问答与话术生成，无需重启后端。',`<section class="panel model-config"><div class="panel-head"><h2>模型连接</h2><span id="modelConnectionState">${config.status.configured?'已配置 · 待测试':'尚未配置'}</span></div><div class="panel-body"><p class="notice" id="modelStatus">${esc(config.status.message)}</p><form id="modelConfigForm"><fieldset id="modelFields"><div class="fields model-config-grid"><label>服务地址<input id="llmBaseUrl" name="base_url" type="url" required maxlength="2000" placeholder="https://api.deepseek.com/v1" value="${esc(config.base_url)}" spellcheck="false" autocomplete="url"><span class="hint">兼容 Chat Completions 的服务地址，也可填写完整接口地址。</span></label><label>模型名称<input id="llmModel" name="model" required maxlength="200" placeholder="填写服务商提供的模型名" value="${esc(config.model)}" spellcheck="false" autocomplete="off"></label><label>API Key<div class="model-key-input"><input id="llmApiKey" name="api_key" type="password" maxlength="4096" placeholder="${config.api_key_configured?'已保存密钥，留空保留':'填写服务商提供的 API Key'}" autocomplete="new-password" spellcheck="false"><button class="btn secondary" type="button" id="toggleModelKey" aria-label="显示新输入的密钥" aria-pressed="false">显示</button></div><span class="hint" id="modelKeyHint">${config.api_key_configured?'密钥已保存在后端，页面不回显；填写新值才会替换。':'密钥仅保存在本机后端，不写入浏览器。'}</span></label><label>请求超时（秒）<input id="llmTimeout" name="timeout_seconds" type="number" min="1" max="120" step="1" required value="${Number(config.timeout_seconds)}"><span class="hint">超时或调用失败时自动回退到本地资料摘录。</span></label></div><label class="model-keyless"><input id="llmClearKey" type="checkbox">此服务无需密钥（清除已保存的密钥）</label><div class="controls"><button class="btn" type="submit" id="saveModel">保存配置</button><button class="btn secondary" type="button" id="probeModel">保存并测试连接</button></div></fieldset><p id="modelResult" class="hint" role="status" aria-live="polite">更换服务地址时，请同时填写新服务的密钥。</p></form></div></section>`,{eyebrow:'扩展能力',tag:'OpenAI 兼容接口'});
    const form=document.querySelector('#modelConfigForm'),fields=form.querySelector('fieldset');
    const key=form.querySelector('#llmApiKey'),clear=form.querySelector('#llmClearKey'),toggle=form.querySelector('#toggleModelKey');
    const result=form.querySelector('#modelResult'),connection=document.querySelector('#modelConnectionState'),notice=document.querySelector('#modelStatus');
    const message=(text,error=false)=>{result.textContent=text;result.className=error?'notice error':'notice';};
    toggle.onclick=()=>{const visible=key.type==='password';key.type=visible?'text':'password';toggle.textContent=visible?'隐藏':'显示';toggle.setAttribute('aria-pressed',String(visible));toggle.setAttribute('aria-label',visible?'隐藏新输入的密钥':'显示新输入的密钥');};
    clear.onchange=()=>{key.disabled=clear.checked;toggle.disabled=clear.checked;};
    form.addEventListener('input',()=>{connection.textContent='有未保存修改';result.textContent='修改尚未保存，当前问答仍使用已保存配置。';result.className='hint';});
    async function save(testConnection){
      if(fields.disabled||!form.reportValidity())return;
      const body={base_url:form.elements.base_url.value.trim(),model:form.elements.model.value.trim(),timeout_seconds:Number(form.elements.timeout_seconds.value),clear_api_key:clear.checked};
      if(!clear.checked&&key.value.trim())body.api_key=key.value.trim();
      fields.disabled=true;message('正在保存配置…');
      try{
        config=await api('/llm/config',json('PUT',body));
        key.value='';key.type='password';toggle.textContent='显示';toggle.setAttribute('aria-pressed','false');toggle.setAttribute('aria-label','显示新输入的密钥');
        clear.checked=false;key.disabled=false;toggle.disabled=false;
        form.elements.base_url.value=config.base_url;form.elements.model.value=config.model;form.elements.timeout_seconds.value=config.timeout_seconds;
        key.placeholder=config.api_key_configured?'已保存密钥，留空保留':'填写服务商提供的 API Key';
        form.querySelector('#modelKeyHint').textContent=config.api_key_configured?'密钥已保存在后端，页面不回显；填写新值才会替换。':'当前未保存密钥。';
        connection.textContent='已配置 · 待测试';notice.textContent=`当前模型：${config.model}。配置已保存，无需重启后端。`;
        message('配置已保存并生效。');
        if(testConnection){
          message('配置已保存，正在测试连接…');
          const tested=await api('/llm/test',{method:'POST'});
          connection.textContent=tested.ok?'连接成功':'已保存 · 连接未通过';
          message(tested.ok?`连接成功，${config.model} 已可用于问答和话术生成。`:`配置已保存，但${tested.message}。可修改后重新测试。`,!tested.ok);
        }
      }catch(e){message(e.message,true);}finally{fields.disabled=false;}
    }
    form.onsubmit=e=>{e.preventDefault();void save(false);};
    form.querySelector('#probeModel').onclick=()=>void save(true);
  }
  async function evaluationView(){
    const [voices,result]=await Promise.all([api('/voices'),api('/voice-evaluations')]);
    const categories=[['similarity','音色相似度'],['clarity','发音清晰度'],['pause','自然停顿'],['emotion','情绪节奏'],['overall','整体拟人度']];
    layout('音色听测','由真实听测者按统一文案与参数打分，用于量化音色拟人度。',`<section class="panel"><div class="panel-body"><p class="notice">${esc(result.message)}</p><form id="evaluationForm"><div class="fields"><label>参考音色<select name="voice_id">${VoiceLibrary.options(voices.filter(v=>v.builtin||v.cloned),esc)}</select></label><label>听测者代号<input name="reviewer" required maxlength="50" placeholder="例如：评测者A"></label></div><label>试听文案<textarea name="text" required>大家好，欢迎来到汽车直播间。今天我们一起了解这款车的续航、空间和智能配置。你最关心哪一点呢？</textarea></label><div class="fields">${categories.map(([key,label])=>`<label>${label}<select name="${key}" required><option value="">请选择</option>${[1,2,3,4,5].map(n=>`<option value="${n}">${n}分</option>`).join('')}</select></label>`).join('')}</div><label>听感备注<input name="notes" maxlength="1000"></label><p><button class="btn secondary" type="button" id="playEvaluation">生成试听</button> <button class="btn" type="submit">保存评分</button></p><audio id="evaluationAudio" controls></audio><p id="evaluationMessage"></p></form></div></section>${result.voices.map(v=>`<section class="panel"><div class="panel-body"><b>${esc(voices.find(x=>x.id===v.voice_id)?.name||v.voice_id)}</b><p>${v.reviewers} 名听测者 · ${v.samples} 条记录</p><p>${categories.map(([key,label])=>`${label} ${v.averages[key]}`).join(' · ')}</p></div></section>`).join('')}`,{eyebrow:'扩展能力',tag:'主观评测'});
    const form=document.querySelector('#evaluationForm');let audioURL;
    document.querySelector('#playEvaluation').onclick=async()=>{
      const node=document.querySelector('#evaluationMessage');node.textContent='正在生成当前文案…';
      try{const response=await api('/tts/synthesize',json('POST',{voice_id:form.elements.voice_id.value,text:form.elements.text.value,delivery:'natural'}));const blob=await response.blob();if(audioURL)URL.revokeObjectURL(audioURL);audioURL=URL.createObjectURL(blob);const player=document.querySelector('#evaluationAudio');player.src=audioURL;node.textContent='音频已生成，请点击播放器试听后评分。';}catch(e){node.textContent=e.message;}
    };
    form.onsubmit=async e=>{e.preventDefault();const data=Object.fromEntries(new FormData(form));categories.forEach(([k])=>data[k]=Number(data[k]));try{await api('/voice-evaluations',json('POST',data));await evaluationView();}catch(error){document.querySelector('#evaluationMessage').textContent=error.message;}};
  }
  // Navigation lives in index.html. app.js resolves the active loader through
  // viewLoaders() at click time, so registering the loaders is all that is needed.
  window.CarLiveViews={analytics:analyticsView,evaluation:evaluationView,model:modelView};
})();
