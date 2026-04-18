// ── DOM refs ──────────────────────────────────────────────────────────────────
const chatLog      = document.getElementById('chat-log');
const input        = document.getElementById('input');
const btnSend      = document.getElementById('btn-send');
const btnMic       = document.getElementById('btn-mic');
const audioFile    = document.getElementById('audio-file');
const resultOverlay = document.getElementById('result-overlay');

const logicPct     = document.getElementById('logic-pct');
const enginePill   = document.getElementById('engine-pill');
const workspacePill = document.getElementById('workspace-pill');
const dataLink     = document.getElementById('data-link');
const osVersion    = document.getElementById('os-version');

const gaugeCpuArc  = document.getElementById('gauge-cpu-arc');
const gaugeRamArc  = document.getElementById('gauge-ram-arc');
const gaugeNetArc  = document.getElementById('gauge-net-arc');
const gaugeCpuTxt  = document.getElementById('gauge-cpu-txt');
const gaugeRamTxt  = document.getElementById('gauge-ram-txt');
const gaugeNetTxt  = document.getElementById('gauge-net-txt');

const barCpuFreq   = document.getElementById('bar-cpu-freq');
const barMem       = document.getElementById('bar-mem');
const netUp        = document.getElementById('net-up');
const netDown      = document.getElementById('net-down');

const execState    = document.getElementById('exec-state');
const btnMin       = document.getElementById('btn-min');
const btnMax       = document.getElementById('btn-max');
const btnClose     = document.getElementById('btn-close');

// ── State ─────────────────────────────────────────────────────────────────────
let backendBase = 'http://127.0.0.1:8765';
let apiToken    = '';
let sessionId   = 'sess_' + Math.random().toString(36).substr(2, 9);
const ARC_LEN   = 239;

// ── Helpers ───────────────────────────────────────────────────────────────────
function nowTime() {
  return new Date().toTimeString().slice(0, 8);
}

function setGauge(arcEl, pct) {
  const p = Math.max(0, Math.min(100, pct));
  arcEl.style.strokeDashoffset = String(ARC_LEN * (1 - p / 100));
}

function authHeaders() {
  const h = { 'Content-Type': 'application/json' };
  if (apiToken) h['Authorization'] = 'Bearer ' + apiToken;
  return h;
}

function appendCommsLine(tag, text, isUser) {
  const wrap  = document.createElement('div');
  wrap.className = 'comms-line';
  const tagEl = document.createElement('span');
  tagEl.className = 'comms-tag' + (isUser ? ' user' : '');
  tagEl.textContent = '[' + tag + ']';
  const timeEl = document.createElement('span');
  timeEl.className = 'comms-time';
  timeEl.textContent = '[' + nowTime() + ']';
  const line = document.createElement('div');
  line.appendChild(timeEl);
  line.appendChild(tagEl);
  const body = document.createElement('span');
  body.className = 'comms-text';
  // Render URLs as clickable links that open in the system browser
  body.innerHTML = _linkify(text);
  wrap.appendChild(line);
  wrap.appendChild(body);
  chatLog.appendChild(wrap);
  chatLog.scrollTop = chatLog.scrollHeight;
}

/** Convert bare URLs in text to <a> tags that open in the system browser. */
function _linkify(text) {
  const escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  return escaped.replace(
    /(https?:\/\/[^\s<>"]+)/g,
    (url) => `<a class="comms-link" href="#" data-url="${url}">${url}</a>`
  );
}

function showResultCard(type, content, data = {}) {
  const card = document.createElement('div');
  card.className = `result-card card-${type}`;

  const iconMap = {
    weather: '☁️', news: '📰', email: '📧', calendar: '📅',
    memory: '🧠', places: '📍', maps: '🗺️', confirmation: '⚠️', whatsapp: '💬',
    gmail: '📧', system: '⚙️', search: '🔍', default: '⚡',
  };
  const titleMap = {
    weather: 'Environmental Data', news: 'Global Intel', email: 'Comms Update',
    calendar: 'Schedule Sync', memory: 'Neural Recall', places: 'Proximity Scan',
    maps: 'Navigation Path', confirmation: 'Authorization Required', whatsapp: 'WhatsApp Authorization',
    gmail: 'Comms Update', system: 'System Control', search: 'Search Result', default: 'System Result',
  };

  card.innerHTML = `
    <div class="result-header">
      <span class="result-title">${titleMap[type] || 'System Result'}</span>
      <span class="result-icon">${iconMap[type] || '⚡'}</span>
    </div>
    <div class="result-body">${content}</div>
  `;

  if (type === 'confirmation') {
    const row = document.createElement('div');
    row.className = 'btn-confirm-row';
    const btnApprove = document.createElement('button');
    btnApprove.className = 'btn-ui btn-confirm';
    btnApprove.textContent = 'AUTHORIZE';
    btnApprove.onclick = () => { card.remove(); sendMessage(true); };
    const btnDeny = document.createElement('button');
    btnDeny.className = 'btn-ui';
    btnDeny.textContent = 'ABORT';
    btnDeny.onclick = () => card.remove();
    row.appendChild(btnApprove);
    row.appendChild(btnDeny);
    card.appendChild(row);
  } else if (type === 'whatsapp') {
    const row = document.createElement('div');
    row.className = 'btn-confirm-row';
    const btnApprove = document.createElement('button');
    btnApprove.className = 'btn-ui btn-confirm';
    btnApprove.textContent = 'AUTHORIZE';
    btnApprove.onclick = async () => { if (await approveNotification(data.id)) card.remove(); };
    const btnDeny = document.createElement('button');
    btnDeny.className = 'btn-ui';
    btnDeny.textContent = 'ABORT';
    btnDeny.onclick = async () => { await rejectNotification(data.id); card.remove(); };
    row.appendChild(btnApprove);
    row.appendChild(btnDeny);
    card.appendChild(row);
  }

  resultOverlay.appendChild(card);

  // Auto-dismiss after 10 seconds (except confirmation cards)
  if (type !== 'confirmation' && type !== 'whatsapp') {
    const dismissDelay = 10000;
    const fadeDelay    = 800;
    setTimeout(() => {
      card.classList.add('dismissing');
      setTimeout(() => card.remove(), fadeDelay);
    }, dismissDelay);
  }
  return card;
}

function setLinkConnected(on) {
  dataLink.textContent = on ? 'DATA_LINK: ONLINE' : 'DATA_LINK: OFFLINE';
  dataLink.classList.toggle('tb-cyan', on);
}

function setWorkspace(label, kind) {
  workspacePill.textContent = 'WORKSPACE: ' + label;
  workspacePill.className = 'tb-pill ' + (kind === 'idle' ? 'tb-dim' : 'tb-cyan');
}

// ── Metrics rendering (shared by WS and HTTP fallback) ────────────────────────
function applyMetrics(m) {
  setLinkConnected(true);
  const cpu = m.cpu_percent ?? 0;
  const ram = m.ram_percent ?? 0;
  logicPct.textContent = (m.logic_core_percent ?? cpu).toFixed(1);

  setGauge(gaugeCpuArc, cpu);
  setGauge(gaugeRamArc, ram);
  gaugeCpuTxt.textContent = Math.round(cpu) + '%';
  gaugeRamTxt.textContent = Math.round(ram) + '%';

  const recv = m.net_recv_mb ?? 0;
  gaugeNetTxt.textContent = recv.toFixed(0) + ' MB';
  setGauge(gaugeNetArc, Math.min(100, recv * 2));

  netUp.textContent   = (m.net_sent_mb ?? 0) + ' MB';
  netDown.textContent = recv + ' MB';

  barCpuFreq.style.width = Math.min(100, ((m.cpu_freq_mhz || 2000) / 5000) * 100) + '%';
  barMem.style.width     = ram + '%';
}

// ── WebSocket manager ─────────────────────────────────────────────────────────
const WS = (() => {
  let socket = null;
  let usingWS = false;
  let httpFallbackTimer = null;
  let reconnectTimer = null;
  let reconnectDelay = 2000;

  function wsUrl() {
    const base = backendBase.replace(/^http/, 'ws');
    return `${base}/ws${apiToken ? '?token=' + encodeURIComponent(apiToken) : ''}`;
  }

  function startHttpFallback() {
    if (httpFallbackTimer) return;
    httpFallbackTimer = setInterval(async () => {
      try {
        const res = await fetch(backendBase + '/api/system/metrics', { headers: authHeaders() });
        if (res.ok) applyMetrics(await res.json());
      } catch { setLinkConnected(false); }
    }, 2000);
  }

  function stopHttpFallback() {
    if (httpFallbackTimer) { clearInterval(httpFallbackTimer); httpFallbackTimer = null; }
  }

  function connect() {
    if (socket && socket.readyState <= WebSocket.OPEN) return;
    try {
      socket = new WebSocket(wsUrl());
    } catch {
      startHttpFallback();
      return;
    }

    socket.onopen = () => {
      usingWS = true;
      reconnectDelay = 2000;
      stopHttpFallback();
      setLinkConnected(true);
    };

    socket.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }

      if (msg.type === 'metrics') {
        // Throttle DOM updates to animation frames
        requestAnimationFrame(() => applyMetrics(msg));
      } else if (msg.type === 'token') {
        // Streaming LLM token — append to last JARVIS line
        const lines = chatLog.querySelectorAll('.comms-line');
        const last = lines[lines.length - 1];
        if (last) {
          const body = last.querySelector('.comms-text');
          if (body) body.textContent += msg.text;
          chatLog.scrollTop = chatLog.scrollHeight;
        }
      } else if (msg.type === 'reply') {
        execState.textContent = 'AWAITING DIRECTIVE';
        execState.classList.remove('busy');
        setWorkspace('IDLE', 'idle');
        if (msg.tts_audio_base64) playBase64Audio(msg.tts_audio_base64);
      }
    };

    socket.onerror = () => {
      usingWS = false;
      startHttpFallback();
    };

    socket.onclose = () => {
      usingWS = false;
      setLinkConnected(false);
      startHttpFallback();
      // Exponential back-off reconnect
      reconnectTimer = setTimeout(() => {
        reconnectDelay = Math.min(reconnectDelay * 1.5, 30000);
        connect();
      }, reconnectDelay);
    };
  }

  return { connect, isLive: () => usingWS };
})();

// ── Backend init ──────────────────────────────────────────────────────────────
async function initBackend() {
  if (window.jarvis?.getBackendUrl) backendBase = await window.jarvis.getBackendUrl();
  if (window.jarvis?.getApiToken)   apiToken    = await window.jarvis.getApiToken();
}

async function fetchHealth() {
  try {
    const res  = await fetch(backendBase + '/health', { headers: authHeaders() });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    setLinkConnected(true);
    if (data.engine)  enginePill.textContent = 'ENGINE: ' + String(data.engine).toUpperCase();
    if (data.version) osVersion.textContent  = data.version;
  } catch { setLinkConnected(false); }
}

// ── Notifications ─────────────────────────────────────────────────────────────
async function fetchNotifications() {
  try {
    const res   = await fetch(backendBase + '/api/notifications', { headers: authHeaders() });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const items = await res.json();
    for (const item of items) {
      if (document.getElementById(`notif-${item.id}`)) continue;
      const content = `<strong>From ${item.sender}:</strong><br/>"${item.incoming_text}"<hr/><strong>Proposed Reply:</strong><br/>"${item.proposed_reply}"`;
      const card = showResultCard('whatsapp', content, item);
      if (card) card.id = `notif-${item.id}`;
    }
  } catch (e) { console.error('Failed to fetch notifications:', e); }
}

async function approveNotification(id) {
  try {
    const res = await fetch(backendBase + '/api/notifications/approve', {
      method: 'POST', headers: authHeaders(), body: JSON.stringify({ id }),
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return (await res.json()).ok;
  } catch { return false; }
}

async function rejectNotification(id) {
  try {
    await fetch(backendBase + '/api/notifications/reject', {
      method: 'POST', headers: authHeaders(), body: JSON.stringify({ id }),
    });
  } catch {}
}

// ── Audio ─────────────────────────────────────────────────────────────────────
function playBase64Audio(base64) {
  if (!base64) return;
  new Audio('data:audio/wav;base64,' + base64).play().catch(console.error);
}

// ── Chat ──────────────────────────────────────────────────────────────────────
async function sendMessage(confirmed = false) {
  const text = confirmed ? (window._lastCommand || '') : input.value.trim();
  if (!text) return;
  if (!confirmed) {
    window._lastCommand = text;
    input.value = '';
    appendCommsLine('USER', text, true);
  }

  // ── Local command intercepts ──────────────────────────────────────────────
  const tl = text.toLowerCase().trim();
  if (tl.includes('whatsapp qr') || tl.includes('scan qr') || tl.includes('connect whatsapp')) {
    await showWhatsAppQR();
    return;
  }

  setWorkspace('PROCESSING', 'think');
  execState.textContent = 'PROCESSING DIRECTIVE...';
  execState.classList.add('busy');
  btnSend.disabled = true;

  try {
    const res = await fetch(backendBase + '/api/chat', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({
        message: text,
        user_confirmed: confirmed,
        session_id: sessionId
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || data.error || ('HTTP ' + res.status));
    }

    const reply = data.reply || 'Directive processed.';
    appendCommsLine('JARVIS_CORE', reply, false);

    if (data.tts_audio_base64) playBase64Audio(data.tts_audio_base64);

    if (data.needs_confirmation) {
      showResultCard('confirmation', reply);
    } else if (data.skill_type === 'food_grocery') {
      const g = (data.skill_result?.result?.data) || data.data || {};
      if (g.step === 'awaiting_selection' && g.search_results) {
        showFoodCards(g.search_results, g.query || '');
      } else if (g.step === 'awaiting_confirmation' && g.chosen_item) {
        showCartSummary(g.chosen_item, g.platform || 'Swiggy');
      }
    } else if (data.skill_type) {
      // Show result card for known skill types
      showResultCard(data.skill_type, reply, data.skill_result);
    } else {
      // Always show a notification card for every command result
      showResultCard('default', reply);
    }

    execState.textContent = 'AWAITING DIRECTIVE';
    execState.classList.remove('busy');
    setWorkspace('IDLE', 'idle');
  } catch (e) {
    appendCommsLine('JARVIS_CORE', 'Uplink fault: ' + e.message, false);
    setWorkspace('IDLE', 'idle');
  } finally {
    btnSend.disabled = false;
  }
}

// ── Event listeners ───────────────────────────────────────────────────────────
btnSend.addEventListener('click', () => sendMessage(false));
input.addEventListener('keydown', (e) => { if (e.key === 'Enter') sendMessage(false); });
btnMic.addEventListener('click', () => audioFile.click());
audioFile.addEventListener('change', () => {
  const f = audioFile.files[0];
  if (!f) return;
  appendCommsLine('USER', '[VOICE INPUT]', true);
  const fd = new FormData();
  fd.append('file', f);
  const headers = {};
  if (apiToken) headers['Authorization'] = 'Bearer ' + apiToken;
  fetch(backendBase + '/api/voice', { method: 'POST', headers, body: fd })
    .then(async (r) => {
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || data.error || ('HTTP ' + r.status));
      return data;
    })
    .then(data => {
      if (data.transcript) appendCommsLine('USER', data.transcript, true);
      const reply = data.reply || 'Voice processed.';
      appendCommsLine('JARVIS_CORE', reply, false);
      if (data.tts_audio_base64) playBase64Audio(data.tts_audio_base64);
    })
    .catch(e => appendCommsLine('JARVIS_CORE', 'Voice error: ' + e.message, false));
});

btnMin.addEventListener('click',   () => window.jarvis?.minimize());
btnMax.addEventListener('click',   () => window.jarvis?.maximize());
btnClose.addEventListener('click', () => window.jarvis?.close());

// ── Food ordering cards — Premium Upgrade ────────────────────────────────────
function showFoodCards(items, query) {
  const existing = document.getElementById('food-cards-panel');
  if (existing) existing.remove();

  const panel = document.createElement('div');
  panel.id = 'food-cards-panel';
  panel.className = 'food-cards-panel';

  panel.innerHTML = `
    <div class="food-cards-header">
      <span class="food-cards-title">🍽️ Results: "${query}"</span>
      <button class="food-cards-close btn-ui" onclick="this.closest('#food-cards-panel').remove()">✕</button>
    </div>
    <div class="food-cards-grid" id="food-grid"></div>
  `;

  const grid = panel.querySelector('#food-grid');

  items.forEach((item, idx) => {
    const card = document.createElement('div');
    card.className = 'food-item-card';
    const rating   = item.rating ? `⭐ ${item.rating}` : '';
    const price    = item.price  ? `₹${Number(item.price).toLocaleString('en-IN')}` : '';
    const eta      = item.eta    ? `🕐 ${item.eta}` : '';
    const platform = item.platform || 'Swiggy';

    card.innerHTML = `
      <div class="food-card-top">
        <div class="food-card-num">${String(idx + 1).padStart(2, '0')}</div>
        <div class="food-card-body">
          <div class="food-card-name">${item.name}</div>
          <div class="food-card-meta">
            ${price  ? `<span class="food-price">${price}</span>` : ''}
            ${rating ? `<span class="food-rating">${rating}</span>` : ''}
            ${eta    ? `<span class="food-eta">${eta}</span>` : ''}
          </div>
        </div>
      </div>
      <div class="food-card-footer">
        <span class="food-platform">${platform}</span>
        <button class="food-select-btn btn-ui btn-confirm" data-idx="${idx + 1}">SELECT</button>
      </div>
    `;

    card.querySelector('.food-select-btn').addEventListener('click', () => {
      panel.remove();
      sendFoodChoice(idx + 1);
    });

    grid.appendChild(card);
  });

  resultOverlay.appendChild(panel);
}

// ── Address Panel ──────────────────────────────────────────────────────────
function renderAddressPanel(address = 'Detecting location...') {
  let panel = document.getElementById('address-panel');
  if (!panel) {
    panel = document.createElement('div');
    panel.id = 'address-panel';
    panel.className = 'address-panel';
    document.querySelector('.hud-root').appendChild(panel);
  }

  panel.innerHTML = `
    <div class="address-head">
      <span>Delivery Location</span>
      <button class="address-edit-btn" onclick="promptAddress()">EDIT</button>
    </div>
    <div class="address-val" title="${address}">${address}</div>
  `;
}

window.promptAddress = () => {
  const newAddr = prompt('Enter delivery address:');
  if (newAddr) _postLocation(newAddr, 0, 0);
};

// ── Cart Summary Panel ──────────────────────────────────────────────────
function showCartSummary(item, platform) {
  const existing = document.getElementById('cart-summary-panel');
  if (existing) existing.remove();

  const panel = document.createElement('div');
  panel.id = 'cart-summary-panel';
  panel.className = 'food-cards-panel'; // Reuse base styles
  panel.style.maxHeight = '300px';

  const price = item.price ? `₹${Number(item.price).toLocaleString('en-IN')}` : '';
  
  panel.innerHTML = `
    <div class="food-cards-header">
      <span class="food-cards-title">🛍️ Final Confirmation</span>
      <button class="food-cards-close btn-ui" onclick="this.closest('#cart-summary-panel').remove()">✕</button>
    </div>
    <div style="padding: 20px; text-align: center;">
      <div style="font-size: 16px; font-weight: 700; color: #fff; margin-bottom: 8px;">${item.name}</div>
      <div style="color: var(--cyan); font-size: 20px; font-weight: 800; margin-bottom: 20px;">${price}</div>
      <div style="font-size: 11px; color: var(--muted); margin-bottom: 20px;">Platform: ${platform.toUpperCase()}</div>
      
      <div style="display: flex; gap: 10px; justify-content: center;">
        <button class="btn-ui btn-confirm" style="flex: 1; padding: 12px;" onclick="sendChoice('yes')">PLACE ORDER</button>
        <button class="btn-ui" style="flex: 1; padding: 12px; border-color: #ef4444; color: #ef4444;" onclick="sendChoice('cancel')">CANCEL</button>
      </div>
    </div>
  `;

  resultOverlay.appendChild(panel);
}

window.sendChoice = (text) => {
  const p = document.getElementById('cart-summary-panel');
  if (p) p.remove();
  input.value = text;
  sendMessage(false);
};

// ── Location detection ────────────────────────────────────────────────────────
async function detectAndSendLocation() {
  // Try browser geolocation first
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const lat = pos.coords.latitude;
        const lng = pos.coords.longitude;
        // Reverse geocode to get city name
        try {
          const r = await fetch(`https://ipapi.co/json/`);
          const d = await r.json();
          const city = d.city || d.region || '';
          await _postLocation(city, lat, lng);
        } catch {
          await _postLocation('', lat, lng);
        }
      },
      async () => {
        // Geolocation denied — try IP-based
        try {
          const r = await fetch('https://ipapi.co/json/');
          const d = await r.json();
          await _postLocation(d.city || '', parseFloat(d.latitude) || 0, parseFloat(d.longitude) || 0);
        } catch { /* silent */ }
      },
      { timeout: 5000 }
    );
  }
}

async function _postLocation(city, lat, lng) {
  if (!city && !lat && !lng) return;
  renderAddressPanel(city || `Lat: ${lat.toFixed(2)}, Lng: ${lng.toFixed(2)}`);
  try {
    const res = await fetch(backendBase + '/api/location', {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify({ city, lat, lng }),
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    console.log('Location sent:', city, lat, lng);
  } catch (e) {
    console.warn('Location send failed:', e);
  }
}

// ── WhatsApp QR code display ──────────────────────────────────────────────────
async function showWhatsAppQR() {
  try {
    const res  = await fetch(backendBase + '/api/whatsapp/qr', { headers: authHeaders() });
    const data = await res.json();

    // Remove existing QR card
    const existing = document.getElementById('wa-qr-card');
    if (existing) existing.remove();

    if (data.status === 'connected') {
      appendCommsLine('JARVIS_CORE', '✅ WhatsApp is already connected!', false);
      return;
    }

    if (!data.has_qr) {
      appendCommsLine('JARVIS_CORE',
        'WhatsApp QR not available yet. The bridge may still be starting. Try again in a few seconds.',
        false);
      return;
    }

    // Render QR using qrcode.js (loaded from CDN) or show raw text
    const card = document.createElement('div');
    card.id = 'wa-qr-card';
    card.className = 'result-card card-whatsapp';
    card.style.cssText = 'max-width:320px;margin:8px auto;text-align:center;';
    card.innerHTML = `
      <div class="result-header">
        <span class="result-title">📱 Scan WhatsApp QR</span>
        <button class="btn-ui" onclick="this.closest('#wa-qr-card').remove()" style="font-size:12px;padding:2px 8px;">✕</button>
      </div>
      <div style="padding:12px;">
        <p style="font-size:11px;color:#80cbc4;margin-bottom:8px;">
          Open WhatsApp → Linked Devices → Link a Device → Scan this QR
        </p>
        <canvas id="wa-qr-canvas" style="border:2px solid #00e5ff;border-radius:4px;background:#fff;"></canvas>
        <p style="font-size:10px;color:#546e7a;margin-top:6px;">QR expires in ~60s. Refresh if expired.</p>
        <button class="btn-ui btn-confirm" onclick="showWhatsAppQR()" style="margin-top:8px;font-size:10px;">
          🔄 REFRESH QR
        </button>
      </div>
    `;
    resultOverlay.appendChild(card);

    // Try to render QR with qrcode library
    try {
      if (typeof QRCode !== 'undefined') {
        QRCode.toCanvas(document.getElementById('wa-qr-canvas'), data.qr, { width: 220 });
      } else {
        // Fallback: load qrcode.js dynamically
        const script = document.createElement('script');
        script.src = 'https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js';
        script.onload = () => {
          QRCode.toCanvas(document.getElementById('wa-qr-canvas'), data.qr, { width: 220 });
        };
        document.head.appendChild(script);
      }
    } catch (e) {
      // Last resort: show raw QR text
      const canvas = document.getElementById('wa-qr-canvas');
      if (canvas) {
        canvas.style.display = 'none';
        const pre = document.createElement('pre');
        pre.style.cssText = 'font-size:6px;line-height:1;color:#000;background:#fff;padding:8px;';
        pre.textContent = data.qr;
        canvas.parentNode.insertBefore(pre, canvas);
      }
    }

    // Auto-poll for connection
    const pollInterval = setInterval(async () => {
      try {
        const r2   = await fetch(backendBase + '/api/whatsapp/qr', { headers: authHeaders() });
        const d2   = await r2.json();
        if (d2.status === 'connected') {
          clearInterval(pollInterval);
          document.getElementById('wa-qr-card')?.remove();
          appendCommsLine('JARVIS_CORE', '✅ WhatsApp connected successfully!', false);
        }
      } catch { clearInterval(pollInterval); }
    }, 3000);

    // Stop polling after 2 minutes
    setTimeout(() => clearInterval(pollInterval), 120000);

  } catch (e) {
    appendCommsLine('JARVIS_CORE', 'Could not fetch WhatsApp QR: ' + e.message, false);
  }
}

// ── Link click handler — open URLs in system browser ─────────────────────────
// Uses event delegation on chatLog so it catches dynamically added links.
chatLog.addEventListener('click', (e) => {
  const link = e.target.closest('a.comms-link');
  if (!link) return;
  e.preventDefault();
  const url = link.dataset.url;
  if (!url) return;
  // In Electron, shell.openExternal opens the system default browser.
  // We expose it via IPC; fall back to window.open for non-Electron contexts.
  if (window.jarvis?.openExternal) {
    window.jarvis.openExternal(url);
  } else {
    window.open(url, '_blank');
  }
});

// ── Boot ──────────────────────────────────────────────────────────────────────
initBackend().then(() => {
  renderAddressPanel();
  fetchHealth();
  WS.connect();
  detectAndSendLocation();                   // detect location on startup
  setInterval(fetchNotifications, 3000);
});
