/* Jarvis Web UI v16 — faster STT + lower reply latency */

const API = window.location.origin;
const APP_VERSION = '72';

const MUTE_AFTER_SPEECH_MS = 350; // unmute ASAP after TTS
const FINAL_DEBOUNCE_MS = 500;    // wait for full sentence before executing
const POST_WAKE_LISTEN_MS = 12000; // stay open for command after wake
const STT_LANG = 'en-US';         // consistent Chrome STT language

let ws = null;
let recognition = null;
let isListening = false;
let micMuted = false;          // true while Jarvis speaks OR processes
let audioCtx = null;
let radarAngle = 0;
let commandBusy = false;
let lastWakeAt = 0;
let lastExecuted = '';
let lastExecutedAt = 0;
let britishVoice = null;
let ttsKeepAlive = null;
let unmuteTimer = null;
let postWakeUntil = 0;
let pendingFinal = '';
let finalDebounceTimer = null;
let restartTimer = null;

// Screen share state
let userShareStream = null;
let userShareTimer = null;
let userSharing = false;
let jarvisSharing = false;
let jarvisPollTimer = null;
let jarvisFrameUrl = null;
let userFrameCanvas = null;
let userFrameUploading = false;
let jarvisPollInFlight = false;

// Capture cadence (speed-tuned)
const USER_FRAME_INTERVAL_MS = 220;   // ~4.5 fps upload
const USER_JPEG_QUALITY = 0.58;
const USER_MAX_WIDTH = 1280;
const JARVIS_POLL_MS = 130;           // ~7–8 fps panel refresh

const chatLog = document.getElementById('chat-log');
const commandInput = document.getElementById('command-input');
const sendBtn = document.getElementById('send-btn');
const micBtn = document.getElementById('mic-btn');
const briefingBtn = document.getElementById('briefing-btn');
const stateDot = document.getElementById('state-dot');
const stateText = document.getElementById('state-text');
const pluginList = document.getElementById('plugin-list');
const voiceHint = document.getElementById('voice-hint');
const activateOverlay = document.getElementById('activate-overlay');
const activateBtn = document.getElementById('activate-btn');
const hud = document.querySelector('.hud');

const WAKE_RE = /\b(hey|hi|hello|okay|ok)\s*(jarvis|service|gervis|jar vis)\b/i;
const WAKE_ONLY_RE = /^(hey|hi|hello|okay|ok)?\s*(jarvis|service|gervis|jar vis)[\s,!.?]*$/i;

// ── Clock & radar ───────────────────────────────────
function updateClock() {
  const now = new Date();
  document.getElementById('clock').textContent = now.toLocaleTimeString('en-US', { hour12: true });
  document.getElementById('date').textContent = now.toLocaleDateString('en-US', {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
  });
}
setInterval(updateClock, 1000);
updateClock();

function drawRadar() {
  const canvas = document.getElementById('radar');
  if (!canvas || canvas.width < 20 || canvas.height < 20 || canvas.hidden) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const w = canvas.width, h = canvas.height;
  const cx = w / 2, cy = h / 2, r = w / 2 - 10;
  if (r <= 0) return;
  ctx.clearRect(0, 0, w, h);
  for (let i = 1; i <= 3; i++) {
    ctx.beginPath();
    ctx.arc(cx, cy, (r / 3) * i, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(34, 211, 238, 0.2)';
    ctx.stroke();
  }
  const rad = (radarAngle * Math.PI) / 180;
  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.lineTo(cx + r * Math.cos(rad), cy + r * Math.sin(rad));
  ctx.strokeStyle = '#22d3ee';
  ctx.lineWidth = 2;
  ctx.stroke();
  radarAngle = (radarAngle + 3) % 360;
  requestAnimationFrame(drawRadar);
}
try { drawRadar(); } catch (_) { /* radar optional on company layout */ }

// ── Status ──────────────────────────────────────────
function setConnectionOnline() {
  document.getElementById('connection-status').innerHTML =
    '<span class="dot online"></span> SYSTEM ONLINE';
}
function setConnectionOffline() {
  document.getElementById('connection-status').innerHTML =
    '<span class="dot" style="background:#f87171"></span> OFFLINE';
}
async function fetchStatus() {
  // Never block commands — short timeout, no retry chain
  try {
    const res = await fetch(`${API}/api/status`, { signal: AbortSignal.timeout(2500) });
    if (!res.ok) { setConnectionOffline(); return; }
    setConnectionOnline();
    const data = await res.json();
    const setTxt = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    const setW = (id, val) => { const el = document.getElementById(id); if (el && el.style) el.style.width = val; };
    setTxt('cpu', `${data.cpu}%`);
    setTxt('ram', `${data.memory}%`);
    setTxt('disk', `${data.disk}%`);
    setTxt('battery', data.battery != null ? `${data.battery}%` : 'N/A');
    setW('cpu-bar', `${data.cpu}%`);
    setW('ram-bar', `${data.memory}%`);
    setW('disk-bar', `${data.disk}%`);
    setTxt('user-greeting', `OWNER: ${(data.user || 'SIR').toUpperCase()}`);
    if (pluginList) {
      pluginList.innerHTML = (data.plugins || []).map(p =>
        `<li><span class="mod-dot"></span> ${p.replace(/_/g, ' ')}</li>`
      ).join('') || '<li>No plugins</li>';
    }
  } catch (e) {
    setConnectionOffline();
  }
}
setInterval(fetchStatus, 10000);
fetchStatus();

function setState(status) {
  const map = {
    ONLINE: { cls: 'online', text: 'STANDBY' },
    LISTENING: { cls: 'listening', text: 'LISTENING' },
    THINKING: { cls: 'thinking', text: 'PROCESSING' },
    ASSEMBLING: { cls: 'thinking', text: 'ASSEMBLING' },
    SPEAKING: { cls: 'speaking', text: 'SPEAKING' },
  };
  const s = map[status] || map.ONLINE;
  stateDot.className = `dot ${s.cls}`;
  stateText.textContent = s.text;
}

function pulseHud() {
  if (!hud) return;
  hud.classList.remove('wake-pulse');
  void hud.offsetWidth;
  hud.classList.add('wake-pulse');
}

function addMessage(role, text) {
  const div = document.createElement('div');
  div.className = `msg ${role}`;
  div.innerHTML = `<span class="msg-label">${role === 'user' ? 'YOU' : 'JARVIS'}</span><p>${escapeHtml(text)}</p>`;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
}
function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Mic mute — never listen to Jarvis; soft-stop (not abort) ──
function muteMic() {
  micMuted = true;
  if (unmuteTimer) { clearTimeout(unmuteTimer); unmuteTimer = null; }
  if (finalDebounceTimer) { clearTimeout(finalDebounceTimer); finalDebounceTimer = null; }
  pendingFinal = '';
  // Prefer stop() over abort() — abort drops the session and hurts restart reliability
  if (recognition) {
    try { recognition.stop(); } catch (e) { /* ok */ }
  }
}

function restartRecognitionSoon(delayMs = 80) {
  if (restartTimer) clearTimeout(restartTimer);
  restartTimer = setTimeout(() => {
    restartTimer = null;
    if (!isListening || micMuted || commandBusy || !recognition) return;
    try { recognition.start(); } catch (e) { /* already started */ }
    setState('LISTENING');
    const wakeOpen = Date.now() < postWakeUntil;
    voiceHint.textContent = wakeOpen
      ? '🎙 Listening for your command…'
      : '🎙 Listening... say "Hey Jarvis" + command';
  }, delayMs);
}

function scheduleUnmute() {
  if (unmuteTimer) clearTimeout(unmuteTimer);
  unmuteTimer = setTimeout(() => {
    micMuted = false;
    unmuteTimer = null;
    if (isListening && !commandBusy) restartRecognitionSoon(50);
  }, MUTE_AFTER_SPEECH_MS);
}

function playWakePing() {
  if (!audioCtx) return;
  try {
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = 'sine';
    osc.frequency.value = 880;
    gain.gain.value = 0.07;
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + 0.07);
  } catch (e) { /* ok */ }
}

function loadBritishVoice() {
  if (!window.speechSynthesis) return;
  const voices = speechSynthesis.getVoices();
  britishVoice = voices.find(v => v.name.includes('Google UK English Male'))
    || voices.find(v => v.name.includes('Daniel'))
    || voices.find(v => v.lang === 'en-GB')
    || voices.find(v => v.lang.startsWith('en'));
}

/** Speak and return promise — mic stays OFF until done + cooldown */
function instantSpeak(text) {
  return new Promise((resolve) => {
    if (!text || !window.speechSynthesis) { resolve(); return; }
    muteMic();
    loadBritishVoice();
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'en-GB';
    u.rate = 1.12;
    u.pitch = 0.85;
    if (britishVoice) u.voice = britishVoice;
    setState('SPEAKING');
    const done = () => {
      scheduleUnmute();
      resolve();
    };
    u.onend = done;
    u.onerror = done;
    speechSynthesis.resume();
    speechSynthesis.speak(u);
  });
}

function startTtsKeepAlive() {
  if (ttsKeepAlive) clearInterval(ttsKeepAlive);
  ttsKeepAlive = setInterval(() => {
    if (!micMuted) speechSynthesis.resume();
  }, 4000);
}

async function unlockAudio() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (audioCtx.state === 'suspended') await audioCtx.resume();
  loadBritishVoice();
  startTtsKeepAlive();
}

// ── Parsing ─────────────────────────────────────────
function normalizeCommand(raw) {
  let text = raw.trim();
  const lower = text.toLowerCase();
  const hasWake = WAKE_RE.test(lower) || /\bjarvis\b/i.test(lower);
  if (hasWake) {
    text = text
      .replace(/\b(hey|hi|hello|okay|ok)\s*,?\s*(jarvis|service|gervis|jar vis)[,\s]*/gi, '')
      .replace(/\bjarvis[,\s]*/gi, '')
      .trim();
  }
  return { hasWake, command: text, raw: raw.trim() };
}

function isWakeOnly(raw) {
  return WAKE_ONLY_RE.test(raw.trim());
}

/** Block only near-exact duplicate fires (was too aggressive on prefixes) */
function shouldSkipCommand(text) {
  const now = Date.now();
  const t = text.toLowerCase().trim();
  const last = lastExecuted.toLowerCase().trim();
  // Exact duplicate within 2s only — allow legitimate repeats after that
  if (now - lastExecutedAt < 2000 && t === last) return true;
  lastExecuted = text;
  lastExecutedAt = now;
  return false;
}

/** Acks that already answer the user — don't speak the API reply again */
function isSelfContainedAck(text) {
  const lower = text.toLowerCase();
  return lower.includes('time') || lower.includes('screenshot');
}

function instantAck(text) {
  const lower = text.toLowerCase();
  if (/\b(upload|post|publish)\b.{0,40}\byoutube\b/.test(lower)
      || /\b(post|upload)\s+(?:this|it|last|that|the)\s+(?:video|clip|short)\b/.test(lower)) {
    return 'Uploading to YouTube, sir.';
  }
  if (/\b(connect|link|authorize)\b.{0,20}\byoutube\b/.test(lower)) {
    return 'Connecting YouTube, sir.';
  }
  if (isMiraCommand(text)) return 'Generating with Mira, sir.';
  if (lower.includes('youtube')) return 'YouTube, sir.';
  if ((lower.includes('sheet') || lower.includes('tab')) && (lower.includes('go') || lower.includes('open') || lower.includes('api'))) {
    return 'Opening tab, sir.';
  }
  if (/https?:\/\//i.test(text) || lower.includes('this link')) return 'Opening, sir.';
  if (lower.includes('google sheet') || lower.includes('spreadsheet')) return 'Sheet, sir.';
  if (lower.includes('check') && lower.includes('api')) return 'Checking, sir.';
  if (isApiCountCommand(text)) return 'Counting, sir.';
  if (lower.includes('copy') || lower.includes('upload') || lower.includes('transfer')) return 'On it.';
  if (/^(open|launch|start)\s+/.test(lower)) return 'On it.';
  if (/^(close|search|google|look up|find)\s+/.test(lower) && !lower.includes('sheet') && !lower.includes('youtube')) return 'On it.';
  if (lower.includes('api key') || lower.includes('sign in') || lower.includes('get api')) return 'On it.';
  if (lower.includes('time')) return `It is ${new Date().toLocaleTimeString('en-US', { hour12: true })}, sir.`;
  if (lower.includes('screenshot')) return 'Capturing.';
  if (lower.includes('share my screen') || lower.includes('watch me') || lower.includes('watch my screen')) {
    return 'Ready.';
  }
  if (lower.includes('share your screen') || lower.includes('show me what you') || lower.includes('show your screen')) {
    return 'Sharing.';
  }
  if (lower.includes('stop sharing')) return 'Stopping.';
  return null;
}

/** AI generate video/image — Mira pipeline (do not require saying "mira") */
function isMiraCommand(text) {
  const lower = text.toLowerCase();
  // Upload / connect YouTube MUST win before the generic youtube early-exit
  if (/\b(connect|link|authorize)\b.{0,20}\byoutube\b/.test(lower)) return true;
  if (/\b(schedule|auto[\s-]?post|auto[\s-]?upload)\b.{0,40}\b(short|shorts|reel|viral|growth)\b/.test(lower)) return true;
  if (/\bschedule\s+shorts?\b/.test(lower)) return true;
  if (/\b(stop|pause|cancel)\s+(?:the\s+)?(?:shorts?\s+)?schedule\b/.test(lower)) return true;
  if (/\b(schedule\s+status|add\s+(?:schedule\s+)?topics?)\b/.test(lower)) return true;
  if (/\b(youtube\s+analytics|shorts?\s+analytics|grow\s+my\s+topics|suggest\s+topics)\b/.test(lower)) return true;
  if (/\b(export\s+(?:to\s+)?(?:reels?|tiktok|instagram)|export\s+(?:last\s+)?(?:short|video)|reply\s+to\s+comments?|clip\s+library)\b/.test(lower)) return true;
  if (/\b(clip\s+(?:this|the|last|my)|make\s+clips|cut\s+into\s+shorts|clip\s+into\s+shorts|turn\s+into\s+shorts|slice\s+into\s+shorts)\b/.test(lower)) return true;
  if (/\bclipping\b/.test(lower) && /\b(last|this|video|clip|it)\b/.test(lower)) return true;
  if (/\b(viral|growth|grow|clipping)\b.{0,30}\b(short|shorts|reel|youtube)\b/.test(lower)) return true;
  if (/\b(post|publish|drop)\s+(?:a\s+)?(?:viral\s+|growth\s+)?short\b/.test(lower)) return true;
  if (/\bpost\s+(?:a\s+)?short\s+about\b/.test(lower)) return true;
  if (/\b(upload|post|publish)\b.{0,40}\byoutube\b/.test(lower) && !/\b(make|create|generate)\b/.test(lower)) return true;
  if (/\b(post|upload)\s+(?:this|it|last|that|the)\s+(?:video|clip|short|reel)\b/.test(lower)) return true;
  if (/\b(title\s*[:=]|captions?\s*[:=]|description\s*[:=]|post\s+now|upload\s+now)\b/.test(lower)) return true;
  // Watch/search YouTube — not Mira
  if (/\byoutube\b/.test(lower) && !/\b(make|create|generate|render|shorts?|reel|story|upload|post|publish|connect|authorize)\b/.test(lower)) return false;
  if (/\b(search|find|play|look\s*up)\b.{0,40}\b(video|clip)\b/.test(lower) && !/\b(make|create|generate|render)\b/.test(lower)) {
    return false;
  }
  if (/(?:mira\s+)?rate\s+(?:this\s+)?(?:video|image|media)?\s*[1-5]\b/.test(lower)) return true;
  if (/\bmira_rate\s+[1-5]\b/.test(lower)) return true;
  if (/\b(mira\s+status|status\s+of\s+mira)\b/.test(lower)) return true;
  if (/\b(office\s*(day|routine|series)|daily\s+office|9\s*-?\s*to\s*-?\s*5|agent\s+office|day\s+in\s+the\s+(life|office))\b/.test(lower)) {
    return true;
  }
  if (/\b(make|create|generate)\b.{0,30}\boffice\b/.test(lower) && /\b(day|routine|video|episode)\b/.test(lower)) {
    return true;
  }
  // Format / mood replies after Mira asks (1-6, shorts, reels, funny…)
  if (/^[\s#]*[1-6]\b/.test(lower)) return true;
  if (/\b(youtube\s+shorts?|instagram\s+reels?|instagram\s+stories?|tiktok|facebook\s+reels?|shorts?|reels?|stories)\b/.test(lower)
      && lower.split(/\s+/).length <= 8) return true;
  if (/\b(crop|reframe|trim|mute|speed)\b.{0,40}\b(video|clip|reel|short|this|last|it)\b/.test(lower)) return true;
  if (/\b(make\s+(?:it|this|last\s+video)\s+(?:vertical|horizontal|shorts?|reels?|stories|faster|slower|mute))\b/.test(lower)) return true;
  if (/\b(make|create|generate|render|produce|shoot|edit|build|craft|compose)\b.{0,80}\b(an?\s+)?(ai\s+)?(video|clip|reel|short|shorts|film|movie|montage|image|picture|photo|still)\b/.test(lower)) {
    return true;
  }
  if (/\b(i\s+want|i\s+need|i'?d\s+like|can\s+you|could\s+you|please|wanna).{0,60}\b(an?\s+)?(ai\s+)?(video|clip|reel|film|movie|image|picture|photo)\b/.test(lower)) {
    return true;
  }
  if (/\b(using|with|from)\s+my\s+(uploads?|videos?|clips?|images?|photos?|pictures?|media|footage)\b/.test(lower)) {
    return true;
  }
  if (/\bmira\b/.test(lower) && /\b(video|image|clip|reel|picture|photo|upload|film|short|story)\b/.test(lower)) return true;
  // Platform / screen-tour asks (CryptoRafts, HF, …) — even without "create"
  if (/\b(full\s+)?(platform\s+)?(video|tour|walkthrough|screen\s*record)\b.{0,40}\b(of|for|on)\b/.test(lower)) return true;
  if (/\b(screen\s*record|record\s+(?:the\s+)?(?:live\s+)?(?:site|page|platform))\b/.test(lower)) return true;
  if (/\b(crypto\s*rafts?|cryptorafts|hugging\s*face|chatgpt|cursor\s+ai|gemini|google\s+gemini)\b/.test(lower)
      && /\b(video|tour|record|clip|mira)\b/.test(lower)) return true;
  return false;
}

// ── Wake (instant, no server) ───────────────────────
async function handleWakeWord() {
  const now = Date.now();
  if (now - lastWakeAt < 1500) return;
  lastWakeAt = now;
  postWakeUntil = now + POST_WAKE_LISTEN_MS;
  playWakePing();
  pulseHud();
  addMessage('user', 'Hey Jarvis');
  addMessage('jarvis', 'Yes?');
  // Short ack so mic unmutes sooner for the actual command
  await instantSpeak('Yes?');
  voiceHint.textContent = '🎙 Listening for your command…';
}

function isApiHuntCommand(text) {
  const lower = text.toLowerCase();
  if (/api\s*key|get\s+(me\s+)?(the\s+)?api|fetch\s+api|grab\s+api|get\s+.*\s+key|refresh\s+\w+\s+api/.test(lower)) return true;
  if (/\b(get|fetch|grab|sign\s*in|login)\b/.test(lower) && /\b(key|keys|api)\b/.test(lower)) return true;
  if (/from there|this ai|that ai|from here|that site/.test(lower) && /\b(get|fetch|api|key)\b/.test(lower)) return true;
  if (/\b(get|fetch|grab)\b/.test(lower) && /\b(groq|fish|eleven|11\s*labs?|openrouter|nvidia|gemini|anthropic|openai|cursor|together|hugging|deepseek|claude|lab)\b/.test(lower)) return true;
  // Explicit .env save — Phase 1, never Groq
  if (/\b(save|put|post|write|add)\b.{0,40}\b(to|into|in)\b.{0,20}\.?env\b/.test(lower)) return true;
  if (/\b(save|put|post|write|add)\b.{0,20}\.?env\b/.test(lower) && /\b(api|key|groq|fish|eleven|openai|gemini|anthropic)\b/.test(lower)) return true;
  return false;
}

/** Sheet count / remaining / missing — must stay on /api/fast, never brain */
function isApiCountCommand(text) {
  const lower = text.toLowerCase();
  if (!/\bapis?\b/.test(lower)) return false;
  if (/\b(get|fetch|grab|sign\s*in|login)\b.{0,40}\b(api\s*key|key)\b/.test(lower)) return false;
  if (/get all api|fetch all api|paste api|paste apis|put apis/.test(lower)) return false;
  return (
    /how\s+many/.test(lower)
    || /\b(left|remaining|missing|still|empty|without)\b/.test(lower)
    || /\b(count|which|status|check)\b/.test(lower)
  );
}

async function apiPost(path, body, timeoutMs) {
  let lastErr = null;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const res = await fetch(`${API}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(timeoutMs),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (e) {
      lastErr = e;
      if (attempt < 1) await new Promise(r => setTimeout(r, 150));
    }
  }
  throw lastErr || new Error('request failed');
}

async function pollMiraResult(maxMs = 1200000) {
  const start = Date.now();
  let lastProgress = '';
  let sawRunning = false;
  let baselineUrl = null;
  let baselineResponse = null;
  let baselineJobId = null;
  try {
    const snap = await fetch(`${API}/api/mira-status`, { signal: AbortSignal.timeout(5000) });
    const base = await snap.json();
    baselineUrl = base.media_url || null;
    baselineResponse = base.response || null;
    baselineJobId = base.job_id || null;
    // If a job is already mid-flight, count that as live work
    if (base.running || base.status === 'running') sawRunning = true;
  } catch (e) { /* ignore */ }
  setState('ASSEMBLING');
  while (Date.now() - start < maxMs) {
    const wait = /upload|recording|chrome|platform|signing|encoding|tour|on /i.test(lastProgress)
      ? 900
      : 1800;
    await new Promise(r => setTimeout(r, wait));
    try {
      const res = await fetch(`${API}/api/mira-status`, { signal: AbortSignal.timeout(5000) });
      const data = await res.json();
      if (data.running || data.status === 'running') {
        sawRunning = true;
        setState('ASSEMBLING');
        if (data.response && data.response !== lastProgress) {
          lastProgress = data.response;
          speakMiraProgress(data.response);
        }
        continue;
      }
      // Ignore STALE done from a previous video — wait until we saw a live job
      // or the finished media/response/job actually changed.
      if (data.status === 'done' || data.status === 'error') {
        const url = data.media_url || null;
        const resp = data.response || '';
        const jid = data.job_id || null;
        const fresh =
          sawRunning ||
          (url && url !== baselineUrl) ||
          (jid && jid !== baselineJobId) ||
          (resp && resp !== baselineResponse);
        if (!fresh && data.status === 'done') {
          // Still the previous finished job — keep waiting for the new one
          continue;
        }
        setState('ONLINE');
        if (data.status === 'done' && url) {
          try { window.open(url, '_blank', 'noopener'); } catch (e) { /* ignore */ }
        }
        return {
          response: data.response || 'Mira finished, sir.',
          media_url: url,
        };
      }
    } catch (e) { /* keep polling */ }
  }
  setState('ONLINE');
  return null;
}

async function pollHuntResult(maxMs = 180000) {
  const start = Date.now();
  let lastProgress = '';
  while (Date.now() - start < maxMs) {
    await new Promise(r => setTimeout(r, 3000));
    try {
      const res = await fetch(`${API}/api/hunt-status`, { signal: AbortSignal.timeout(5000) });
      const data = await res.json();
      if (data.status === 'done' || data.status === 'error') {
        return data.response || 'Hunt finished, sir.';
      }
      if (data.status === 'running' && data.response && data.response !== lastProgress) {
        lastProgress = data.response;
        addMessage('jarvis', data.response);
      }
    } catch (e) { /* keep polling */ }
  }
  return null;
}

// ── Commands — mute mic entire time ─────────────────
async function sendCommand(text, showUser = true) {
  text = text.trim();
  if (!text || shouldSkipCommand(text) || commandBusy) return;

  commandBusy = true;
  muteMic();
  postWakeUntil = 0;

  if (showUser) addMessage('user', text);
  commandInput.value = '';

  const isHunt = isApiHuntCommand(text);
  const isMira = !isHunt && isMiraCommand(text);
  const isCount = !isHunt && !isMira && isApiCountCommand(text);
  const isYtUpload = /\b(upload|post|publish)\b.{0,40}\byoutube\b/i.test(text)
    || /\b(post|upload)\s+(?:this|it|last|that|the)\s+(?:video|clip|short|reel)\b/i.test(text)
    || /\b(title\s*[:=]|captions?\s*[:=]|description\s*[:=]|post\s+now|upload\s+now)\b/i.test(text);
  const isGrowth = /\b(viral|growth|grow)\b.{0,30}\b(short|shorts|reel)/i.test(text)
    || /\b(post|publish|drop)\s+(?:a\s+)?(?:viral\s+|growth\s+)?short\b/i.test(text)
    || /\bpost\s+(?:a\s+)?short\s+about\b/i.test(text);
  const isSchedule = /\b(schedule|auto[\s-]?post)\b.{0,40}\b(short|shorts|reel|viral)/i.test(text)
    || /\bschedule\s+shorts?\b/i.test(text)
    || /\b(stop|pause)\s+(?:the\s+)?(?:shorts?\s+)?schedule\b/i.test(text)
    || /\bschedule\s+status\b/i.test(text);
  const isClip = /\b(clip\s+(?:this|the|last|my)|make\s+clips|cut\s+into\s+shorts|clip\s+into\s+shorts|turn\s+into\s+shorts)\b/i.test(text)
    || (/\bclipping\b/i.test(text) && /\b(last|this|video|clip|it)\b/i.test(text));
  const ack = isHunt
    ? 'Signing in now. Watch Chrome.'
    : isSchedule
      ? 'Shorts schedule updated.'
      : isClip
        ? 'Clipping into Shorts — cutting punchy verticals.'
        : isGrowth
          ? 'Growth Short — make, hook, publish public.'
          : isYtUpload
            ? 'Watch Chrome — publishing Short public.'
            : isMira
              ? 'Mira assigned — watch progress live (Chrome opens for platform tours).'
              : instantAck(text);

  // Speak short ack only when useful — never "Right away" + full reply (double TTS lag)
  if (ack) {
    addMessage('jarvis', ack);
    let speakBit = ack;
    if (isHunt) speakBit = 'Signing in.';
    else if (isSchedule) speakBit = 'Scheduled.';
    else if (isClip) speakBit = 'Clipping.';
    else if (isGrowth || isYtUpload) speakBit = 'Uploading.';
    else if (isMira) speakBit = 'Generating.';
    await instantSpeak(speakBit);
  } else {
    setState('THINKING');
  }

  // Local instant answers (time) — skip server round-trip
  if (ack && isSelfContainedAck(text) && /\btime\b/i.test(text) && !isHunt && !isMira) {
    commandBusy = false;
    scheduleUnmute();
    voiceHint.textContent = '🎙 Say "Hey Jarvis" + your command';
    return;
  }

  // Count/status stays on fast path; Mira/hunt get longer windows
  const timeout = isHunt ? 45000 : (isMira ? 45000 : (isCount ? 20000 : 15000));

  try {
    let data;
    // Mira video/image MUST hit /api/mira (starts live job + mira-status).
    // Crew-first was returning "Assigned Mira" while HUD read a STALE done video
    // and claimed "ready" in seconds without recording.
    let crew = null;
    if (isMira) {
      data = await apiPost('/api/mira', { message: text }, timeout);
      data.handled = true;
    } else {
      try {
        crew = await apiPost('/api/crew/command', { message: text }, Math.min(timeout, 25000));
      } catch (_) { crew = null; }

      if (crew && crew.routed && !crew.handle_locally) {
        data = {
          response: crew.response || crew.message || 'Assigned.',
          handled: true,
          source: 'crew',
          agent_id: crew.agent_id,
          poll: crew.poll,
        };
      } else if (isHunt) {
        data = await apiPost('/api/hunt', { message: text }, timeout);
        data.handled = true;
      } else {
        data = await apiPost('/api/fast', { message: text }, timeout);

        if (!data.handled) {
          // Never send sheet API counts to the slow brain path
          if (isCount) {
            data = { response: 'Could not read the sheet yet, sir. Save the sheet link first.', handled: true };
          } else {
            data = await apiPost('/api/command', { message: text, speak: false }, 20000);
          }
        }
      }
    }

    let reply = data.response || 'Done, sir.';
    const viaCrewHunter = data.source === 'crew' && data.agent_id === 'hunter';
    const viaCrewMira = data.source === 'crew' && data.agent_id === 'mira';

    if (isHunt || viaCrewHunter) {
      addMessage('jarvis', reply);
      // Don't stack long acks — short progress only
      if (/already have|Got your|Saved your|gsk_|sk_|Saved to \.env/i.test(reply) && !/Chrome is opening/i.test(reply)) {
        const hasKey = /gsk_|sk_|sk-|AIza|nvapi/i.test(reply);
        if (hasKey || /already have|Saved your|Saved to \.env/i.test(reply)) {
          await instantSpeak(hasKey ? 'Got the key.' : 'Done.');
        }
      } else {
        await instantSpeak('Working.');
        const huntResult = await pollHuntResult(240000);
        if (huntResult) {
          reply = huntResult;
          addMessage('jarvis', huntResult);
          const hasKey = /gsk_|sk_|sk-|AIza|nvapi/i.test(huntResult);
          if (hasKey) {
            await instantSpeak('Got the key.');
          } else {
            const short = huntResult.split(/[.!?\n]/)[0];
            if (short) await instantSpeak(short.slice(0, 100) + '.');
          }
        }
      }
    } else if (isMira || isYtUpload || isGrowth || viaCrewMira) {
      addMessage('jarvis', reply);
      const needsWait =
        /generating|uploading|growth mode|clipping mode|one to two minutes|under a minute|already (generating|busy)|chrome tab|watch chrome|when it'?s live|publishing|assigned mira|watch them work|watch agent town|Generating your|screen record|recording live|encoding|mira is working/i.test(reply) ||
        (isMira && data.handled);
      if (needsWait) {
        await instantSpeak(/upload/i.test(reply) ? 'Uploading.' : 'Working.');
        const miraResult = await pollMiraResult(1200000);
        if (miraResult) {
          const msg = typeof miraResult === 'string' ? miraResult : (miraResult.response || 'Done, sir.');
          addMessage('jarvis', msg);
          if (/^done\b/i.test(msg) || /posted to youtube/i.test(msg)) {
            await instantSpeak('Done.');
          } else {
            const short = msg.split(/[.!?\n]/).filter(Boolean)[0]?.trim();
            if (short) await instantSpeak((short.length > 100 ? short.slice(0, 100) + '…' : short).replace(/\.*$/, '.'));
            else scheduleUnmute();
          }
        } else {
          addMessage('jarvis', 'Still working, sir. Check again in a moment.');
          await instantSpeak('Still working.');
        }
      } else {
        const short = reply.split(/[.!?\n]/).filter(Boolean)[0]?.trim();
        if (short) await instantSpeak(short.endsWith('.') ? short : short + '.');
        else scheduleUnmute();
      }
    } else if (ack && isSelfContainedAck(text)) {
      // Already answered (e.g. time) — show server reply in chat only if different
      if (reply && reply !== ack) addMessage('jarvis', reply);
      scheduleUnmute();
    } else if (!ack || reply !== ack) {
      addMessage('jarvis', reply);
      // Speak first sentence only — skip long TTS that blocks listening
      const short = reply.split(/[.!?\n]/).filter(Boolean)[0]?.trim();
      if (short && short.length > 2 && short.length < 120) {
        await instantSpeak(short.endsWith('.') ? short : short + '.');
      } else if (short && short.length >= 120) {
        await instantSpeak(short.slice(0, 100).trim() + '…');
      } else {
        scheduleUnmute();
      }
    } else {
      scheduleUnmute();
    }
  } catch (e) {
    if (isHunt) {
      addMessage('jarvis', 'Chrome is working in the background, sir. I will post the key when ready.');
      const huntResult = await pollHuntResult(240000);
      if (huntResult) {
        addMessage('jarvis', huntResult);
        await instantSpeak(/gsk_|sk_|sk-/i.test(huntResult) ? 'Got the key.' : 'Check Chrome.');
      }
    } else if (isMira) {
      addMessage('jarvis', 'Mira is working in the background, sir.');
      const miraResult = await pollMiraResult(1200000);
      if (miraResult) {
        const msg = typeof miraResult === 'string' ? miraResult : (miraResult.response || 'Done.');
        addMessage('jarvis', msg);
        await instantSpeak('Done.');
      }
    } else if (!ack) {
      try {
        const data = await apiPost('/api/fast', { message: text }, 12000);
        if (data.response) {
          addMessage('jarvis', data.response);
          await instantSpeak('Done.');
        } else {
          addMessage('jarvis', 'Connection issue, sir. Try that command again.');
          await instantSpeak('Try again.');
        }
      } catch (_) {
        addMessage('jarvis', 'Connection issue, sir. Try that command again.');
        await instantSpeak('Try again.');
      }
    } else {
      scheduleUnmute();
    }
  }

  commandBusy = false;
  if (!micMuted) scheduleUnmute();
  voiceHint.textContent = '🎙 Say "Hey Jarvis" + your command';
}

function processFinalSpeech(raw) {
  if (!raw || micMuted || commandBusy) return;
  const trimmed = raw.trim();
  if (trimmed.length < 2) return;

  if (isWakeOnly(trimmed)) {
    handleWakeWord();
    return;
  }

  const { hasWake, command } = normalizeCommand(trimmed);
  const inPostWake = Date.now() < postWakeUntil;

  // Prefer wake-tagged or post-wake commands (12s window after "Yes?")
  let toRun = '';
  if (hasWake && command.length > 1) {
    toRun = command;
  } else if (inPostWake && command.length > 1) {
    toRun = command;
  } else if (inPostWake && !hasWake) {
    toRun = trimmed;
  } else if (!hasWake && command.length > 1) {
    // Still allow bare commands (typed / continuous mode)
    toRun = command.length > 1 ? command : trimmed;
  } else if (!hasWake) {
    toRun = trimmed;
  }

  if (!toRun || toRun.length < 2) return;

  if (hasWake && command.length > 1) addMessage('user', `Hey Jarvis, ${toRun}`);
  sendCommand(toRun, !(hasWake && command.length > 1));
}

function queueFinalSpeech(chunk) {
  pendingFinal = (pendingFinal ? `${pendingFinal} ${chunk}` : chunk).trim();
  if (finalDebounceTimer) clearTimeout(finalDebounceTimer);
  finalDebounceTimer = setTimeout(() => {
    finalDebounceTimer = null;
    const full = pendingFinal;
    pendingFinal = '';
    if (full) processFinalSpeech(full);
  }, FINAL_DEBOUNCE_MS);
}

// ── Voice — FINAL results only (debounce full sentence) ──
function initSpeech() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    voiceHint.textContent = 'Use Chrome for voice. Type commands below.';
    micBtn.disabled = true;
    return;
  }

  recognition = new SR();
  recognition.continuous = true;
  recognition.interimResults = true; // show live text only — never execute interim
  recognition.lang = STT_LANG;
  recognition.maxAlternatives = 3; // keep best transcript

  recognition.onresult = (e) => {
    // IGNORE everything while Jarvis talks or processes
    if (micMuted || commandBusy) return;

    let interim = '';
    let finalText = '';

    for (let i = e.resultIndex; i < e.results.length; i++) {
      const alt = e.results[i][0];
      const t = alt ? alt.transcript : '';
      if (e.results[i].isFinal) finalText += t;
      else interim += t;
    }

    // Show what user is saying (live preview only)
    const preview = (interim || finalText).trim();
    if (preview) {
      voiceHint.textContent = interim
        ? `🎙 "${preview}..."`
        : `🎙 "${preview}"`;
    }

    // ONLY act on FINAL speech — debounce so mid-phrase finals merge into one sentence
    if (finalText.trim()) {
      queueFinalSpeech(finalText.trim());
    }
  };

  recognition.onerror = (e) => {
    if (e.error === 'not-allowed') {
      voiceHint.textContent = '⚠ Allow microphone in Chrome settings';
      isListening = false;
      micBtn.classList.remove('active');
    }
    // aborted / no-speech: ignore — onend restarts
  };

  recognition.onend = () => {
    if (isListening && !micMuted && !commandBusy) {
      restartRecognitionSoon(120);
    }
  };
}

function startListening() {
  if (!recognition || isListening) return;
  isListening = true;
  micMuted = false;
  micBtn.classList.add('active');
  setState('LISTENING');
  try { recognition.start(); } catch (e) { /* ok */ }
  voiceHint.textContent = '🎙 Speak your full command, then pause';
}

function stopListening() {
  isListening = false;
  micMuted = false;
  micBtn.classList.remove('active');
  if (finalDebounceTimer) { clearTimeout(finalDebounceTimer); finalDebounceTimer = null; }
  pendingFinal = '';
  if (recognition) {
    try { recognition.stop(); } catch (e) { /* ok */ }
  }
  setState('ONLINE');
}

function toggleMic() {
  if (isListening) stopListening();
  else startListening();
}

if (window.speechSynthesis) {
  loadBritishVoice();
  speechSynthesis.onvoiceschanged = loadBritishVoice;
}
initSpeech();

// ── WebSocket ───────────────────────────────────────
function connectWS() {
  try {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${location.host}/ws`);
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === 'status') setState(msg.status);
      // Server asks HUD to speak so Owner hears Jarvis during live Mira jobs
      if (msg.type === 'speak' && msg.text) {
        const line = String(msg.text || '').trim();
        if (line) {
          if (msg.chat !== false) addMessage('jarvis', line);
          instantSpeak(line).catch(() => {});
        }
      }
      if (msg.type === 'crew' && msg.event) {
        (window.handleCrewEvent || handleCrewEvent)(msg.event);
      }
      if (msg.type === 'screen_share_prompt') {
        if (msg.mode === 'user') startUserScreenShare();
        if (msg.mode === 'jarvis') startJarvisScreenShare();
      }
      if (msg.type === 'screen_share') {
        if (msg.user === false) stopUserScreenShare(false);
        if (msg.jarvis === true) showJarvisScreenPanel(true);
        if (msg.jarvis === false) stopJarvisScreenShare(false);
      }
    };
    ws.onclose = () => setTimeout(connectWS, 8000);
  } catch (e) { /* ok */ }
}
connectWS();

// ── Screen share (user → Jarvis + Jarvis → HUD) ─────
const shareMyBtn = document.getElementById('share-my-screen-btn');
const jarvisScreenBtn = document.getElementById('jarvis-screen-btn');
const shareStatus = document.getElementById('share-status');
const jarvisPanel = document.getElementById('jarvis-screen-panel');
const jarvisImg = document.getElementById('jarvis-screen-img');
const jarvisPlaceholder = document.getElementById('jarvis-screen-placeholder');
const jarvisMeta = document.getElementById('jarvis-screen-meta');
const jarvisClose = document.getElementById('jarvis-screen-close');

function setShareStatus(text) {
  if (shareStatus) shareStatus.textContent = text;
}

function showJarvisScreenPanel(show) {
  if (!jarvisPanel) return;
  if (show) jarvisPanel.hidden = false;
  else jarvisPanel.hidden = true;
}

async function uploadUserFrame(blob) {
  if (userFrameUploading) return; // drop frame if previous upload still in flight
  userFrameUploading = true;
  try {
    const fd = new FormData();
    fd.append('file', blob, 'frame.jpg');
    await fetch(`${API}/api/screen/user/frame`, { method: 'POST', body: fd });
  } finally {
    userFrameUploading = false;
  }
}

function captureAndSendFrame(video) {
  if (!video || video.readyState < 2) return;
  if (!userFrameCanvas) userFrameCanvas = document.createElement('canvas');
  const canvas = userFrameCanvas;
  const scale = Math.min(1, USER_MAX_WIDTH / (video.videoWidth || USER_MAX_WIDTH));
  canvas.width = Math.max(1, Math.floor((video.videoWidth || 640) * scale));
  canvas.height = Math.max(1, Math.floor((video.videoHeight || 360) * scale));
  const ctx = canvas.getContext('2d', { alpha: false });
  ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
  canvas.toBlob((blob) => {
    if (blob) uploadUserFrame(blob).catch(() => {});
  }, 'image/jpeg', USER_JPEG_QUALITY);
}

async function startUserScreenShare() {
  if (userSharing) return;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
    setShareStatus('Screen capture not supported in this browser');
    addMessage('jarvis', 'This browser cannot share screen, sir. Use Chrome.');
    return;
  }

  // Show watching immediately — don't block mic/command UI
  setShareStatus('Watching…');
  if (shareMyBtn) {
    shareMyBtn.classList.add('active');
    shareMyBtn.textContent = 'Stop sharing my screen';
  }

  let stream;
  try {
    stream = await navigator.mediaDevices.getDisplayMedia({
      video: { frameRate: { ideal: 8, max: 10 } },
      audio: false,
    });
  } catch (e) {
    setShareStatus('Permission denied or cancelled');
    if (shareMyBtn) {
      shareMyBtn.classList.remove('active');
      shareMyBtn.textContent = 'Share my screen';
    }
    return;
  }

  const track = stream.getVideoTracks()[0];
  if (!track) {
    setShareStatus('No video track');
    if (shareMyBtn) {
      shareMyBtn.classList.remove('active');
      shareMyBtn.textContent = 'Share my screen';
    }
    return;
  }

  userShareStream = stream;
  const video = document.createElement('video');
  video.srcObject = userShareStream;
  video.muted = true;
  await video.play().catch(() => {});

  userSharing = true;
  setShareStatus('Watching your screen…');

  // Fire-and-forget — keep UI responsive
  fetch(`${API}/api/screen/user/start`, { method: 'POST' }).catch(() => {});

  captureAndSendFrame(video);
  if (userShareTimer) clearInterval(userShareTimer);
  userShareTimer = setInterval(() => captureAndSendFrame(video), USER_FRAME_INTERVAL_MS);

  track.addEventListener('ended', () => stopUserScreenShare(true));
}

async function stopUserScreenShare(notifyServer) {
  if (userShareTimer) {
    clearInterval(userShareTimer);
    userShareTimer = null;
  }
  if (userShareStream) {
    userShareStream.getTracks().forEach((t) => t.stop());
    userShareStream = null;
  }
  userSharing = false;
  userFrameUploading = false;
  if (shareMyBtn) {
    shareMyBtn.classList.remove('active');
    shareMyBtn.textContent = 'Share my screen';
  }
  setShareStatus(jarvisSharing ? 'Jarvis screen live' : 'Idle');
  if (notifyServer !== false) {
    fetch(`${API}/api/screen/user/stop`, { method: 'POST' }).catch(() => {});
  }
}

function pollJarvisFrame() {
  if (!jarvisSharing || jarvisPollInFlight) return;
  const img = jarvisImg;
  if (!img) return;
  jarvisPollInFlight = true;
  const url = `${API}/api/screen/jarvis/frame?t=${Date.now()}`;
  fetch(url, { cache: 'no-store' })
    .then((res) => {
      if (!res.ok) throw new Error('no frame');
      const source = res.headers.get('X-Frame-Source') || '';
      if (jarvisMeta) jarvisMeta.textContent = source || 'live';
      return res.blob();
    })
    .then((blob) => {
      if (jarvisFrameUrl) URL.revokeObjectURL(jarvisFrameUrl);
      jarvisFrameUrl = URL.createObjectURL(blob);
      img.src = jarvisFrameUrl;
      if (jarvisPlaceholder) jarvisPlaceholder.classList.add('hidden');
    })
    .catch(() => {
      if (jarvisMeta) jarvisMeta.textContent = 'waiting…';
    })
    .finally(() => {
      jarvisPollInFlight = false;
    });
}

async function startJarvisScreenShare() {
  // Show panel immediately — don't wait on network
  jarvisSharing = true;
  showJarvisScreenPanel(true);
  if (jarvisScreenBtn) {
    jarvisScreenBtn.classList.add('active');
    jarvisScreenBtn.textContent = 'Hide Jarvis screen';
  }
  if (jarvisPlaceholder) jarvisPlaceholder.classList.remove('hidden');
  if (jarvisMeta) jarvisMeta.textContent = 'starting…';
  setShareStatus(userSharing ? 'Both shares active' : 'Jarvis screen live');

  fetch(`${API}/api/screen/jarvis/start`, { method: 'POST' }).catch(() => {
    setShareStatus('Could not start Jarvis share');
  });

  if (jarvisPollTimer) clearInterval(jarvisPollTimer);
  pollJarvisFrame();
  jarvisPollTimer = setInterval(pollJarvisFrame, JARVIS_POLL_MS);
}

async function stopJarvisScreenShare(notifyServer) {
  jarvisSharing = false;
  jarvisPollInFlight = false;
  if (jarvisPollTimer) {
    clearInterval(jarvisPollTimer);
    jarvisPollTimer = null;
  }
  if (jarvisFrameUrl) {
    URL.revokeObjectURL(jarvisFrameUrl);
    jarvisFrameUrl = null;
  }
  showJarvisScreenPanel(false);
  if (jarvisScreenBtn) {
    jarvisScreenBtn.classList.remove('active');
    jarvisScreenBtn.textContent = 'Show Jarvis screen';
  }
  setShareStatus(userSharing ? 'Watching your screen…' : 'Idle');
  if (notifyServer !== false) {
    fetch(`${API}/api/screen/jarvis/stop`, { method: 'POST' }).catch(() => {});
  }
}

if (shareMyBtn) {
  shareMyBtn.addEventListener('click', () => {
    if (userSharing) stopUserScreenShare(true);
    else startUserScreenShare();
  });
}
if (jarvisScreenBtn) {
  jarvisScreenBtn.addEventListener('click', () => {
    if (jarvisSharing) stopJarvisScreenShare(true);
    else startJarvisScreenShare();
  });
}
if (jarvisClose) {
  jarvisClose.addEventListener('click', () => stopJarvisScreenShare(true));
}

// ── Activate ────────────────────────────────────────
async function activateJarvis() {
  if (activateOverlay) {
    activateOverlay.classList.add('hidden');
    activateOverlay.style.display = 'none';
  }
  try {
    // Open Nexus HQ: guards → gate → employees walk to cabins
    if (typeof window.__townOpenDay === 'function') {
      window.__townOpenDay();
    }
    await unlockAudio();
    playWakePing();
    addMessage('jarvis', 'Opening Nexus HQ. Guards clearing the gate.');
    await instantSpeak('Opening Nexus HQ.');
    startListening();
  } catch (err) {
    console.warn('activate error', err);
    try {
      addMessage('jarvis', 'Online, sir. Mic may need a click on the microphone button.');
    } catch (_) { /* ok */ }
  }
}
window.__activateJarvis = activateJarvis;

if (activateBtn && activateOverlay) {
  activateBtn.addEventListener('click', (e) => {
    e.preventDefault();
    activateJarvis();
  });
}

sendBtn.addEventListener('click', () => sendCommand(commandInput.value));
commandInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendCommand(commandInput.value);
});
micBtn.addEventListener('click', toggleMic);

// ── Paste / drop screenshots into chat ──────────────
function blobExt(blob) {
  const t = (blob && blob.type) || 'image/png';
  if (t.includes('jpeg') || t.includes('jpg')) return 'jpg';
  if (t.includes('webp')) return 'webp';
  if (t.includes('gif')) return 'gif';
  return 'png';
}

function showPastedThumb(blob, caption) {
  try {
    const url = URL.createObjectURL(blob);
    const wrap = document.createElement('div');
    wrap.className = 'msg user';
    wrap.innerHTML = `<div class="bubble"><img src="${url}" alt="paste" style="max-width:min(320px,70vw);border-radius:8px;display:block;margin-bottom:6px" /><div>${caption || 'Screenshot pasted'}</div></div>`;
    chatLog.appendChild(wrap);
    chatLog.scrollTop = chatLog.scrollHeight;
  } catch (_) { /* ignore */ }
}

async function handlePastedImage(fileOrBlob, question) {
  if (!fileOrBlob) return;
  const blob = fileOrBlob;
  const name = (blob.name && String(blob.name)) || `screenshot_${Date.now()}.${blobExt(blob)}`;
  showPastedThumb(blob, 'Screenshot — reading…');
  if (miraUploadStatus) miraUploadStatus.textContent = 'Reading pasted screenshot…';
  const fd = new FormData();
  fd.append('file', blob, name);
  if (question) fd.append('question', question);
  try {
    const res = await fetch(`${API}/api/chat/paste-image`, { method: 'POST', body: fd });
    const data = await res.json();
    const text = data.text || data.message || 'Saved screenshot.';
    addMessage('jarvis', text);
    if (data.read_ok) {
      try { await instantSpeak('Screenshot read, sir.'); } catch (_) {}
    }
    refreshMiraUploadStatus();
  } catch (e) {
    addMessage('jarvis', 'Could not read that paste, sir. Try Mira Upload instead.');
  }
}

function extractImageFromClipboard(e) {
  const items = (e.clipboardData && e.clipboardData.items) || [];
  for (const it of items) {
    if (it.type && it.type.startsWith('image/')) {
      const f = it.getAsFile();
      if (f) return f;
    }
  }
  const files = (e.clipboardData && e.clipboardData.files) || [];
  for (const f of files) {
    if (f.type && f.type.startsWith('image/')) return f;
  }
  return null;
}

if (commandInput) {
  commandInput.addEventListener('paste', (e) => {
    const img = extractImageFromClipboard(e);
    if (!img) return;
    e.preventDefault();
    const q = (commandInput.value || '').trim();
    commandInput.value = '';
    handlePastedImage(img, q);
  });
}

if (chatLog) {
  chatLog.addEventListener('paste', (e) => {
    const img = extractImageFromClipboard(e);
    if (!img) return;
    e.preventDefault();
    handlePastedImage(img, (commandInput && commandInput.value) || '');
  });
  // Drag-drop screenshots onto chat
  chatLog.addEventListener('dragover', (e) => {
    e.preventDefault();
  });
  chatLog.addEventListener('drop', (e) => {
    e.preventDefault();
    const files = e.dataTransfer && e.dataTransfer.files;
    if (!files || !files.length) return;
    for (const f of files) {
      if (f.type && f.type.startsWith('image/')) {
        handlePastedImage(f, (commandInput && commandInput.value) || '');
        break;
      }
    }
  });
}

// ── Mira user media upload ─────────────────────────
const miraUploadBtn = document.getElementById('mira-upload-btn');
const miraUploadInput = document.getElementById('mira-upload-input');
const miraUploadStatus = document.getElementById('mira-upload-status');

async function refreshMiraUploadStatus() {
  if (!miraUploadStatus) return;
  try {
    const res = await fetch(`${API}/api/mira/uploads`, { signal: AbortSignal.timeout(5000) });
    const data = await res.json();
    const n = data.count || 0;
    miraUploadStatus.textContent = n
      ? `${n} file(s) ready — Mira uses YOUR uploads FIRST (Ctrl+V screenshot into chat also works)`
      : 'Ctrl+V a screenshot into chat, or Upload pics/clips — Mira uses them first.';
  } catch (_) {
    miraUploadStatus.textContent = 'Ctrl+V screenshot into chat to save + read it';
  }
}

async function uploadMiraFiles(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) return;
  if (miraUploadStatus) miraUploadStatus.textContent = `Uploading ${files.length}…`;
  const fd = new FormData();
  files.forEach((f) => fd.append('files', f));
  try {
    const res = await fetch(`${API}/api/mira/upload`, { method: 'POST', body: fd });
    const data = await res.json();
    const msg = data.message || (data.ok ? 'Uploaded.' : 'Upload failed.');
    if (miraUploadStatus) miraUploadStatus.textContent = msg;
    addMessage('jarvis', msg);
  } catch (e) {
    if (miraUploadStatus) miraUploadStatus.textContent = 'Upload failed.';
    addMessage('jarvis', 'Upload failed, sir.');
  }
}

if (miraUploadBtn && miraUploadInput) {
  miraUploadBtn.addEventListener('click', () => miraUploadInput.click());
  miraUploadInput.addEventListener('change', () => {
    uploadMiraFiles(miraUploadInput.files).finally(() => {
      miraUploadInput.value = '';
      refreshMiraUploadStatus();
    });
  });
  refreshMiraUploadStatus();
}

briefingBtn.addEventListener('click', async () => {
  commandBusy = true;
  muteMic();
  setState('THINKING');
  try {
    const res = await fetch(`${API}/api/briefing`, { signal: AbortSignal.timeout(12000) });
    const data = await res.json();
    addMessage('jarvis', data.response);
    await instantSpeak(data.response.split('.').slice(0, 2).join('.') + '.');
  } catch (e) {
    addMessage('jarvis', 'Briefing unavailable, sir.');
    await instantSpeak('Unavailable.');
  }
  commandBusy = false;
  scheduleUnmute();
});

document.querySelectorAll('.quick-btn').forEach(btn => {
  btn.addEventListener('click', () => sendCommand(btn.dataset.cmd));
});

// ── Agent Floor (reel-style: each agent = live screen) ─
const agentScreensEl = document.getElementById('agent-screens');
const agentChatSeen = new Set();
let crewLastSeq = 0;

function ensureAgentScreen(agent) {
  if (!agentScreensEl || agentScreensEl.hidden || !agent || !agent.id) return null;
  let el = agentScreensEl.querySelector(`[data-id="${agent.id}"]`);
  if (el) return el;
  el = document.createElement('article');
  el.className = 'agent-screen';
  el.dataset.id = agent.id;
  el.innerHTML = `
    <div class="agent-screen-titlebar">
      <span class="dots"><i></i><i></i><i></i></span>
      <span class="agent-screen-name">${escapeHtml((agent.name || agent.id).toUpperCase())} · ${(agent.station || agent.role || '').toUpperCase()}</span>
      <span class="agent-screen-badge idle" data-badge>IDLE</span>
    </div>
    <div class="agent-screen-meta">${escapeHtml(agent.title || agent.role || '')}</div>
    <div class="agent-screen-activity" data-activity>${escapeHtml(agent.activity || 'Standing by')}</div>
    <div class="agent-screen-chat" data-chat></div>
  `;
  agentScreensEl.appendChild(el);
  return el;
}

function updateAgentScreen(agent) {
  const el = ensureAgentScreen(agent);
  if (!el) return;
  const badge = el.querySelector('[data-badge]');
  const act = el.querySelector('[data-activity]');
  const st = String(agent.status || 'idle').toLowerCase();
  if (badge) {
    badge.textContent = st;
    badge.className = `agent-screen-badge ${st}`;
  }
  if (act) act.textContent = agent.activity || '—';
}

function pushAgentLine(agentId, ev) {
  if (!ev || !ev.text) return;
  const key = ev.id || `${ev.seq}-${ev.from}-${ev.text.slice(0, 24)}`;
  if (agentChatSeen.has(key)) return;
  agentChatSeen.add(key);

  // Show on involved agent screens (and always on from-agent)
  const targets = new Set();
  if (ev.from && ev.from !== 'owner' && ev.from !== 'system') targets.add(ev.from);
  if (ev.to && ev.to !== 'owner') targets.add(ev.to);
  if (targets.size === 0 && agentId) targets.add(agentId);

  const when = ev.ts ? new Date(ev.ts * 1000).toLocaleTimeString() : '';
  for (const id of targets) {
    let el = agentScreensEl && agentScreensEl.querySelector(`[data-id="${id}"]`);
    if (!el) {
      el = ensureAgentScreen({ id, name: id, station: id === 'mira' ? 'Studio' : 'Command', status: 'idle', activity: '…' });
    }
    if (!el) continue;
    const chat = el.querySelector('[data-chat]');
    if (!chat) continue;
    const line = document.createElement('div');
    line.className = 'agent-line';
    const who = `${(ev.from || '?').toUpperCase()}${ev.to ? ' → ' + String(ev.to).toUpperCase() : ''}`;
    line.innerHTML = `<div class="al-meta"><span>${escapeHtml(who)}</span><span>${escapeHtml(when)}</span></div>
      <div class="al-body">${escapeHtml(ev.text)}</div>`;
    chat.appendChild(line);
    while (chat.children.length > 40) chat.removeChild(chat.firstChild);
    chat.scrollTop = chat.scrollHeight;
  }
}

let _lastMiraSpeak = '';
let _miraSpeakAt = 0;

function speakMiraProgress(text) {
  const line = String(text || '').replace(/[…]/g, ' ').trim().slice(0, 110);
  if (!line) return;
  const now = Date.now();
  // Don't spam TTS — one line every ~4s max, skip exact repeats
  if (line === _lastMiraSpeak || now - _miraSpeakAt < 4000) return;
  _lastMiraSpeak = line;
  _miraSpeakAt = now;
  addMessage('jarvis', line);
  setState('SPEAKING');
  instantSpeak(line.endsWith('.') ? line : line + '.').catch(() => {});
}

function handleCrewEvent(ev) {
  if (!ev) return;
  crewLastSeq = Math.max(crewLastSeq, Number(ev.seq) || 0);
  if (ev.kind === 'status' && ev.from) {
    updateAgentScreen({
      id: ev.from,
      status: ev.status || (ev.extra && ev.extra.status) || 'working',
      activity: ev.activity || ev.text || '',
      name: ev.from,
    });
  }
  if (ev.kind === 'chat' || ev.kind === 'progress' || ev.kind === 'system') {
    pushAgentLine(ev.from, ev);
  }
  // Live Mira progress → Jarvis speaks so Owner hears generation
  if (
    (ev.kind === 'progress' || ev.kind === 'chat') &&
    String(ev.from || '').toLowerCase() === 'mira' &&
    (ev.text || ev.activity)
  ) {
    speakMiraProgress(ev.text || ev.activity);
  }
  if (ev.kind === 'status' || ev.kind === 'task') {
    // soft refresh badges
    refreshCrewFloor(false);
  }
}
window.handleCrewEvent = handleCrewEvent;

async function refreshCrewFloor(seedChat) {
  if (!agentScreensEl) return;
  try {
    const res = await fetch(`${API}/api/crew/state`, { signal: AbortSignal.timeout(8000) });
    const data = await res.json();
    const agents = Object.values(data.agents || {});
    agents.forEach(updateAgentScreen);
    if (seedChat) {
      (data.chat || []).slice(-30).forEach((ev) => pushAgentLine(ev.from, ev));
    }
  } catch (_) { /* ignore */ }
}

async function pollCrewEvents() {
  try {
    const res = await fetch(`${API}/api/crew/events?since=${crewLastSeq}`, { signal: AbortSignal.timeout(8000) });
    const data = await res.json();
    (data.events || []).forEach(handleCrewEvent);
  } catch (_) { /* ignore */ }
}

if (agentScreensEl && !agentScreensEl.hidden) {
  refreshCrewFloor(true);
  setInterval(() => refreshCrewFloor(false), 8000);
  setInterval(pollCrewEvents, 3500);
}

// Always narrate live Mira jobs — even if chat wasn't used to start them
let _miraWatchLast = '';
async function watchMiraSpeech() {
  try {
    const res = await fetch(`${API}/api/mira-status`, { signal: AbortSignal.timeout(4000) });
    const data = await res.json();
    if (!(data.running || data.status === 'running')) return;
    const line = String(data.response || '').trim();
    if (line && line !== _miraWatchLast) {
      _miraWatchLast = line;
      setState('ASSEMBLING');
      speakMiraProgress(line);
    }
  } catch (_) { /* ignore */ }
}
setInterval(watchMiraSpeech, 5000);
watchMiraSpeech();

console.log(`JARVIS UI v${APP_VERSION} — Iron Man HUD`);
