(function(root) {
  const SCRIPT = '大家好，欢迎来到直播间。今天一起了解这款车，看看它有哪些亮点。';

  function encodeWav(samples, rate = 24000) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    const text = (offset, value) => [...value].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0)));
    text(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true);
    text(8, 'WAVE'); text(12, 'fmt '); view.setUint32(16, 16, true);
    view.setUint16(20, 1, true); view.setUint16(22, 1, true);
    view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true);
    view.setUint16(32, 2, true); view.setUint16(34, 16, true);
    text(36, 'data'); view.setUint32(40, samples.length * 2, true);
    samples.forEach((value, index) => {
      const clipped = Math.max(-1, Math.min(1, value));
      view.setInt16(44 + index * 2, Math.round(clipped * (clipped < 0 ? 32768 : 32767)), true);
    });
    return buffer;
  }

  function validateRecording(samples, rate) {
    const duration = samples.length / rate;
    if (duration < 3) throw new Error('录音不足 3 秒，请重新录制并完整朗读。');
    if (duration > 10.5) throw new Error('录音超过 10 秒，请重新录制。');
    let energy = 0;
    for (const sample of samples) energy += sample * sample;
    if (Math.sqrt(energy / samples.length) < 0.002) throw new Error('没有检测到清晰声音，请检查麦克风是否静音或离得太远。');
    return duration;
  }

  function markup() {
    return `<div id="cloneCapture" class="clone-capture">
      <div class="capture-tabs" role="tablist" aria-label="克隆方式"><button class="btn secondary" id="captureUploadTab" type="button" role="tab" aria-selected="true" aria-controls="captureUpload">上传音频</button><button class="btn secondary" id="captureRecordTab" type="button" role="tab" aria-selected="false" aria-controls="captureRecord">麦克风录制</button></div>
      <div id="captureUpload" role="tabpanel" aria-labelledby="captureUploadTab" class="capture-upload-grid">
        <label>主参考音频<input id="voiceFile" type="file" accept=".wav,.mp3,.flac,.ogg,.m4a"><small id="voiceFileMeta" class="hint">建议 5-10 秒，最低 3 秒；主参考音频必须填写对应原文</small></label>
        <label>辅助参考音频（可选）<input id="voiceAuxFiles" type="file" multiple accept=".wav,.mp3,.flac,.ogg,.m4a"><small id="voiceAuxMeta" class="hint">最多 2 条；同一说话人的不同句子，不需要填写文字</small></label>
        <label class="capture-transcript">参考文本（必填）<input id="voicePrompt" maxlength="500" placeholder="填写主参考音频中实际说出的原文，须逐字一致"><small id="voicePromptMeta" class="hint">至少 4 个字；标点和停顿也尽量保持一致</small></label>
      </div>
      <div id="captureRecord" role="tabpanel" aria-labelledby="captureRecordTab" hidden>
        <p class="hint">点击开始录音后，用平时介绍产品的语气完整朗读下方文字，约 5～10 秒。录完可先回听，再创建音色。</p>
        <blockquote class="record-script" id="recordScript">${SCRIPT}</blockquote>
        <div class="controls"><button class="btn" id="recordStart" type="button">开始录音</button><button class="btn secondary" id="recordStop" type="button" disabled>结束录音</button><output id="recordTimer" aria-label="录音时长">0.0 / 10 秒</output></div>
        <p id="recordStatus" role="status" aria-live="polite" class="hint">参考文本会自动使用上方朗读文案；录音仅在你检查样本或创建音色时上传。</p>
        <audio id="recordPreview" controls hidden aria-label="回听我的录音"></audio>
      </div>
    </div>`;
  }

  function mount(container, {onBusy = () => {}, beforeRecord = () => {}} = {}) {
    let mode = 'upload', file = null, duration = 0, stream = null, recorder = null;
    let timer = null, deadline = null, url = null, generation = 0, disposed = false;
    const $ = selector => container.querySelector(selector);
    const status = message => { if (!disposed) $('#recordStatus').textContent = message; };
    const stopTracks = () => { stream?.getTracks().forEach(track => track.stop()); stream = null; };
    const clearTimers = () => { clearInterval(timer); clearTimeout(deadline); timer = deadline = null; };
    const busy = value => {
      if (disposed) return;
      $('#recordStart').disabled = value;
      onBusy(value);
    };
    function discard() {
      file = null; duration = 0;
      const player = $('#recordPreview'); player.pause(); player.removeAttribute('src'); player.hidden = true;
      if (url) URL.revokeObjectURL(url);
      url = null;
    }
    function cancel() {
      generation++; clearTimers();
      if (recorder?.state === 'recording') recorder.stop();
      recorder = null; stopTracks();
      if (!disposed) { $('#recordStop').disabled = true; busy(false); }
    }
    function selectMode(next) {
      cancel(); mode = next;
      $('#recordPreview').pause();
      $('#captureUpload').hidden = mode !== 'upload';
      $('#captureRecord').hidden = mode !== 'record';
      $('#captureUploadTab').setAttribute('aria-selected', String(mode === 'upload'));
      $('#captureRecordTab').setAttribute('aria-selected', String(mode === 'record'));
      status(file ? '录音已准备好，可以回听或创建音色。' : '准备好后点击开始录音，并完整朗读上方文字。');
    }
    async function start() {
      cancel(); discard(); beforeRecord();
      const token = generation;
      if (!navigator.mediaDevices?.getUserMedia || !root.MediaRecorder) {
        status('当前浏览器无法录音，请用 Chrome 或 Edge 访问 localhost / HTTPS，或选择上传音频。'); return;
      }
      busy(true); status('正在请求麦克风权限，请在浏览器提示中允许使用。');
      try {
        const input = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1, echoCancellation:true, noiseSuppression:true}, video:false});
        if (disposed || token !== generation) { input.getTracks().forEach(track => track.stop()); return; }
        stream = input;
        const mimeType = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm'].find(type => MediaRecorder.isTypeSupported(type));
        const active = new MediaRecorder(stream, mimeType ? {mimeType} : {});
        recorder = active;
        const chunks = [];
        active.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
        active.onerror = () => { if (token === generation) { cancel(); status('录音中断，请检查麦克风后重新录制。'); } };
        active.onstop = async () => {
          if (disposed || token !== generation) return;
          clearTimers(); stopTracks(); recorder = null; $('#recordStop').disabled = true;
          status('正在整理录音…');
          let decoder;
          try {
            decoder = new (root.AudioContext || root.webkitAudioContext)();
            const audio = await decoder.decodeAudioData(await new Blob(chunks, {type:active.mimeType}).arrayBuffer());
            const offline = new OfflineAudioContext(1, Math.ceil(audio.duration * 24000), 24000);
            const source = offline.createBufferSource(); source.buffer = audio; source.connect(offline.destination); source.start();
            const converted = await offline.startRendering();
            if (disposed || token !== generation) return;
            const samples = converted.getChannelData(0);
            duration = validateRecording(samples, 24000);
            file = new File([encodeWav(samples)], 'microphone-reference.wav', {type:'audio/wav'});
            url = URL.createObjectURL(file); $('#recordPreview').src = url; $('#recordPreview').hidden = false;
            $('#recordStart').textContent = '重新录制';
            status(`已录制 ${duration.toFixed(1)} 秒。请回听确认完整读完上方文案；读错或未读完可重新录制。`);
          } catch (error) { if (token === generation) { file = null; status(error.message || '录音处理失败，请重新录制。'); } }
          finally { if (decoder) await decoder.close(); if (token === generation) busy(false); }
        };
        stream.getAudioTracks().forEach(track => track.addEventListener('ended', () => {
          if (token === generation && active.state === 'recording') active.stop();
        }));
        active.start(200);
        const started = performance.now();
        $('#recordTimer').textContent = '0.0 / 10 秒';
        timer = setInterval(() => { $('#recordTimer').textContent = `${Math.min(10,(performance.now()-started)/1000).toFixed(1)} / 10 秒`; }, 100);
        deadline = setTimeout(() => { if (active.state === 'recording') active.stop(); }, 9800);
        $('#recordStop').disabled = false;
        status('正在录音，请朗读上方文字；读完后点击结束录音，最长 10 秒。');
      } catch (error) {
        if (disposed || token !== generation) return;
        stopTracks(); busy(false);
        status(({NotAllowedError:'未获得麦克风权限，请在浏览器地址栏允许麦克风后重试，也可以上传录音。', NotFoundError:'未找到麦克风，请连接设备后重试。', NotReadableError:'麦克风被占用或无法读取，请关闭占用它的应用后重试。'})[error.name] || '无法启动录音，请检查麦克风后重试。');
      }
    }
    $('#captureUploadTab').onclick = () => selectMode('upload');
    $('#captureRecordTab').onclick = () => selectMode('record');
    $('#recordStart').onclick = start;
    $('#recordStop').onclick = () => { if (recorder?.state === 'recording') recorder.stop(); };
    return {
      sample() {
        if (mode === 'record') return {file, prompt:SCRIPT, auxiliary:[], duration, mode};
        return {file:$('#voiceFile').files[0], prompt:$('#voicePrompt').value.trim(), auxiliary:[...$('#voiceAuxFiles').files], duration:Number($('#voiceFile').dataset.duration || 0), mode};
      },
      dispose() { cancel(); discard(); disposed = true; },
    };
  }
  const api = {SCRIPT, markup, mount, encodeWav, validateRecording};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.VoiceRecorder = api;
})(typeof window !== 'undefined' ? window : globalThis);
