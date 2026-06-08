// Application orchestration: wires the UI to the API and the Monaco diff view.
import { marked } from 'https://cdn.jsdelivr.net/npm/marked@12/+esm';
import DOMPurify from 'https://cdn.jsdelivr.net/npm/dompurify@3/+esm';

import * as api from './api.js';
import * as diff from './diff.js';
import { initLayout } from './layout.js';

const state = {
  source: 'github',
  diffId: null,
  files: [],
  currentPath: null,
  chat: [],             // [{role, content}]
};

const $ = (sel) => document.querySelector(sel);
const md = (text) => DOMPurify.sanitize(marked.parse(text || ''));

// Set from /api/config on boot; gates the AI pane (chat/summary/explain).
let aiEnabled = true;

function setStatus(text, kind = '') {
  const el = $('#status');
  el.textContent = text;
  el.className = `status ${kind}`;
}

// ---------- Source switching + loading ----------

function wireSourceToggle() {
  $('#source-seg').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-src]');
    if (!btn) return;
    state.source = btn.dataset.src;
    document.querySelectorAll('#source-seg button').forEach((b) => b.classList.toggle('active', b === btn));
    $('#fields-github').classList.toggle('hidden', state.source !== 'github');
    $('#fields-local').classList.toggle('hidden', state.source !== 'local');
    if (state.source === 'local' && $('#local-path').value.trim()) loadRefs();
  });
}

// Read the repo's branches and fill the base/head dropdowns.
async function loadRefs() {
  const path = $('#local-path').value.trim();
  if (!path) return;
  setStatus('Reading branches…', 'busy');
  try {
    const refs = await api.getRefs(path);
    fillRefs($('#local-base'), refs, false);
    fillRefs($('#local-head'), refs, true);
    const all = [...refs.branches, ...refs.remotes];
    $('#local-base').value = all.includes(refs.default_base) ? refs.default_base : (all[0] || '');
    $('#local-head').value = '';   // default to the working tree (uncommitted)
    setStatus(`${refs.branches.length} branches · on ${refs.current}`);
  } catch (err) {
    setStatus(err.message || String(err), 'error');
  }
}

function fillRefs(sel, refs, withWorktree) {
  sel.innerHTML = '';
  if (withWorktree) {
    sel.appendChild(makeOption('', '◆ Working tree (uncommitted)'));
    sel.appendChild(makeOption('HEAD', 'HEAD (current commit)'));
  } else {
    sel.appendChild(makeOption('', '(default branch)'));
  }
  if (refs.branches.length) sel.appendChild(makeGroup('Local branches', refs.branches));
  if (refs.remotes.length) sel.appendChild(makeGroup('Remote branches', refs.remotes));
}

function makeOption(value, label) {
  const o = document.createElement('option');
  o.value = value;
  o.textContent = label;
  return o;
}

function makeGroup(label, items) {
  const g = document.createElement('optgroup');
  g.label = label;
  for (const it of items) g.appendChild(makeOption(it, it));
  return g;
}

async function load() {
  setStatus('Loading…', 'busy');
  $('#load-btn').disabled = true;
  try {
    const result = state.source === 'github'
      ? await api.loadGithub($('#gh-url').value.trim())
      : await api.loadLocal($('#local-path').value.trim(), $('#local-base').value.trim(), $('#local-head').value.trim());
    onDiffLoaded(result);
  } catch (err) {
    const msg = err.message || String(err);
    setStatus('Load failed', 'error');
    $('#file-list').innerHTML = `<div class="empty load-error">Load failed:\n\n${escapeHtml(msg)}</div>`;
  } finally {
    $('#load-btn').disabled = false;
  }
}

function onDiffLoaded(result) {
  state.diffId = result.diff_id;
  state.files = result.files;
  state.currentPath = null;
  state.chat = [];
  renderFiles();
  if (aiEnabled) {
    renderChat();
    $('#summary-out').innerHTML = '';
    resetExplain();
  }
  $('#diff-title').textContent = result.title;
  setStatus(`${result.files.length} files · ${result.source}`);
  if (result.files.length) selectFile(result.files[0].path);
  updateNav();
}

// ---------- File list ----------

function renderFiles() {
  $('#file-count').textContent = state.files.length ? `(${state.files.length})` : '';
  const list = $('#file-list');
  if (!state.files.length) {
    list.innerHTML = '<div class="empty">No changed files.</div>';
    return;
  }
  list.innerHTML = '';
  for (const f of state.files) {
    const item = document.createElement('div');
    item.className = 'file-item' + (f.path === state.currentPath ? ' active' : '');
    item.innerHTML = `
      <span class="badge ${f.status}">${f.status[0]}</span>
      <span class="file-name" title="${f.path}">${f.path}</span>
      <span class="stat"><span class="add">+${f.additions}</span> <span class="del">-${f.deletions}</span></span>`;
    item.addEventListener('click', () => selectFile(f.path));
    list.appendChild(item);
  }
}

function currentIndex() {
  return state.files.findIndex((f) => f.path === state.currentPath);
}

function navigateFile(delta) {
  if (!state.files.length) return;
  const idx = currentIndex();
  const next = Math.min(state.files.length - 1, Math.max(0, (idx < 0 ? 0 : idx) + delta));
  if (next !== idx) selectFile(state.files[next].path);
}

function updateNav() {
  const idx = currentIndex();
  $('#nav-prev').disabled = idx <= 0;
  $('#nav-next').disabled = idx < 0 || idx >= state.files.length - 1;
  $('#file-pos').textContent = state.files.length && idx >= 0 ? `${idx + 1}/${state.files.length}` : '';
}

let maximized = false;
function toggleMaximize(force) {
  maximized = force === undefined ? !maximized : force;
  document.body.classList.toggle('maximized', maximized);
  $('#ctl-max').textContent = maximized ? '✕' : '⛶';
  $('#ctl-max').title = maximized ? 'Exit full screen (Esc)' : 'Full screen (Esc to exit)';
  requestAnimationFrame(() => diff.relayout());
}

async function selectFile(path) {
  state.currentPath = path;
  renderFiles();
  updateNav();
  if (aiEnabled) resetExplain();
  $('#diff-title').textContent = path;
  setStatus('Loading file…', 'busy');
  try {
    const file = await api.getFile(state.diffId, path);
    diff.showFile(file);
    setStatus(file.truncated ? 'File too large — showing what is available' : '', file.truncated ? 'error' : '');
  } catch (err) {
    setStatus(err.message || String(err), 'error');
  }
}

// ---------- AI: tabs ----------

function wireTabs() {
  $('#ai-tabs').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-tab]');
    if (!btn) return;
    document.querySelectorAll('#ai-tabs button').forEach((b) => b.classList.toggle('active', b === btn));
    document.querySelectorAll('.tab-pane').forEach((p) => p.classList.toggle('active', p.id === `tab-${btn.dataset.tab}`));
  });
}

function requireDiff() {
  if (!state.diffId) { setStatus('Load a diff first.', 'error'); return false; }
  return true;
}

// ---------- AI: chat ----------

function renderChat() {
  const box = $('#chat-messages');
  if (!state.chat.length) {
    box.innerHTML = '<div class="hint">Ask anything about the loaded change. Open a file to give the AI its full contents as extra context.</div>';
    return;
  }
  box.innerHTML = '';
  for (const m of state.chat) {
    const el = document.createElement('div');
    el.className = `msg ${m.role}`;
    el.innerHTML = m.role === 'assistant' ? md(m.content) : escapeHtml(m.content);
    box.appendChild(el);
  }
  box.scrollTop = box.scrollHeight;
}

async function sendChat() {
  if (!requireDiff()) return;
  const text = $('#chat-text').value.trim();
  if (!text) return;
  $('#chat-text').value = '';
  state.chat.push({ role: 'user', content: text });
  const assistant = { role: 'assistant', content: '' };
  state.chat.push(assistant);
  renderChat();

  const box = $('#chat-messages');
  const bubble = box.lastElementChild;
  bubble.classList.add('streaming');
  $('#chat-send').disabled = true;
  try {
    await api.chatStream(state.diffId, state.chat.slice(0, -1), state.currentPath, (chunk) => {
      assistant.content += chunk;
      bubble.innerHTML = md(assistant.content);
      box.scrollTop = box.scrollHeight;
    });
  } catch (err) {
    assistant.content = `_Error: ${err.message || err}_`;
    bubble.innerHTML = md(assistant.content);
  } finally {
    bubble.classList.remove('streaming');
    $('#chat-send').disabled = false;
  }
}

// ---------- AI: summary ----------

async function runSummary() {
  if (!requireDiff()) return;
  const out = $('#summary-out');
  out.innerHTML = '<div class="hint">Thinking…</div>';
  $('#summary-btn').disabled = true;
  try {
    const { summary } = await api.summary(state.diffId);
    out.innerHTML = md(summary);
  } catch (err) {
    out.innerHTML = `<div class="hint">Error: ${escapeHtml(err.message || String(err))}</div>`;
  } finally {
    $('#summary-btn').disabled = false;
  }
}

// ---------- AI: explain current file ----------

// Reflect the open file in the Explain tab and clear any stale explanation.
function resetExplain() {
  $('#explain-file').textContent = state.currentPath || '';
  $('#explain-out').innerHTML = state.currentPath
    ? ''
    : '<div class="hint">Open a file, then explain the changes in it.</div>';
}

async function runExplain() {
  if (!requireDiff()) return;
  if (!state.currentPath) { setStatus('Open a file to explain.', 'error'); return; }
  const out = $('#explain-out');
  out.innerHTML = '<div class="hint">Explaining…</div>';
  $('#explain-btn').disabled = true;
  try {
    const { explanation } = await api.explain(state.diffId, state.currentPath);
    out.innerHTML = md(explanation);
  } catch (err) {
    out.innerHTML = `<div class="hint">Error: ${escapeHtml(err.message || String(err))}</div>`;
  } finally {
    $('#explain-btn').disabled = false;
  }
}

// ---------- helpers + bootstrap ----------

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (ch) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));
}

async function main() {
  try {
    aiEnabled = (await api.getConfig()).ai_enabled;
  } catch {
    aiEnabled = true;  // fail open: keep the AI pane if config can't be read.
  }
  if (!aiEnabled) $('#pane-ai').remove();

  initLayout({ aiEnabled });
  await diff.initDiff($('#diff-editor'));
  wireSourceToggle();

  $('#load-btn').addEventListener('click', load);
  $('#gh-url').addEventListener('keydown', (e) => { if (e.key === 'Enter') load(); });
  $('#local-path').addEventListener('change', loadRefs);
  $('#local-path').addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); loadRefs(); } });

  if (aiEnabled) {
    wireTabs();
    $('#chat-send').addEventListener('click', sendChat);
    $('#chat-text').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
    });
    $('#summary-btn').addEventListener('click', runSummary);
    $('#explain-btn').addEventListener('click', runExplain);
  }

  $('#ctl-sbs').addEventListener('change', (e) => diff.setSideBySide(e.target.checked));
  $('#ctl-wrap').addEventListener('change', (e) => diff.setWrap(e.target.checked));
  $('#ctl-font').addEventListener('input', (e) => diff.setFont(Number(e.target.value)));
  $('#ctl-fontfamily').addEventListener('change', (e) => diff.setFontFamily(e.target.value));
  $('#ctl-theme').addEventListener('change', (e) => diff.setTheme(e.target.value));

  $('#nav-prev').addEventListener('click', () => navigateFile(-1));
  $('#nav-next').addEventListener('click', () => navigateFile(1));
  $('#ctl-max').addEventListener('click', () => toggleMaximize());
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && maximized) { toggleMaximize(false); return; }
    if (e.altKey && e.key === 'ArrowLeft') { e.preventDefault(); navigateFile(-1); }
    if (e.altKey && e.key === 'ArrowRight') { e.preventDefault(); navigateFile(1); }
  });

  setStatus('Ready');
}

main();
