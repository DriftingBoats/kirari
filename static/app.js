const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
let currentFile = 'SOUL.md';
let accessKey = localStorage.getItem('kirari_access_key') || '';
const tg = window.Telegram?.WebApp;
const telegramInitData = tg?.initData || '';

if (tg) {
  tg.ready();
  tg.expand();
}

function toast(text) {
  const el = $('#toast');
  el.textContent = text;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 1800);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      ...(telegramInitData ? { 'X-Telegram-Init-Data': telegramInitData } : {}),
      ...(accessKey ? { 'X-Kirari-Key': accessKey } : {}),
      ...(opts.headers || {}),
    },
    ...opts,
  });
  if (res.status === 401) {
    showAuth();
    throw new Error('需要访问密钥');
  }
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function showAuth() {
  $('#authPanel').hidden = false;
  $('#accessKeyInput').focus();
}

function hideAuth() {
  $('#authPanel').hidden = true;
}

function fmt(ts) {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleString();
}

function toTs(value) {
  return Math.floor(new Date(value).getTime() / 1000);
}

function emptyState(title, detail) {
  return `<div class="empty-state"><strong>${escapeHtml(title)}</strong>${escapeHtml(detail)}</div>`;
}

async function loadStatus() {
  const data = await api('/api/status');
  const runtime = data.runtime || {};
  const index = data.memory_index || {};
  const runtimeStatus = runtime.available && runtime.auth === 'chatgpt'
    ? 'Codex 订阅已登录'
    : runtime.available ? 'Codex 待登录' : 'Codex 未安装';
  const vectorStatus = index.configured
    ? `向量 ${index.indexed || 0}/${index.active_memories || 0}`
    : '向量待配置';
  const status = `${runtimeStatus} · ${vectorStatus}`;
  $('#statusPill').innerHTML = `<i aria-hidden="true"></i><span>${status}</span>`;
  $('#statusPill').dataset.state = runtime.available && runtime.auth === 'chatgpt' ? 'ready' : 'attention';
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
      <button class="ghost" data-pin-message="${m.id}">钉入记忆</button>
    </div>
  `).join('') || emptyState('今天还没有新消息', '去和 Kirari 说句话吧。');
}

async function loadLocalChat() {
  const messages = await api('/api/messages?limit=100&chat_id=-1');
  $('#localChatList').innerHTML = messages.map(m => `
    <div class="item ${m.direction === 'out' ? 'ai' : 'user'}">
      <div class="item-head"><strong>${m.direction === 'in' ? '我' : 'Kirari'}</strong><small>${fmt(m.created_at)}</small></div>
      <div>${escapeHtml(m.text)}</div>
      <button class="ghost" data-pin-message="${m.id}">钉入记忆</button>
    </div>
  `).join('') || emptyState('这里还很安静', '你的第一句话，会成为这段对话的开始。');
  $('#localChatList').scrollTop = $('#localChatList').scrollHeight;
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
  await loadFileVersions(name);
}

async function loadFileVersions(name) {
  const versions = await api(`/api/files/${encodeURIComponent(name)}/versions`);
  $('#fileVersions').innerHTML = versions.map(v => `
    <div class="item">
      <div class="item-head">
        <strong>#${v.id}</strong>
        <small>${fmt(v.created_at)} · ${v.size} chars</small>
      </div>
      <button class="ghost" data-restore-file="${name}" data-version="${v.id}">恢复</button>
    </div>
  `).join('') || emptyState('还没有历史版本', '第一次保存后，会在这里留下可恢复的记录。');
}

async function saveFile() {
  await api(`/api/files/${encodeURIComponent(currentFile)}`, {
    method: 'PUT',
    body: JSON.stringify({ content: $('#fileEditor').value }),
  });
  toast('已保存并即时生效');
  loadFiles();
}

async function loadBoard() {
  const items = await api('/api/board');
  $('#boardList').innerHTML = items.map(i => `
    <article class="note ${i.author}">
      <div class="item-head"><span class="chip">${i.author === 'ai' ? 'TA' : '我'}</span><small>${fmt(i.created_at)}</small></div>
      <p>${escapeHtml(i.text)}</p>
      <button class="ghost" data-archive="${i.id}" data-archived="${i.archived ? 'true' : 'false'}">${i.archived ? '取消归档' : '归档'}</button>
    </article>
  `).join('') || emptyState('留言板还是空的', '留下一句话，晚一点再回来读。');
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
  `).join('') || emptyState('日历里还没有安排', '把值得期待的日子放进来。');
}

async function loadReminders() {
  const items = await api('/api/reminders');
  $('#reminderList').innerHTML = items.map(i => `
    <div class="item">
      <div class="item-head">
        <strong>${escapeHtml(i.title)}</strong>
        <span class="chip">${statusName(i.status)}</span>
      </div>
      <small>${fmt(i.remind_at)}</small>
      <div>${escapeHtml(i.description || '')}</div>
      ${i.status === 'pending' ? `
        <button class="ghost" data-done="${i.id}">完成</button>
        <button class="ghost" data-snooze="${i.id}">稍后 10 分钟</button>` : ''}
    </div>
  `).join('') || emptyState('没有等待中的提醒', '需要记住的事，交给 Kirari。');
}

async function loadReviews() {
  const items = await api('/api/reviews');
  $('#reviewList').innerHTML = items.map(i => `
    <div class="item">
      <div class="item-head"><strong>${escapeHtml(i.kind)}</strong><span class="chip">${statusName(i.status)}</span></div>
      <div>${escapeHtml(i.payload?.text || JSON.stringify(i.payload))}</div>
      <small>${escapeHtml(i.reason || '')}</small>
      ${i.status === 'pending' ? `
        <div>
          <button class="primary" data-review="${i.id}" data-action="approve">通过</button>
          <button class="ghost" data-review="${i.id}" data-action="reject">拒绝</button>
        </div>` : ''}
    </div>
  `).join('') || emptyState('现在没有需要确认的内容', '重要改变出现时，Kirari 会把决定交给你。');
}

async function loadLogs() {
  const logs = await api('/api/logs');
  $('#logList').innerHTML = logs.map(l => `
    <div class="item">
      <div class="item-head"><strong>${l.level}</strong><small>${fmt(l.created_at)}</small></div>
      <div>${escapeHtml(l.message)}</div>
    </div>
  `).join('') || emptyState('还没有系统记录', '运行事件会按时间出现在这里。');
}

function layerName(layer) {
  return ({ life: '生活', relationship: '关系', work: '工作' })[layer] || layer;
}

function statusName(status) {
  return ({ pending: '等待中', done: '已完成', approved: '已通过', rejected: '已拒绝' })[status] || status;
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
    loadLocalChat(),
    loadFiles(),
    loadBoard(),
    loadCalendar(),
    loadReminders(),
    loadReviews(),
    loadLogs(),
  ]);
}

function switchTab(tabName, { updateHash = true } = {}) {
  const targetButton = $(`.nav button[data-tab="${tabName}"]`);
  const targetView = $('#' + tabName);
  if (!targetButton || !targetView) return;
  $$('.nav button').forEach(button => {
    const active = button === targetButton;
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  $$('.view').forEach(view => view.classList.toggle('active', view === targetView));
  if (updateHash) history.replaceState(null, '', `#${tabName}`);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

$$('.nav button').forEach(btn => {
  btn.onclick = () => switchTab(btn.dataset.tab);
});

window.addEventListener('hashchange', () => {
  const tabName = location.hash.slice(1);
  if (tabName) switchTab(tabName, { updateHash: false });
});

$('#saveFileBtn').onclick = saveFile;
$('#testCodexBtn').onclick = async () => {
  const originalLabel = $('#testCodexBtn').textContent;
  $('#testCodexBtn').disabled = true;
  $('#testCodexBtn').textContent = '正在检查…';
  try {
    const result = await api('/api/chat/test', {
      method: 'POST',
      body: JSON.stringify({ text: '只用一句自然的中文告诉我：连接正常。' }),
    });
    toast(result.ok ? result.text : 'Codex 连接失败');
  } catch (e) {
    toast('Codex 连接失败');
  } finally {
    $('#testCodexBtn').disabled = false;
    $('#testCodexBtn').textContent = originalLabel;
  }
};

$('#chatForm').onsubmit = async (e) => {
  e.preventDefault();
  const input = $('#chatText');
  const text = input.value.trim();
  if (!text) return;
  const button = e.target.querySelector('button');
  const originalLabel = button.textContent;
  button.disabled = true;
  button.textContent = 'Kirari 在想…';
  input.value = '';
  try {
    await api('/api/chat', { method: 'POST', body: JSON.stringify({ text, chat_id: -1 }) });
    await Promise.all([loadLocalChat(), loadDashboard(), loadReviews()]);
  } catch (err) {
    input.value = text;
    toast('发送失败');
  } finally {
    button.disabled = false;
    button.textContent = originalLabel;
    input.focus();
  }
};

$('#runDreamBtn').onclick = async () => {
  const originalLabel = $('#runDreamBtn').textContent;
  $('#runDreamBtn').disabled = true;
  $('#runDreamBtn').textContent = '正在整理…';
  try {
    await api('/api/dream/run', { method: 'POST', body: '{}' });
    toast('今日记忆已整理好');
    refreshAll();
  } catch (e) {
    toast('暂时没能整理记忆，请稍后再试');
  } finally {
    $('#runDreamBtn').disabled = false;
    $('#runDreamBtn').textContent = originalLabel;
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
      repeat_rule: $('#remRepeat').value,
    }),
  });
  e.target.reset();
  loadReminders();
};

document.body.onclick = async (e) => {
  const jump = e.target.closest('[data-jump]');
  if (jump) switchTab(jump.dataset.jump);
  const archive = e.target.closest('[data-archive]');
  if (archive) {
    const archived = archive.dataset.archived === 'true';
    await api(`/api/board/${archive.dataset.archive}`, { method: 'PATCH', body: JSON.stringify({ archived: !archived }) });
    loadBoard();
  }
  const done = e.target.closest('[data-done]');
  if (done) {
    await api(`/api/reminders/${done.dataset.done}`, { method: 'PATCH', body: JSON.stringify({ status: 'done' }) });
    loadReminders();
  }
  const snoozeBtn = e.target.closest('[data-snooze]');
  if (snoozeBtn) {
    await api(`/api/reminders/${snoozeBtn.dataset.snooze}`, {
      method: 'PATCH', body: JSON.stringify({ snooze_seconds: 600 })
    });
    loadReminders();
  }
  const pin = e.target.closest('[data-pin-message]');
  if (pin) {
    await api(`/api/messages/${pin.dataset.pinMessage}/pin`, {
      method: 'POST', body: JSON.stringify({ target: 'memory' })
    });
    toast('已钉入长期记忆');
    loadFiles();
  }
  const review = e.target.closest('[data-review]');
  if (review) {
    await api(`/api/reviews/${review.dataset.review}`, {
      method: 'POST',
      body: JSON.stringify({ action: review.dataset.action }),
    });
    refreshAll();
  }
  const restore = e.target.closest('[data-restore-file]');
  if (restore) {
    await api(
      `/api/files/${encodeURIComponent(restore.dataset.restoreFile)}/versions/${restore.dataset.version}/restore`,
      { method: 'POST', body: '{}' }
    );
    toast('已恢复');
    loadFile(currentFile);
  }
};

$('#authForm').onsubmit = async (e) => {
  e.preventDefault();
  accessKey = $('#accessKeyInput').value.trim();
  localStorage.setItem('kirari_access_key', accessKey);
  try {
    await refreshAll();
    hideAuth();
  } catch (err) {
    toast('密钥不正确');
  }
};

$('#clearAccessKeyBtn').onclick = () => {
  accessKey = '';
  localStorage.removeItem('kirari_access_key');
  if (!telegramInitData) showAuth();
};

(async () => {
  $('#currentDate').textContent = new Intl.DateTimeFormat('zh-CN', {
    month: 'long', day: 'numeric', weekday: 'long'
  }).format(new Date()).replace(/日(?=星期)/, '日 · ');
  $('#dateDigits').textContent = new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit'
  }).format(new Date()).replace('/', '—');
  const initialTab = location.hash.slice(1);
  if (initialTab) switchTab(initialTab, { updateHash: false });
  const auth = await fetch('/api/auth/status').then(res => res.json());
  $('#clearAccessKeyBtn').hidden = Boolean(telegramInitData);
  if (auth.required && !accessKey && !telegramInitData) {
    showAuth();
    return;
  }
  refreshAll().catch(err => toast(err.message));
})();
