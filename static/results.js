/* Seating editor: renders the plan from the server's JSON and edits it via /api/*. */
(() => {
  'use strict';

  // ── tiny DOM helpers (all text goes through textContent: names are never HTML) ──
  const h = (tag, attrs = {}, ...kids) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  };
  const SVG = 'http://www.w3.org/2000/svg';
  const s = (tag, attrs = {}) => {
    const el = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  };

  const LS_KEY = 'tableplanner:plan';
  const S = { st: null, sel: null, opts: null, armed: null, confirm: null };
  const app = document.getElementById('app');

  // ── persistent chrome: action sheet, toast, busy overlay, modal ──
  const sheet = h('div', { class: 'sheet', role: 'dialog', 'aria-live': 'polite' });
  const toastEl = h('div', { class: 'toast', role: 'status' });
  const busyEl = h('div', { class: 'busy' }, h('div', { class: 'spinner' }), h('p', { class: 'text-muted' }));
  const modalBg = h('div', { class: 'modal-backdrop' });
  document.body.append(sheet, toastEl, busyEl, modalBg);
  modalBg.addEventListener('click', e => { if (e.target === modalBg) closeModal(); });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    if (modalBg.classList.contains('open')) closeModal(); else clearSel();
  });

  // ── server ──
  const loadLocal = () => {
    try { return JSON.parse(localStorage.getItem(LS_KEY) || 'null'); } catch (e) { return null; }
  };
  const persist = () => {
    try {
      const at = new Date().toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
      localStorage.setItem(LS_KEY, JSON.stringify({ plan: S.st.plan, at }));
    } catch (e) { /* private mode etc. */ }
  };

  async function api(path, body, retry = true) {
    let init = {};
    if (body instanceof FormData) init = { method: 'POST', body };
    else if (body !== undefined) init = { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
    let r;
    try { r = await fetch(path, init); } catch (e) { throw new Error('Can’t reach the server. Check your connection and try again.'); }
    let j = null;
    try { j = await r.json(); } catch (e) { /* not JSON */ }
    if (r.status === 409 && retry) {
      // The server forgot this session (e.g. it restarted). Restore from this device and retry once.
      const saved = loadLocal();
      if (saved && saved.plan) {
        const r2 = await fetch('/api/load_plan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(saved.plan) });
        if (r2.ok) return api(path, body, false);
      }
    }
    if (!r.ok || !j || j.error) throw new Error((j && j.error) || 'Something went wrong. Please try again.');
    return j;
  }

  function setState(j) {
    S.st = j;
    persist();
    if (S.sel && !seatOf(S.sel.meal, S.sel.name)) S.sel = null;
    render();
    if (S.sel) loadOptions();
  }

  async function mutate(path, body, msg, busyMsg) {
    const prev = S.st && S.st.plan;
    S.opts = null; S.armed = null;
    if (busyMsg) busy(busyMsg);
    try {
      const j = await api(path, body);
      setState(j);
      if (msg) toast(msg, prev ? () => restore(prev) : null);
      return j;
    } catch (e) {
      toast(e.message, null, true);
      render();
    } finally {
      if (busyMsg) busy(false);
    }
  }

  async function restore(prevPlan) {
    try { S.sel = null; setState(await api('/api/load_plan', prevPlan)); toast('Undone'); }
    catch (e) { toast(e.message, null, true); }
  }

  // ── plan lookups ──
  const plan = () => S.st.plan;
  const sexOf = name => (plan().people.find(p => p.name === name) || {}).sex;
  const tablesOf = meal => plan().seating[meal] || [];
  const isLocked = (meal, name) => ((plan().locks || {})[meal] || []).includes(name);
  function seatOf(meal, name) {
    const ts = tablesOf(meal);
    for (let t = 0; t < ts.length; t++) { const i = ts[t].indexOf(name); if (i >= 0) return [t, i]; }
    return null;
  }
  const realIssues = list => list.filter(i => i.level !== 'low');
  function uniqueProblems() {
    const seen = new Set();
    for (const m of plan().meals) for (const i of realIssues(S.st.issues[m] || [])) seen.add(i.kind + '|' + i.names.join('|'));
    return seen.size;
  }

  // ── selection & swapping ──
  async function loadOptions() {
    const { meal, name } = S.sel;
    if (isLocked(meal, name)) { S.opts = null; renderSheet(); return; }
    try {
      const j = await api('/api/options', { meal, name });
      if (S.sel && S.sel.meal === meal && S.sel.name === name) { S.opts = j.options; render(); }
    } catch (e) { toast(e.message, null, true); }
  }

  function tap(meal, name) {
    if (S.sel && S.sel.meal === meal && S.sel.name === name) return clearSel();
    if (S.sel && S.sel.meal === meal && S.opts && S.opts[name]) return trySwap(name);
    S.sel = { meal, name }; S.opts = null; S.armed = null; S.confirm = null;
    render();
    loadOptions();
  }

  function clearSel() { S.sel = null; S.opts = null; S.armed = null; S.confirm = null; render(); }

  function trySwap(other) {
    const o = S.opts[other];
    const { meal, name } = S.sel;
    if (o.verdict === 'locked') { toast(o.reason); return; }
    if (o.verdict === 'bad' && S.armed !== other) { S.armed = other; renderSheet(); return; }
    S.sel = null;
    mutate('/api/swap', { meal, a: name, b: other }, `Swapped ${name} and ${other}`);
  }

  // ── rendering ──
  function render() {
    if (!S.st) return;
    const p = plan();
    const tableCount = p.meals.reduce((n, m) => n + tablesOf(m).length, 0);
    const problems = uniqueProblems();
    app.replaceChildren(
      h('div', { class: 'results-top' },
        h('div', {},
          h('h1', { text: p.event }),
          h('p', { class: 'subtitle', text: `${p.people.length} guests · ${p.meals.length} meals · ${tableCount} tables` })),
        h('span', { class: 'status ' + (problems ? 'status-bad' : 'status-ok'),
          text: problems ? `${problems} clash${problems > 1 ? 'es' : ''} to sort` : '✓ No repeat neighbours or clashes' })),
      toolbar(),
      h('div', { class: 'hint' },
        'Tap a guest to move them: other seats turn ', h('strong', { text: 'green' }), ' (safe swap), ',
        h('strong', { text: 'amber' }), ' (minor) or ', h('strong', { text: 'red' }),
        ' (would repeat neighbours). 🔒 Lock seats you want to keep, then Regenerate to re-seat everyone else.'),
      ...p.meals.map(mealSection),
      neighbours());
    renderSheet();
  }

  function twoTap(id, label, confirmLabel, action, cls = 'btn btn-secondary') {
    const armed = S.confirm === id;
    return h('button', {
      class: cls + (armed ? ' btn-danger' : ''), type: 'button', text: armed ? confirmLabel : label,
      onclick: () => {
        if (armed) { S.confirm = null; action(); return; }
        S.confirm = id; render();
        setTimeout(() => { if (S.confirm === id) { S.confirm = null; render(); } }, 4000);
      },
    });
  }

  function toolbar() {
    const dl = (kind, title, sub) => h('a', { href: '/download/' + kind }, title, h('small', { text: sub }));
    return h('div', { class: 'action-bar' },
      twoTap('regen-all', '↻ Regenerate all', 'Tap again: re-seat every meal',
        () => mutate('/api/regenerate', {}, 'Re-seated every meal', 'Re-seating every meal… locked seats stay put')),
      h('button', { class: 'btn btn-secondary', type: 'button', text: '＋ Add guest', onclick: openAddGuest }),
      h('button', { class: 'btn btn-secondary', type: 'button', text: '⇆ Keep apart & past events', onclick: openKeepApart }),
      h('a', { class: 'btn btn-secondary', href: '/download/plan', text: '💾 Save plan',
        title: 'Download a file you can reopen later, or use as a past event next time' }),
      h('details', { class: 'menu' },
        h('summary', { class: 'btn btn-secondary', text: '🖨 Print ▾' }),
        h('div', { class: 'menu-list' },
          dl('diagrams', 'Table diagrams', 'One table per page'),
          dl('diagrams4', 'Table diagrams, 4 per page', 'Saves paper'),
          dl('lists', 'Table lists', 'Seat-by-seat names'),
          dl('who', 'Who sits where', 'A–Z guest list with table and seat'),
          dl('cards', 'Place cards', 'Fold-over cards, 4 per sheet'),
          dl('csv', 'Spreadsheet (CSV)', 'For Excel or Google Sheets'))),
      h('a', { class: 'btn btn-ghost', href: '/configure_tables', text: 'Tables' }),
      h('a', { class: 'btn btn-ghost', href: '/attendees', text: 'Guests' }));
  }

  function mealSection(meal) {
    const tables = tablesOf(meal);
    const issues = S.st.issues[meal] || [];
    const real = realIssues(issues);
    const flagged = new Set(real.flatMap(i => i.names));
    const guests = tables.reduce((n, t) => n + t.length, 0);
    const status = real.length
      ? h('span', { class: 'status status-bad', text: `${real.length} clash${real.length > 1 ? 'es' : ''}` })
      : h('span', { class: 'status status-ok', text: '✓ No clashes' });
    return h('section', { class: 'meal-section' },
      h('div', { class: 'meal-header' },
        h('div', {}, h('h2', { text: meal }),
          h('div', { class: 'meal-meta' }, `${guests} guests · ${tables.length} table${tables.length === 1 ? '' : 's'}`, status)),
        h('div', { class: 'meal-actions' },
          h('button', { class: 'btn btn-sm btn-secondary', type: 'button', text: '↻ Regenerate',
            title: 'Re-seat this meal. Locked seats stay put.',
            onclick: () => mutate('/api/regenerate', { meal }, `Re-seated ${meal}`, `Re-seating ${meal}…`) }))),
      issues.length ? h('ul', { class: 'issues' },
        issues.map(i => h('li', { class: 'lv-' + i.level, text: (tables.length > 1 ? `Table ${i.table + 1}: ` : '') + i.text }))) : null,
      tables.length ? h('div', { class: 'tables-grid' }, tables.map((t, ti) => tableCard(meal, ti, t, flagged)))
        : h('p', { class: 'text-muted', text: 'Nobody is coming to this meal.' }));
  }

  function seatState(meal, name) {
    const cls = [];
    if (S.sel && S.sel.meal === meal) {
      if (S.sel.name === name) cls.push('sel');
      else if (S.opts && S.opts[name]) cls.push('v-' + S.opts[name].verdict);
    }
    return cls;
  }

  const TAGS = { good: '✓ safe', better: '✓ fixes clash', warn: '! minor', bad: '✗ clash', locked: '🔒' };

  function tableCard(meal, ti, table, flagged) {
    const list = h('div', { class: 'seat-list' }, table.map((name, si) => {
      const st = seatState(meal, name);
      const o = S.opts && S.sel && S.sel.meal === meal ? S.opts[name] : null;
      const row = h('div', {
        class: ['seat-row', ...st, flagged.has(name) ? 'has-issue' : ''].join(' '),
        role: 'button', tabindex: '0', title: o ? o.reason : null,
        onclick: () => tap(meal, name),
        onkeydown: e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); tap(meal, name); } },
      },
        h('span', { class: 'seat-num', text: si + 1 }),
        h('span', { class: 'seat-name', text: name }),
        isLocked(meal, name) ? h('span', { class: 'lock', text: '🔒', title: 'Seat locked' }) : null,
        o ? h('span', { class: 'tag', text: TAGS[o.verdict] }) : null,
        h('span', { class: 'badge badge-' + sexOf(name), text: (sexOf(name) || '?')[0].toUpperCase() }));
      return row;
    }));
    return h('div', { class: 'table-card' },
      h('div', { class: 'table-card-header' }, h('h3', { text: `Table ${ti + 1} · ${table.length}` })),
      h('div', { class: 'table-body' }, h('div', { class: 'diagram-wrap' }, circle(meal, table, flagged)), list));
  }

  function circle(meal, table, flagged) {
    const n = table.length, size = 260, c = size / 2;
    const sr = Math.max(12, Math.min(22, 230 / Math.max(n, 1)));
    const r = c - sr - 14;
    const svg = s('svg', { class: 'table-svg', viewBox: `0 0 ${size} ${size}`, role: 'img', 'aria-label': `Table with ${n} guests` });
    svg.append(s('circle', { cx: c, cy: c, r: r * 0.55, fill: '#f2ede4', stroke: '#d8d0c4', 'stroke-width': 1.5 }));
    table.forEach((name, i) => {
      const a = -Math.PI / 2 + 2 * Math.PI * i / n;
      const x = c + r * Math.cos(a), y = c + r * Math.sin(a);
      const male = sexOf(name) === 'male';
      const g = s('g', { class: ['seat', ...seatState(meal, name), flagged.has(name) ? 'has-issue' : ''].join(' ') });
      g.addEventListener('click', () => tap(meal, name));
      const title = s('title'); title.textContent = `${i + 1}. ${name}`;
      g.append(title,
        s('circle', { cx: x, cy: y, r: sr, fill: male ? '#dde8f5' : '#f5ddeb', stroke: male ? '#5a7ab8' : '#b85a7a' }));
      const label = s('text', { x, y: y + sr * 0.22, 'text-anchor': 'middle', 'font-size': Math.max(7, sr * 0.55).toFixed(1), 'font-weight': 700, fill: '#1a1410' });
      label.textContent = name.length > 9 ? name.slice(0, 8) + '…' : name;
      const num = s('text', { x: c + (r + sr + 7) * Math.cos(a), y: c + (r + sr + 7) * Math.sin(a) + 3, 'text-anchor': 'middle', 'font-size': 8, fill: '#7a6f65' });
      num.textContent = i + 1;
      g.append(label, num);
      if (isLocked(meal, name)) {
        const lock = s('text', { x: x + sr * 0.75, y: y - sr * 0.55, 'font-size': 10 });
        lock.textContent = '🔒';
        g.append(lock);
      }
      svg.append(g);
    });
    return svg;
  }

  function neighbours() {
    const p = plan();
    const next = {};
    for (const meal of p.meals) for (const t of tablesOf(meal)) {
      const n = t.length;
      t.forEach((name, i) => {
        const ns = n === 2 ? [t[1 - i]] : n > 2 ? [t[(i + n - 1) % n], t[(i + 1) % n]] : [];
        ((next[name] = next[name] || {})[meal] = ns);
      });
    }
    const rows = Object.keys(next).sort((a, b) => a.localeCompare(b)).map(name => {
      const counts = {};
      Object.values(next[name]).flat().forEach(x => counts[x] = (counts[x] || 0) + 1);
      return h('tr', {}, h('td', {}, h('strong', { text: name })),
        p.meals.map(m => h('td', {}, (next[name][m] || []).map((x, k) => [k ? ', ' : '',
          h('span', { class: counts[x] > 1 ? 'rep' : '', style: counts[x] > 1 ? 'color:var(--rust);font-weight:700' : null, text: x })]))));
    });
    return h('details', { class: 'card mt3' },
      h('summary', { style: 'cursor:pointer;font-weight:700' }, 'Who sits next to whom ',
        h('span', { class: 'text-muted', text: '(repeats in red)' })),
      h('div', { style: 'overflow-x:auto;margin-top:1rem' },
        h('table', { class: 'attendee-table neighbours' },
          h('thead', {}, h('tr', {}, h('th', { text: 'Guest' }), p.meals.map(m => h('th', { text: m })))),
          h('tbody', {}, rows))));
  }

  // ── action sheet ──
  function renderSheet() {
    document.body.classList.toggle('sheet-open', !!S.sel);
    if (!S.sel || !S.st) { sheet.classList.remove('open'); return; }
    const { meal, name } = S.sel;
    const pos = seatOf(meal, name);
    if (!pos) { sheet.classList.remove('open'); return; }
    const locked = isLocked(meal, name);
    let msg, bad = false;
    if (locked) msg = '🔒 Seat locked: stays put when you regenerate. Unlock to move them.';
    else if (!S.opts) msg = 'Checking which swaps are safe…';
    else if (S.armed) {
      bad = true;
      msg = `Swapping with ${S.armed}: ${S.opts[S.armed].reason}. Tap ${S.armed} again to swap anyway.`;
    } else {
      const safe = Object.values(S.opts).filter(o => o.verdict === 'good' || o.verdict === 'better').length;
      msg = `Tap another guest at ${meal} to swap seats (any table). ${safe} safe swap${safe === 1 ? '' : 's'}.`;
    }
    sheet.replaceChildren(h('div', { class: 'sheet-inner' },
      h('div', { class: 'flex-between' },
        h('div', {}, h('div', { class: 'sheet-title', text: name }),
          h('div', { class: 'sheet-sub', text: `${meal} · Table ${pos[0] + 1}, seat ${pos[1] + 1}` })),
        h('button', { class: 'btn btn-sm btn-ghost', type: 'button', text: 'Done', onclick: clearSel })),
      h('div', { class: 'sheet-msg' + (bad ? ' bad' : ''), text: msg }),
      !locked && S.opts ? h('div', { class: 'legend-inline' },
        h('span', { class: 'lg-good', text: 'safe' }), h('span', { class: 'lg-warn', text: 'minor' }),
        h('span', { class: 'lg-bad', text: 'clash' })) : null,
      h('div', { class: 'sheet-actions' },
        h('button', { class: 'btn btn-sm btn-primary', type: 'button', text: locked ? '🔓 Unlock seat' : '🔒 Lock seat',
          onclick: () => mutate('/api/lock', { meal, name, locked: !locked }, locked ? `Unlocked ${name}` : `Locked ${name} in place`) }),
        h('button', { class: 'btn btn-sm btn-secondary', type: 'button', text: '✎ Rename', onclick: () => openRename(name) }),
        twoTap('rm-meal', 'Not at this meal', `Remove from ${meal}?`,
          () => { S.sel = null; mutate('/api/remove_guest', { name, meal }, `Removed ${name} from ${meal}`); }, 'btn btn-sm btn-secondary'),
        twoTap('rm-all', 'Remove guest', 'Remove from every meal?',
          () => { S.sel = null; mutate('/api/remove_guest', { name }, `Removed ${name}`); }, 'btn btn-sm btn-ghost'))));
    sheet.classList.add('open');
  }

  // ── toast & busy ──
  let toastTimer;
  function toast(text, undo, error) {
    toastEl.replaceChildren(h('span', { text }),
      undo ? h('button', { type: 'button', text: 'Undo', onclick: () => { toastEl.classList.remove('open'); undo(); } }) : null);
    toastEl.classList.toggle('error', !!error);
    toastEl.classList.add('open');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('open'), undo ? 7000 : 4000);
  }
  function busy(msg) {
    busyEl.classList.toggle('open', !!msg);
    if (msg) busyEl.querySelector('p').textContent = msg;
  }

  // ── modals ──
  function openModal(title, ...content) {
    modalBg.replaceChildren(h('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true' },
      h('div', { class: 'flex-between' }, h('h2', { text: title }),
        h('button', { class: 'btn btn-sm btn-ghost', type: 'button', text: '✕', 'aria-label': 'Close', onclick: closeModal })),
      ...content));
    modalBg.classList.add('open');
    const first = modalBg.querySelector('input,select');
    if (first) setTimeout(() => first.focus(), 50);
  }
  function closeModal() { modalBg.classList.remove('open'); }

  const field = (label, input) => h('div', { class: 'form-group' }, h('label', { text: label }), input);
  const sexSelect = value => h('select', {},
    h('option', { value: 'female', text: 'Female', selected: value === 'female' }),
    h('option', { value: 'male', text: 'Male', selected: value === 'male' }));

  function openRename(name) {
    const input = h('input', { type: 'text', value: name, maxlength: 60 });
    const sex = sexSelect(sexOf(name));
    const save = async e => {
      e.preventDefault();
      closeModal(); S.sel = null;
      await mutate('/api/rename', { old: name, new: input.value, sex: sex.value }, `Updated ${input.value.trim() || name}`);
    };
    openModal('Rename guest',
      h('p', { class: 'text-muted', style: 'margin-bottom:1rem', text: 'Fill in a placeholder (like “Weldon guest”) or correct a name. Changes every meal.' }),
      h('form', { onsubmit: save }, field('Name', input), field('Sex', sex),
        h('button', { class: 'btn btn-primary', type: 'submit', text: 'Save' })));
  }

  function openAddGuest() {
    const input = h('input', { type: 'text', maxlength: 60, placeholder: 'Name' });
    const sex = sexSelect('female');
    const boxes = plan().meals.map(m => h('label', {}, h('input', { type: 'checkbox', value: m }), ' ' + m));
    const save = async e => {
      e.preventDefault();
      const meals = boxes.map(b => b.querySelector('input')).filter(i => i.checked).map(i => i.value);
      closeModal();
      await mutate('/api/add_guest', { name: input.value, sex: sex.value, meals },
        `Added ${input.value.trim()} to the smallest table. Tap them to move`);
    };
    openModal('Add a late guest',
      h('p', { class: 'text-muted', style: 'margin-bottom:1rem', text: 'They’re added to the smallest table at each meal. Swap them into place, or lock the seats you like and regenerate.' }),
      h('form', { onsubmit: save }, field('Name', input), field('Sex', sex),
        field('Meals', h('div', { class: 'checkbox-group' }, boxes)),
        h('button', { class: 'btn btn-primary', type: 'submit', text: 'Add guest' })));
  }

  function openKeepApart() {
    const p = plan();
    const names = p.people.map(x => x.name).sort((a, b) => a.localeCompare(b));
    const pick = () => h('select', {}, h('option', { value: '', text: 'Choose…' }), names.map(n => h('option', { value: n, text: n })));
    const a = pick(), b = pick();
    const refresh = async (path, body, msg) => { await mutate(path, body, msg); openKeepApart(); };
    const file = h('input', { type: 'file', accept: '.json,.csv', style: 'display:none',
      onchange: async () => {
        if (!file.files[0]) return;
        const fd = new FormData(); fd.append('file', file.files[0]);
        await refresh('/api/history', fd, 'Past event added');
      } });
    openModal('Keep apart & past events',
      h('h3', { text: 'Never seat together' }),
      h('p', { class: 'text-muted', text: 'For people who must not sit next to each other at any meal, like John and Susie C.' }),
      (p.keep_apart || []).length
        ? h('ul', { class: 'pair-list' }, p.keep_apart.map(([x, y]) => h('li', {}, h('span', { text: `${x} & ${y}` }),
          h('button', { type: 'button', 'aria-label': 'Remove', text: '✕',
            onclick: () => refresh('/api/keep_apart', { a: x, b: y, remove: true }, `${x} & ${y} can sit together again`) }))))
        : h('p', { class: 'text-muted mt1', style: 'margin-bottom:.75rem', text: 'None yet.' }),
      h('form', { class: 'inline-form', style: 'margin-bottom:1.5rem', onsubmit: e => {
        e.preventDefault();
        refresh('/api/keep_apart', { a: a.value, b: b.value }, `${a.value} & ${b.value} will be kept apart`);
      } }, a, '&', b, h('button', { class: 'btn btn-sm btn-primary', type: 'submit', text: 'Add' })),
      h('h3', { text: 'Past events' }),
      h('p', { class: 'text-muted', text: 'Add a plan you saved from a previous weekend (or its seating CSV). Anyone who sat together then is kept apart now where possible.' }),
      (p.history || []).length
        ? h('ul', { class: 'pair-list' }, p.history.map(ev => h('li', {},
          h('span', { text: `${ev.event} · ${ev.pairs.length} pairs` }),
          h('button', { type: 'button', 'aria-label': 'Remove', text: '✕',
            onclick: () => refresh('/api/history_remove', { event: ev.event }, `Removed ${ev.event}`) }))))
        : h('p', { class: 'text-muted mt1', style: 'margin-bottom:.75rem', text: 'None yet.' }),
      file,
      h('button', { class: 'btn btn-sm btn-secondary', type: 'button', text: '＋ Add past event', onclick: () => file.click() }),
      h('p', { class: 'text-muted mt2', style: 'font-size:.8rem', text: 'Changes here apply next time you regenerate. Tap ↻ Regenerate to re-seat around them now.' }));
  }

  // ── start ──
  (async () => {
    const msg = document.getElementById('loading-msg');
    try {
      if (window.BOOT && window.BOOT.generate) {
        if (msg) msg.textContent = 'Creating your seating plan… this takes a few seconds.';
        setState(await api('/api/regenerate', {}));
      } else {
        setState(await api('/api/state'));
      }
    } catch (e) {
      app.replaceChildren(h('div', { class: 'alert alert-error', text: e.message }),
        h('a', { class: 'btn btn-secondary', href: '/', text: '← Start again' }));
    }
  })();
})();
