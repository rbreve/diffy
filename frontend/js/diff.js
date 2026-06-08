// Owns the Monaco diff editor: model creation, language detection,
// and view controls.

let monaco = null;
let diffEditor = null;
let extMap = null;

export async function initDiff(container) {
  monaco = await window.monacoReady;
  diffEditor = monaco.editor.createDiffEditor(container, {
    theme: 'vs-dark',
    automaticLayout: true,      // tracks pane resizing on its own
    readOnly: true,
    originalEditable: false,
    renderSideBySide: true,
    fontSize: 13,
    minimap: { enabled: true },
    scrollBeyondLastLine: false,
    renderOverviewRuler: true,
  });
}

function buildExtMap() {
  if (extMap) return extMap;
  extMap = {};
  for (const lang of monaco.languages.getLanguages()) {
    (lang.extensions || []).forEach((ext) => { extMap[ext.toLowerCase()] = lang.id; });
    (lang.filenames || []).forEach((fn) => { extMap['name:' + fn.toLowerCase()] = lang.id; });
  }
  return extMap;
}

function languageFor(path) {
  const map = buildExtMap();
  const base = path.split('/').pop().toLowerCase();
  if (map['name:' + base]) return map['name:' + base];
  const dot = base.lastIndexOf('.');
  if (dot >= 0 && map[base.slice(dot)]) return map[base.slice(dot)];
  return 'plaintext';
}

// file = { path, old_content, new_content }
export function showFile(file) {
  const language = languageFor(file.path);
  const original = monaco.editor.createModel(file.old_content || '', language);
  const modified = monaco.editor.createModel(file.new_content || '', language);

  const prev = diffEditor.getModel();
  diffEditor.setModel({ original, modified });
  if (prev) { prev.original?.dispose(); prev.modified?.dispose(); }
}

export function relayout() { diffEditor?.layout(); }
export function setSideBySide(on) { diffEditor.updateOptions({ renderSideBySide: on }); }

export async function setFontFamily(family) {
  diffEditor.updateOptions({ fontFamily: family, fontLigatures: true });
  // Web fonts load lazily; wait for the chosen one then remeasure so Monaco's
  // column metrics (cursor, selections) line up with the new glyph widths.
  const match = family.match(/'([^']+)'/);
  if (match && document.fonts?.load) {
    try {
      await document.fonts.load(`14px '${match[1]}'`);
      monaco.editor.remeasureFonts();
    } catch { /* fall back to whatever loaded */ }
  }
}
export function setWrap(on) { diffEditor.updateOptions({ wordWrap: on ? 'on' : 'off' }); }
export function setFont(px) { diffEditor.updateOptions({ fontSize: px }); }
export function setTheme(name) { monaco.editor.setTheme(name); }
