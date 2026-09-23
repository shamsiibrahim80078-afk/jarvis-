/* Nexus Agents Workspace — live floor */
(() => {
  const cardsEl = document.getElementById('agent-cards');
  const chatEl = document.getElementById('crew-chat');
  const tasksEl = document.getElementById('task-board');
  const form = document.getElementById('owner-form');
  const input = document.getElementById('owner-input');
  const clockEl = document.getElementById('wx-clock');
  const livePill = document.getElementById('wx-live');

  let lastSeq = 0;
  let seenChat = new Set();

  function fmtTime(ts) {
    try {
      return new Date((ts || 0) * 1000).toLocaleTimeString();
    } catch {
      return '';
    }
  }

  function renderAgents(agents) {
    const list = Object.values(agents || {});
    cardsEl.innerHTML = list.map((a) => {
      const st = (a.status || 'idle').toLowerCase();
      return `<article class="agent-card" data-id="${a.id}">
        <div class="row">
          <div>
            <div class="name">${a.name}</div>
            <div class="role">${a.title || a.role}</div>
          </div>
          <span class="status ${st}">${st}</span>
        </div>
        <div class="activity">${a.activity || '—'}</div>
        <div class="station">Station · ${a.station || '—'}</div>
      </article>`;
    }).join('');
  }

  function appendChat(ev) {
    if (!ev || !ev.id || seenChat.has(ev.id)) return;
    if (!(ev.kind === 'chat' || ev.kind === 'progress' || ev.kind === 'system')) return;
    if (!ev.text) return;
    seenChat.add(ev.id);
    const from = (ev.from || 'system').toLowerCase();
    const to = ev.to ? ` → ${ev.to}` : '';
    const div = document.createElement('div');
    div.className = `chat-line from-${from}`;
    div.innerHTML = `<div class="meta"><span class="who">${from}${to}</span><span>${fmtTime(ev.ts)}</span></div>
      <div class="body">${escapeHtml(ev.text)}</div>`;
    chatEl.appendChild(div);
    chatEl.scrollTop = chatEl.scrollHeight;
  }

  function renderTasks(tasks) {
    const list = [...(tasks || [])].reverse().slice(0, 24);
    if (!list.length) {
      tasksEl.innerHTML = '<div class="task-card"><div class="t-title">No tasks yet — assign Mira a Shorts brief.</div></div>';
      return;
    }
    tasksEl.innerHTML = list.map((t) => {
      const st = (t.status || 'queued').toLowerCase();
      return `<article class="task-card ${st}">
        <div class="t-title">${escapeHtml(t.title || '')}</div>
        <div class="t-meta"><span>${t.agent_id || ''}</span><span>${st}</span></div>
        ${t.result ? `<div class="t-result">${escapeHtml(String(t.result).slice(0, 220))}</div>` : ''}
      </article>`;
    }).join('');
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  async function refreshState() {
    const res = await fetch('/api/crew/state');
    const data = await res.json();
    renderAgents(data.agents || {});
    renderTasks(data.tasks || []);
    (data.chat || []).forEach(appendChat);
    if (data.chat && data.chat.length) {
      lastSeq = Math.max(lastSeq, ...data.chat.map((c) => c.seq || 0));
    }
  }

  async function pollEvents() {
    try {
      const res = await fetch(`/api/crew/events?since=${lastSeq}`);
      const data = await res.json();
      const events = data.events || [];
      for (const ev of events) {
        lastSeq = Math.max(lastSeq, ev.seq || 0);
        appendChat(ev);
        if (ev.kind === 'status' || ev.kind === 'task') {
          refreshState();
        }
      }
      livePill.style.opacity = '1';
    } catch {
      livePill.style.opacity = '0.5';
    }
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    appendChat({
      id: `local_${Date.now()}`,
      kind: 'chat',
      from: 'owner',
      to: 'jarvis',
      text,
      ts: Date.now() / 1000,
      seq: lastSeq,
    });
    try {
      const res = await fetch('/api/crew/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      const data = await res.json();
      if (data.message) {
        appendChat({
          id: `ack_${Date.now()}`,
          kind: 'chat',
          from: 'jarvis',
          to: 'owner',
          text: data.message,
          ts: Date.now() / 1000,
          seq: lastSeq,
        });
      }
      refreshState();
    } catch (err) {
      appendChat({
        id: `err_${Date.now()}`,
        kind: 'system',
        from: 'system',
        text: 'Command failed — is Jarvis server running?',
        ts: Date.now() / 1000,
      });
    }
  });

  function tickClock() {
    clockEl.textContent = new Date().toLocaleTimeString();
  }

  // WebSocket live push (same /ws)
  try {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${proto}//${location.host}/ws`);
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === 'crew' && msg.event) {
          const e = msg.event;
          lastSeq = Math.max(lastSeq, e.seq || 0);
          appendChat(e);
          if (e.kind === 'status' || e.kind === 'task' || e.kind === 'progress') refreshState();
        }
      } catch {}
    };
  } catch {}

  tickClock();
  setInterval(tickClock, 1000);
  refreshState();
  setInterval(pollEvents, 1500);
  setInterval(refreshState, 4000);
})();
