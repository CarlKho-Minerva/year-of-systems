/* Year of Systems — vanilla JS, no framework, no build step.
 *
 * WHY NO BUILD STEP: a build step is a thing that rots. This file is what runs; there is
 * no transpile, no lockfile, and nothing to re-install in a year when you want to change
 * a label. The whole app is three static files and one Python process.
 *
 * WHY A CACHED LAST-GOOD STATE: on a phone the request will sometimes fail — the zone is
 * asleep, the tunnel dropped, you are on a plane. Rendering a blank error screen in that
 * case is the "silence is the bug" failure in UI form, so we keep the last good state in
 * localStorage, render it, and say plainly at the top that it is stale.
 */
'use strict';

const CACHE_KEY = 'yos.state.v1';
const COURSE_KEY = 'yos.course.v1';
const VIEWS = ['now', 'course', 'year', 'library', 'settings'];
let S = null;              // current state
/* The tab lives in the URL hash so a tab is linkable, the phone's back gesture works, and
 * the home-screen icon can be pinned straight to a tab. A lesson is `#course/12`, which
 * means an individual lesson is bookmarkable and shareable-to-self. */
function parseHash() {
  const [v, id] = location.hash.slice(1).split('/');
  return {
    view: VIEWS.includes(v) ? v : 'now',
    lessonId: v === 'course' && /^\d+$/.test(id || '') ? Number(id) : null,
  };
}
let view = parseHash().view;
let editing = null;        // week number being edited, or null
let C = null;              // course tree (modules + lesson stubs), lazily loaded
let openLesson = null;     // full lesson object currently being read, or null

// ---------------------------------------------------------------- utils

const $ = (sel, root = document) => root.querySelector(sel);
const el = (tag, props = {}, kids = []) => {
  const n = Object.assign(document.createElement(tag), props);
  for (const k of [].concat(kids)) n.append(k?.nodeType ? k : document.createTextNode(k));
  return n;
};
const esc = (s) => String(s ?? '');
const cat = (key) => S.categories.find((c) => c.key === key) || { label: key, hue: 210 };
const sys = (wk) => S.systems.find((s) => s.week === wk);

function toast(msg, bad = false) {
  document.querySelectorAll('.toast').forEach((t) => t.remove());
  const t = el('div', { className: 'toast' + (bad ? ' bad' : ''), textContent: msg });
  document.body.append(t);
  setTimeout(() => t.remove(), bad ? 5200 : 2100);
}

function setOffline(on) { $('#offline').hidden = !on; }

// ---------------------------------------------------------------- transport

async function api(path, body) {
  const res = await fetch(path, body
    ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
    : { headers: { Accept: 'application/json' } });
  if (!res.ok) {
    let detail = res.status + ' ' + res.statusText;
    try { detail = (await res.json()).error || detail; } catch { /* keep status text */ }
    throw new Error(detail);
  }
  return res.json();
}

async function load() {
  try {
    S = await api('/api/state');
    localStorage.setItem(CACHE_KEY, JSON.stringify(S));
    setOffline(false);
  } catch (e) {
    const cached = localStorage.getItem(CACHE_KEY);
    if (!cached) throw e;               // nothing to fall back to: let the caller show it
    S = JSON.parse(cached);
    setOffline(true);
  }
  render();
}

/* Every mutation goes through here so that a failed write is impossible to miss: the
 * server's fresh state replaces ours on success, and on failure we say so and reload
 * rather than leaving optimistic UI that lies about what was saved. */
async function save(week, patch, okMsg) {
  try {
    S = await api('/api/system/' + week, patch);
    localStorage.setItem(CACHE_KEY, JSON.stringify(S));
    setOffline(false);
    if (okMsg) toast(okMsg);
    render();
  } catch (e) {
    toast('Not saved: ' + e.message, true);
    setOffline(true);
  }
}

// ---------------------------------------------------------------- views

function render() {
  document.querySelectorAll('.tab').forEach((t) =>
    t.setAttribute('aria-selected', String(t.dataset.view === view)));
  const root = $('#view');
  root.innerHTML = '';
  root.scrollTop = 0;
  ({ now: viewNow, course: viewCourse, year: viewYear,
     library: viewLibrary, settings: viewSettings }[view])(root);
  window.scrollTo(0, 0);
}

function systemCard(s, { hero = false } = {}) {
  const c = cat(s.category);
  const card = el('div', { className: 'card' + (hero ? ' hero' : '') });
  card.style.setProperty('--hue', c.hue);

  const top = el('div', { className: 'row' });
  top.style.marginTop = '0';
  top.append(el('span', { className: 'chip', textContent: c.label }));
  if (s.source === 'starter') {
    top.append(el('span', { className: 'chip warn', textContent: 'starter — replace' }));
  }
  if (s.status === 'installed') top.append(el('span', { className: 'chip plain', textContent: '✓ installed' }));
  if (s.status === 'dropped') top.append(el('span', { className: 'chip plain', textContent: 'dropped' }));
  if (s.review_due) top.append(el('span', { className: 'chip warn', textContent: 'still running?' }));
  card.append(top);

  card.append(el('p', { className: 'eyebrow', textContent: 'Week ' + s.week }));
  card.append(el('h1', { textContent: s.title || 'Not filled in yet' }));

  const bits = [];
  if (s.minutes) bits.push(s.minutes + ' min to set up');
  if (s.tool) bits.push(s.tool);
  if (s.installed_on) bits.push('installed ' + s.installed_on);
  if (bits.length) card.append(el('div', { className: 'meta' }, bits.map((b) => el('span', { textContent: b }))));

  if (s.why) card.append(el('p', { className: 'why', textContent: s.why }));

  if (s.steps.length) {
    const ul = el('ul', { className: 'steps' });
    s.steps.forEach((st, i) => {
      const box = el('input', { type: 'checkbox', checked: !!st.done });
      box.addEventListener('change', () => {
        const steps = s.steps.map((x, j) => ({ text: x.text, done: j === i ? box.checked : x.done }));
        save(s.week, { steps });
      });
      ul.append(el('li', {}, [el('label', {}, [box, el('span', { textContent: st.text })])]));
    });
    card.append(ul);
  }

  const row = el('div', { className: 'row' });
  if (s.status !== 'installed') {
    row.append(btn('Mark installed', 'primary', () =>
      save(s.week, { status: 'installed' }, 'Installed — week ' + s.week)));
  } else {
    row.append(btn('Still running', '', () => save(s.week, { reviewed: true }, 'Confirmed')));
    row.append(btn('Dropped it', 'ghost danger', () =>
      save(s.week, { status: 'dropped' }, 'Marked dropped — that is useful data')));
  }
  if (s.status === 'dropped') {
    row.append(btn('Restart it', '', () => save(s.week, { status: 'planned' }, 'Back to planned')));
  }
  row.append(btn('Edit', 'ghost', () => { editing = s.week; view = 'library'; render(); }));
  card.append(row);
  return card;
}

function btn(label, cls, onClick) {
  const b = el('button', { className: 'btn ' + cls, type: 'button', textContent: label });
  b.addEventListener('click', onClick);
  return b;
}

function viewNow(root) {
  const s = sys(S.current_week);
  root.append(el('p', { className: 'eyebrow', textContent: 'Week ' + S.current_week + ' of 52 · ' + S.week_of }));
  root.append(el('h1', { textContent: 'This week' }));
  root.append(el('p', { className: 'sub', textContent: 'One system. Set it up once; it runs for years.' }));

  const st = S.stats;
  const stats = el('div', { className: 'stats' });
  [['installed', st.installed + '', 'installed'],
   ['left', (52 - S.current_week) + '', 'weeks left'],
   ['setup', st.minutes_saved_setup + 'm', 'setup spent']]
    .forEach(([, v, l]) => stats.append(el('div', { className: 'stat' }, [el('b', { textContent: v }), el('small', { textContent: l })])));
  root.append(stats);

  if (s) root.append(systemCard(s, { hero: true }));

  const due = S.systems.filter((x) => x.review_due);
  if (due.length) {
    root.append(el('h2', { textContent: 'Still running? (' + due.length + ')' }));
    root.append(el('p', { className: 'sub', textContent: 'Installed over ' + S.settings.review_after_days + ' days ago and not confirmed since. Dropping one is a fine answer — a list that quietly holds dead systems is worse than a short list.' }));
    due.forEach((x) => {
      const c = cat(x.category);
      const wrap = el('div', { className: 'card' });
      wrap.style.setProperty('--hue', c.hue);
      wrap.append(el('strong', { textContent: 'Week ' + x.week + ' — ' + (x.title || 'untitled') }));
      const r = el('div', { className: 'row' });
      r.append(btn('Still running', 'primary', () => save(x.week, { reviewed: true }, 'Confirmed')));
      r.append(btn('Dropped', 'ghost danger', () => save(x.week, { status: 'dropped' }, 'Marked dropped')));
      wrap.append(r);
      root.append(wrap);
    });
  }
}

// ---------------------------------------------------------------- course reader

/* The course tree is fetched lazily and cached, because it is the one view that is
 * useless without a network round-trip on first use but perfectly readable from cache
 * afterwards — which is the whole point of reading lessons on a train. */
async function loadCourse(force) {
  if (C && !force) return C;
  try {
    C = await api('/api/course');
    localStorage.setItem(COURSE_KEY, JSON.stringify(C));
    setOffline(false);
  } catch (e) {
    const cached = localStorage.getItem(COURSE_KEY);
    if (!cached) throw e;
    C = JSON.parse(cached);
    setOffline(true);
  }
  return C;
}

function viewCourse(root) {
  if (openLesson) return viewLesson(root, openLesson);

  root.append(el('h1', { textContent: 'Course' }));
  const sub = el('p', { className: 'sub', textContent: 'Loading…' });
  root.append(sub);
  const holder = el('div');
  root.append(holder);

  loadCourse().then((c) => {
    if (!c.modules.length) {
      sub.textContent = 'Nothing imported yet.';
      holder.append(el('p', { className: 'empty', textContent:
        'The lessons live in this app’s database, never in the git repo. '
        + 'Once they are imported they read offline, and each one gets its own notes field.' }));
      return;
    }
    sub.textContent = c.stats.lessons + ' lessons in ' + c.stats.modules + ' modules · '
      + c.stats.with_notes + ' annotated';
    c.modules.forEach((m) => {
      holder.append(el('h2', { textContent: m.title }));
      m.lessons.forEach((l) => {
        const b = el('button', { className: 'list-item', type: 'button' });
        b.style.setProperty('--hue', 210);
        b.append(el('span', { className: 'wk', textContent: l.week ? 'W' + l.week : '·' }));
        b.append(el('span', { className: 'ttl', textContent: l.title }));
        const marks = [];
        if (l.has_video) marks.push('▶');
        if (l.assets) marks.push('⎘' + l.assets);
        if (l.has_notes) marks.push('✎');
        if (marks.length) b.append(el('span', { className: 'marks', textContent: marks.join(' ') }));
        b.addEventListener('click', () => openLessonById(l.id));
        holder.append(b);
      });
    });
  }).catch((e) => {
    sub.textContent = '';
    holder.append(el('p', { className: 'empty', textContent: 'Could not load the course: ' + e.message }));
  });
}

async function openLessonById(id) {
  try {
    openLesson = await api('/api/lesson/' + id);
    if (location.hash !== '#course/' + id) location.hash = 'course/' + id;
    render();
  } catch (e) {
    toast('Could not open lesson: ' + e.message, true);
  }
}

function viewLesson(root, l) {
  root.append(btn('‹ ' + (l.module_title || 'Course'), 'ghost', () => { openLesson = null; render(); }));
  root.append(el('h1', { textContent: l.title }));

  const meta = el('div', { className: 'row' });
  if (l.video_url) meta.append(extLink('▶ Watch', l.video_url));
  (l.assets || []).forEach((a) => meta.append(extLink('⎘ ' + (a.name || 'asset'), a.url)));
  if (l.source_url) meta.append(extLink('Open original', l.source_url));
  if (meta.children.length) root.append(meta);

  if (l.body) {
    const card = el('div', { className: 'card' });
    card.append(renderBody(l.body));
    root.append(card);
  } else {
    root.append(el('p', { className: 'empty', textContent: 'No text captured for this lesson — use "Open original".' }));
  }

  const nc = el('div', { className: 'card' });
  const ta = field(nc, 'Your notes', el('textarea', { value: l.notes || '' }));
  ta.style.minHeight = '160px';

  const wk = el('select');
  wk.append(el('option', { value: '', textContent: '— not linked —', selected: !l.week }));
  for (let i = 1; i <= 52; i++) {
    wk.append(el('option', { value: String(i), textContent: 'Week ' + i, selected: l.week === i }));
  }
  field(nc, 'Link to a week in the tracker', wk);

  const row = el('div', { className: 'row' });
  row.append(btn('Save notes', 'primary', async () => {
    try {
      openLesson = await api('/api/lesson/' + l.id, { notes: ta.value, week: wk.value || null });
      C = null;                       // stub counts (✎, week badge) are now stale
      toast('Saved');
      render();
    } catch (e) { toast('Not saved: ' + e.message, true); }
  }));
  nc.append(row);
  root.append(nc);

  const nav = el('div', { className: 'row' });
  if (l.prev_id) nav.append(btn('‹ Previous', '', () => openLessonById(l.prev_id)));
  if (l.next_id) nav.append(btn('Next ›', '', () => openLessonById(l.next_id)));
  if (nav.children.length) root.append(nav);
}

/* The lesson body arrives as plain text with a consistent shape: a few section labels
 * ("The System:", "The Outcome", "Setup"), numbered steps, and prose. Promoting those to
 * headings is the difference between a wall of text and something readable on a phone.
 *
 * Every line becomes a TEXT node — never innerHTML. The body is scraped from a page this
 * app does not control, so treating it as markup would run whatever that page carries.
 */
const SECTION = /^(the system:?|the outcome:?|setup:?|why it works:?|the payoff:?|notes?:?|tools?:?|examples?:?)$/i;
const STEP = /^step\s*\d+\s*[:.\-—]/i;

function renderBody(text) {
  const wrap = el('div', { className: 'body' });
  for (const raw of String(text).split('\n')) {
    const line = raw.trim();
    if (!line) { wrap.append(el('div', { className: 'gap' })); continue; }
    if (SECTION.test(line)) { wrap.append(el('h3', { className: 'sec', textContent: line.replace(/:$/, '') })); continue; }
    if (STEP.test(line)) { wrap.append(el('h4', { className: 'step', textContent: line })); continue; }
    wrap.append(el('p', { textContent: line }));
  }
  return wrap;
}

function extLink(label, href) {
  // noopener/noreferrer: these point at pages this app does not control.
  const a = el('a', { href, className: 'btn', textContent: label, target: '_blank', rel: 'noopener noreferrer' });
  a.style.cssText = 'display:inline-flex;align-items:center;text-decoration:none';
  return a;
}

function viewYear(root) {
  root.append(el('h1', { textContent: 'The year' }));
  root.append(el('p', { className: 'sub', textContent: S.stats.installed + ' installed · ' + S.stats.filled + ' of 52 planned out · ' + S.stats.dropped + ' dropped' }));

  const grid = el('div', { className: 'grid' });
  S.systems.forEach((s) => {
    const c = cat(s.category);
    const b = el('button', {
      className: 'cell'
        + (s.filled ? ' filled' : '')
        + (s.status === 'installed' ? ' installed' : '')
        + (s.status === 'dropped' ? ' dropped' : '')
        + (s.week === S.current_week ? ' current' : ''),
      type: 'button',
      textContent: s.week,
      title: 'Week ' + s.week + ' — ' + (s.title || 'empty') + ' (' + c.label + ')',
    });
    b.style.setProperty('--hue', c.hue);
    b.addEventListener('click', () => { editing = s.week; view = 'library'; render(); });
    grid.append(b);
  });
  root.append(grid);

  const lg = el('div', { className: 'legend' });
  S.categories.forEach((c) => {
    const s = el('span');
    s.style.setProperty('--hue', c.hue);
    s.append(el('i'), c.label);
    lg.append(s);
  });
  root.append(lg);
}

function viewLibrary(root) {
  if (editing != null) return viewEdit(root, sys(editing));

  root.append(el('h1', { textContent: 'Library' }));
  root.append(el('p', { className: 'sub', textContent: 'Everything you have installed, by category. This is the payoff — the thing worth re-reading.' }));

  const q = el('input', { type: 'text', placeholder: 'Search…' });
  q.addEventListener('input', () => paint(q.value.toLowerCase().trim()));
  root.append(q);
  const holder = el('div');
  root.append(holder);

  function paint(term) {
    holder.innerHTML = '';
    let shown = 0;
    S.categories.forEach((c) => {
      const items = S.systems.filter((s) =>
        s.category === c.key && (s.filled || s.status !== 'planned')
        && (!term || (s.title + ' ' + s.why + ' ' + s.tool + ' ' + s.notes).toLowerCase().includes(term)));
      if (!items.length) return;
      shown += items.length;
      holder.append(el('h2', { textContent: c.label }));
      items.forEach((s) => {
        const b = el('button', { className: 'list-item', type: 'button' });
        b.style.setProperty('--hue', c.hue);
        b.append(el('span', { className: 'wk', textContent: 'W' + s.week }));
        const ttl = el('span', { className: 'ttl', textContent: s.title || '(empty)' });
        if (s.status === 'dropped') ttl.classList.add('struck');
        b.append(ttl);
        b.append(el('span', { className: 'dot ' + s.status, title: s.status }));
        b.addEventListener('click', () => { editing = s.week; render(); });
        holder.append(b);
      });
    });
    if (!shown) holder.append(el('p', { className: 'empty', textContent: term ? 'Nothing matches.' : 'Nothing filled in yet. Open a week from the Year tab and write it down.' }));
  }
  paint('');
}

function viewEdit(root, s) {
  const c = cat(s.category);
  root.append(btn('‹ Back', 'ghost', () => { editing = null; render(); }));
  root.append(el('p', { className: 'eyebrow', textContent: 'Week ' + s.week }));
  root.append(el('h1', { textContent: s.title || 'New system' }));

  const f = el('div', { className: 'card' });
  f.style.setProperty('--hue', c.hue);

  const title = field(f, 'What is the system?', el('input', { type: 'text', value: s.title }));
  const sel = el('select');
  S.categories.forEach((x) => sel.append(el('option', { value: x.key, textContent: x.label, selected: x.key === s.category })));
  field(f, 'Category', sel);
  const tool = field(f, 'Tool', el('input', { type: 'text', value: s.tool, placeholder: 'App, object, or "none"' }));
  const mins = field(f, 'Minutes to set up', el('input', { type: 'number', value: s.minutes || '', min: '0' }));
  const why = field(f, 'Why it works', el('textarea', { value: s.why }));
  const steps = field(f, 'Setup steps (one per line)', el('textarea', { value: s.steps.map((x) => x.text).join('\n') }));
  const notes = field(f, 'Your notes', el('textarea', { value: s.notes, placeholder: 'What actually happened when you ran it.' }));

  const row = el('div', { className: 'row' });
  row.append(btn('Save', 'primary', () => {
    const lines = steps.value.split('\n').map((x) => x.trim()).filter(Boolean);
    const prev = new Map(s.steps.map((x) => [x.text, x.done]));
    save(s.week, {
      title: title.value, category: sel.value, tool: tool.value,
      minutes: parseInt(mins.value || '0', 10) || 0,
      why: why.value, notes: notes.value,
      // Preserve tick state across an edit, matched by text. Retyping a step you had
      // already done should not silently un-do it.
      steps: lines.map((t) => ({ text: t, done: !!prev.get(t) })),
      source: s.source === 'starter' && title.value !== s.title ? 'mine' : s.source,
    }, 'Saved');
    editing = null;
  }));
  row.append(btn('Cancel', 'ghost', () => { editing = null; render(); }));
  f.append(row);
  root.append(f);
}

function field(parent, label, input) {
  const l = el('label', { className: 'field' });
  l.append(el('span', { textContent: label }), input);
  parent.append(l);
  return input;
}

function viewSettings(root) {
  root.append(el('h1', { textContent: 'Settings' }));

  const card = el('div', { className: 'card' });
  const sd = field(card, 'Start date (week 1 snaps to that Monday)', el('input', { type: 'date', value: S.settings.start_date }));
  const r = el('div', { className: 'row' });
  r.append(btn('Save start date', 'primary', async () => {
    try {
      S = await api('/api/settings', { start_date: sd.value });
      localStorage.setItem(CACHE_KEY, JSON.stringify(S));
      toast('Week 1 = ' + S.settings.start_date);
      render();
    } catch (e) { toast('Not saved: ' + e.message, true); }
  }));
  card.append(r);
  root.append(card);

  root.append(el('h2', { textContent: 'Export' }));
  root.append(el('p', { className: 'sub', textContent: 'Nothing here is trapped. Markdown drops straight into the vault.' }));
  const ex = el('div', { className: 'row' });
  ex.style.marginTop = '0';
  ex.append(link('Systems', '/api/export.md'),
            link('Course notes', '/api/export-notes.md'),
            link('JSON', '/api/export.json'));
  root.append(ex);
  root.append(el('p', { className: 'sub', textContent:
    'Course notes export your writing only. Lesson text stays in this database — it is not '
    + 'yours to redistribute, and the repo is public.' }));

  root.append(el('h2', { textContent: 'About' }));
  root.append(el('p', { className: 'sub' , textContent:
    'Local-only: no API keys, no CDN, no analytics, no outbound requests. Data lives in SQLite next to the app. '
    + 'Weeks 1–7 ship as generic starter examples so nothing is blank — replace each with the real system as you reach it.' }));
  root.append(el('p', { className: 'sub', textContent: 'Today ' + S.today + ' · week ' + S.current_week + ' · review after ' + S.settings.review_after_days + ' days' }));
}

function link(label, href) {
  const a = el('a', { href, className: 'btn', textContent: label });
  a.style.cssText = 'display:inline-flex;align-items:center;text-decoration:none';
  a.setAttribute('download', '');
  return a;
}

// ---------------------------------------------------------------- boot

function go(next) {
  view = next;
  editing = null;
  openLesson = null;
  if (location.hash.slice(1) !== next) location.hash = next;
  render();
}

document.querySelectorAll('.tab').forEach((t) =>
  t.addEventListener('click', () => go(t.dataset.view)));

window.addEventListener('hashchange', () => {
  const h = parseHash();
  if (h.lessonId && h.lessonId !== (openLesson && openLesson.id)) {
    view = 'course';
    return void openLessonById(h.lessonId);
  }
  if (!h.lessonId && openLesson) { openLesson = null; view = h.view; return render(); }
  if (h.view !== view) { view = h.view; editing = null; openLesson = null; render(); }
});

// A deep link to a lesson must survive a cold start, so resolve it once after boot.
const _boot = parseHash();
if (_boot.lessonId) openLessonById(_boot.lessonId);

load().catch((e) => {
  $('#view').innerHTML = '';
  $('#view').append(
    el('h1', { textContent: 'Cannot reach the app' }),
    el('p', { className: 'sub', textContent: String(e.message) }),
    btn('Retry', 'primary', () => load().catch(() => location.reload())));
});

// Refresh when the phone brings the app back to the foreground — day boundaries and the
// review queue both move while it is backgrounded.
// Never refresh while a text field is open — a background reload that re-renders the
// view would throw away notes typed but not yet saved.
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && editing == null && openLesson == null) {
    load().catch(() => setOffline(true));
  }
});

if ('serviceWorker' in navigator) {
  // Registration only succeeds in a secure context (https, or localhost). Over plain
  // http on a LAN address it throws — that is expected, and it must not take the app
  // down with it, so the failure is logged and swallowed here only.
  navigator.serviceWorker.register('/sw.js').catch((e) => console.warn('SW not registered:', e.message));
}
