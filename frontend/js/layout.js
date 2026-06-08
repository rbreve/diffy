// Resizable three-pane layout via Split.js (loaded as an ES module from CDN).
import Split from 'https://cdn.jsdelivr.net/npm/split.js@1.6.5/+esm';

export function initLayout({ aiEnabled = true } = {}) {
  if (aiEnabled) {
    Split(['#pane-files', '#pane-diff', '#pane-ai'], {
      sizes: [20, 52, 28],
      minSize: [140, 360, 260],
      gutterSize: 6,
      snapOffset: 0,
    });
  } else {
    Split(['#pane-files', '#pane-diff'], {
      sizes: [22, 78],
      minSize: [140, 360],
      gutterSize: 6,
      snapOffset: 0,
    });
  }
}
