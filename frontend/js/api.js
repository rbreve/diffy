// Thin wrapper around the backend API.

async function postJson(url, body) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    throw new Error(await readError(resp));
  }
  return resp.json();
}

async function readError(resp) {
  try {
    const data = await resp.json();
    return typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
  } catch {
    return `${resp.status} ${resp.statusText}`;
  }
}

export async function getConfig() {
  const resp = await fetch('/api/config');
  if (!resp.ok) throw new Error(await readError(resp));
  return resp.json();
}

export function loadGithub(url) {
  return postJson('/api/diff/github', { url });
}

export function loadLocal(repoPath, base, head) {
  // Blank head -> working tree (uncommitted); blank base -> default branch.
  return postJson('/api/diff/local', { repo_path: repoPath, base, head });
}

export async function getRefs(repoPath) {
  const resp = await fetch(`/api/local/refs?repo_path=${encodeURIComponent(repoPath)}`);
  if (!resp.ok) throw new Error(await readError(resp));
  return resp.json();
}

export async function getFile(diffId, path) {
  const resp = await fetch(`/api/file?diff_id=${encodeURIComponent(diffId)}&path=${encodeURIComponent(path)}`);
  if (!resp.ok) throw new Error(await readError(resp));
  return resp.json();
}

export function summary(diffId) {
  return postJson('/api/ai/summary', { diff_id: diffId });
}

export function explain(diffId, path) {
  return postJson('/api/ai/explain', { diff_id: diffId, path });
}

// Streams the assistant reply; calls onChunk(text) for each delta.
export async function chatStream(diffId, messages, focusPath, onChunk) {
  const resp = await fetch('/api/ai/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ diff_id: diffId, messages, focus_path: focusPath }),
  });
  if (!resp.ok) throw new Error(await readError(resp));
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    onChunk(decoder.decode(value, { stream: true }));
  }
}
