/* Progressive enhancement: AJAX forms, live search/filter, live polling, toasts, drafts, drag-and-drop. */
(() => {
  const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const dyn = () => $('#dyn');
  if (!dyn()) return;                       // login/register pages stay plain
  let dirty = false, sig = null, busy = false;

  function toast(msg, kind) {
    const t = document.createElement('div');
    t.className = 'toast ' + (kind || ''); t.textContent = msg; $('#toasts').append(t);
    setTimeout(() => { t.classList.add('out'); setTimeout(() => t.remove(), 350); }, 2800);
  }
  async function load(url, opts) {
    const r = await fetch(url, { credentials: 'same-origin', ...opts });
    if (r.redirected && new URL(r.url).pathname.startsWith('/login')) { location.href = r.url; return null; }
    if (!r.ok && r.status !== 200) { toast('Something went wrong (' + r.status + ')', 'error'); return null; }
    return new DOMParser().parseFromString(await r.text(), 'text/html');
  }
  function flashes(doc) {
    $$('.flash', doc).forEach(f => { toast(f.textContent.trim(), f.classList.contains('error') ? 'error' : ''); f.remove(); });
  }
  function title() {
    const n = +dyn().dataset.pending; const base = 'Assignment Portal';
    document.title = n > 0 ? `(${n}) ${base}` : base;
  }
  function swap(doc) {
    const nd = $('#dyn', doc); if (!nd) return;
    flashes(nd);
    const open = $$('details[open]').map(d => d.dataset.k);
    dyn().innerHTML = nd.innerHTML; dyn().dataset.pending = nd.dataset.pending || 0;
    $$('details').forEach(d => { if (open.includes(d.dataset.k)) d.open = true; });
    dirty = false; enhance(); title();
  }
  function count(el) {
    const to = +el.dataset.n, t0 = performance.now();
    (function step(t) { const p = Math.min(1, (t - t0) / 500); el.textContent = Math.round(to * (1 - Math.pow(1 - p, 3)));
      if (p < 1) requestAnimationFrame(step); })(t0);
  }
  function enhance() {
    $$('.stat b[data-n]').forEach(count);
    $$('input[type=file]').forEach(inp => {
      if (inp.closest('.dz')) return;
      const w = document.createElement('div'); w.className = 'dz'; inp.replaceWith(w);
      const txt = document.createElement('span'); txt.textContent = 'Drop a file here or click to browse';
      w.append(txt, inp);
      inp.addEventListener('change', () => { const f = inp.files[0]; w.classList.toggle('has', !!f);
        txt.textContent = f ? `${f.name} · ${f.size > 1048576 ? (f.size / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.ceil(f.size / 1024)) + ' KB'}` : 'Drop a file here or click to browse'; });
      ['dragenter', 'dragover'].forEach(e => w.addEventListener(e, () => w.classList.add('over')));
      ['dragleave', 'drop'].forEach(e => w.addEventListener(e, () => w.classList.remove('over')));
    });
    $$('textarea[name=content]').forEach(ta => {
      if (ta.dataset.on) return; ta.dataset.on = 1;
      const key = 'draft:' + ta.form.getAttribute('action'), cc = document.createElement('div'); cc.className = 'cc'; ta.after(cc);
      const upd = (msg) => { const w = ta.value.trim() ? ta.value.trim().split(/\s+/).length : 0; cc.textContent = `${w} word${w === 1 ? '' : 's'} · ${ta.value.length} characters${msg ? ' · ' + msg : ''}`; };
      try { const d = localStorage.getItem(key); if (d && !ta.value.trim().length) { ta.value = d; } } catch (e) {}
      upd(ta.value && localStorage.getItem(key) ? 'draft restored' : '');
      ta.addEventListener('input', () => { dirty = true; try { localStorage.setItem(key, ta.value); } catch (e) {} upd('draft saved'); });
      ta.form.addEventListener('submit', () => { try { localStorage.removeItem(key); } catch (e) {} });
    });
  }

  /* --- AJAX form submission (no page reload) --- */
  document.addEventListener('submit', async e => {
    const f = e.target;
    if (f.hasAttribute('data-plain') || e.defaultPrevented || !dyn().contains(f)) return;
    e.preventDefault();
    if (f.id === 'filters') return filter();
    const btn = $('button:not([type=button])', f), label = btn && btn.textContent;
    if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }
    const doc = await load(f.action, { method: 'POST', body: new FormData(f) });
    if (btn) { btn.disabled = false; btn.textContent = label; }
    if (doc) swap(doc);
  });

  /* --- live search / filter / sort (only the results list is swapped) --- */
  let ft;
  async function filter() {
    const f = $('#filters'); if (!f) return;
    const url = location.pathname + '?' + new URLSearchParams(new FormData(f));
    history.replaceState(null, '', url);
    const doc = await load(url); if (doc && $('#subs', doc)) $('#subs').innerHTML = $('#subs', doc).innerHTML;
  }
  document.addEventListener('input', e => { if (e.target.closest('#filters')) { clearTimeout(ft); ft = setTimeout(filter, 250); } });
  document.addEventListener('change', e => { if (e.target.closest('#filters')) filter(); });
  document.addEventListener('click', e => {           // stat cards act as quick filters
    const c = e.target.closest('.stat.click'); if (!c) return;
    const sel = $('#filters select[name=status]'); if (!sel) return;
    sel.value = c.dataset.status; filter(); $('#filters').scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
  document.addEventListener('keydown', e => {          // "/" focuses search
    if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) && $('#q')) { e.preventDefault(); $('#q').focus(); }
  });

  /* --- live updates: poll a tiny signature endpoint --- */
  async function poll() {
    if (document.hidden || busy) return; busy = true;
    try {
      const r = await fetch('/api/sig', { credentials: 'same-origin' }); if (!r.ok) return;
      const s = (await r.json()).sig;
      if (sig !== null && s !== sig) {
        if (!dirty && !/TEXTAREA|INPUT/.test(document.activeElement.tagName)) {
          const doc = await load(location.href); if (doc) { swap(doc); toast('Updated with the latest changes'); }
        } else if (!$('#upd')) {
          const b = document.createElement('div'); b.id = 'upd'; b.className = 'on';
          b.innerHTML = '<span>New updates are available.</span><button type="button">Refresh</button>';
          $('button', b).onclick = async () => { const doc = await load(location.href); if (doc) swap(doc); };
          dyn().prepend(b);
        }
      }
      sig = s;
    } catch (e) {} finally { busy = false; }
  }
  poll(); setInterval(poll, 8000); document.addEventListener('visibilitychange', poll);
  flashes(document); enhance(); title();
})();
