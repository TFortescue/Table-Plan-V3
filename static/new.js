/* No-file plan builder: event & meals → guests (men / women boxes) → couples → who's at which meal. */
(() => {
  'use strict';
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

  const DRAFT_KEY = 'tableplanner:draft';
  const PRESETS = {
    'Fri–Sun weekend': ['Friday Dinner', 'Saturday Lunch', 'Saturday Dinner', 'Sunday Lunch'],
    'Sat–Sun': ['Saturday Lunch', 'Saturday Dinner', 'Sunday Lunch'],
    'One day': ['Lunch', 'Dinner'],
    'One meal': ['Dinner'],
  };
  const blank = () => ({ event: '', meals: PRESETS['Fri–Sun weekend'].slice(), men: '', women: '', partners: {}, absent: {} });
  let D;
  try { D = Object.assign(blank(), JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null') || {}); } catch (e) { D = blank(); }
  const save = () => { try { localStorage.setItem(DRAFT_KEY, JSON.stringify(D)); } catch (e) { /* ignore */ } };

  // "1. Tom", "- Weez", "Tom, Weez, John" → clean names
  function parse(text) {
    const lines = text.includes('\n') ? text.split('\n') : text.split(',');
    const out = [];
    for (let line of lines) {
      line = line.replace(/^\s*(?:[-•*·]|\d+[.)])\s*/, '').replace(/,/g, ' ').replace(/\s+/g, ' ').trim();
      if (line && !out.some(x => x.toLowerCase() === line.toLowerCase())) out.push(line);
    }
    return out;
  }
  const men = () => parse(D.men);
  const women = () => parse(D.women);
  const everyone = () => [...men().map(n => ({ name: n, sex: 'male' })), ...women().map(n => ({ name: n, sex: 'female' }))];
  const attends = (name, meal) => !(D.absent[name] || []).includes(meal);

  const root = document.getElementById('builder');
  const dyn = {};  // containers re-rendered on change

  function section(n, title, help, ...body) {
    return h('section', { class: 'card builder-step mt2' },
      h('div', { class: 'step-head' }, h('span', { class: 'step-num', text: n }),
        h('div', {}, h('h2', { text: title }), help ? h('p', { class: 'text-muted', text: help }) : null)),
      ...body);
  }

  // ── 1. event & meals ──
  const eventInput = h('input', { type: 'text', maxlength: 80, placeholder: 'e.g. Shoot Weekend 7th', value: D.event,
    oninput: e => { D.event = e.target.value; save(); } });
  const mealInput = h('input', { type: 'text', maxlength: 40, placeholder: 'Add a meal, e.g. Sunday Breakfast' });
  const addMeal = e => {
    e.preventDefault();
    const m = mealInput.value.replace(/\s+/g, ' ').trim();
    if (m && !D.meals.includes(m)) D.meals.push(m);
    mealInput.value = ''; update();
  };
  dyn.meals = h('div', { class: 'chips' });

  // ── 2. guests ──
  const box = (key, label, ph) => {
    const count = h('span', { class: 'count' });
    const ta = h('textarea', { rows: 8, placeholder: ph, spellcheck: 'false', autocapitalize: 'words' });
    ta.value = D[key];
    let t;
    ta.addEventListener('input', () => { D[key] = ta.value; save(); clearTimeout(t); t = setTimeout(update, 250); });
    dyn[key + 'Count'] = count;
    return h('div', { class: 'form-group' }, h('label', {}, label, ' ', count), ta);
  };
  const reuse = h('input', { type: 'file', accept: '.json', style: 'display:none', onchange: () => importPlan(reuse.files[0]) });
  dyn.dupes = h('div');

  // ── 3. couples / 4. meals ──
  dyn.couples = h('div');
  dyn.grid = h('div', { style: 'overflow-x:auto' });

  // ── create bar ──
  dyn.summary = h('span', { class: 'summary' });
  dyn.error = h('div', { class: 'bar-error', role: 'alert' });
  const createBtn = h('button', { class: 'btn btn-primary', type: 'button', text: 'Create plan →', onclick: create });

  root.replaceChildren(
    h('div', { class: 'flex-between', style: 'flex-wrap:wrap;gap:.5rem' },
      h('div', {}, h('h1', { text: 'New seating plan' }),
        h('p', { class: 'subtitle', style: 'margin-bottom:0', text: 'Saved on this device as you type.' })),
      h('button', { class: 'btn btn-sm btn-ghost', type: 'button', text: 'Start over', onclick: () => {
        if (!confirm('Clear everything you’ve typed?')) return;
        D = blank(); save(); location.reload();
      } })),
    section(1, 'Event & meals', 'In the order they happen.',
      h('div', { class: 'form-group' }, h('label', { text: 'Event name' }), eventInput),
      h('label', { text: 'Meals' }), dyn.meals,
      h('form', { class: 'inline-form mt1', onsubmit: addMeal }, mealInput, h('button', { class: 'btn btn-sm btn-secondary', type: 'submit', text: 'Add' })),
      h('div', { class: 'presets mt1' }, h('span', { class: 'text-muted', text: 'Quick: ' }),
        Object.entries(PRESETS).map(([label, list]) => h('button', { class: 'btn btn-sm btn-ghost', type: 'button', text: label,
          onclick: () => { D.meals = list.slice(); update(); } })))),
    section(2, 'Guests', 'One name per line, or paste a list. Use an initial to tell two people apart (Tom W).',
      h('div', { class: 'form-row' },
        box('men', 'Men', 'Tom\nJohn\nFergus\n…'),
        box('women', 'Women', 'Weez\nPhoebe\nKitty\n…')),
      dyn.dupes,
      reuse,
      h('button', { class: 'btn btn-sm btn-ghost', type: 'button', text: '↺ Copy guests from a saved plan', onclick: () => reuse.click() })),
    section(3, 'Couples', 'Couples are never seated next to each other. Skip anyone who’s single.', dyn.couples),
    section(4, 'Who’s at which meal', 'Everyone is ticked. Untick anyone missing a meal.', dyn.grid),
    h('div', { class: 'create-bar' }, h('div', { class: 'create-inner' }, dyn.summary, createBtn), dyn.error));

  function update() {
    save();
    // meals chips
    dyn.meals.replaceChildren(...(D.meals.length ? D.meals.map((m, i) => h('span', { class: 'chip' },
      i > 0 ? h('button', { type: 'button', class: 'chip-move', 'aria-label': `Move ${m} earlier`, text: '‹',
        onclick: () => { [D.meals[i - 1], D.meals[i]] = [D.meals[i], D.meals[i - 1]]; update(); } }) : null,
      h('span', { text: m }),
      h('button', { type: 'button', class: 'chip-x', 'aria-label': `Remove ${m}`, text: '✕',
        onclick: () => { D.meals.splice(i, 1); update(); } })))
      : [h('span', { class: 'text-muted', text: 'No meals yet: add one below.' })]));

    const M = men(), W = women();
    dyn.menCount.textContent = M.length ? `· ${M.length}` : '';
    dyn.womenCount.textContent = W.length ? `· ${W.length}` : '';
    const both = M.filter(n => W.some(w => w.toLowerCase() === n.toLowerCase()));
    dyn.dupes.replaceChildren(...(both.length ? [h('div', { class: 'alert alert-warning',
      text: `${both.join(', ')} ${both.length > 1 ? 'are' : 'is'} in both lists. Add an initial to tell them apart, or remove one.` })] : []));

    // couples: one row per man
    for (const k of Object.keys(D.partners)) if (!M.includes(k) || !W.includes(D.partners[k])) delete D.partners[k];
    if (!M.length || !W.length) {
      dyn.couples.replaceChildren(h('p', { class: 'text-muted', text: 'Add men and women above first.' }));
    } else {
      const taken = Object.fromEntries(Object.entries(D.partners).map(([m, w]) => [w, m]));
      dyn.couples.replaceChildren(h('div', { class: 'couples' }, M.map(m => {
        const sel = h('select', { 'aria-label': `${m}'s partner`, onchange: e => {
          if (e.target.value) D.partners[m] = e.target.value; else delete D.partners[m];
          update();
        } }, h('option', { value: '', text: '—' }),
          W.map(w => h('option', { value: w, text: taken[w] && taken[w] !== m ? `${w} (with ${taken[w]})` : w, selected: D.partners[m] === w })));
        return h('div', { class: 'couple-row' }, h('span', { class: 'couple-name', text: m }), h('span', { class: 'text-muted', text: '&' }), sel);
      })));
    }

    // attendance grid
    for (const k of Object.keys(D.absent)) {
      if (!M.includes(k) && !W.includes(k)) delete D.absent[k];
      else D.absent[k] = D.absent[k].filter(m => D.meals.includes(m));
    }
    const people = everyone();
    if (!people.length || !D.meals.length) {
      dyn.grid.replaceChildren(h('p', { class: 'text-muted', text: 'Add meals and guests first.' }));
    } else {
      const toggle = (name, meal, on) => {
        const a = new Set(D.absent[name] || []);
        on ? a.delete(meal) : a.add(meal);
        D.absent[name] = [...a]; if (!D.absent[name].length) delete D.absent[name];
      };
      const head = h('tr', {}, h('th', { text: 'Guest' }), D.meals.map(meal => {
        const all = people.every(p => attends(p.name, meal));
        const short = meal.replace(/\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*day\b/gi, '$1');
        return h('th', {}, h('button', { type: 'button', class: 'col-toggle', title: `${meal}: ${all ? 'untick' : 'tick'} everyone`,
          onclick: () => { people.forEach(p => toggle(p.name, meal, !all)); update(); } }, short));
      }));
      const rows = people.map(p => h('tr', {},
        h('td', {}, h('span', { class: 'badge badge-' + p.sex, text: p.sex[0].toUpperCase() }), ' ', p.name),
        D.meals.map(meal => h('td', { class: 'tick' }, h('input', { type: 'checkbox', checked: attends(p.name, meal),
          'aria-label': `${p.name} at ${meal}`, onchange: e => { toggle(p.name, meal, e.target.checked); save(); summary(); } })))));
      dyn.grid.replaceChildren(h('table', { class: 'attend-grid' }, h('thead', {}, head), h('tbody', {}, rows)));
    }
    summary();
  }

  function summary() {
    const M = men(), W = women();
    const counts = D.meals.map(meal => everyone().filter(p => attends(p.name, meal)).length);
    dyn.summary.textContent = `${M.length} men · ${W.length} women · ${D.meals.length} meal${D.meals.length === 1 ? '' : 's'}` +
      (counts.length ? ` (${counts.join(' / ')} seated)` : '');
    dyn.error.textContent = '';
  }

  async function importPlan(file) {
    if (!file) return;
    try {
      const p = JSON.parse(await file.text());
      if (!p || !Array.isArray(p.people)) throw new Error();
      const sex = Object.fromEntries(p.people.map(x => [x.name, x.sex]));
      D.men = p.people.filter(x => x.sex === 'male').map(x => x.name).join('\n');
      D.women = p.people.filter(x => x.sex === 'female').map(x => x.name).join('\n');
      D.partners = {};
      for (const x of p.people) if (x.sex === 'male') {
        const w = (x.relations || []).find(r => sex[r] === 'female' && (p.people.find(y => y.name === r).relations || []).includes(x.name));
        if (w) D.partners[x.name] = w;
      }
      D.absent = {};
      document.querySelectorAll('.builder-step textarea')[0].value = D.men;
      document.querySelectorAll('.builder-step textarea')[1].value = D.women;
      update();
      dyn.error.textContent = '';
    } catch (e) {
      dyn.error.textContent = 'That doesn’t look like a saved plan file (.json from 💾 Save plan).';
    }
  }

  async function create() {
    const guests = everyone().map(p => ({
      name: p.name, sex: p.sex, meals: D.meals.filter(m => attends(p.name, m)),
      partner: p.sex === 'male' ? (D.partners[p.name] || '') : '',
    }));
    createBtn.disabled = true; createBtn.textContent = 'Creating…';
    try {
      const r = await fetch('/api/new_plan', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event: D.event, meals: D.meals, guests }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok || j.error) throw new Error(j.error || 'Something went wrong. Please try again.');
      try { localStorage.removeItem(DRAFT_KEY); } catch (e) { /* ignore */ }
      location.href = j.next;
    } catch (e) {
      dyn.error.textContent = e.message;
      createBtn.disabled = false; createBtn.textContent = 'Create plan →';
    }
  }

  update();
})();
