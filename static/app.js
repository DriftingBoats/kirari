const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
let currentFile = 'SOUL.md';

function toast(text) {
  const el = $('#toast');
  el.textContent = text;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 1800);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function fmt(ts) {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleString();
}

function toTs(value) {
  return Math.floor(new Date(value).getTime() / 1000);
}

async function loadStatus() {
  const data = await api('/api/status');
  $('#statusPill').textContent = data.hermes_available ? 'Hermes 在线' : 'Hermes 未安装';
  $('#statusBlock').textContent = JSON.stringify(data, null, 2);
}

async function loadDashboard() {
  const [messages, board, reminders, reviews] = await Promise.all([
    api('/api/messages?limit=12'),
    api('/api/board'),
    api('/api/reminders'),
    api('/api/reviews'),
  ]);
  $('#metricMessages').textContent = messages.length;
  $('#metricBoard').textContent = board.length;
  $('#metricReminders').textContent = reminders.filter(r => r.status === 'pending').length;
  $('#metricReviews').textContent = reviews.filter(r => r.status === 'pending').length;
  $('#recentMessages').innerHTML = messages.map(m => `
    <div class="item">
      <div class="item-head"><strong>${m.direction === 'in' ? '我' : 'TA'}</strong><small>${fmt(m.created_at)}</small></div>
      <div>${escapeHtml(m.text)}</div>
    </div>
  `).join('') || '<div class="item">还没有 Telegram 消息。</div>';
}

async function loadFiles() {
  const files = await api('/api/files');
  $('#fileList').innerHTML = files.map(f => `
    <button class="${f.name === currentFile ? 'active' : ''}" data-file="${f.name}">
      ${f.name}<br><small>${f.size} chars</small>
    </button>
  `).join('');
  $('#fileList').onclick = (e) => {
    const btn = e.target.closest('button[data-file]');
    if (!btn) return;
    currentFile = btn.dataset.file;
    loadFile(currentFile);
    loadFiles();
  };
  await loadFile(currentFile);
}

async function loadFile(name) {
  const file = await api(`/api/files/${encodeURIComponent(name)}`);
  $('#currentFile').textContent = file.name;
  $('#fileEditor').value = file.content;
}

async function saveFile() {
  await api(`/api/files/${encodeURIComponent(currentFile)}`, {
    method: 'PUT',
    body: JSON.stringify({ content: $('#fileEditor').value }),
  });
  toast('已保存');
  loadFiles();
}

async function loadBoard() {
  const items = await api('/api/board');
  $('#boardList').innerHTML = items.map(i => `
    <article class="note ${i.author}">
      <div class="item-head"><span class="chip">${i.author === 'ai' ? 'TA' : '我'}</span><small>${fmt(i.created_at)}</small></div>
      <p>${escapeHtml(i.text)}</p>
      <button class="ghost" data-archive="${i.id}">${i.archived ? '取消归档' : '归档'}</button>
    </article>
  `).join('') || '<div class="item">留言板还是空的。</div>';
}

async function loadCalendar() {
  const items = await api('/api/calendar');
  $('#calendarList').innerHTML = items.map(i => `
    <div class="item">
      <div class="item-head">
        <strong>${escapeHtml(i.title)}</strong>
        <span class="chip ${i.layer}">${layerName(i.layer)}</span>
      </div>
      <small>${fmt(i.starts_at)}</small>
      <div>${escapeHtml(i.description || '')}</div>
    </div>
  `).join('') || '<div class="item">还没有日历事件。</div>';
}

async function loadReminders() {
  const items = await api('/api/reminders');
  $('#reminderList').innerHTML = items.map(i => `
    <div class="item">
      <div class="item-head">
        <strong>${escapeHtml(i.title)}</strong>
        <span class="chip">${i.status}</span>
      </div>
      <small>${fmt(i.remind_at)}</small>
      <div>${escapeHtml(i.description || '')}</div>
      ${i.status === 'pending' ? `<button class="ghost" data-done="${i.id}">完成</button>` : ''}
    </div>
  `).join('') || '<div class="item">没有提醒。</div>';
}

async function loadReviews() {
  const items = await api('/api/reviews');
  $('#reviewList').innerHTML = items.map(i => `
    <div class="item">
      <div class="item-head"><strong>${i.kind}</strong><span class="chip">${i.status}</span></div>
      <div>${escapeHtml(i.payload?.text || JSON.stringify(i.payload))}</div>
      <small>${escapeHtml(i.reason || '')}</small>
      ${i.status === 'pending' ? `
        <div>
          <button class="primary" data-review="${i.id}" data-action="approve">通过</button>
          <button class="ghost" data-review="${i.id}" data-action="reject">拒绝</button>
        </div>` : ''}
    </div>
  `).join('') || '<div class="item">没有待确认内容。</div>';
}

async function loadLogs() {
  const logs = await api('/api/logs');
  $('#logList').innerHTML = logs.map(l => `
    <div class="item">
      <div class="item-head"><strong>${l.level}</strong><small>${fmt(l.created_at)}</small></div>
      <div>${escapeHtml(l.message)}</div>
    </div>
  `).join('');
}

function layerName(layer) {
  return ({ life: '生活', relationship: '关系', work: '工作' })[layer] || layer;
}

function escapeHtml(text) {
  return String(text || '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

async function refreshAll() {
  await Promise.all([
    loadStatus(),
    loadDashboard(),
    loadFiles(),
    loadBoard(),
    loadCalendar(),
    loadReminders(),
    loadReviews(),
    loadLogs(),
  ]);
}

$$('.nav button').forEach(btn => {
  btn.onclick = () => {
    $$('.nav button').forEach(b => b.classList.remove('active'));
    $$('.view').forEach(v => v.classList.remove('active'));
    btn.classList.add('active');
    $('#' + btn.dataset.tab).classList.add('active');
  };
});

$('#saveFileBtn').onclick = saveFile;
$('#syncHermesBtn').onclick = async () => {
  $('#syncHermesBtn').disabled = true;
  try {
    const result = await api('/api/import/hermes-sessions', { method: 'POST', body: '{}' });
    toast(`已同步 ${result.messages} 条`);
    refreshAll();
  } catch (e) {
    toast('同步失败');
  } finally {
    $('#syncHermesBtn').disabled = false;
  }
};

$('#runDreamBtn').onclick = async () => {
  $('#runDreamBtn').disabled = true;
  try {
    await api('/api/dream/run', { method: 'POST', body: '{}' });
    toast('dream 已完成');
    refreshAll();
  } catch (e) {
    toast('dream 失败');
  } finally {
    $('#runDreamBtn').disabled = false;
  }
};

$('#boardForm').onsubmit = async (e) => {
  e.preventDefault();
  await api('/api/board', {
    method: 'POST',
    body: JSON.stringify({ author: $('#boardAuthor').value, text: $('#boardText').value }),
  });
  $('#boardText').value = '';
  loadBoard();
};

$('#calendarForm').onsubmit = async (e) => {
  e.preventDefault();
  await api('/api/calendar', {
    method: 'POST',
    body: JSON.stringify({
      layer: $('#calLayer').value,
      title: $('#calTitle').value,
      starts_at: toTs($('#calWhen').value),
      description: $('#calDesc').value,
    }),
  });
  e.target.reset();
  loadCalendar();
};

$('#reminderForm').onsubmit = async (e) => {
  e.preventDefault();
  await api('/api/reminders', {
    method: 'POST',
    body: JSON.stringify({
      title: $('#remTitle').value,
      remind_at: toTs($('#remWhen').value),
      description: $('#remDesc').value,
    }),
  });
  e.target.reset();
  loadReminders();
};

document.body.onclick = async (e) => {
  const archive = e.target.closest('[data-archive]');
  if (archive) {
    await api(`/api/board/${archive.dataset.archive}`, { method: 'PATCH', body: JSON.stringify({ archived: true }) });
    loadBoard();
  }
  const done = e.target.closest('[data-done]');
  if (done) {
    await api(`/api/reminders/${done.dataset.done}`, { method: 'PATCH', body: JSON.stringify({ status: 'done' }) });
    loadReminders();
  }
  const review = e.target.closest('[data-review]');
  if (review) {
    await api(`/api/reviews/${review.dataset.review}`, {
      method: 'POST',
      body: JSON.stringify({ action: review.dataset.action }),
    });
    loadReviews();
  }
};

refreshAll().catch(err => toast(err.message));
