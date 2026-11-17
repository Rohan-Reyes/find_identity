// Find Identity web UI. Plain ES module, no build step.
// Every value from the server or the web is inserted with textContent / attributes,
// never innerHTML, and links are only followed if they are http(s).

const $view = document.getElementById('view');
const state = { info: null, platforms: null, files: [], source: null, filter: 'found', query: '' };

// ---------- helpers ----------
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'html') el.innerHTML = v; // only used for our own static SVG icons
    else if (k === 'style') el.style.cssText = v; // CSSOM, allowed by the CSP
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
const safeUrl = (u) => { try { const x = new URL(u, location.href); return /^https?:$/.test(x.protocol) ? x.href : null; } catch { return null; } };
const ext = (href, attrs, ...kids) => h('a', { href: safeUrl(href) || '#', target: '_blank', rel: 'noopener noreferrer nofollow', ...attrs }, ...kids);

const ICONS = {
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  out: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
  image: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="3"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/></svg>',
  down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
  redo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
  pin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 21s-7-6.2-7-12a7 7 0 0 1 14 0c0 5.8-7 12-7 12z"/><circle cx="12" cy="9" r="2.5"/></svg>',
  sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  moon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/></svg>',
  pulse: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>',
};
const put = (...kids) => $view.append(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
const icon = (name) => h('span', { html: ICONS[name], style: 'display:contents' });

function toast(msg, bad = false) {
  const t = h('div', { class: 'toast' + (bad ? ' bad' : '') }, msg);
  document.getElementById('toasts').append(t);
  setTimeout(() => t.remove(), bad ? 6000 : 3200);
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = `Request failed (HTTP ${res.status})`;
    try { const j = await res.json(); if (j.detail) msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch {}
    throw new Error(msg);
  }
  const type = res.headers.get('content-type') || '';
  return type.includes('json') ? res.json() : res;
}

const fmtDate = (iso) => iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '';
const STATUS_LABEL = { found: 'Found', not_found: 'Not found', error: "Couldn't check", manual: 'Check by hand', skipped: 'Not valid there' };

// ---------- theme ----------
function applyTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
  const dark = t ? t === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
  const btn = document.getElementById('theme');
  btn.innerHTML = dark ? ICONS.sun : ICONS.moon;
}
function initTheme() {
  let saved = null;
  try { saved = localStorage.getItem('fi-theme'); } catch {}
  const forced = new URLSearchParams(location.search).get('theme');
  if (forced === 'light' || forced === 'dark') saved = forced;
  applyTheme(saved);
  document.getElementById('theme').addEventListener('click', () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === 'dark'
      : matchMedia('(prefers-color-scheme: dark)').matches;
    const next = dark ? 'light' : 'dark';
    try { localStorage.setItem('fi-theme', next); } catch {}
    applyTheme(next);
  });
}

// ---------- router ----------
function closeStream() { if (state.source) { state.source.close(); state.source = null; } }
async function route() {
  closeStream();
  const hash = location.hash.slice(1) || '/';
  const [, page, id] = hash.split('/');
  document.querySelectorAll('[data-nav]').forEach((a) => a.classList.toggle('active',
    a.dataset.nav === ({ '': 'scan', r: 'history', history: 'history', tools: 'tools', platforms: 'platforms' }[page || ''])));
  $view.replaceChildren();
  try {
    if (!page) await viewScan();
    else if (page === 'r' && id) await viewReport(id);
    else if (page === 'history') await viewHistory();
    else if (page === 'tools') viewTools();
    else if (page === 'platforms') await viewPlatforms();
    else location.hash = '#/';
  } catch (e) {
    put(h('div', { class: 'card' }, h('h2', {}, 'Something went wrong'), h('p', { class: 'muted' }, e.message)));
  }
  $view.focus({ preventScroll: true });
}

// ---------- new scan ----------
function parseNames(text) {
  const out = [];
  for (const t of text.split(/[\s,;]+/)) {
    const n = t.trim().replace(/^@/, '');
    if (n && !out.some((o) => o.toLowerCase() === n.toLowerCase())) out.push(n);
  }
  return out;
}

async function viewScan() {
  const info = state.info;
  const namesBox = h('textarea', { class: 'names', id: 'names', placeholder: 'jane.doe\n@janedoe_art\njdoe99', spellcheck: 'false', autocomplete: 'off' });
  const preview = h('div', { class: 'chips', style: 'margin-top:8px' });
  const updatePreview = () => {
    const names = parseNames(namesBox.value);
    preview.replaceChildren(...names.slice(0, 30).map((n) => h('span', { class: 'tag' + (/^[A-Za-z0-9._-]{1,40}$/.test(n) ? '' : ' error') }, '@' + n)));
  };
  namesBox.addEventListener('input', updatePreview);

  const variants = h('input', { type: 'checkbox', id: 'variants' });
  const cats = Object.entries(info.categories).map(([key, label]) =>
    h('label', { class: 'chip' }, h('input', { type: 'checkbox', value: key, name: 'cat' }), label));

  // images
  const fileInput = h('input', { type: 'file', accept: 'image/*', multiple: true, class: 'hidden' });
  const thumbs = h('div', { class: 'thumbs' });
  const renderThumbs = () => {
    thumbs.replaceChildren(...state.files.map((f, i) => {
      const url = URL.createObjectURL(f);
      return h('figure', { title: f.name },
        h('img', { src: url, alt: f.name, onload: () => URL.revokeObjectURL(url) }),
        h('button', { type: 'button', 'aria-label': `Remove ${f.name}`, onclick: () => { state.files.splice(i, 1); renderThumbs(); } }, '×'));
    }));
  };
  const addFiles = (list) => {
    for (const f of list) {
      if (!f.type.startsWith('image/')) { toast(`${f.name} is not an image`, true); continue; }
      if (f.size > info.max_image_mb * 1048576) { toast(`${f.name} is over ${info.max_image_mb} MB`, true); continue; }
      if (state.files.length >= info.max_images) { toast(`Up to ${info.max_images} images per scan`, true); break; }
      state.files.push(f);
    }
    renderThumbs();
  };
  fileInput.addEventListener('change', () => { addFiles(fileInput.files); fileInput.value = ''; });
  const drop = h('div', { class: 'drop', tabindex: '0', role: 'button',
    onclick: () => fileInput.click(),
    onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); } },
    ondragover: (e) => { e.preventDefault(); drop.classList.add('over'); },
    ondragleave: () => drop.classList.remove('over'),
    ondrop: (e) => { e.preventDefault(); drop.classList.remove('over'); addFiles(e.dataTransfer.files); } },
    icon('image'), h('strong', {}, 'Drop photos or click to choose'),
    h('div', { class: 'hint' }, `Up to ${info.max_images} images, ${info.max_image_mb} MB each. You can also paste one.`));
  const urlBox = h('textarea', { rows: 2, placeholder: 'https://example.com/photo.jpg (one per line)' });
  renderThumbs();

  const label = h('input', { type: 'text', placeholder: 'Label this scan (optional), e.g. "My accounts audit"', maxlength: 80 });
  const startBtn = h('button', { class: 'btn primary big', type: 'submit' }, icon('search'), 'Start scan');

  const form = h('form', { onsubmit: async (e) => {
    e.preventDefault();
    const names = parseNames(namesBox.value);
    const urls = urlBox.value.split(/\s+/).filter(Boolean);
    if (!names.length && !state.files.length && !urls.length) { toast('Enter a username or add an image', true); namesBox.focus(); return; }
    const fd = new FormData();
    fd.append('usernames', names.join(','));
    fd.append('include_variants', variants.checked ? 'true' : 'false');
    fd.append('categories', [...form.querySelectorAll('input[name=cat]:checked')].map((c) => c.value).join(','));
    fd.append('image_urls', urls.join('\n'));
    fd.append('label', label.value.trim());
    state.files.forEach((f) => fd.append('images', f, f.name));
    startBtn.disabled = true;
    startBtn.replaceChildren(h('span', { class: 'spin' }), 'Starting…');
    try {
      const res = await api('/api/scans', { method: 'POST', body: fd });
      state.files = [];
      location.hash = `#/r/${res.id}`;
    } catch (err) {
      toast(err.message, true);
      startBtn.disabled = false;
      startBtn.replaceChildren(icon('search'), 'Start scan');
    }
  } },
    h('div', { class: 'grid-2' },
      h('section', { class: 'card stack' },
        h('div', {}, h('label', { class: 'label', for: 'names' }, 'Usernames'),
          namesBox, preview,
          h('div', { class: 'hint' }, `One per line, or separated by commas. Up to ${info.max_usernames}.`)),
        h('label', { class: 'switch' }, variants, h('span', {}, h('b', {}, 'Try common variations'), h('br'),
          h('span', { class: 'muted small' }, 'jane.doe also checks janedoe, jane_doe, jdoe…'))),
        h('div', {}, h('span', { class: 'label' }, 'Only these categories'),
          h('div', { class: 'chips' }, cats),
          h('div', { class: 'hint' }, `Leave empty to check all ${state.platforms.length} platforms.`))),
      h('section', { class: 'card stack' },
        h('div', {}, h('span', { class: 'label' }, 'Images'), drop, fileInput, thumbs),
        h('div', {}, h('label', { class: 'label' }, 'Image links'), urlBox,
          h('div', { class: 'hint' }, 'Links get one-click reverse searches on Google Lens, Bing, Yandex and TinEye.')),
        h('div', { class: 'hint' }, info.lens_enabled
          ? 'Google Lens matches are on (SerpApi key found).'
          : 'Add SERPAPI_API_KEY to .env to also get Google Lens matches inside the app.'))),
    h('div', { class: 'start-bar' }, label, startBtn));

  const recent = h('div');
  put(
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Find public profiles'),
      h('p', {}, 'Check where a username exists and what a photo gives away, using public data only.'))),
    form, recent);

  // paste images anywhere on this page
  const onPaste = (e) => {
    if (!document.body.contains(form)) { window.removeEventListener('paste', onPaste); return; }
    const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith('image/'));
    if (files.length) { e.preventDefault(); addFiles(files); }
  };
  window.addEventListener('paste', onPaste);

  const list = await api('/api/reports');
  if (list.length) {
    recent.append(h('div', { class: 'card', style: 'margin-top:16px' },
      h('div', { class: 'row', style: 'margin-bottom:8px' }, h('h2', {}, 'Recent scans'), h('span', { class: 'spacer' }), h('a', { href: '#/history' }, 'All history')),
      historyTable(list.slice(0, 4), false)));
  }
}

// ---------- report ----------
function hitEl(r) {
  const sub = r.status === 'found' ? r.url.replace(/^https?:\/\/(www\.)?/, '')
    : r.status === 'error' ? r.detail || "Couldn't check"
    : r.status === 'manual' ? 'Open to check' : STATUS_LABEL[r.status];
  const kids = [h('span', { class: 'dot' }), h('span', { class: 'meta' }, h('div', { class: 'name' }, r.platform), h('div', { class: 'sub' }, sub))];
  if (r.status === 'found' || r.status === 'manual') return ext(r.url, { class: `hit ${r.status}`, title: r.url }, kids, icon('out'));
  return h('div', { class: `hit ${r.status}`, title: r.detail || '' }, kids);
}

function renderProfiles(report, box) {
  const q = state.query.toLowerCase();
  const variantOf = {};
  for (const [base, vs] of Object.entries(report.query.variants || {})) vs.forEach((v) => { variantOf[v.toLowerCase()] = base; });
  const names = [...report.query.usernames, ...Object.values(report.query.variants || {}).flat()];
  const blocks = [];
  for (const u of names) {
    const rows = report.profiles.filter((r) => r.username === u);
    const found = rows.filter((r) => r.status === 'found').length;
    let shown = rows.filter((r) => state.filter === 'all' || r.status === state.filter);
    if (q) shown = shown.filter((r) => r.platform.toLowerCase().includes(q) || r.category.includes(q));
    shown.sort((a, b) => (a.status !== 'found') - (b.status !== 'found') || a.platform.localeCompare(b.platform));
    const isVariant = variantOf[u.toLowerCase()];
    if (isVariant && !found && state.filter === 'found') continue; // hide empty variations
    blocks.push(h('section', { class: 'user-block' },
      h('div', { class: 'user-head' }, h('h2', {}, '@' + u),
        isVariant ? h('span', { class: 'tag' }, `variation of @${isVariant}`) : null,
        h('span', { class: 'tag' + (found ? ' found' : '') }, `${found} found`),
        h('span', { class: 'muted small' }, `${rows.length} checked`)),
      shown.length ? h('div', { class: 'hits' }, shown.map(hitEl))
        : h('div', { class: 'empty small' }, rows.length < (report.query.platforms || []).length ? 'Checking…' : 'Nothing in this view.')));
  }
  box.replaceChildren(...blocks);
}

function imageCard(report, img, thumb) {
  if (img.error) return h('div', { class: 'card' }, h('h3', {}, img.filename), h('p', { class: 'muted' }, img.error));
  const fact = (k, v) => v || v === 0 ? h('div', {}, h('span', {}, k), h('b', {}, v)) : null;
  const flags = (img.flags || []).map((f) => h('li', { class: /No EXIF|No colour/.test(f) ? 'info' : '' }, f));
  const exifRows = Object.entries(img.exif || {}).sort().map(([k, v]) => h('tr', {}, h('td', {}, k), h('td', {}, v)));
  const matches = img.matches || [];
  return h('article', { class: 'card img-card' },
    h('img', { class: 'shot', src: thumb || `/api/scans/${report.id}/images/${img.index}`, alt: img.filename }),
    h('div', {},
      h('div', { class: 'row' }, h('h3', {}, img.filename),
        img.source_url ? ext(img.source_url, { class: 'small' }, 'source link') : null),
      h('div', { class: 'facts' },
        fact('Size', `${img.width} × ${img.height} (${img.megapixels} MP)`),
        fact('Format', `${img.format} · ${img.file_size_kb} KB`),
        fact('Camera', img.camera), fact('Taken', img.taken), fact('Software', img.software),
        fact('dHash', h('span', { class: 'mono' }, img.dhash))),
      flags.length ? h('ul', { class: 'flags' }, flags) : null,
      img.gps ? h('div', { class: 'gps' }, icon('pin'),
        h('div', {}, h('div', { class: 'small muted' }, 'GPS location in EXIF'),
          h('b', {}, `${img.gps.latitude}, ${img.gps.longitude}`),
          img.gps.altitude_m !== undefined ? h('span', { class: 'muted small' }, ` · ${img.gps.altitude_m} m`) : null),
        h('span', { class: 'spacer' }),
        ext(img.gps.maps_url, { class: 'btn' }, 'OpenStreetMap'), ext(img.gps.google_maps_url, { class: 'btn' }, 'Google Maps')) : null,
      h('div', { class: 'engines' }, (img.links || []).map((l) =>
        ext(l.url, { class: 'btn', title: l.direct ? 'Runs the search with this image link' : 'Opens the engine; upload the image there' }, icon('search'), l.engine))),
      img.lens_error ? h('div', { class: 'callout' }, img.lens_error) : null,
      matches.length ? h('div', {}, h('h3', { style: 'margin-top:16px' }, `Google Lens: ${matches.length} matches`),
        h('div', { class: 'matches' }, matches.slice(0, 24).map((m) => ext(m.url, { class: 'match', title: m.url },
          m.thumbnail && safeUrl(m.thumbnail) ? h('img', { src: m.thumbnail, alt: '', loading: 'lazy', referrerpolicy: 'no-referrer' }) : null,
          h('div', {}, h('b', {}, m.title), h('span', {}, `${m.source}${m.kind === 'exact' ? ' · exact' : ''}`)))))) : null,
      exifRows.length ? h('details', {}, h('summary', {}, `All EXIF tags (${exifRows.length})`), h('table', { class: 'kv' }, exifRows)) : null,
      h('details', {}, h('summary', {}, 'File hashes'), h('table', { class: 'kv' },
        h('tr', {}, h('td', {}, 'MD5'), h('td', { class: 'mono' }, img.md5)),
        h('tr', {}, h('td', {}, 'SHA-256'), h('td', { class: 'mono' }, img.sha256))))));
}

async function viewReport(id) {
  let report = await api(`/api/reports/${id}`);
  const nImg = report.query.images.length;
  const users = report.query.usernames.map((u) => '@' + u);
  const title = report.label || [users.slice(0, 3).join(', ') + (users.length > 3 ? ` +${users.length - 3}` : ''),
    nImg ? `${nImg} image${nImg > 1 ? 's' : ''}` : ''].filter(Boolean).join(' · ') || 'Scan';
  const pill = h('span', { class: 'tag' });
  const bar = h('span');
  const status = h('span', { class: 'muted small' });
  const statEls = {};
  const stat = (key, label) => (statEls[key] = h('b', {}, '0'), h('div', { class: `stat ${key}` }, statEls[key], h('span', {}, label)));
  const profilesBox = h('div');
  const imagesBox = h('div', { class: 'stack' });
  const similarBox = h('div');
  const logBox = h('div', { class: 'log' });
  const logWrap = h('details', {}, h('summary', {}, 'Live log'), logBox);

  const cancelBtn = h('button', { class: 'btn', onclick: async () => { await api(`/api/scans/${id}/cancel`, { method: 'POST' }); } }, icon('stop'), 'Stop');
  const retryBtn = h('button', { class: 'btn', onclick: async () => {
    try { await api(`/api/scans/${id}/retry`, { method: 'POST' }); route(); } catch (e) { toast(e.message, true); }
  } }, icon('redo'), 'Retry failed checks');
  const exportBtns = ['json', 'csv', 'md'].map((f) => h('a', { class: 'btn', href: `/api/reports/${id}/export.${f}`, download: '' }, icon('down'), f.toUpperCase()));
  const delBtn = h('button', { class: 'btn ghost danger', title: 'Delete report', onclick: async () => {
    if (delBtn.dataset.armed !== '1') { delBtn.dataset.armed = '1'; delBtn.lastChild.textContent = 'Click again to delete'; setTimeout(() => { delBtn.dataset.armed = ''; delBtn.lastChild.textContent = 'Delete'; }, 3000); return; }
    await api(`/api/reports/${id}`, { method: 'DELETE' }); toast('Report deleted'); location.hash = '#/history';
  } }, icon('trash'), h('span', {}, 'Delete'));

  const seg = h('div', { class: 'seg', role: 'tablist' });
  const filters = [['found', 'Found'], ['all', 'All'], ['error', "Couldn't check"], ['manual', 'Check by hand']];
  const drawSeg = () => seg.replaceChildren(...filters.map(([k, l]) =>
    h('button', { class: state.filter === k ? 'on' : '', role: 'tab', 'aria-selected': String(state.filter === k), onclick: () => { state.filter = k; drawSeg(); renderProfiles(report, profilesBox); } }, l)));
  drawSeg();
  const search = h('input', { type: 'search', placeholder: 'Filter platforms', value: state.query, oninput: (e) => { state.query = e.target.value; renderProfiles(report, profilesBox); } });

  const hasNames = report.query.usernames.length > 0;
  put(
    h('div', { class: 'page-head' },
      h('div', {}, h('div', { class: 'row' }, h('h1', {}, title), pill),
        h('p', {}, `Started ${fmtDate(report.created)}${report.query.platforms.length ? ` · ${report.query.platforms.length} platforms` : ''}`, status)),
      h('div', { class: 'row' }, cancelBtn, retryBtn, ...exportBtns, delBtn)),
    h('div', { class: 'progress' }, bar),
    h('div', { class: 'stats' }, stat('found', 'Profiles found'), stat('not_found', 'Not found'), stat('error', "Couldn't check"), stat('manual', 'Check by hand'), stat('images', 'Images analysed')),
    similarBox,
    hasNames ? h('div', { class: 'toolbar' }, h('h2', {}, 'Profiles'), h('span', { class: 'spacer' }), seg, search) : null,
    profilesBox,
    report.query.images.length ? h('div', { class: 'toolbar' }, h('h2', {}, 'Images')) : null,
    imagesBox,
    hasNames ? logWrap : null);

  const paint = (running, completed, total) => {
    const counts = { found: 0, not_found: 0, error: 0, manual: 0, skipped: 0 };
    report.profiles.forEach((r) => { counts[r.status]++; });
    for (const k of ['found', 'not_found', 'error', 'manual']) statEls[k].textContent = counts[k];
    statEls.images.textContent = report.images.length;
    const pct = running ? (total ? Math.round(100 * completed / total) : 0) : 100;
    bar.style.width = pct + '%';
    pill.className = 'tag ' + (running ? 'running' : report.status === 'done' ? 'found' : 'error');
    pill.textContent = running ? `Scanning ${pct}%` : { done: 'Complete', cancelled: 'Stopped', error: 'Stopped with an error', interrupted: 'Interrupted (server restarted)' }[report.status] || report.status;
    cancelBtn.classList.toggle('hidden', !running);
    retryBtn.classList.toggle('hidden', running || !counts.error);
    exportBtns.forEach((b) => b.classList.toggle('hidden', running));
    status.textContent = running ? '' : report.finished ? ` · finished ${fmtDate(report.finished)}` : '';
  };
  const paintSimilar = () => {
    similarBox.replaceChildren(...(report.similar || []).map((p) => h('div', { class: 'callout' },
      p.identical ? `${p.a} and ${p.b} are the same file.` : `${p.a} and ${p.b} look like the same picture (${p.similarity}% similar).`)));
  };
  const paintImages = () => imagesBox.replaceChildren(...report.images.map((img) => imageCard(report, img)));

  renderProfiles(report, profilesBox);
  paintImages();
  paintSimilar();

  if (report.status !== 'running') { paint(false); return; }
  paint(true, 0, 1);
  const es = new EventSource(`/api/scans/${id}/events`);
  state.source = es;
  let pending = false;
  const schedule = () => { if (!pending) { pending = true; requestAnimationFrame(() => { pending = false; renderProfiles(report, profilesBox); }); } };
  es.onmessage = (msg) => {
    const ev = JSON.parse(msg.data);
    if (ev.type === 'start') {
      report.query = ev.query;
    } else if (ev.type === 'profile') {
      const r = ev.row;
      const i = report.profiles.findIndex((x) => x.platform === r.platform && x.username === r.username);
      if (i >= 0) report.profiles[i] = r; else report.profiles.push(r);
      schedule();
      logBox.prepend(h('div', { class: r.status }, `${new Date().toLocaleTimeString()}  @${r.username} · ${r.platform}: ${STATUS_LABEL[r.status]}${r.detail ? ` (${r.detail})` : ''}`));
    } else if (ev.type === 'image_start') {
      imagesBox.append(h('div', { class: 'card muted', 'data-pending': '1' }, h('span', { class: 'spin' }), ` Analysing ${ev.filename}…`));
    } else if (ev.type === 'image') {
      report.images.push(ev.image);
      paintImages();
    } else if (ev.type === 'problem') {
      toast(ev.message, true);
    } else if (ev.type === 'end') {
      es.close(); state.source = null;
      report.status = ev.status; report.similar = ev.similar; report.finished = new Date().toISOString();
      renderProfiles(report, profilesBox); paintSimilar();
      if (ev.status === 'done') toast(`Scan complete: ${ev.summary.found} profiles found`);
      paint(false);
      return;
    }
    paint(true, ev.completed, ev.total);
  };
  es.onerror = async () => {
    // The browser reconnects by itself and resumes from the last event. If the
    // server restarted, the job is gone; fall back to the saved report.
    if (es.readyState === EventSource.CLOSED) {
      state.source = null;
      try { report = await api(`/api/reports/${id}`); if (report.status !== 'running') route(); } catch {}
    }
  };
}

// ---------- history ----------
function historyTable(list, withDelete = true) {
  return h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
    h('thead', {}, h('tr', {}, h('th', {}, 'Scan'), h('th', {}, 'Date'), h('th', {}, 'Found'), h('th', {}, 'Images'), h('th', {}, 'Status'), withDelete ? h('th', {}) : null)),
    h('tbody', {}, list.map((r) => {
      const name = r.label || [r.usernames.slice(0, 3).map((u) => '@' + u).join(', '), r.images.length ? `${r.images.length} image${r.images.length > 1 ? 's' : ''}` : ''].filter(Boolean).join(' · ') || r.id;
      const more = r.usernames.length - 3;
      return h('tr', { class: 'click', onclick: () => { location.hash = `#/r/${r.id}`; } },
        h('td', {}, h('b', {}, name), more > 0 ? h('span', { class: 'muted small' }, ` +${more} more`) : null),
        h('td', { class: 'muted small' }, fmtDate(r.created)),
        h('td', {}, h('span', { class: 'tag' + (r.summary.found ? ' found' : '') }, r.summary.found)),
        h('td', {}, r.summary.images || '–'),
        h('td', {}, h('span', { class: 'tag ' + (r.status === 'done' ? '' : r.status === 'running' ? 'running' : 'error') }, r.status)),
        withDelete ? h('td', {}, h('button', { class: 'btn ghost danger', title: 'Delete', 'aria-label': 'Delete report', onclick: async (e) => {
          e.stopPropagation();
          const btn = e.currentTarget;
          if (btn.dataset.armed !== '1') { btn.dataset.armed = '1'; btn.title = 'Click again to delete'; btn.style.background = 'var(--error-soft)'; return; }
          await api(`/api/reports/${r.id}`, { method: 'DELETE' }); btn.closest('tr').remove(); toast('Report deleted');
        } }, icon('trash'))) : null);
    }))));
}

async function viewHistory() {
  const list = await api('/api/reports');
  const box = h('div');
  const draw = (q) => {
    const f = q ? list.filter((r) => [r.label, ...r.usernames, ...r.images].join(' ').toLowerCase().includes(q.toLowerCase())) : list;
    box.replaceChildren(f.length ? historyTable(f) : h('div', { class: 'empty' }, list.length ? 'No scans match.' : 'No scans yet. Start one from New scan.'));
  };
  put(
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'History'), h('p', {}, `${list.length} saved report${list.length === 1 ? '' : 's'}, stored on this computer in data/reports.`)),
      h('input', { type: 'search', placeholder: 'Search scans', style: 'max-width:260px', oninput: (e) => draw(e.target.value) })),
    h('div', { class: 'card' }, box));
  draw('');
}

// ---------- image tools ----------
function pickFile(onPick) {
  const input = h('input', { type: 'file', accept: 'image/*', class: 'hidden', onchange: () => { if (input.files[0]) onPick(input.files[0]); input.value = ''; } });
  return input;
}

function viewTools() {
  // Inspect + clean
  const out = h('div', { class: 'tool-result' });
  let current = null;
  const inspect = async (file) => {
    current = file;
    out.replaceChildren(h('p', { class: 'muted' }, h('span', { class: 'spin' }), ' Reading metadata…'));
    const fd = new FormData(); fd.append('image', file);
    try {
      const a = await api('/api/tools/inspect', { method: 'POST', body: fd });
      const url = URL.createObjectURL(file);
      const card = imageCard({ id: '' }, { ...a, index: 0, links: [], matches: [] }, url);
      const risky = (a.gps ? 1 : 0) + (a.camera ? 1 : 0) + Object.keys(a.exif).length;
      out.replaceChildren(card, h('div', { class: 'row', style: 'margin-top:12px' },
        h('button', { class: 'btn primary', onclick: clean }, icon('down'), 'Download a clean copy'),
        h('span', { class: 'muted small' }, risky ? `Removes ${Object.keys(a.exif).length} EXIF tags${a.gps ? ', including GPS' : ''}.` : 'This image has no EXIF to remove, but a clean copy still drops text chunks and comments.')));
    } catch (e) { out.replaceChildren(h('p', { class: 'muted' }, e.message)); }
  };
  const clean = async () => {
    const fd = new FormData(); fd.append('image', current);
    try {
      const res = await api('/api/tools/strip', { method: 'POST', body: fd });
      const blob = await res.blob();
      const name = (res.headers.get('content-disposition') || '').match(/filename="([^"]+)"/)?.[1] || 'clean.jpg';
      const a = h('a', { href: URL.createObjectURL(blob), download: name });
      document.body.append(a); a.click(); a.remove();
      toast('Clean copy downloaded');
    } catch (e) { toast(e.message, true); }
  };
  const inp1 = pickFile(inspect);
  const drop1 = h('div', { class: 'drop', tabindex: '0', role: 'button', onclick: () => inp1.click(),
    onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); inp1.click(); } },
    ondragover: (e) => { e.preventDefault(); drop1.classList.add('over'); }, ondragleave: () => drop1.classList.remove('over'),
    ondrop: (e) => { e.preventDefault(); drop1.classList.remove('over'); if (e.dataTransfer.files[0]) inspect(e.dataTransfer.files[0]); } },
    icon('image'), h('strong', {}, 'Drop a photo to see what it reveals'), h('div', { class: 'hint' }, 'Nothing is saved. The photo is read on this computer and discarded.'));

  // Compare
  const files = [null, null];
  const result = h('div', { class: 'tool-result' });
  const slot = (i) => {
    const label = h('div', { class: 'hint' }, 'No image');
    const img = h('img', { alt: '', style: 'width:100%;aspect-ratio:1;object-fit:cover;border-radius:10px;display:none' });
    const inp = pickFile((f) => { files[i] = f; label.textContent = f.name; img.src = URL.createObjectURL(f); img.style.display = 'block'; compare(); });
    return h('div', { class: 'drop', role: 'button', tabindex: '0', onclick: () => inp.click(),
      onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); inp.click(); } } },
      img, h('strong', {}, `Image ${i ? 'B' : 'A'}`), label, inp);
  };
  const compare = async () => {
    if (!files[0] || !files[1]) return;
    result.replaceChildren(h('span', { class: 'spin' }));
    const fd = new FormData(); fd.append('a', files[0]); fd.append('b', files[1]);
    try {
      const r = await api('/api/tools/compare', { method: 'POST', body: fd });
      const verdict = r.identical ? 'Same file, byte for byte.' : r.similarity >= 90 ? 'Almost certainly the same picture (resized, recompressed or lightly edited).'
        : r.similarity >= 80 ? 'Probably the same picture with edits or a crop.' : 'Different pictures.';
      result.replaceChildren(h('div', { class: 'row' }, h('div', { class: 'compare-score' }, `${r.similarity}%`),
        h('div', {}, h('b', {}, verdict), h('div', { class: 'muted small' }, `dHash distance ${r.distance} of 64 bits · ${r.a.dhash} vs ${r.b.dhash}`))));
    } catch (e) { result.replaceChildren(h('p', { class: 'muted' }, e.message)); }
  };

  put(
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Image tools'), h('p', {}, 'Check your own photos before you post them.'))),
    h('section', { class: 'card' }, h('h2', {}, 'Metadata inspector & cleaner'),
      h('p', { class: 'muted' }, 'See the camera, time and GPS location hidden in a photo, then download a copy with all of it removed.'),
      drop1, inp1, out),
    h('section', { class: 'card' }, h('h2', {}, 'Compare two images'),
      h('p', { class: 'muted' }, 'Perceptual hashing tells you if two files are the same picture, even after resizing or recompression.'),
      h('div', { class: 'grid-2' }, slot(0), slot(1)), result));
}

// ---------- platforms ----------
async function viewPlatforms() {
  const list = state.platforms;
  const healthCells = {};
  const runBtn = h('button', { class: 'btn', onclick: async () => {
    runBtn.disabled = true; runBtn.replaceChildren(h('span', { class: 'spin' }), 'Checking every rule…');
    Object.values(healthCells).forEach((c) => c.replaceChildren(h('span', { class: 'spin' })));
    try {
      const res = await api('/api/platforms/health', { method: 'POST' });
      const ok = res.filter((r) => r.health === 'ok').length;
      for (const r of res) {
        const cell = healthCells[r.platform];
        if (cell) cell.replaceChildren(h('span', { class: `health ${r.health}`, title: `@${r.known_user}: ${r.known_result}; random name: ${r.random_result}${r.detail ? ' · ' + r.detail : ''}` },
          { ok: 'Working', blocked: 'Blocked now', broken: 'Needs update' }[r.health]));
      }
      Object.entries(healthCells).forEach(([n, c]) => { if (!res.some((r) => r.platform === n)) c.replaceChildren(h('span', { class: 'muted small' }, 'n/a')); });
      toast(`${ok} of ${res.length} rules working`);
    } catch (e) { toast(e.message, true); }
    runBtn.disabled = false; runBtn.replaceChildren(icon('pulse'), 'Run health check');
  } }, icon('pulse'), 'Run health check');

  const groups = Object.entries(state.info.categories).map(([key, label]) => {
    const items = list.filter((p) => p.category === key);
    return h('section', { class: 'card' }, h('div', { class: 'row', style: 'margin-bottom:6px' }, h('h2', {}, label), h('span', { class: 'tag' }, items.length)),
      h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', {}, h('tr', {}, h('th', {}, 'Platform'), h('th', {}, 'Method'), h('th', {}, 'Notes'), h('th', {}, 'Health'))),
        h('tbody', {}, items.map((p) => h('tr', {},
          h('td', {}, ext(p.example, {}, p.name)),
          h('td', {}, h('span', { class: 'tag' + (p.kind === 'manual' ? ' manual' : '') }, p.method)),
          h('td', { class: 'muted small' }, p.notes),
          h('td', {}, (healthCells[p.name] = h('span', { class: 'muted small' }, p.kind === 'manual' ? 'n/a' : '–')))))))));
  });
  put(
    h('div', { class: 'page-head' }, h('div', {}, h('h1', {}, 'Platforms'),
      h('p', {}, `${list.length} sites. The health check looks up a known public account and a random name on each, so you can see when a site changes.`)), runBtn),
    ...groups);
}

// ---------- boot ----------
async function boot() {
  initTheme();
  try {
    [state.info, state.platforms] = await Promise.all([api('/api/info'), api('/api/platforms')]);
    document.getElementById('version').textContent = 'v' + state.info.version;
  } catch (e) {
    put(h('div', { class: 'card' }, h('h2', {}, 'Cannot reach the server'), h('p', { class: 'muted' }, e.message)));
    return;
  }
  window.addEventListener('hashchange', route);
  route();
}
boot();
