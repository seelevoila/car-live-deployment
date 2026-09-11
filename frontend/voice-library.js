(function (root) {
  const unavailable = voice => voice.kind !== 'system' && voice.provider !== 'browser' &&
    (voice.quality?.status !== 'ready' || voice.warming ||
      voice.synthesis_check?.status === 'pending' || voice.synthesis_check?.status === 'failed');

  function preferred(voices, savedId) {
    const saved = voices.find(voice => voice.id === savedId && !unavailable(voice));
    return (saved || voices.find(voice => voice.builtin && !unavailable(voice)) ||
      voices.find(voice => !unavailable(voice)))?.id || '';
  }

  function options(voices, esc) {
    return [['builtin', '内置主播'], ['clone', '我的克隆'], ['system', '系统声音']].map(([kind, label]) => {
      const group = voices.filter(voice => voice.kind === kind);
      if (!group.length) return '';
      return `<optgroup label="${label}">${group.map(voice =>
        `<option value="${esc(voice.id)}" data-provider="${esc(voice.provider || '')}" data-cloned="${voice.cloned ? '1' : '0'}"${unavailable(voice) ? ' disabled' : ''}>${esc(voice.name)}${unavailable(voice) ? ' · 暂不可用' : ''}</option>`
      ).join('')}</optgroup>`;
    }).join('');
  }

  function cards(voices, esc) {
    return `<section class="panel"><div class="panel-head"><h2>内置主播</h2><span>选一个喜欢的声音，直接开始讲解</span></div><div class="panel-body preset-voice-grid">${voices.filter(voice => voice.builtin).map(voice =>
      `<article class="preset-voice-card" data-voice-card="${esc(voice.id)}"><div class="preset-voice-title"><span class="voice-monogram" aria-hidden="true">${esc(voice.name.slice(-1))}</span><div><h3>${esc(voice.name)}</h3><p>${esc(voice.gender)} · ${esc(voice.style)}</p></div><span class="voice-selected-label" hidden>使用中</span></div><p class="preset-voice-description">${esc(voice.description)}</p>${unavailable(voice) ? '<p class="hint">声音暂不可用，请检查服务与内置资源。</p>' : ''}<div class="controls"><button class="btn secondary voice-preview" data-id="${esc(voice.id)}" aria-label="试听${esc(voice.name)}"${unavailable(voice) ? ' disabled' : ''}>试听</button><button class="btn voice-use" data-id="${esc(voice.id)}" aria-label="使用${esc(voice.name)}"${unavailable(voice) ? ' disabled' : ''}>使用</button></div></article>`
    ).join('')}</div></section>`;
  }

  const api = {unavailable, preferred, options, cards};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.VoiceLibrary = api;
})(typeof window !== 'undefined' ? window : globalThis);
