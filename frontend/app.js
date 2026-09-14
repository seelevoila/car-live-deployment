let voiceRecorder = null;
const API = 'http://127.0.0.1:8000/api';
const app = document.querySelector('#app');
let session = null;
let sessionRequest = null;
let currentView = '';
let playPending = 0;
let revisionPending = false;
let questionRequest = null;

// Track active view loading to prevent race conditions
let activeViewLoading = null;

// Cache API responses to avoid repeated requests
const apiCache = {
  data: new Map(),
  timestamps: new Map(),
  ttl: 30000, // 30 seconds cache

  get(key) {
    const timestamp = this.timestamps.get(key);
    if (timestamp && Date.now() - timestamp < this.ttl) {
      return this.data.get(key);
    }
    return null;
  },

  set(key, value) {
    this.data.set(key, value);
    this.timestamps.set(key, Date.now());
  },

  invalidate(key) {
    this.data.delete(key);
    this.timestamps.delete(key);
  }
};

async function cachedApi(endpoint, options = {}) {
  const cacheKey = endpoint + JSON.stringify(options);
  const cached = apiCache.get(cacheKey);
  if (cached && (!options.method || options.method === 'GET')) {
    return cached;
  }
  const result = await api(endpoint, options);
  if (!options.method || options.method === 'GET') {
    apiCache.set(cacheKey, result);
  }
  return result;
}

// Global error handler to catch and log null errors
window.addEventListener('error', (event) => {
  if (event.message.includes('Cannot set properties of null')) {
    console.error('❌ Null DOM Error:', {
      message: event.message,
      filename: event.filename,
      lineno: event.lineno,
      colno: event.colno,
      stack: event.error?.stack
    });
  }
});

// Prefer the cloned path while the studio is loading. A temporary backend or
// model warmup failure must not silently replace a selected clone with the
// browser's mechanical voice.
let ttsMode = 'gpt-sovits';
let ttsStatus = null;
let ttsCheckedAt = 0;
let audioCtx = null;
let gainNode = null;
let activeSource = null;
let liveRun = null;
let currentAnswer = '';
let serviceOnline = null;
let healthTimer = null;
let healthReloadInFlight = false;
let live2dApp = null;
let live2dModel = null;
let live2dResizeObserver = null;
const lipSync = new SpeechLipSync.Timeline();
const avatarPerformer = new AvatarPerformer.Performer();
let audioIntent = 0;
let audioRequestedAt = 0;

function serverTtsLabel() {
  if (ttsStatus?.provider_label) return ttsStatus.provider_label;
  if (ttsStatus?.provider === 'idextts2') {
    return ttsStatus?.model_version ? `IndexTTS-${ttsStatus.model_version}` : 'IndexTTS';
  }
  return 'GPT-SoVITS';
}

const api = async (path, options = {}) => {
  let response;
  try {
    response = await fetch(API + path, options);
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('无法连接后端服务，请确认项目已启动');
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      try { detail += ` ${(await response.text()).slice(0, 200)}`; } catch {}
    }
    throw new Error(detail);
  }
  if (options.method && options.method !== 'GET' && /^\/(documents|knowledge|voices)(\/|$)/.test(path)) {
    apiCache.data.clear();
    apiCache.timestamps.clear();
  }
  const type = response.headers.get('content-type') || '';
  return type.includes('application/json') ? response.json() : response;
};

function showViewError(error) {
  const message = error?.message || '页面加载失败';
  if (!app) {
    console.error('❌ showViewError: app element not found');
    return;
  }
  try {
    app.innerHTML = `<section class="panel"><div class="panel-body"><div class="notice error">${esc(message)}</div><button class="btn" id="retryView">重试</button></div></section>`;
    const retryBtn = $('#retryView');
    if (retryBtn) {
      retryBtn.addEventListener('click', () => {
        const active = document.querySelector('nav button.active') || document.querySelector('nav button');
        const view = active?.dataset.view || 'knowledge';
        void renderView(view);
      });
    }
  } catch (err) {
    console.error('❌ showViewError failed:', err);
  }
}

function setServiceStatus(online) {
  const node = document.querySelector('#status');
  if (!node) return;
  node.classList.toggle('offline', !online);
  node.textContent = online ? '服务正常' : '服务离线 · 自动重试';
}

async function loadActiveView() {
  if (healthReloadInFlight) return;
  const active = document.querySelector('nav button.active') || document.querySelector('nav button');
  const view = active?.dataset.view || 'knowledge';
  healthReloadInFlight = true;
  try { await renderView(view); }
  finally { healthReloadInFlight = false; }
}

let healthChecking = false;
async function pollHealth() {
  if (healthChecking) return;
  healthChecking = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 3000);
  try {
    // Use fetch directly to avoid any caching issues during health check
    const response = await fetch(API + '/health', {signal: controller.signal});
    if (!response.ok) throw new Error('Health check failed');

    const recovered = serviceOnline === false;
    serviceOnline = true;
    setServiceStatus(true);
    // A first load can happen before the backend has finished starting. Once
    // it recovers, replace the error view automatically without a manual click.
    if (recovered && app && app.isConnected && app.querySelector('#retryView')) {
      await loadActiveView();
    }
  } catch (error) {
    serviceOnline = false;
    setServiceStatus(false);
  } finally {
    clearTimeout(timeout);
    healthChecking = false;
  }
}

function startHealthMonitor() {
  if (healthTimer) return;
  pollHealth();
  healthTimer = setInterval(pollHealth, 5000);
}

const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// Safe DOM access helpers to prevent null errors
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => document.querySelectorAll(selector);
const safeSet = (selector, prop, value) => {
  const el = $(selector);
  if (el) el[prop] = value;
  return !!el;
};
const safeClick = (selector, handler) => {
  const el = $(selector);
  if (el) el.onclick = handler;
};
const safeForEach = (selector, callback) => {
  $$(selector).forEach(callback);
};

// Live mode 2 emits the first progressive fragment sooner than mode 1. Keep
// each request short enough that the model can produce that fragment within
// the competition's three-second first-audio target.
const SPEECH_MAX_CHARS = 24;
const SPEECH_SHORT_CLAUSE_CHARS = 10;
// Keep a short salutation attached to enough phonetic context, while keeping
// the merged request within a phrase that still reaches the 3-second target.
const SPEECH_CLAUSE_MERGED_MAX = 24;
const SPEECH_MIN_TAIL_CHARS = 8;
const sentenceList = text => {
  const raw = text.match(/[^。！？；.!?]+[。！？；.!?]?/g)?.map(x => x.trim()).filter(Boolean) || [];
  if (!raw.length && text.trim()) return [text.trim()];
  // Use natural sentence boundaries first. Long sentences are split into
  // speech-sized phrases, rather than tiny 8-12 character requests that make
  // GPT-SoVITS sound clipped and mechanical.
  const units = [];
  for (const sentence of raw) {
    const clauses = sentence.match(/[^，,、：:]+[，,、：:]?/g)?.map(x => x.trim()).filter(Boolean) || [sentence];
    // A tiny salutation such as “老板，” is a poor standalone cloning prompt.
    // Keep it with the following clause so the first request has enough
    // phonetic context and does not begin with a clipped consonant.
    const pauseClauses = [];
    for (let index = 0; index < clauses.length; index += 1) {
      let combined = clauses[index];
      let relaxed = false;
      const next = clauses[index + 1];
      // Merge punctuation-aligned clauses whenever they fit. The previous
      // two-sided >=10 rule could never satisfy its 16-character total cap.
      const canMerge = next && combined.length + next.length <= SPEECH_CLAUSE_MERGED_MAX;
      if (canMerge) {
        combined += next;
        relaxed = true;
        index += 1;
        while (index + 1 < clauses.length && combined.length + clauses[index + 1].length <= SPEECH_CLAUSE_MERGED_MAX) {
          combined += clauses[index + 1];
          index += 1;
        }
      } else if (next && combined.length < SPEECH_SHORT_CLAUSE_CHARS) {
        // Attach a bounded phonetic context to a short salutation. Sending
        // "老板" alone clips the initial consonant; sending the whole next
        // clause delays the first playable PCM fragment.
        const room = SPEECH_CLAUSE_MERGED_MAX - combined.length - 1; // reserve comma
        const prefixEnd = safeSpeechCut(next, Math.max(1, room));
        const prefix = next.slice(0, prefixEnd).replace(/[，,、：:]$/, '');
        if (prefix) {
          combined += prefix + '，';
          clauses[index + 1] = next.slice(prefixEnd).trim();
          relaxed = true;
        }
      }
      pauseClauses.push({text: combined, relaxed});
    }
    const sentenceUnits = [];
    let current = '';
    for (const clauseInfo of pauseClauses) {
      let clause = clauseInfo.text;
      const clauseLimit = clauseInfo.relaxed ? SPEECH_CLAUSE_MERGED_MAX : SPEECH_MAX_CHARS;
      while (clause.length > clauseLimit) {
        if (current) { sentenceUnits.push(current); current = ''; }
        const cut = safeSpeechCut(clause, SPEECH_MAX_CHARS);
        if (clause.length - cut < SPEECH_MIN_TAIL_CHARS) {
          current = clause;
          clause = '';
          break;
        }
        sentenceUnits.push(clause.slice(0, cut).replace(/[，,、：:]$/, '') + '，');
        clause = clause.slice(cut).trim();
      }
      if (current && current.length + clause.length > 30) {
        sentenceUnits.push(current);
        current = '';
      }
      current += clause;
    }
    if (current) sentenceUnits.push(current);
    // A full stop is an explicit host-facing safety boundary. Never combine two
    // visible sentences, even if either is short: dynamic revisions must be able
    // to replace sentence 2 without disturbing sentence 1.
    units.push(...sentenceUnits);
  }
  return units;
};
const setState = (text, unit = '') => {
  try {
    const node = document.querySelector('#playstate');
    if (node && node.isConnected) node.textContent = text;
    const detail = document.querySelector('#playunit');
    if (detail && detail.isConnected) detail.textContent = unit ? `当前短语：${unit}` : '';
    updatePlaybackControls();
  } catch (err) {
    console.warn('⚠️ setState failed:', err.message);
  }
};

function renderScriptUnits() {
  try {
    const node = document.querySelector('#scriptUnits');
    const script = document.querySelector('#script');
    if (!node || !script || !node.isConnected || !script.isConnected) return;
    const units = sentenceList(normalizeSpeechText(script.value));
    node.innerHTML = units.length
      ? `播报切分：${units.map((unit, index) => `<span>${index + 1}. ${esc(unit)}</span>`).join('')}`
      : '播报切分：暂无内容';
    saveStudioDraft();
    updatePlaybackControls();
  } catch (err) {
    console.warn('⚠️ renderScriptUnits failed:', err.message);
  }
}

const CN_DIGITS = ['零','一','二','三','四','五','六','七','八','九'];
const TTS_ATOMIC_TOKEN = /(?:百分之[零一二三四五六七八九十百千万亿兆点\d.]+|\d+(?:\.\d+)?\s*(?:km\/h|kWh|N·m|km|kW|Nm|公里|毫米|小时|秒|%|L|万元|万|元|年|款|版|型号|EV)?|[零一二三四五六七八九十百千万亿兆点]+(?:公里每小时|千瓦时|牛米|公里|毫米|小时|秒|百分之|升|万元|元|年|款|版|型号|EV)?)/gi;
function safeSpeechCut(text, limit) {
  if (text.length <= limit) return text.length;
  let end = Math.max(1, limit);
  TTS_ATOMIC_TOKEN.lastIndex = 0;
  for (const match of text.matchAll(TTS_ATOMIC_TOKEN)) {
    const start = match.index ?? 0;
    if (start < end && end < start + match[0].length) {
      end = start === 0 ? start + match[0].length : start;
      break;
    }
  }
  return Math.max(1, end);
}
function sectionToChinese(section) {
  if (!section) return '';
  const units = ['','十','百','千'];
  const digits = String(section).split('').map(Number);
  let out = '';
  let pendingZero = false;
  for (let index = 0; index < digits.length; index++) {
    const digit = digits[index];
    const unit = units[digits.length - index - 1];
    if (!digit) {
      if (out) pendingZero = true;
      continue;
    }
    if (pendingZero) { out += '零'; pendingZero = false; }
    out += CN_DIGITS[digit] + unit;
  }
  return out.replace(/^一十/, '十');
}

function numberToChinese(value) {
  const text = String(value);
  if (!/^\d+(?:\.\d+)?$/.test(text)) return text;
  const [intPart, fracPart] = text.split('.');
  const num = parseInt(intPart, 10);
  if (!Number.isFinite(num)) return text;
  if (num === 0) return fracPart ? '零点' + fracPart.split('').map(d => CN_DIGITS[Number(d)]).join('') : '零';
  const sectionUnits = ['', '万', '亿'];
  let n = num;
  const sections = [];
  while (n > 0) { sections.unshift(n % 10000); n = Math.floor(n / 10000); }
  let out = '';
  for (let i = 0; i < sections.length; i++) {
    const sec = sections[i];
    const secText = sectionToChinese(sec);
    if (!secText) {
      if (out && !out.endsWith('零')) out += '零';
      continue;
    }
    out += secText + sectionUnits[sections.length - 1 - i];
    if (i < sections.length - 1 && sections[i + 1] < 1000 && sections[i + 1] > 0) out += '零';
  }
  out = out.replace(/零+/g, '零').replace(/零$/,'');
  if (fracPart) out += '点' + fracPart.split('').map(d => CN_DIGITS[Number(d)]).join('');
  return out;
}

function normalizeSpeechText(input) {
  let text = String(input || '');
  // Keep citations in the editable source and evidence UI, not in the queue.
  text = text.replace(/\[\s*\d+(?:\s*[,，、\-–—]\s*\d+)*\s*\]|【\s*\d+(?:\s*[,，、\-–—]\s*\d+)*\s*】|［\s*\d+(?:\s*[,，、\-–—]\s*\d+)*\s*］/g, '');
  text = text.replace(/^根据当前车型资料[:：]\s*/g, '');
  text = text.replace(/^根据资料[:：]\s*/g, '');
  text = text.replace(/^回答[:：]\s*/g, '');
  text = text.replace(/(\d+(?:\.\d+)?)[ \t]*[%％]/g, (_match, number) => '百分之' + numberToChinese(number));
  // Normalize quantities before sentence splitting so a token such as
  // `580km` remains one speech unit and is read as“五百八十公里”.
  text = text.replace(/(?<!\d)(19\d{2}|20\d{2})(?=\s*(?:年|款|版|型号))/g, match => match.split('').map(d => CN_DIGITS[Number(d)]).join(''));
  const speechUnits = { 'km/h':'公里每小时', 'kWh':'千瓦时', 'N·m':'牛米', km:'公里', kW:'千瓦', Nm:'牛米', L:'升', 万元:'万元', 万:'万元', 元:'元', 公里:'公里', 毫米:'毫米', 小时:'小时', 秒:'秒' };
  const speechUnitPattern = 'km/h|kWh|N·m|公里|毫米|小时|秒|km|kW|Nm|L|万元|万|元';
  text = text.replace(new RegExp(`(?<![\\d点])(\\d+(?:\\.\\d+)?)[ \\t]*(${speechUnitPattern})?`, 'gi'), (_match, number, unit = '') => numberToChinese(number) + (speechUnits[unit] || unit));
  text = text.replace(/[:：]/g, '，');
  // Remove layout spaces before queue splitting. GPT-SoVITS otherwise treats
  // spaces around model names and quantities as extra pronunciation pauses.
  text = text.replace(/\s+/g, '').trim();
  text = text.replace(/，+/g, '，').replace(/。+/g, '。');
  return text;
}

function layout(title, desc, body, { eyebrow = '直播工作台', tag = '' } = {}) {
  if (!app || !app.isConnected) {
    console.error('❌ Layout error: app element not found or disconnected');
    return;
  }
  try {
    app.innerHTML = `<section class="heading"><div><p class="eyebrow">${esc(eyebrow)}</p><h1>${esc(title)}</h1><p>${esc(desc)}</p></div>${tag ? `<span class="module-tag">${esc(tag)}</span>` : ''}</section>${body}`;
  } catch (error) {
    console.error('❌ Layout error:', error);
  }
}

// View loaders are resolved at click time so features.js can register its pages
// without depending on script execution order.
function viewLoaders() {
  return { knowledge, studio, voices, avatar, tests, ...window.CarLiveViews };
}

function beginViewLoad(view) {
  if (currentView && currentView !== view) return null;
  return activeViewLoading = Symbol(view);
}

async function renderView(view) {
  const loader = viewLoaders()[view];
  if (typeof loader !== 'function' || currentView !== view) return;
  const task = loader();
  const loadingId = activeViewLoading;
  try { await task; }
  catch (error) {
    if (currentView === view && activeViewLoading === loadingId) showViewError(error);
  }
}

const DRAFT_FIELDS = ['script', 'question', 'vehicle', 'speed', 'volume', 'pitch'];
function saveStudioDraft() {
  if (!document.querySelector('#script')) return;
  const draft = {};
  for (const id of DRAFT_FIELDS) {
    const node = document.querySelector('#' + id);
    if (node) draft[id] = node.value;
  }
  try { sessionStorage.setItem('carLiveStudioDraft', JSON.stringify(draft)); } catch {}
}

function initializeStudioDraft() {
  const units = document.querySelector('#scriptUnits');
  if (units && !units.closest('details')) {
    const details = document.createElement('details');
    details.className = 'script-breakdown';
    const summary = document.createElement('summary');
    summary.textContent = '播报分句';
    details.append(summary);
    units.parentElement.append(details);
    details.append(units);
  }
  let draft = {};
  try { draft = JSON.parse(sessionStorage.getItem('carLiveStudioDraft') || '{}') || {}; } catch {}
  for (const id of DRAFT_FIELDS) {
    const node = document.querySelector('#' + id);
    if (!node) continue;
    if (typeof draft[id] === 'string' && (id !== 'vehicle' || [...node.options].some(option => option.value === draft[id]))) {
      node.value = draft[id];
    }
    node.addEventListener('input', saveStudioDraft);
  }
  document.querySelector('#vehicle')?.addEventListener('change', () => {
    stop();
    session = null;
    sessionRequest = null;
    clearAnswer();
    saveStudioDraft();
  });
  document.querySelector('#question')?.addEventListener('input', clearAnswer);
  const stateNode = document.querySelector('#playstate');
  stateNode?.setAttribute('role', 'status');
  stateNode?.setAttribute('aria-live', 'polite');
  document.querySelector('#script')?.setAttribute('aria-label', '直播脚本');
  document.querySelector('#question')?.setAttribute('aria-label', '观众问题');
  clearAnswer();
  safeSet('#speakAnswer', 'textContent', '播报回答');
  updateOutputs();
  renderScriptUnits();
}

function updatePlaybackControls() {
  const busy = Boolean(playPending);
  const running = Boolean(liveRun && !liveRun.stopped && !liveRun.failed);
  const hasScript = Boolean(document.querySelector('#script')?.value.trim());
  safeSet('#play', 'disabled', busy || !hasScript || (running && !liveRun.paused));
  safeSet('#play', 'textContent', busy ? '准备中…' : running && liveRun.paused ? '继续播报' : '开始播报');
  safeSet('#pause', 'disabled', !running || liveRun.paused);
  safeSet('#stop', 'disabled', !liveRun && !busy);
  safeSet('#stopPreview', 'disabled', !liveRun && !busy);
  safeSet('#revise', 'disabled', busy || Boolean(revisionPending) || !hasScript);
  safeSet('#speakAnswer', 'disabled', !currentAnswer || Boolean(questionRequest) || busy);
  safeSet('#previewVoice', 'disabled', busy);
}

function clearAnswer() {
  questionRequest?.abort();
  questionRequest = null;
  currentAnswer = '';
  safeSet('#answer', 'innerHTML', '');
  safeSet('#ask', 'disabled', false);
  safeSet('#ask', 'textContent', '检索回答');
  updatePlaybackControls();
}

function stopCurrentView() {
  saveStudioDraft();
  activeViewLoading = null;
  clearAnswer();
  voiceRecorder?.dispose(); voiceRecorder = null;
  stop();
  session = null;
  sessionRequest = null;
  revisionPending = false;
  cleanupLive2D();
  document.querySelector('#generateScriptDialog')?.remove();
}

function cleanupLive2D() {
  lipSync.clear();
  live2dResizeObserver?.disconnect();
  live2dResizeObserver = null;
  try { live2dModel?.destroy({children:true, texture:true, baseTexture:true}); } catch {}
  try { live2dApp?.destroy(true, {children:true, texture:true, baseTexture:true}); } catch {}
  live2dModel = null;
  live2dApp = null;
}

function updateLive2DMouth() {
  if (!live2dModel) return;
  lipSync.offsetMs=Number(localStorage.getItem('avatarLipOffset') || 0);
  lipSync.sensitivity=Number(localStorage.getItem('avatarLipStrength') || 1.25);
  const mouth = lipSync.sample(
    SpeechLipSync.outputTime(audioCtx, performance.now()),
    audioCtx?.state === 'running' && !liveRun?.paused,
    gainNode?.gain.value ?? 1,
  );
  // Run after motions/physics and immediately before Cubism updates its
  // mesh. A separate RAF fights Cubism's save/load parameter cycle.
  const core=live2dModel.internalModel.coreModel;
  core.setParameterValueById('ParamMouthOpenY', mouth);
  core.setParameterValueById('ParamMouthForm',mouth>.02 ? lipSync.form : .15);
}

function updateLive2DPerformance() {
  if (!live2dModel) return;
  const core=live2dModel.internalModel.coreModel;
  const mouth=lipSync.level;
  avatarPerformer.update(core,performance.now()/1000,mouth,{style:'warm',enabled:document.querySelector('#avatarMotion')?.checked !== false,paused:Boolean(liveRun?.paused)});
}

async function loadLive2DModel(modelUrl) {
  const stage = document.querySelector('#avatarStage');
  const canvas = document.querySelector('#avatarCanvas');
  const state = document.querySelector('#avatarModelState');
  if (!stage || !canvas) return;
  if (!window.PIXI?.live2d?.Live2DModel || !window.Live2DCubismCore) {
    if (state) state.textContent = 'Live2D 运行库未加载，请检查 frontend/vendor 文件';
    return;
  }
  let pixi;
  try {
    // The UI is served from :5173 while model assets live behind the API on
    // :8000. Keep the model URL absolute so its relative moc/texture paths
    // resolve against the backend asset route as well.
    const resolvedModelUrl = modelUrl.startsWith('/')
      ? API + modelUrl.replace(/^\/api/, '')
      : modelUrl;
    pixi = new PIXI.Application({
      view: canvas,
      resizeTo: stage,
      autoDensity: true,
      resolution: 1,
      backgroundAlpha: 0,
      antialias: true,
    });
    live2dApp = pixi;
    // One 30 FPS ticker owns animation and drawing; no independent mouth RAF.
    pixi.ticker.maxFPS = 30;
    const model = await PIXI.live2d.Live2DModel.from(resolvedModelUrl, {autoInteract:true, autoUpdate:false});
    if (live2dApp !== pixi || !canvas.isConnected) {
      model.destroy({children:true, texture:true, baseTexture:true});
      return;
    }
    live2dModel = model;
    model.internalModel.on('afterMotionUpdate', updateLive2DPerformance);
    model.internalModel.eyeBlink = null;
    model.internalModel.on('beforeModelUpdate', updateLive2DMouth);
    pixi.ticker.add(() => model.update(pixi.ticker.deltaMS), undefined, PIXI.UPDATE_PRIORITY.HIGH);
    model.anchor.set(0.5, 1);
    model.interactive = true;
    const fitModel = () => {
      if (!live2dModel) return;
      const width = Math.max(1, stage.clientWidth);
      const height = Math.max(1, stage.clientHeight);
      const originalWidth = model.internalModel?.originalWidth || model.width;
      const originalHeight = model.internalModel?.originalHeight || model.height;
      const scale = Math.min((width * 0.78) / Math.max(1, originalWidth), (height * 0.96) / Math.max(1, originalHeight));
      model.scale.set(scale);
      model.x = width / 2;
      model.y = height * 0.94;
    };
    pixi.stage.addChild(model);
    fitModel();
    live2dResizeObserver = new ResizeObserver(fitModel);
    live2dResizeObserver.observe(stage);
    try { model.internalModel.motionManager.startRandomMotion('Idle', 0); } catch {}
    if (state) state.textContent = '胡桃已就位 · 可读稿与回答观众问题';
  } catch (error) {
    if (live2dApp !== pixi) return;
    cleanupLive2D();
    if (state) state.textContent = `Live2D 加载失败：${error.message || error}`;
  }
}

async function knowledge() {
  const loadingId = beginViewLoad('knowledge');
  if (!loadingId) return;
  const [docs, dash] = await Promise.all([api('/documents'), api('/dashboard')]);
  if (activeViewLoading !== loadingId) return;
  layout('知识库管理', '批量导入 PDF / Word / TXT 车型资料，自动清洗、分段、向量化入库；检索结果可溯源到文档与版本。', `
    <div class="metrics"><div class="metric"><b>${dash.documents}</b><span>资料文件</span></div><div class="metric"><b>${dash.chunks}</b><span>知识片段</span></div><div class="metric"><b>${dash.versions}</b><span>资料版本</span></div><div class="metric"><b>${dash.vehicles.length}</b><span>车型</span></div></div>
    <section class="panel"><div class="panel-head"><h2>导入资料</h2><span>PDF / Word / TXT</span></div><div class="panel-body upload"><label class="drop">选择资料文件<input id="files" type="file" accept=".pdf,.docx,.txt" multiple hidden></label><div class="fields"><label>品牌<input id="brand" placeholder="欧拉"></label><label>车系<input id="series" placeholder="欧拉5 EV"></label><label>年款<input id="year" placeholder="2026"></label><button class="btn" id="upload">导入并入库</button></div><p class="hint">支持批量上传，自动脱敏手机号、身份证号和邮箱地址</p></div></section>
    <section class="panel"><div class="panel-head"><h2>资料列表</h2><span id="uploadState"></span></div><div class="panel-body"><table class="table"><tr><th>文件名</th><th>车型信息</th><th>片段数</th><th>版本</th><th>操作</th></tr>${docs.map(x => `<tr><td>${esc(x.name)}</td><td>${esc(x.brand)} / ${esc(x.series)} / ${esc(x.year)}</td><td>${x.chunks}</td><td>v${x.version || 1}</td><td><button class="btn secondary versions" data-id="${x.id}">版本</button> <button class="btn secondary replace-trigger" data-id="${x.id}">替换</button> <button class="btn secondary del" data-id="${x.id}" data-name="${esc(x.name)}">删除</button><input class="replace" data-id="${x.id}" data-brand="${esc(x.brand)}" data-series="${esc(x.series)}" data-year="${esc(x.year)}" type="file" accept=".pdf,.docx,.txt" hidden></td></tr>`).join('')}</table></div></section>`, {eyebrow:'核心模块 01', tag:'RAG 知识库管理'});
  safeClick('#upload', uploadBatch);
  safeForEach('.del', button => button.onclick = async () => {
    const fileName = button.dataset.name || '该资料';
    if (confirm(`确定删除"${fileName}"及其所有版本吗？\n\n此操作不可恢复，所有相关知识片段将被永久删除。`)) {
      try {
        button.disabled = true;
        button.textContent = '删除中…';
        await api('/documents/' + button.dataset.id, {method:'DELETE'});
        knowledge();
      } catch (error) {
        alert('删除失败：' + error.message);
        button.disabled = false;
        button.textContent = '删除';
      }
    }
  });
  safeForEach('.replace-trigger', button => button.onclick = () => {
    const input = $(`.replace[data-id="${button.dataset.id}"]`);
    if (input) input.click();
  });
  safeForEach('.replace', input => input.onchange = async () => { if (input.files[0]) await replaceDocument(input); });
  safeForEach('.versions', button => button.onclick = async () => {
    try {
      const rows = await api('/documents/' + button.dataset.id + '/versions');
      const message = rows.length
        ? rows.map(x => `v${x.version} · ${x.name} · ${x.chunks} 片段 · ${new Date(x.created_at).toLocaleString('zh-CN')}`).join('\n')
        : '暂无版本记录';
      alert(message);
    } catch (error) {
      alert('查询版本失败：' + error.message);
    }
  });
}

async function uploadBatch() {
  const filesInput = $('#files');
  if (!filesInput || !filesInput.files || !filesInput.files.length) {
    alert('请先选择一个或多个文件');
    return;
  }

  const brand = safeGetValue('#brand').trim();
  const series = safeGetValue('#series').trim();
  const year = safeGetValue('#year').trim();

  if (!brand || !series || !year) {
    alert('请填写品牌、车系和年款信息');
    return;
  }

  const form = new FormData();
  const fileCount = filesInput.files.length;
  [...filesInput.files].forEach(file => form.append('files', file));
  ['brand','series','year'].forEach(key => {
    const input = $('#' + key);
    form.append(key, input ? input.value.trim() : '');
  });

  const uploadBtn = $('#upload');
  if (uploadBtn) uploadBtn.disabled = true;

  safeSet('#uploadState', 'textContent', `正在上传 ${fileCount} 个文件…`);

  try {
    const result = await api('/documents/batch', {method:'POST', body:form});
    safeSet('#uploadState', 'textContent', `✓ 成功导入 ${result.count} 个文件，共 ${result.total_chunks || 0} 个知识片段`);

    // 清空输入
    if (filesInput) filesInput.value = '';

    // 1秒后刷新列表
    setTimeout(() => {
      knowledge().catch(showViewError);
    }, 1000);
  } catch (error) {
    safeSet('#uploadState', 'textContent', '✗ ' + error.message);
    console.error('❌ Upload failed:', error);
  } finally {
    if (uploadBtn) uploadBtn.disabled = false;
  }
}

async function replaceDocument(input) {
  const file = input.files[0];
  const form = new FormData();
  form.append('file', file);
  form.append('brand', input.dataset.brand || '');
  form.append('series', input.dataset.series || '');
  form.append('year', input.dataset.year || '');
  const state = document.querySelector('#uploadState');
  if (state) state.textContent = `正在替换 ${file.name}…`;
  try {
    const result = await api('/documents/' + input.dataset.id, {method:'PUT', body:form});
    if (state) state.textContent = `已更新为新版本（${result.status}）`;
    await knowledge();
  } catch (error) {
    if (state) state.textContent = error.message;
  } finally {
    input.value = '';
  }
}

function vehicleOptions(vehicles) {
  return vehicles.map(v => `<option value="${esc([v.brand,v.series,v.year].join(' / '))}" data-brand="${esc(v.brand)}" data-series="${esc(v.series)}" data-year="${esc(v.year)}">${esc([v.brand,v.series,v.year].join(' / '))}</option>`).join('');
}

function selectedVoiceIsClone() {
  return document.querySelector('#voice')?.selectedOptions[0]?.dataset.cloned === '1';
}

function selectedVoiceWantsGpt() {
  const option = document.querySelector('#voice')?.selectedOptions[0];
  if (!option) return true;
  // Packaged speakers and uploaded clones use server TTS; browser audio is explicit.
  return option.dataset.provider === 'gpt-sovits' || option.dataset.cloned === '1' || option.value !== 'browser-default';
}

function initializeVoicePicker(voices) {
  const select = document.querySelector('#voice');
  // The 音色克隆 page has no picker of its own; it reuses the stored selection.
  const currentId = () => select ? select.value : storedVoiceId();
  const refresh = () => {
    const voiceId = currentId();
    const voice = voices.find(item => item.id === voiceId);
    const label = document.querySelector('#selectedVoiceName');
    if (label) label.textContent = voice ? `当前：${voice.name}` : '请选择音色';
    document.querySelectorAll('[data-voice-card]').forEach(card => {
      const selected = card.dataset.voiceCard === voiceId;
      card.classList.toggle('selected', selected);
      card.querySelector('.voice-selected-label').hidden = !selected;
      card.querySelector('.voice-use').setAttribute('aria-pressed', String(selected));
    });
    ttsMode = selectedVoiceWantsGpt() ? 'gpt-sovits' : 'browser';
    return voiceId;
  };
  if (select) {
    select.value = VoiceLibrary.preferred(voices, storedVoiceId());
    select.onchange = () => {
      stop();
      session = null;
      sessionRequest = null;
      rememberVoiceId(select.value);
      refresh();
      primeSelectedVoice();
    };
  }
  refresh();
  document.querySelectorAll('.voice-use, .voice-preview').forEach(button => {
    button.onclick = async () => {
      rememberVoiceId(button.dataset.id);
      if (select) {
        select.value = button.dataset.id;
        select.onchange();
      } else {
        stop();
        refresh();
      }
      const voice = voices.find(item => item.id === currentId());
      setState(`已选择${voice?.name || '当前音色'}`);
      if (button.classList.contains('voice-preview')) await previewVoice();
    };
  });
}

async function studio() {
  const loadingId = beginViewLoad('studio');
  if (!loadingId) return;

  // 显示加载状态
  if (app && app.isConnected) {
    app.innerHTML = '<section class="panel"><div class="panel-body"><div class="notice">正在加载直播控制台…</div></div></section>';
  }

  voiceRecorder?.dispose(); voiceRecorder = null;

  try {
    // Use cached API calls
    const [dash, voices, tts] = await Promise.all([
      cachedApi('/dashboard'),
      cachedApi('/voices'),
      api('/tts/status')
    ]);

    // Check if this view is still active
    if (activeViewLoading !== loadingId) {
      console.log('Studio load cancelled - user switched views');
      return;
    }

    ttsStatus = tts;
    ttsMode = tts.provider === 'browser' ? 'browser' : 'gpt-sovits';
    const first = dash.vehicles[0] || {brand:'欧拉',series:'欧拉5 EV',year:'2026'};
    layout('直播控制台', '导入或编写直播话术，边生成边播放；播报中改稿会在下一个自然停顿安全切换。', `
    <section class="panel live-settings-panel"><div class="panel-body fields studio-settings"><label>车型<select id="vehicle">${vehicleOptions(dash.vehicles)}</select></label><label>音色<select id="voice">${VoiceLibrary.options(voices, esc)}</select></label><label>语速 <output id="speedOut">1.00</output><input id="speed" type="range" min="0.7" max="1.4" value="1.00" step="0.01"></label><label>音量 <output id="volumeOut">100%</output><input id="volume" type="range" min="0" max="1" value="1" step="0.05"></label><label>语调 <output id="pitchOut">0</output><input id="pitch" type="range" min="-4" max="4" value="0" step="1"></label><span id="ttsMode">检查语音引擎…</span></div></section>
    <details class="studio-preview"><summary>音色试听<span id="selectedVoiceName"></span></summary><div class="panel-body"><textarea id="voicePreviewText" class="question" aria-label="试听文案">大家好，欢迎来到汽车直播间，今天给大家介绍这款车型。</textarea><div class="controls"><button class="btn" id="previewVoice">试听</button><button class="btn secondary" id="stopPreview">停止</button></div></div></details>
    <div class="studio"><section class="panel"><div class="panel-head"><h2>直播脚本</h2><span id="version"></span></div><div class="panel-body"><div class="inline-tools"><label class="btn secondary file-btn">导入脚本<input id="scriptFile" type="file" accept=".txt,.md" hidden></label><button class="btn secondary" id="generate">生成脚本</button></div><textarea id="script">老板，今天为大家介绍欧拉 5 EV 2026 款 580km 激光雷达版。它的 CLTC 纯电续航为 580 公里，轴距 2720 毫米，最大功率 150 千瓦。</textarea><p id="scriptUnits" class="script-units"></p><div class="controls"><button class="btn" id="play">开始播报</button><button class="btn secondary" id="pause">暂停</button><button class="btn secondary" id="stop">停止</button><button class="btn secondary" id="revise">应用改稿</button></div><p id="playstate">当前句 0 / 0 · 待机</p><p id="playunit" class="hint"></p></div></section>
    <aside class="panel"><div class="panel-head"><h2>观众问答</h2></div><div class="panel-body"><textarea class="question" id="question">欧拉 5 EV 的续航是多少？</textarea><button class="btn" id="ask">检索回答</button><button class="btn secondary" id="speakAnswer">语音播报</button><div id="answer"></div></div></aside></div>`, {eyebrow:'核心模块 02', tag:'流式 TTS 与动态改稿'});

    // Check again before initializing
    if (activeViewLoading !== loadingId) {
      console.log('Studio init cancelled - user switched views');
      return;
    }

    // 使用 requestIdleCallback 延迟非关键初始化
    const initializeUI = () => {
      // Final check before binding events
      if (activeViewLoading !== loadingId) return;

      safeClick('#play', play);
      safeClick('#pause', pause);
      safeClick('#stop', stop);
      safeClick('#revise', revise);
      safeClick('#ask', ask);
      safeClick('#speakAnswer', () => currentAnswer && speakText(currentAnswer));
      const scriptFile = $('#scriptFile');
      if (scriptFile) scriptFile.onchange = readScriptFile;
      const scriptInput = $('#script');
      if (scriptInput) scriptInput.oninput = renderScriptUnits;
      safeClick('#generate', generateScript);
      safeClick('#previewVoice', () => previewVoice());
      safeClick('#stopPreview', () => { stopGpt(); speechSynthesis.cancel(); setState('已停止试听'); });
      ['speed','volume','pitch'].forEach(id => {
        const input = $('#' + id);
        if (input) input.oninput = () => updateOutputs();
      });
      updateOutputs();
      const modeNode = $('#ttsMode');
      if (modeNode) modeNode.textContent = ttsMode === 'gpt-sovits' ? `${tts.provider_label || '服务端 TTS'} · PCM 实时流式播报` : 'Web Speech API（回退模式）';
      initializeVoicePicker(voices);
      if (modeNode) {
        modeNode.textContent = ttsMode === 'gpt-sovits'
          ? (tts?.warming_up ? `${tts.provider_label || '服务端 TTS'} · 正在预热` : `${tts.provider_label || '服务端 TTS'} · PCM 实时流式播报`)
          : 'Web Speech API（回退模式）';
      }
      primeSelectedVoice();
      const vehicleSelect = $('#vehicle');
      if (dash.vehicles.length && vehicleSelect) vehicleSelect.value = [first.brand,first.series,first.year].join(' / ');
      initializeStudioDraft();
    };

    // 优先渲染界面，然后异步初始化
    if (window.requestIdleCallback) {
      requestIdleCallback(initializeUI, { timeout: 50 });
    } else {
      setTimeout(initializeUI, 0);
    }
  } catch (error) {
    if (activeViewLoading === loadingId) {
      showViewError(error);
    }
  }
}

async function voices() {
  const loadingId = beginViewLoad('voices');
  if (!loadingId) return;
  voiceRecorder?.dispose(); voiceRecorder = null;
  const allVoices = await api('/voices');
  if (activeViewLoading !== loadingId) return;
  layout('音色克隆', '内置多套汽车主播音色可一键切换，也可上传或现场录制一段真人样本克隆专属主播。', `
    ${VoiceLibrary.cards(allVoices, esc)}
    <section class="panel"><div class="panel-head"><h2>音色试听</h2><span id="selectedVoiceName"></span></div><div class="panel-body"><textarea id="voicePreviewText" class="question" aria-label="试听文案">大家好，欢迎来到汽车直播间，今天给大家介绍这款车型。</textarea><div class="controls"><button class="btn" id="previewVoice">试听</button><button class="btn secondary" id="stopPreview">停止</button></div><p id="playstate">空闲 · 未播报</p><p id="playunit" class="hint"></p></div></section>
    <section class="panel panel-m3"><div class="panel-head"><h2>快速克隆音色</h2><span>上传或现场录制一段真人样本，检查通过即可用于流式播报</span></div><div class="panel-body clone-grid"><label>名称<input id="voiceName" value="我的主播"></label><label>风格<input id="voiceStyle" placeholder="低沉男声、温柔女声等"></label>${VoiceRecorder.markup()}<div class="clone-actions"><button class="btn secondary" id="analyzeVoice">检查样本</button><button class="btn" id="clone">创建音色</button><progress id="voiceProgress" max="100" value="0" hidden></progress><span id="cloneState"></span></div><div class="voice-list"><h3>已创建音色</h3>${allVoices.filter(v => v.cloned).map(v => { const quality = v.quality?.message || ''; const qualityLabel = v.quality?.status === 'ready' ? ' · 已优化' : v.quality?.status === 'invalid' ? ' · 格式异常' : v.quality?.status === 'needs-review' ? ' · 待优化' : ''; const warmLabel = v.calibrating ? ' · 校准中' : v.calibration_pending ? ' · 待校准' : v.warming ? ' · 预热中' : v.warmed ? ' · 就绪' : ''; const referenceLabel = v.reference_count > 1 ? ` · ${v.reference_count}条参考` : ''; const actionDisabled = v.quality?.status !== 'ready' || v.warming || v.synthesis_check?.status === 'pending' || v.synthesis_check?.status === 'failed' ? ' disabled' : ''; return `<div class="voice-row"><div><span>${esc(v.name)} · ${esc(v.style)}${referenceLabel}${qualityLabel}${warmLabel}</span>${v.cloned ? `${v.quality?.status === 'ready' ? '' : `<small class="hint">${esc(quality)}</small>`}<div class="voice-row-actions"><button class="btn secondary voice-use" data-id="${esc(v.id)}"${actionDisabled}>使用</button><button class="btn secondary voice-preview" data-id="${esc(v.id)}"${actionDisabled}>试听</button><input class="voice-prompt" data-id="${esc(v.id)}" value="${esc(v.prompt_text || '')}" placeholder="参考音频原文"><button class="btn secondary voice-save" data-id="${esc(v.id)}">保存</button></div>` : ''}</div>${v.cloned ? `<button class="btn secondary voice-delete" data-id="${esc(v.id)}">删除</button>` : ''}</div>`; }).join('')}</div></div></section>`, {eyebrow:'核心模块 03', tag:'拟人化语音克隆'});
  voiceRecorder = VoiceRecorder.mount(document.querySelector('#cloneCapture'), {
    beforeRecord: () => { stopLive(); speechSynthesis.cancel(); },
    onBusy: busy => {
      for (const id of ['clone','analyzeVoice']) {
        const btn = document.querySelector('#' + id);
        if (btn) btn.disabled = busy;
      }
    },
  });
  safeClick('#clone', cloneVoice);
  safeClick('#analyzeVoice', analyzeVoiceSample);
  const voiceFile = $('#voiceFile');
  if (voiceFile) voiceFile.onchange = inspectVoiceFile;
  const voiceAuxFiles = $('#voiceAuxFiles');
  if (voiceAuxFiles) voiceAuxFiles.onchange = inspectAuxFiles;
  const voicePrompt = $('#voicePrompt');
  if (voicePrompt) voicePrompt.oninput = updatePromptMeta;
  safeClick('#previewVoice', () => previewVoice());
  safeClick('#stopPreview', () => { stopGpt(); speechSynthesis.cancel(); setState('已停止试听'); });
  document.querySelectorAll('.voice-delete').forEach(button => button.onclick = async () => {
    if (!confirm('确定删除这个克隆音色吗？')) return;
    await api('/voices/' + button.dataset.id, {method:'DELETE'});
    voices();
  });
  document.querySelectorAll('.voice-save').forEach(button => button.onclick = async () => {
    const input = document.querySelector(`.voice-prompt[data-id="${button.dataset.id}"]`);
    button.disabled = true;
    try {
      const result = await api('/voices/' + button.dataset.id, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({prompt_text: input.value.trim()})});
      if (result.warming) {
        button.textContent = '校准中…';
        await waitForVoiceWarmup(button.dataset.id);
        await voices();
      } else {
        button.textContent = '已保存';
        setTimeout(() => { button.textContent = '保存参考文本'; button.disabled = false; }, 1200);
      }
    } catch (error) { button.disabled = false; alert(error.message); }
  });
  document.querySelectorAll('.voice-save').forEach(button => {
    const optimize = document.createElement('button');
    optimize.className = 'btn secondary voice-optimize';
    optimize.textContent = '优化参考音频';
    optimize.dataset.id = button.dataset.id;
    optimize.onclick = async () => {
      optimize.disabled = true;
      optimize.textContent = '处理中…';
      try { await api('/voices/' + optimize.dataset.id + '/optimize', {method:'POST'}); await voices(); }
      catch (error) { optimize.disabled = false; optimize.textContent = '优化失败'; alert(error.message); }
    };
    button.parentElement.appendChild(optimize);
  });
  updatePromptMeta();
  inspectVoiceFile();
  inspectAuxFiles();
  initializeVoicePicker(allVoices);
}

async function avatar() {
  const loadingId = beginViewLoad('avatar');
  if (!loadingId) return;

  // 显示加载状态
  if (app && app.isConnected) {
    app.innerHTML = '<section class="panel"><div class="panel-body"><div class="notice">正在加载数字主播…</div></div></section>';
  }

  try {
    // Use cached API calls
    const [dash, voices, tts, avatarStatus] = await Promise.all([
      cachedApi('/dashboard'),
      cachedApi('/voices'),
      api('/tts/status'),
      cachedApi('/live2d/status'),
    ]);

    // Check if this view is still active
    if (activeViewLoading !== loadingId) {
      console.log('Avatar load cancelled - user switched views');
      return;
    }

    ttsStatus = tts;
    ttsMode = tts.provider === 'browser' ? 'browser' : 'gpt-sovits';
    currentAnswer = '';
    const first = dash.vehicles[0] || {brand:'欧拉',series:'欧拉5 EV',year:'2026'};
    const voiceOptions = VoiceLibrary.options(voices, esc);
    layout('数字主播', 'Live2D 数字人实时播报与智能问答', `
    <div class="avatar-workspace">
      <section class="panel avatar-stage-panel">
        <div class="panel-head"><h2>数字人</h2><span>Live2D · 胡桃</span></div>
        <div class="panel-body avatar-stage-wrap">
          <div id="avatarStage" class="avatar-stage"><canvas id="avatarCanvas"></canvas><div class="avatar-badge">LIVE</div><div id="avatarModelState" class="avatar-model-state">加载中…</div></div>
          <div class="avatar-stage-note"><span class="live-dot"></span><span>实时口型同步</span></div>
        </div>
      </section>
      <section class="avatar-controls">
        <section class="panel"><div class="panel-head"><h2>播报控制</h2><span id="ttsMode">${esc(tts.provider_label || '语音服务')}</span></div><div class="panel-body">
          <div class="fields studio-settings avatar-settings"><label>车型<select id="vehicle">${vehicleOptions(dash.vehicles)}</select></label><label>音色<select id="voice">${voiceOptions}</select></label><label>语速 <output id="speedOut">1.00</output><input id="speed" type="range" min="0.7" max="1.4" value="1.00" step="0.01"></label><label>音量 <output id="volumeOut">100%</output><input id="volume" type="range" min="0" max="1" value="1" step="0.05"></label><label>语调 <output id="pitchOut">0</output><input id="pitch" type="range" min="-4" max="4" value="0" step="1"></label></div>
          <div class="inline-tools"><label class="btn secondary file-btn">导入脚本<input id="scriptFile" type="file" accept=".txt,.md" hidden></label><button class="btn secondary" id="generate">生成脚本</button></div>
          <textarea id="script" class="avatar-script">老板，今天为大家介绍欧拉 5 EV 2026 款 580km 激光雷达版。它的 CLTC 纯电续航为 580 公里，轴距 2720 毫米，最大功率 150 千瓦。</textarea><p id="scriptUnits" class="script-units"></p>
          <div class="controls"><button class="btn" id="play">开始播报</button><button class="btn secondary" id="pause">暂停</button><button class="btn secondary" id="stop">停止</button><button class="btn secondary" id="revise">应用改稿</button></div>
          <p id="playstate">当前句 0 / 0 · 待机</p><p id="playunit" class="hint"></p><p id="version" class="hint"></p>
        </div></section>
        <section class="panel avatar-qa"><div class="panel-head"><h2>观众问答</h2><span>智能问答</span></div><div class="panel-body"><textarea class="question" id="question">欧拉 5 EV 的续航是多少？</textarea><div class="controls"><button class="btn" id="ask">检索</button><button class="btn secondary" id="speakAnswer">播报</button></div><div id="answer"></div></div></section>
      </section>
    </div>`, {eyebrow:'扩展能力', tag:'Live2D 数字主播'});

    // Check again before initializing
    if (activeViewLoading !== loadingId) {
      console.log('Avatar init cancelled - user switched views');
      return;
    }

    // 使用 requestIdleCallback 延迟非关键初始化
    const initializeUI = () => {
      // Final check before binding events
      if (activeViewLoading !== loadingId) return;

      const vehicleSelect = $('#vehicle');
      if (dash.vehicles.length && vehicleSelect) vehicleSelect.value = [first.brand, first.series, first.year].join(' / ');
      initializeVoicePicker(voices);
      safeClick('#play', play);
      safeClick('#pause', pause);
      safeClick('#stop', stop);
      safeClick('#revise', revise);
      safeClick('#ask', ask);
      safeClick('#speakAnswer', () => currentAnswer && speakText(currentAnswer));
      safeClick('#generate', generateScript);
      const scriptFile = $('#scriptFile');
      if (scriptFile) scriptFile.onchange = readScriptFile;
      const scriptInput = $('#script');
      if (scriptInput) scriptInput.oninput = renderScriptUnits;
      ['speed','volume','pitch'].forEach(id => {
        const input = $('#' + id);
        if (input) input.oninput = updateOutputs;
      });
      initializeStudioDraft();
      if (avatarStatus.configured) void loadLive2DModel(avatarStatus.model_url);
      else safeSet('#avatarModelState', 'textContent', '未找到胡桃模型，请检查 LIVE2D_MODEL_ROOT');
    };

    // 优先渲染界面，然后异步初始化
    if (window.requestIdleCallback) {
      requestIdleCallback(initializeUI, { timeout: 50 });
    } else {
      setTimeout(initializeUI, 0);
    }
  } catch (error) {
    if (activeViewLoading === loadingId) {
      showViewError(error);
    }
  }
}

function primeSelectedVoice() {
  const voiceId = document.querySelector('#voice')?.value;
  if (!voiceId || ttsMode !== 'gpt-sovits') return;
  void primeVoice(voiceId);
}

async function primeVoice(voiceId) {
  if (!voiceId || ttsMode !== 'gpt-sovits') return;
  try { await api('/voices/' + encodeURIComponent(voiceId) + '/prime', {method:'POST'}); } catch {}
}

function updateOutputs() {
  const speed = $('#speed');
  const volume = $('#volume');
  const pitch = $('#pitch');
  const temperature = $('#temperature');
  const repetition = $('#repetition');
  if (!speed) return;
  // IndexTTS-2.0 has no duration_factor, so the backend accepts and drops the
  // speed request. Say so instead of letting the slider look functional.
  const speedText = Number(speed.value).toFixed(2);
  safeSet('#speedOut', 'textContent', ttsStatus?.speed_control === false
    ? `${speedText}（当前语音模型不支持）`
    : speedText);
  if (volume) safeSet('#volumeOut', 'textContent', Math.round(Number(volume.value) * 100) + '%');
  if (volume && gainNode && audioCtx) gainNode.gain.setTargetAtTime(Number(volume.value), audioCtx.currentTime, 0.015);
  if (pitch) safeSet('#pitchOut', 'textContent', (Number(pitch.value) > 0 ? '+' : '') + pitch.value);
  if (temperature) safeSet('#temperatureOut', 'textContent', Number(temperature.value).toFixed(2));
  if (repetition) safeSet('#repetitionOut', 'textContent', Number(repetition.value).toFixed(2));
}

async function ensure() {
  if (session) return session;
  if (sessionRequest) return sessionRequest;
  const vehicleSelect = $('#vehicle');
  const scriptInput = $('#script');
  const voiceSelect = $('#voice');
  if (!vehicleSelect || !scriptInput || !voiceSelect) {
    throw new Error('页面未完全加载，请稍后重试');
  }
  const loadingId = activeViewLoading;
  const request = api('/live/sessions', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({vehicle:vehicleSelect.value, script:scriptInput.value, voice_id:voiceSelect.value})});
  sessionRequest = request;
  try {
    const result = await request;
    if (sessionRequest !== request || activeViewLoading !== loadingId) throw new DOMException('会话已取消', 'AbortError');
    session = result;
    return result;
  } finally {
    if (sessionRequest === request) sessionRequest = null;
  }
}

// GPT-SoVITS mode 1 returns stable phrase-sized PCM fragments. The browser
// queues each fragment in one AudioContext without adding synthetic pauses.
const STREAM_LEAD_SECONDS = 0.08;
// One upstream semantic session covers a few visible phrases. This keeps
// first audio responsive while avoiding a model/frontend reset at every comma.
const STREAM_BATCH_UNITS = 5;
// Independently synthesized phrases can start/end at a non-zero waveform
// sample. A short overlap with gain ramps removes the resulting click without
// inserting a silence dip between live units.
const STREAM_BOUNDARY_CROSSFADE_SECONDS = 0.012;

function stopSource() { if (activeSource) { try { activeSource.stop(); } catch {} activeSource = null; } }

function stopSources(run) {
  run?.sources?.forEach(source => { try { source.stop(); } catch {} });
  if (run?.sources) run.sources.clear();
  stopSource();
}

function stopLive({suspend = false} = {}) {
  lipSync.clear();
  const run = liveRun;
  window.CarLiveFeatures?.flushPlayback();
  if (run) {
    run.stopped = true;
    run.abortController?.abort();
    run.resumeWaiter?.();
    if (run.mode === 'browser') speechSynthesis.cancel();
    stopSources(run);
    if (liveRun === run) liveRun = null;
  }
  if (suspend && audioCtx?.state === 'running') audioCtx.suspend();
}

function stopGpt() { stop(); }

async function ensureAudio() {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass) throw new Error('浏览器不支持 Web Audio');
  audioCtx = audioCtx || new AudioContextClass();
  gainNode = gainNode || audioCtx.createGain();
  if (!gainNode.__liveConnected) { gainNode.connect(audioCtx.destination); gainNode.__liveConnected = true; }
  if (audioCtx.state !== 'running') await audioCtx.resume();
  if (audioCtx.state !== 'running') throw new Error('浏览器音频输出被挂起，请点击页面后重试');
}

function saveLiveState(status, sentence) {
  if (!session) return;
  api('/live/sessions/' + session.id + '/state', {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({status, sentence})}).catch(() => {});
}

function createLiveRun(mode, q, startIndex = 0) {
  return {
    requestedAt:performance.now(),
    mode, q, nextIndex:startIndex, currentIndex:startIndex, stopped:false, paused:false,
    failed:false,
    inFlight:0, abortController:null, resumeWaiter:null, sources:new Set(),
    headerBytes:new Uint8Array(), pcm:new Uint8Array(), format:null, scheduledUntil:0,
    hasScheduledAudio:false, lastScheduledSource:null,
    currentBatchStart:startIndex, currentBatchEnd:startIndex,
    revision:0, pendingRestartAt:null,
  };
}

function sharedPrefixLength(before, after) {
  let index = 0;
  while (index < before.length && index < after.length && before[index] === after[index]) index += 1;
  return index;
}

function finishRunIfDrained(run) {
  if (run.stopped || run.failed || liveRun !== run || run.inFlight || run.pendingRestartAt !== null || run.sources.size || run.nextIndex < run.q.length) return;
  saveLiveState('completed', run.q.length);
  window.CarLiveFeatures?.flushPlayback();
  liveRun = null;
  setState(`播报完成 · 共 ${run.q.length} 句`);
}

function appendBytes(left, right) {
  if (!left.length) return new Uint8Array(right);
  const merged = new Uint8Array(left.length + right.length);
  merged.set(left); merged.set(right, left.length);
  return merged;
}

function readFourCC(bytes, offset) {
  return String.fromCharCode(bytes[offset], bytes[offset + 1], bytes[offset + 2], bytes[offset + 3]);
}

function parseWavHeader(bytes) {
  if (bytes.length < 12) return null;
  if (readFourCC(bytes, 0) !== 'RIFF' || readFourCC(bytes, 8) !== 'WAVE') throw new Error('流式接口未返回 PCM WAV 音频');
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let offset = 12;
  let format = null;
  while (offset + 8 <= bytes.length) {
    const name = readFourCC(bytes, offset);
    const size = view.getUint32(offset + 4, true);
    const body = offset + 8;
    if (body + size > bytes.length) return null;
    if (name === 'fmt ') {
      if (size < 16) throw new Error('WAV 音频格式无效');
      format = {
        audioFormat:view.getUint16(body, true), channels:view.getUint16(body + 2, true),
        sampleRate:view.getUint32(body + 4, true), bitsPerSample:view.getUint16(body + 14, true),
      };
    }
    if (name === 'data') return format ? {...format, dataOffset:body} : null;
    offset = body + size + (size % 2);
  }
  return null;
}

function schedulePcm(run, bytes, unitIndex, unitEnd = unitIndex + 1) {
  const {audioFormat, channels, sampleRate, bitsPerSample} = run.format;
  if (audioFormat !== 1 || bitsPerSample !== 16 || !channels || !sampleRate) throw new Error('目前仅支持 16-bit PCM WAV 流');
  const bytesPerFrame = channels * 2;
  run.pcm = appendBytes(run.pcm, bytes);
  const scheduleAvailable = flush => {
    const available=wholeFramesForQueue(run,bytesPerFrame);
    const minimum=Math.ceil(sampleRate*(run.hasScheduledAudio ? .12 : .24));
    if (!flush && available < minimum) return;
    while (wholeFramesForQueue(run, bytesPerFrame) > 0) {
      const available=wholeFramesForQueue(run,bytesPerFrame);
      if(!flush && available < Math.ceil(sampleRate*.12)) break;
      const frames = Math.min(available,Math.ceil(sampleRate*.36));
      const consume = frames * bytesPerFrame;
      const view = new DataView(run.pcm.buffer, run.pcm.byteOffset, consume);
      const buffer = audioCtx.createBuffer(channels, frames, sampleRate);
      for (let channel = 0; channel < channels; channel += 1) {
        const samples = buffer.getChannelData(channel);
        for (let frame = 0; frame < frames; frame += 1) samples[frame] = view.getInt16((frame * channels + channel) * 2, true) / 32768;
      }
      run.pcm = run.pcm.slice(consume);
      const source = audioCtx.createBufferSource();
      source.buffer = buffer;
      source.liveIndex = unitIndex;
      source.liveEndIndex = Math.max(unitIndex, unitEnd - 1);
      const previous = run.lastScheduledSource;
      // Only crossfade independent phrase requests; touching buffers within a
      // phrase would repeatedly dip the volume and sound like artificial pauses.
      const unitBoundary = previous?.buffer
        && previous.liveIndex !== unitIndex
        && run.sources.has(previous);
      const playbackRate = Math.pow(2, Number(document.querySelector('#pitch')?.value || 0) / 12);
      source.playbackRate.value = playbackRate;
      gainNode.gain.value = Number(document.querySelector('#volume')?.value || 1);
      const overlap = unitBoundary ? STREAM_BOUNDARY_CROSSFADE_SECONDS : 0;
      const when = Math.max(audioCtx.currentTime + STREAM_LEAD_SECONDS, run.scheduledUntil - overlap);
      const sourceGain = audioCtx.createGain();
      // The source must feed the per-buffer gain node before it reaches the
      // shared output. Without this connection the stream reports playback
      // normally but produces silence; the preview path does not have this
      // intermediate node and therefore hid the bug.
      source.connect(sourceGain);
      sourceGain.connect(gainNode);
      source.__liveGain = sourceGain;
      if (unitBoundary && previous.__liveGain && when < previous.liveEnd) {
        const fadeEnd = Math.min(previous.liveEnd, when + overlap);
        previous.__liveGain.gain.cancelScheduledValues(when);
        previous.__liveGain.gain.setValueAtTime(1, when);
        previous.__liveGain.gain.linearRampToValueAtTime(0, fadeEnd);
        sourceGain.gain.setValueAtTime(0, when);
        sourceGain.gain.linearRampToValueAtTime(1, fadeEnd);
      } else {
        sourceGain.gain.setValueAtTime(1, when);
      }
      run.scheduledUntil = when + buffer.duration / Math.max(0.01, playbackRate);
      source.liveStart = when;
      source.liveEnd = run.scheduledUntil;
      if (document.querySelector('#avatarCanvas')) lipSync.schedule(source, buffer, when, playbackRate);
      run.sources.add(source); activeSource = source;
      run.hasScheduledAudio = true;
      run.lastScheduledSource = source;
      source.onended = () => { run.sources.delete(source); sourceGain.disconnect(); if (activeSource === source) activeSource = null; finishRunIfDrained(run); };
      source.start(when);
      window.CarLiveFeatures?.audioScheduled(run,source,when);
    }
  };
  scheduleAvailable(false);
  return flush => scheduleAvailable(Boolean(flush));
}

function wholeFramesForQueue(run, bytesPerFrame) {
  return Math.floor(run.pcm.length / bytesPerFrame);
}

function consumeStreamBytes(run, bytes, unitIndex, unitEnd = unitIndex + 1) {
  if (!run.format) {
    run.headerBytes = appendBytes(run.headerBytes, bytes);
    const format = parseWavHeader(run.headerBytes);
    if (!format) return null;
    run.format = format;
    const audioBytes = run.headerBytes.slice(format.dataOffset);
    run.headerBytes = new Uint8Array();
    return schedulePcm(run, audioBytes, unitIndex, unitEnd);
  }
  return schedulePcm(run, bytes, unitIndex, unitEnd);
}

function safePlaybackIndex(run) {
  const now = audioCtx?.currentTime || 0;
  const audible = [...run.sources]
    .filter(source => source.liveStart <= now + 0.01 && source.liveEnd > now + 0.01)
    .map(source => source.liveEndIndex ?? source.liveIndex);
  if (audible.length) return Math.max(...audible);
  const queued = [...run.sources]
    .filter(source => source.liveEnd > now + 0.01)
    .map(source => source.liveIndex);
  // A scheduled-but-not-audible source is still replaceable. Return the
  // boundary immediately before it so revise() regenerates that first source
  // instead of skipping it with `safeIndex + 1`.
  if (queued.length) return Math.min(...queued) - 1;
  // If a new batch is still being generated and no buffer has reached the
  // device, the completed batch immediately before it is the safe boundary.
  return Math.max(0, run.inFlight ? run.currentBatchStart - 1 : run.currentIndex);
}

function discardUnplayedSources(run, fromIndex) {
  const now = audioCtx?.currentTime || 0;
  for (const source of [...run.sources]) {
    if ((source.liveEndIndex ?? source.liveIndex) >= fromIndex && source.liveStart > now + 0.02) {
      lipSync.cancel(source);
      window.CarLiveFeatures?.cancelAudio(source);
      try { source.stop(); } catch {}
      run.sources.delete(source);
    }
  }
  run.scheduledUntil = Math.max(
    now + STREAM_LEAD_SECONDS,
    ...[...run.sources].map(source => source.liveEnd || 0),
  );
}

function waitWhilePaused(run) {
  if (!run.paused) return Promise.resolve();
  return new Promise(resolve => { run.resumeWaiter = resolve; });
}

async function streamGptUnit(run) {
  if (run.stopped || liveRun !== run || run.paused || run.inFlight) return;
  if (run.nextIndex >= run.q.length) { finishRunIfDrained(run); return; }
  const index = run.nextIndex;
  const batchEnd = Math.min(run.q.length, index + STREAM_BATCH_UNITS);
  const batchText = run.q.slice(index, batchEnd).join('');
  run.nextIndex = batchEnd;
  run.currentBatchStart = index;
  run.currentBatchEnd = batchEnd;
  const revision = run.revision;
  run.currentIndex = index;
  run.inFlight += 1;
  run.headerBytes = new Uint8Array(); run.pcm = new Uint8Array(); run.format = null;
  const controller = new AbortController();
  run.abortController = controller;
  setState(`${serverTtsLabel()} 流式生成 · 第 ${index + 1}-${batchEnd} / ${run.q.length} 句`, run.q[index]);
  saveLiveState('generating', index);
  try {
    const response = await fetch(API + '/tts/stream', {method:'POST', headers:{'Content-Type':'application/json'}, body:ttsBody(batchText, true, true), signal:controller.signal});
    if (!response.ok) throw new Error(`TTS HTTP ${response.status} ${(await response.text()).slice(0, 120)}`);
    if (!response.body) throw new Error('浏览器不支持可读音频流');
    const reader = response.body.getReader();
    let flush = null; let playbackStarted = false;
    while (true) {
      await waitWhilePaused(run);
      if (run.stopped || liveRun !== run) { try { await reader.cancel(); } catch {} return; }
      if (revision !== run.revision) { try { await reader.cancel(); } catch {} break; }
      const {done, value} = await reader.read();
      if (run.stopped || liveRun !== run) { try { await reader.cancel(); } catch {} return; }
      if (done) break;
      if (revision !== run.revision) { try { await reader.cancel(); } catch {} break; }
      flush = consumeStreamBytes(run, value, index, batchEnd);
      if (!playbackStarted && run.sources.size) {
        playbackStarted = true;
        setState(`${serverTtsLabel()} 流式播放 · 第 ${index + 1}-${batchEnd} / ${run.q.length} 句`, run.q[index]);
        saveLiveState('playing', index);
      }
    }
    // A revision or stop can cancel a request after its last chunk arrived.
    // Never flush that stale PCM into the scheduler after the safe-cut check.
    if (revision === run.revision && !run.stopped && liveRun === run) flush?.(true);
    if (!playbackStarted && run.sources.size) {
      setState(`${serverTtsLabel()} 流式播放 · 第 ${index + 1}-${batchEnd} / ${run.q.length} 句`, run.q[index]);
      saveLiveState('playing', index);
    }
    if (!playbackStarted && !run.sources.size) throw new Error('TTS 未返回可播放音频');
  } catch (error) {
    if (!run.stopped && error.name !== 'AbortError') {
      run.failed = true;
      run.nextIndex = Math.min(run.nextIndex, run.q.length);
      run.pendingRestartAt = null;
      console.error(error);
      setState(`${serverTtsLabel()} 流式请求失败：` + error.message);
    }
  } finally {
    run.inFlight -= 1;
    if (run.abortController === controller) run.abortController = null;
  }
  if (revision !== run.revision) {
    if (!run.stopped && liveRun === run && !run.paused && run.pendingRestartAt !== null) {
      run.pendingRestartAt = null;
      void streamGptUnit(run);
    }
    return;
  }
  if (run.stopped || run.failed || liveRun !== run || run.paused) return;
  // Start requesting the next sentence as soon as this sentence has finished
  // generating. Its PCM is scheduled after the buffered audio, avoiding a
  // sentence-to-sentence gap without generating the entire script first.
  if (run.nextIndex < run.q.length) void streamGptUnit(run);
  else finishRunIfDrained(run);
}

async function startGptRun(q, startIndex = 0) {
  stopLive();
  const run = createLiveRun('gpt-sovits', q, startIndex);
  run.requestedAt=audioRequestedAt || performance.now();
  liveRun = run;
  try { await ensureAudio(); } catch (error) { liveRun = null; setState('浏览器不支持音频播放：' + error.message); return; }
  if (!run.stopped) void streamGptUnit(run);
}

function speakBrowserUnit(run) {
  if (run.stopped || liveRun !== run || run.paused) return;
  if (run.nextIndex >= run.q.length) { finishRunIfDrained(run); return; }
  const index = run.nextIndex++;
  run.currentIndex = index;
  const utterance = new SpeechSynthesisUtterance(run.q[index]);
  utterance.lang = 'zh-CN'; utterance.rate = Number(document.querySelector('#speed')?.value || 1); utterance.volume = Number(document.querySelector('#volume')?.value || 1);
  utterance.pitch = Math.pow(2, Number(document.querySelector('#pitch')?.value || 0) / 12);
  utterance.onstart = () => { setState(`浏览器语音播报 · 第 ${index + 1} / ${run.q.length} 句`, run.q[index]); saveLiveState('playing', index); };
  utterance.onend = () => { if (!run.stopped) speakBrowserUnit(run); };
  utterance.onerror = event => {
    if (!run.stopped && event.error !== 'canceled') {
      run.failed = true;
      setState('浏览器语音播放失败：' + event.error);
    }
  };
  speechSynthesis.speak(utterance);
}

function startBrowserRun(q, startIndex = 0) {
  if (selectedVoiceWantsGpt()) {
    setState(`当前选择的是克隆音色，${serverTtsLabel()} 暂不可用，未切换为网页机械音`);
    return;
  }
  stopLive(); speechSynthesis.cancel();
  const run = createLiveRun('browser', q, startIndex);
  liveRun = run; speakBrowserUnit(run);
}

async function resumeLive(run) {
  if (run.mode === 'browser') { run.paused = false; speechSynthesis.resume(); setState('浏览器语音继续播报'); return; }
  try { await ensureAudio(); } catch (error) { setState('无法恢复音频：' + error.message); return; }
  if (run.stopped || liveRun !== run) return;
  run.paused = false;
  const resume = run.resumeWaiter; run.resumeWaiter = null; resume?.();
  if (!run.inFlight) void streamGptUnit(run);
  setState(`${serverTtsLabel()} 流式播报已继续`);
}

async function syncTtsMode() {
  const loadingId = activeViewLoading;
  const intent = audioIntent;
  const wantsGpt = selectedVoiceWantsGpt();
  try {
    const status = await api('/tts/status');
    if (activeViewLoading !== loadingId || intent !== audioIntent) return ttsMode;
    ttsStatus = status;
    ttsCheckedAt=performance.now();
    // `provider: browser` is also returned while GPT-SoVITS is warming or
    // briefly restarting. Keep the clone route in that state and let the
    // play action wait/retry instead of silently speaking with Web Speech.
    ttsMode = wantsGpt && status.provider !== 'browser' && (status.configured !== false || status.provider === 'idextts2')
      ? 'gpt-sovits'
      : 'browser';
  } catch {
    if (activeViewLoading !== loadingId || intent !== audioIntent) return ttsMode;
    ttsStatus = null;
    ttsMode = wantsGpt ? 'gpt-sovits' : 'browser';
  }
  const modeNode = document.querySelector('#ttsMode');
  if (modeNode) {
    modeNode.textContent = ttsMode === 'gpt-sovits'
      ? (ttsStatus?.warming_up || ttsStatus?.reachable === false ? `${ttsStatus?.provider_label || '服务端 TTS'} · 正在连接/预热` : `${ttsStatus?.provider_label || '服务端 TTS'} · PCM 实时流式播报`)
      : 'Web Speech API（回退模式）';
  }
  return ttsMode;
}

async function waitForGptReady(maxAttempts = 120) {
  const intent = audioIntent;
  if (!selectedVoiceWantsGpt()) return false;
  if(ttsStatus?.ready && performance.now()-ttsCheckedAt < 2000)return true;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (intent !== audioIntent) return false;
    await syncTtsMode();
    if (intent !== audioIntent) return false;
    if (ttsStatus?.provider !== 'browser' && ttsStatus?.ready) return true;
    if (ttsStatus?.configured === false) return false;
    if (attempt + 1 < maxAttempts) {
      setState(`正在等待 ${serverTtsLabel()} 就绪（${attempt + 1}/${maxAttempts}）`);
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
  }
  return false;
}

async function play() {
  if (playPending || (liveRun && !liveRun.paused && !liveRun.failed)) return;
  const scriptInput = $('#script');
  const scriptText = scriptInput?.value || '';
  const q = sentenceList(normalizeSpeechText(scriptText));
  if (!q.length) return setState('请先填写直播稿');
  const intent=++audioIntent;
  playPending = intent;
  updatePlaybackControls();
  audioRequestedAt=performance.now();
  try {
    if (liveRun?.paused) { await resumeLive(liveRun); return; }
    if (selectedVoiceWantsGpt()) {
      // Unlock audio while the original click still grants autoplay permission.
      await ensureAudio();
      if (intent !== audioIntent) return;
      const ready = await waitForGptReady();
      if (intent !== audioIntent) return;
      if (!ready) return setState(`${serverTtsLabel()} 暂不可用，请检查语音服务后重试`);
      ttsMode = 'gpt-sovits';
    } else {
      ttsMode = 'browser';
    }
    if (intent !== audioIntent) return;
    const saved = await ensure();
    if (intent !== audioIntent) return;
    if (saved.script != null && saved.script !== scriptText) {
      const updated = await api('/live/sessions/' + saved.id + '/script', {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({script:scriptText, sentence:0})});
      if (intent !== audioIntent) return;
      session = updated;
      safeSet('#version', 'textContent', '会话版本 v' + session.version);
    }
    if (ttsMode === 'gpt-sovits') await startGptRun(q); else startBrowserRun(q);
  } catch (error) {
    if (intent === audioIntent && error.name !== 'AbortError') setState('无法开始播报：' + error.message);
  } finally {
    if (playPending === intent) { playPending = 0; updatePlaybackControls(); }
  }
}

function pause() {
  if (!liveRun) return speechSynthesis.pause();
  liveRun.paused = true;
  lipSync.resetMouth();
  if (liveRun.mode === 'browser') speechSynthesis.pause(); else if (audioCtx?.state === 'running') audioCtx.suspend();
  saveLiveState('paused', liveRun.currentIndex);
  setState('已暂停；修改稿件后可继续播放新内容');
}

function stop() {
  audioIntent++;
  playPending = 0;
  if (liveRun) saveLiveState('stopped', liveRun.currentIndex);
  stopLive({suspend:true});
  speechSynthesis.cancel();
  setState('已停止');
}

async function revise() {
  if (revisionPending) return;
  const scriptInput = $('#script');
  if (!scriptInput) return setState('页面未加载完成');
  const scriptText = scriptInput.value;
  const nextQueue = sentenceList(normalizeSpeechText(scriptText));
  if (!nextQueue.length) return setState('改稿内容不能为空');
  const requestId = Symbol('revision');
  revisionPending = requestId;
  const loadingId = activeViewLoading;
  const intent = audioIntent;
  const run = liveRun;
  updatePlaybackControls();
  let saved;
  const beforeQueue = run ? run.q.slice() : [];
  const changedAt = run ? sharedPrefixLength(run.q, nextQueue) : 0;
  try {
    saved = await ensure();
    if (loadingId !== activeViewLoading || intent !== audioIntent) return;
    const updated = await api('/live/sessions/' + saved.id + '/script', {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify({script:scriptText, sentence:changedAt})});
    if (loadingId !== activeViewLoading || intent !== audioIntent || session?.id !== saved.id) return;
    session = updated;
  } catch (error) {
    if (loadingId === activeViewLoading && intent === audioIntent && error.name !== 'AbortError') setState('改稿保存失败：' + error.message);
    return;
  } finally {
    if (revisionPending === requestId) { revisionPending = false; updatePlaybackControls(); }
  }
  // Playback may have advanced while the save request was in flight.
  const safeIndex = run ? (run.mode === 'browser' ? run.currentIndex : safePlaybackIndex(run)) : 0;
  safeSet('#version', 'textContent', '会话版本 v' + session.version);
  window.CarLiveFeatures?.revision();
  if (!run || run.stopped) { setState('稿件已同步；点击”开始播放”后使用新稿'); return; }
  // Never cancel the phrase that is currently audible. The old implementation
  // called stopLive() here, which clipped the current sentence and made even a
  // distant edit feel like a restart. We keep the active phrase and replace
  // only the tail at its next natural pause.
  run.q = nextQueue;
  const scriptChanged = changedAt < beforeQueue.length || nextQueue.length !== beforeQueue.length;
  let applyFrom = Math.max(changedAt, safeIndex + 1);
  if (run.mode === 'gpt-sovits' && scriptChanged) {
    const now = audioCtx?.currentTime || 0;
    const activeBatch = run.inFlight > 0 && run.currentBatchEnd > run.currentBatchStart;
    const batchNotAudible = activeBatch && ![...run.sources].some(source =>
      source.liveIndex === run.currentBatchStart &&
      source.liveStart <= now + 0.02 &&
      source.liveEnd > now + 0.01,
    );
    const editInActiveBatch = activeBatch &&
      changedAt >= run.currentBatchStart && changedAt < run.currentBatchEnd;
    // Before the first buffer is audible, restart from the edited phrase. Once
    // any part of a batch is audible, preserve the entire batch and apply the
    // new script at its end so the listener never hears a clipped semantic
    // fragment.
    applyFrom = editInActiveBatch
      ? (batchNotAudible ? changedAt : Math.max(changedAt, run.currentBatchEnd))
      : Math.max(changedAt, safeIndex + 1);
    // Invalidate generated-but-not-audible tail audio. If the active request
    // is still before the edit point, let it finish and continue through any
    // unchanged phrases before requesting the replacement tail.
    const abortFuture = editInActiveBatch && batchNotAudible;
    const hasQueuedTail = [...run.sources].some(source =>
      (source.liveEndIndex ?? source.liveIndex) >= applyFrom &&
      source.liveStart > now + 0.02,
    );
    const hadStaleIndex = run.nextIndex > applyFrom;
    if (abortFuture || hasQueuedTail || hadStaleIndex || run.nextIndex < nextQueue.length) {
      if (abortFuture) run.revision += 1;
      run.nextIndex = Math.min(run.nextIndex, applyFrom);
      run.pendingRestartAt = abortFuture ? applyFrom : null;
      discardUnplayedSources(run, applyFrom);
      if (abortFuture) run.abortController?.abort();
      if (!abortFuture && !run.paused && run.nextIndex < run.q.length && !run.inFlight) void streamGptUnit(run);
      setState(`稿件已更新；当前第 ${safeIndex + 1} 段继续播放，新第 ${applyFrom + 1} 段正在生成`);
      return;
    }
    if (changedAt <= safeIndex && nextQueue.length <= applyFrom) {
      run.nextIndex = nextQueue.length;
      setState('稿件已更新；当前短语不打断，结束后停止播报');
      return;
    }
  } else {
    if (changedAt <= safeIndex && nextQueue.length <= applyFrom) {
      run.nextIndex = nextQueue.length;
      setState('稿件已更新；当前短语不打断，结束后停止播报');
      return;
    }
  }
  // The changed content has not entered the synthesizer yet. Its next request
  // reads the replacement queue directly, so no active audio needs touching.
  setState(run.paused
    ? `稿件已同步，继续播放后从第 ${applyFrom + 1} 段使用新稿`
    : `稿件已更新；当前第 ${safeIndex + 1} 段继续播放，后续使用新稿`);
}

async function ask() {
  const vehicleSelect = $('#vehicle');
  const questionInput = $('#question');
  const answerNode = $('#answer');

  if (!vehicleSelect || !questionInput) return;
  if (questionRequest) return;
  const question = questionInput.value.trim();
  clearAnswer();
  if (question.length < 2) {
    if (answerNode) answerNode.textContent = '请输入至少两个字的问题';
    return;
  }
  const request = new AbortController();
  questionRequest = request;
  safeSet('#ask', 'disabled', true);
  safeSet('#ask', 'textContent', '检索中…');
  updatePlaybackControls();

  // 显示加载状态
  if (answerNode && answerNode.isConnected) {
    answerNode.innerHTML = '<div class="notice">正在检索并生成回答…</div>';
  }

  try {
    const option = vehicleSelect.selectedOptions[0];
    const r = await api('/query', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      signal: request.signal,
      body: JSON.stringify({
        question,
        brand: option?.dataset.brand || '',
        series: option?.dataset.series || '',
        year: option?.dataset.year || ''
      })
    });

    if (questionRequest !== request || !answerNode?.isConnected) return;
    currentAnswer = r.answer;
    const generation = r.generation?.status === 'fallback' ? ` · ${esc(r.generation.reason)}` : '';
    const conflict = (r.conflict_warnings || []).map(x => `<div class="notice warning">${esc(x)}</div>`).join('');

    if (answerNode && answerNode.isConnected) {
      answerNode.innerHTML = `${conflict}<div class="notice">${esc(r.answer)}</div><p class="hint">${r.provider === 'llm-grounded-rag' ? '大模型依据回答' : '本地资料摘录'} · 语义混合检索＋独立重排 · 依据充分度：${esc(({high: '高', medium: '中', low: '不足'})[r.confidence] || r.confidence)}${generation}</p>${r.sources.map((s, i) => `<details class="source"><summary>[${i + 1}] ${esc(s.document_name)} · v${s.version || 1}${s.page ? ' · 第' + s.page + '页' : ''} · 重排相关度 ${Math.round(Math.min(1, s.score) * 100)}%</summary><p>${esc(s.content)}</p><small>${esc(s.metadata.series || '')} · ${esc(s.metadata.kind || '资料')} · ${esc(s.license || '来源待审核')}</small>${(s.metadata.warnings || []).map(w => `<p class="hint warning">${esc(w)}</p>`).join('')}${s.source_url && /^https?:\/\//.test(s.source_url) ? `<p><a href="${esc(s.source_url)}" target="_blank" rel="noopener noreferrer">查看原始来源</a></p>` : ''}</details>`).join('')}`;
    }
  } catch (error) {
    if (error.name === 'AbortError' || questionRequest !== request) return;
    if (answerNode && answerNode.isConnected) {
      answerNode.innerHTML = `<div class="notice error">检索失败：${esc(error.message)}</div><button class="btn secondary" onclick="ask()">重试</button>`;
    }
    console.error('❌ Ask failed:', error);
  } finally {
    if (questionRequest === request) {
      questionRequest = null;
      safeSet('#ask', 'disabled', false);
      safeSet('#ask', 'textContent', '检索回答');
      updatePlaybackControls();
    }
  }
}

async function speakText(text) {
  if (playPending) return;
  const q = sentenceList(normalizeSpeechText(text));
  if (!q.length) return;
  const intent=++audioIntent;
  playPending = intent;
  updatePlaybackControls();
  audioRequestedAt=performance.now();
  try {
    if (selectedVoiceWantsGpt()) {
      await ensureAudio();
      if (intent !== audioIntent) return;
      const ready = await waitForGptReady();
      if (intent !== audioIntent) return;
      if (!ready) return setState(`${serverTtsLabel()} 暂不可用，请检查语音服务后重试`);
      await startGptRun(q);
    } else if (intent === audioIntent) {
      startBrowserRun(q);
    }
  } catch (error) {
    if (intent === audioIntent && error.name !== 'AbortError') setState('播报失败：' + error.message);
  } finally {
    if (playPending === intent) { playPending = 0; updatePlaybackControls(); }
  }
}

function ttsBody(text, unitized = false, streamBatch = false) {
  const value = (selector, fallback) => document.querySelector(selector)?.value ?? fallback;
  return JSON.stringify({text:normalizeSpeechText(text), unitized,
    voice_id: value('#voice', storedVoiceId()),
    stream_batch:Boolean(streamBatch),
    speed_factor:Number(value('#speed', 1)), delivery:'natural'});
}

function storedVoiceId() {
  try { return localStorage.getItem('selectedVoiceId') || ''; } catch { return ''; }
}

function rememberVoiceId(id) {
  try { localStorage.setItem('selectedVoiceId', id); } catch {}
}

async function startQualityPreview(text) {
  stopLive();
  const run = createLiveRun('preview', [text]);
  liveRun = run;
  try {
    await ensureAudio();
    setState(`${serverTtsLabel()} 高质量试听合成中…`);
    const controller = new AbortController();
    run.abortController = controller;
    const response = await fetch(API + '/tts/synthesize', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:ttsBody(text),
      signal:controller.signal,
    });
    if (!response.ok) throw new Error(`TTS HTTP ${response.status} ${(await response.text()).slice(0, 120)}`);
    const audioData = await response.arrayBuffer();
    if (run.stopped || liveRun !== run) return;
    const buffer = await audioCtx.decodeAudioData(audioData);
    if (run.stopped || liveRun !== run) return;
    const source = audioCtx.createBufferSource();
    source.buffer = buffer;
    source.playbackRate.value = Math.pow(2, Number(document.querySelector('#pitch')?.value || 0) / 12);
    source.connect(gainNode);
    gainNode.gain.value = Number(document.querySelector('#volume')?.value || 1);
    run.sources.add(source);
    activeSource = source;
    source.onended = () => {
      run.sources.delete(source);
      if (activeSource === source) activeSource = null;
      if (liveRun === run) {
        liveRun = null;
        setState('试听完成');
      }
    };
    const when = audioCtx.currentTime + STREAM_LEAD_SECONDS;
    if (document.querySelector('#avatarCanvas')) lipSync.schedule(source, buffer, when, source.playbackRate.value);
    source.start(when);
    setState('正在试听当前音色');
  } catch (error) {
    if (!run.stopped && error.name !== 'AbortError') setState('试听失败：' + error.message);
    if (liveRun === run && !run.sources.size) liveRun = null;
  } finally {
    if (run.abortController) run.abortController = null;
  }
}

async function previewVoice() {
  const text = document.querySelector('#voicePreviewText')?.value.trim();
  if (!text) return;
  // Preview uses the same progressive path as live playback. Waiting for a
  // complete quality render made a short preview look stalled and could take
  // eight seconds before any sound reached the browser.
  await speakText(text);
}

async function readScriptFile(event) {
  const file = event.target.files[0];
  if (file) {
    const scriptInput = $('#script');
    if (scriptInput) {
      scriptInput.value = await file.text();
      renderScriptUnits();
    }
  }
}

async function generateScript() {
  const vehicleSelect = $('#vehicle');
  if (!vehicleSelect) return;

  const option = vehicleSelect.selectedOptions[0];

  // 创建模态对话框替代 prompt
  const existingDialog = document.querySelector('#generateScriptDialog');
  if (existingDialog) existingDialog.remove();

  const dialog = document.createElement('dialog');
  dialog.id = 'generateScriptDialog';
  dialog.innerHTML = `
    <h2>生成直播话术</h2>
    <p>请输入车型卖点，系统将基于知识库生成专业直播话术</p>
    <label>
      车型卖点
      <textarea id="scriptSellingPoints" rows="4" placeholder="请输入车型卖点，多个卖点用逗号或顿号分隔&#x0a;&#x0a;示例 1：580公里续航、激光雷达、智能泊车&#x0a;示例 2：百公里加速7.8秒、L2级辅助驾驶、15.6寸中控大屏&#x0a;示例 3：全景天窗、座椅加热、无线充电、语音控制"></textarea>
    </label>
    <div class="fields">
      <label>
        话术时长
        <select id="scriptDuration">
          <option value="30">约 30 秒</option>
          <option value="60" selected>约 60 秒</option>
          <option value="90">约 90 秒</option>
          <option value="120">约 120 秒</option>
        </select>
      </label>
      <label>
        播报风格
        <select id="scriptDelivery">
          <option value="natural" selected>自然专业</option>
          <option value="warm">亲切温和</option>
          <option value="lively">活泼热情</option>
        </select>
      </label>
    </div>
    <p id="generateMessage" class="hint">提示：生成的话术将基于已上传的知识库内容</p>
    <p class="dialog-actions">
      <button class="btn" id="confirmGenerate">生成话术</button>
      <button class="btn secondary" data-close>取消</button>
    </p>
  `;

  document.body.append(dialog);
  requestAnimationFrame(() => { if (dialog.isConnected) dialog.showModal(); });

  dialog.querySelector('[data-close]')?.addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', (e) => {
    if (e.target === dialog) dialog.close();
  });

  const scriptInput = $('#script');
  const stateNode = $('#playstate');

  dialog.querySelector('#confirmGenerate').onclick = async () => {
    const points = dialog.querySelector('#scriptSellingPoints').value.trim();
    const duration = Number(dialog.querySelector('#scriptDuration').value);
    const delivery = dialog.querySelector('#scriptDelivery').value;

    if (!points) {
      dialog.querySelector('#generateMessage').textContent = '⚠️ 请至少输入一个卖点';
      dialog.querySelector('#generateMessage').className = 'notice warning';
      return;
    }

    const generateBtn = dialog.querySelector('#confirmGenerate');
    generateBtn.disabled = true;
    generateBtn.textContent = '生成中…';
    dialog.querySelector('#generateMessage').textContent = '正在生成直播话术，请稍候…';
    dialog.querySelector('#generateMessage').className = 'hint';

    try {
      const result = await api('/script/generate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          brand: option?.dataset.brand || '欧拉',
          series: option?.dataset.series || '欧拉5 EV',
          year: option?.dataset.year || '2026',
          selling_points: points,
          delivery: delivery,
          duration_seconds: duration
        })
      });

      if (scriptInput && scriptInput.isConnected) {
        scriptInput.value = result.script;
        renderScriptUnits();
      }

      if (scriptInput?.isConnected) setState(result.notice || '已生成新直播稿');
      dialog.close();
    } catch (error) {
      dialog.querySelector('#generateMessage').textContent = '✗ 生成失败：' + error.message;
      dialog.querySelector('#generateMessage').className = 'notice error';
      generateBtn.disabled = false;
      generateBtn.textContent = '重试生成';
      console.error('❌ Script generation failed:', error);
    }
  };

  // 聚焦到输入框
  dialog.querySelector('#scriptSellingPoints').focus();
}

function updatePromptMeta() {
  const node = document.querySelector('#voicePromptMeta');
  const input = document.querySelector('#voicePrompt');
  if (!node || !input) return;
  const core = input.value.replace(/[\s\p{P}\p{S}]+/gu, '');
  node.textContent = `${core.length} 个有效字 · 必须与录音逐字一致`;
  node.classList.toggle('warning', core.length > 0 && core.length < 4);
}

async function inspectVoiceFile() {
  const input = document.querySelector('#voiceFile');
  const node = document.querySelector('#voiceFileMeta');
  const file = input?.files?.[0];
  if (!node) return;
  if (!file) { node.textContent = '建议 5-10 秒，最低 3 秒；主参考音频必须填写对应原文'; return; }
  const suffix = file.name.split('.').pop()?.toLowerCase() || '';
  const localUrl = URL.createObjectURL(file);
  const audio = new Audio();
  audio.preload = 'metadata';
  audio.src = localUrl;
  try {
    await new Promise((resolve, reject) => { audio.onloadedmetadata = resolve; audio.onerror = reject; });
    const duration = Number(audio.duration);
    input.dataset.duration = String(duration);
    const warning = duration < 3 || duration > 10 ? ' · 时长不在 3-10 秒范围' : duration < 5 ? ' · 少于 5 秒，音色稳定性可能下降' : '';
    node.textContent = `${file.name} · ${duration.toFixed(1)} 秒 · ${(file.size / 1024).toFixed(0)} KB${warning}`;
    node.classList.toggle('warning', Boolean(warning));
  } catch {
    input.dataset.duration = '';
    node.textContent = `${file.name} · ${suffix.toUpperCase()}，等待服务端检查音频`;
    node.classList.remove('warning');
  } finally { URL.revokeObjectURL(localUrl); }
}

function inspectAuxFiles() {
  const input = document.querySelector('#voiceAuxFiles');
  const node = document.querySelector('#voiceAuxMeta');
  if (!input || !node) return;
  const files = [...(input.files || [])];
  if (!files.length) {
    node.textContent = '最多 2 条；同一说话人的不同句子，不需要填写文字';
    node.classList.remove('warning');
    return;
  }
  const warning = files.length > 2;
  node.textContent = `${files.length} 条辅助参考${warning ? ' · 最多只能使用 2 条' : ' · 将用于同一说话人的音色融合'}`;
  node.classList.toggle('warning', warning);
}

function cloneUpload(form, onProgress) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('POST', API + '/voices/clone');
    request.responseType = 'json';
    request.upload.onprogress = event => { if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100)); };
    request.onerror = () => reject(new Error('无法连接后端服务，请确认项目已启动'));
    request.onload = () => {
      const body = request.response || {};
      if (request.status >= 200 && request.status < 300) return resolve(body);
      reject(new Error(body.detail || `音色克隆失败（HTTP ${request.status}）`));
    };
    request.send(form);
  });
}

async function analyzeVoiceSample() {
  const {file, auxiliary, prompt, duration, mode} = voiceRecorder.sample();
  if (!file) {
    safeSet('#cloneState', 'textContent', mode === 'record' ? '请先录制并回听一段完整朗读。' : '请先选择参考音频。');
    return;
  }
  safeSet('#cloneState', 'textContent', '正在检查音频质量…');
  const form = new FormData();
  form.append('sample', file);
  auxiliary.slice(0, 2).forEach(item => form.append('aux_samples', item));
  form.append('prompt_text', prompt);
  try {
    const result = await api('/voices/analyze', {method:'POST', body:form});
    const advice = result.prompt_advice?.message ? `；${result.prompt_advice.message}` : '';
    safeSet('#cloneState', 'textContent', `${result.quality?.message || result.recommendation}${advice}`);
    const stateNode = $('#cloneState');
    if (stateNode) {
      stateNode.classList.toggle('warning', result.status !== 'ready' || result.prompt_advice?.status === 'review');
    }
  } catch (error) {
    safeSet('#cloneState', 'textContent', error.message);
    const stateNode = $('#cloneState');
    if (stateNode) stateNode.classList.add('warning');
  }
}

async function waitForVoiceWarmup(voiceId) {
  const state = document.querySelector('#cloneState');
  for (let attempt = 0; attempt < 180; attempt += 1) {
    try {
      const voices = await api('/voices');
      const voice = voices.find(item => item.id === voiceId);
      if (voice?.synthesis_check?.status === 'failed' || voice?.quality?.status === 'failed') {
        if (state) {
          state.textContent = voice.synthesis_check.message || voice.quality.message || '实际合成验收失败，请重新录制参考音频';
          state.classList.add('warning');
        }
        return false;
      }
      if (voice && voice.warmed && !voice.warming) {
        if (state) {
          state.textContent = voice.calibrating || voice.calibration_pending
            ? '音色已通过实际合成验收，可立即试听；后台继续优化音色'
            : '音色已预热，可直接试听或用于直播';
          state.classList.remove('warning');
        }
        return true;
      }
      if (state) state.textContent = `音色已创建，正在进行合成验收… ${attempt + 1} 秒`;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  if (state) state.textContent = '音色已保存；预热仍在进行，可稍后试听';
  return false;
}

async function cloneVoice() {
  const {file, auxiliary, prompt, duration, mode} = voiceRecorder.sample();
  const promptCore = prompt.replace(/[\s\p{P}\p{S}]+/gu, '');
  if (!file) {
    safeSet('#cloneState', 'textContent', mode === 'record' ? '请先录制并回听一段完整朗读。' : '请选择真人语音样本。');
    return;
  }
  if (auxiliary.length > 2) return alert('辅助参考音频最多选择 2 条');
  if (promptCore.length < 4) return alert('请填写至少 4 个字且与录音逐字一致的参考文本');
  if (mode === 'upload' && duration && (duration < 3 || duration > 10) && !confirm('当前样本不在 3-10 秒范围内，继续创建可能降低音色稳定性。仍要继续吗？')) return;
  const form = new FormData();
  form.append('sample', file);
  auxiliary.forEach(item => form.append('aux_samples', item));
  const voiceName = $('#voiceName');
  const voiceStyle = $('#voiceStyle');
  form.append('name', voiceName ? voiceName.value.trim() || '我的主播' : '我的主播');
  form.append('style', voiceStyle ? voiceStyle.value.trim() || '自然' : '自然');
  form.append('prompt_text', prompt);
  const progress = $('#voiceProgress');
  const button = $('#clone');
  if (button) button.disabled = true;
  if (progress) { progress.hidden = false; progress.value = 0; }
  const stateNode = $('#cloneState');
  if (stateNode) stateNode.classList.remove('warning');
  safeSet('#cloneState', 'textContent', '上传参考音频…');
  try {
    const result = await cloneUpload(form, value => {
      if (progress) progress.value = value;
      safeSet('#cloneState', 'textContent', value >= 100 ? '音频已上传，正在生成标准 PCM 并预热…' : `上传参考音频… ${value}%`);
    });
    localStorage.setItem('selectedVoiceId', result.id);
    apiCache.data.clear(); apiCache.timestamps.clear();
    if (currentView !== 'voices') return;
    activateView('studio');
    safeSet('#cloneState', 'textContent', result.quality_hint || '音色已创建，正在预热…');
    await waitForVoiceWarmup(result.id);
    apiCache.data.clear(); apiCache.timestamps.clear();
  } catch (error) {
    safeSet('#cloneState', 'textContent', error.message);
    if (stateNode) stateNode.classList.add('warning');
  } finally {
    if (button) button.disabled = false;
    if (progress) progress.hidden = true;
  }
}

async function tests() {
  if (!beginViewLoad('tests')) return;
  layout('效果验证', '一键复测检索准确率、回答命中率与语音首包延迟，并可导出完整测试数据。', '<div id="testResult">测试中…</div>', {eyebrow:'扩展能力', tag:'量化测试报告'});

  const resultNode = document.querySelector('#testResult');
  if (!resultNode) return;

  try {
    resultNode.innerHTML = '<div class="notice">正在运行检索测试…</div>';
    const [rag, qa] = await Promise.all([
      api('/tests/retrieval', {method:'POST'}),
      api('/tests/qa', {method:'POST'})
    ]);

    if (resultNode.isConnected) {
      resultNode.innerHTML = '<div class="notice">正在测试 TTS 首包延迟…</div>';
    }

    if (!resultNode.isConnected) return;
    const tts = await api('/tests/tts', {method:'POST'});
    const stats = await api('/analytics');

    if (resultNode.isConnected) {
      resultNode.innerHTML = `<div class="metrics"><div class="metric"><b>${rag.accuracy}%</b><span>完整依据命中 ${rag.passed}/${rag.total}</span></div><div class="metric"><b>${qa.accuracy}%</b><span>本地回答命中 ${qa.passed}/${qa.total}</span></div><div class="metric"><b>${tts.average_first_audio_ms ?? '-'} ms</b><span>模型首包平均延迟</span></div><div class="metric"><b>${tts.meets_target ? '✓ 通过' : '⚠ 需优化'}</b><span>全部首包样本 ≤3秒</span></div></div><p class="notice">首包延迟仅统计后端出音；客户端近期 ${stats.first_audio.count} 次播报，最大排程延迟 ${stats.first_audio.max_ms == null ? '暂无' : Math.round(stats.first_audio.max_ms) + ' ms'}。</p><details class="report-raw"><summary>查看完整测试明细</summary><pre>${esc(JSON.stringify({retrieval: rag, local_qa: qa, model_first_audio: tts}, null, 2))}</pre></details><a class="btn secondary" href="${API}/reports/export" download>导出运行与听测报告</a>`;
    }
  } catch(error) {
    if (resultNode && resultNode.isConnected) {
      resultNode.innerHTML = `<p class="notice error">${esc(error.message)}</p><button class="btn" id="retryTests">重试</button>`;
      const retryBtn = document.querySelector('#retryTests');
      if (retryBtn) retryBtn.onclick = tests;
    }
    console.error('❌ Tests failed:', error);
  }
}

function activateView(view, {updateHash = true} = {}) {
  const loader = viewLoaders()[view];
  if (typeof loader !== 'function') return false;
  const button = [...document.querySelectorAll('nav button')].find(node => node.dataset.view === view);
  if (!button) return false;
  if (updateHash && location.hash !== '#' + view) location.hash = view;
  // The hash write above fires hashchange; only render when the view changes.
  if (view === currentView) return true;
  currentView = view;
  stopCurrentView();
  app.dataset.view = view;
  document.querySelectorAll('nav button').forEach(x => x.classList.toggle('active', x === button));
  void renderView(view);
  return true;
}

document.querySelectorAll('nav button').forEach(button => {
  button.onclick = () => activateView(button.dataset.view);
});
// Deep links such as #studio or #voices survive a refresh and can be bookmarked.
window.addEventListener('hashchange', () => activateView(location.hash.slice(1), {updateHash: false}));

function activateInitialView() {
  if (!activateView(location.hash.slice(1), {updateHash: false})) {
    activateView('knowledge', {updateHash: false});
  }
}

// features.js registers the remaining loaders after this file runs, so wait for
// the whole document before resolving a deep link such as #model.
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', activateInitialView);
} else {
  activateInitialView();
}
startHealthMonitor();
window.addEventListener('pagehide', () => { saveStudioDraft(); stop(); });
