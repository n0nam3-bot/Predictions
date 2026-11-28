// Runs the real site/app.js against site/demo/latest.json with a tiny DOM stub and writes the rendered page as static HTML.
// Used by scripts/preview_site.py to look at the design without a browser. Usage: node scripts/preview_dom.js <out.html> [dark] [open]
const fs = require('fs'), vm = require('vm'), path = require('path');
const site = path.join(__dirname, '..', 'site');
const [out, ...flags] = process.argv.slice(2);
const dark = flags.includes('dark'), expand = flags.includes('open');
const demo = JSON.parse(fs.readFileSync(path.join(site, 'demo', 'latest.json'), 'utf8'));
const els = {};
const mk = () => ({ innerHTML: '', textContent: '', hidden: false, value: '', disabled: false, min: '', max: '', dataset: {}, setAttribute() {}, addEventListener() {} });
const document = { hidden: false, querySelector: (s) => (els[s] = els[s] || mk()), addEventListener() {} };
const window = { PicksLib: require(path.join(site, 'lib.js')), addEventListener() {} };
const sandbox = { window, document, URLSearchParams, location: { search: '?demo=1', hostname: 'localhost', hash: '', pathname: '/' },
  localStorage: { getItem() { return null; }, setItem() {} }, history: { replaceState() {} }, fetch: async () => ({ ok: true, json: async () => demo }),
  setInterval() {}, console };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(site, 'app.js'), 'utf8'), sandbox);
setTimeout(() => {
  let html = fs.readFileSync(path.join(site, 'index.html'), 'utf8');
  let list = els['#list'].innerHTML;
  if (expand) list = list.replace('aria-expanded="false"', 'aria-expanded="true"').replace('data-open="false"', 'data-open="true"');
  html = html.replace('<section id="summary" class="summary" aria-live="polite"></section>', '<section id="summary" class="summary">' + els['#summary'].innerHTML + '</section>')
    .replace('<nav id="tabs" class="tabs" aria-label="Sport"></nav>', '<nav id="tabs" class="tabs">' + els['#tabs'].innerHTML + '</nav>')
    .replace('<main id="list" aria-busy="true"></main>', '<main id="list">' + list + '</main>')
    .replace('<span id="dateLabel">Today</span>', '<span id="dateLabel">' + els['#dateLabel'].textContent + '</span>');
  // WeasyPrint collapses button boxes that hold block children and ignores <details>; browsers do neither. Preview buttons as blocks.
  html = html.replace(/<button\b/g, '<div').replace(/<\/button>/g, '</div>').replace('<div class="primary" id="todayBtn">Today</div>', '');
  const night = ':root{--page:#0a0b0d;--bg:#0e0f11;--card:#15171a;--fg:#eef0f2;--muted:#a0a6af;--line:#262a30;--wash:#1d2025;--accent:#7aa2ff;--accent-fg:#0b1020;--accent-bg:#172345;--pos:#4cc38a;--pos-bg:#12301f;--neg:#ff8a7d;--neg-bg:#3a1a17;--gold:#f2c14e;--gold-bg:#3a2f10;--shadow:none}';
  const css = fs.readFileSync(path.join(site, 'styles.css'), 'utf8') + '\n@page{size:390px 6000px;margin:0}body{width:390px}.panel{display:block}.panel[data-open="false"]{display:none}.enter{animation:none}' + (dark ? night : '');
  html = html.replace('<link rel="stylesheet" href="styles.css">', '<style>' + css + '</style>');
  fs.writeFileSync(out, html);
}, 400);
