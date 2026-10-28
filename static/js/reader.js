/* 本地同人志文库 前端 · reader.js
   阅读器 v2（页面/滚动双模式）
   3.6.84 从 static/app.js 拆出：按顶层区块切分，仍是 classic script，
   与其余分片共享同一个全局词法环境（顺序加载，勿调整 index.html 里的 <script> 次序）。 */
'use strict';

/* ---------- 阅读器 v2：页面/滚动 双模式 + 缩放拉条 + 页码拉条 ---------- */
const reader = {
  open: false, group: null, work: null, total: 0, idx: 0, kinds: [],
  mode: localStorage.getItem('rd_mode') || 'page',   // 'page' | 'scroll'
  zoom: parseInt(localStorage.getItem('rd_zoom') || '100', 10),  // 缩放百分比
};

async function openReader(group, work) {
  if (reader.open) return;
  try {
    const data = await api('/api/pages?group=' + enc(group) + '&work=' + enc(work));
    if (!data.total) { showToast(t('该作品没有可浏览的页面')); return; }
    reader.open = true;
    reader.group = group; reader.work = work;
    reader.total = data.total; reader.idx = 0;
    reader.ver = data.ver || '';      // 页面缓存键：删首页图片后页序变化也能让浏览器丢缓存
    reader.kinds = Array.isArray(data.kinds) && data.kinds.length === data.total ? data.kinds : null;
    // 3.1 继续阅读：拉取上次阅读位置（在线/离线一视同仁，服务端为准）
    try {
      const st = await api('/api/reading/state?key=' + enc(group + '/' + work));
      if (st.last_page > 0 && st.last_page < data.total) reader.idx = st.last_page;
    } catch (_e) { /* 无记录/离线：从头读 */ }
    try {
      buildReaderDom(data);
      applyMode();
    } catch (e) {
      closeReader();          // 构建/渲染失败必须复位 reader.open，否则阅读器再也无法打开
      throw e;
    }
  } catch (e) {
    showToast(tf('无法打开阅读器：%1', e.message));
  }
}

function isVideoPage(n) {
  return !!(reader.kinds && reader.kinds[n] === 'video');
}

function buildReaderDom(data) {
  let r = $('#reader');
  if (!r) {
    r = document.createElement('div');
    r.id = 'reader';
    document.body.appendChild(r);
  }
  r.classList.remove('hidden');
  r.innerHTML =
    '<div class="reader-top">' +
      '<button id="rdClose" title="' + esc(t('关闭 (Esc)')) + '">✕</button>' +
      '<div class="rd-title">' + esc(data.name) + '</div>' +
      '<div class="rd-mode">' +
        '<button id="rdModePage" title="翻页模式：A/D、左右键、点击翻页，滚轮缩放"><!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-book-open" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M12 7v14" /> <path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z" /> </svg> 页面</button>' +
        '<button id="rdModeScroll" title="滚动模式：滚轮向下滚动阅读，到底自动翻页"><!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-scroll-text" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M15 12h-5" /> <path d="M15 8h-5" /> <path d="M19 17V5a2 2 0 0 0-2-2H4" /> <path d="M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2a1 1 0 0 0 1 1h3" /> </svg> 滚动</button>' +
      '</div>' +
      '<div id="rdZoomWrap" title="' + esc(t('图片缩放')) + '">' +
        '<span id="rdZoomVal">' + reader.zoom + '%</span>' +
        '<input id="rdZoom" type="range" min="30" max="300" step="5" value="' + reader.zoom + '">' +
      '</div>' +
      '<div class="rd-count"><span id="rdIdx">1</span> / <span id="rdTotal">' + data.total + '</span></div>' +
    '</div>' +
    '<div class="rd-stage" id="rdStage"></div>' +
    '<div class="reader-bottom">' +
      '<button id="rdPrev" class="rd-nav" title="' + esc(t('上一页 (A / ←)')) + '">◀</button>' +
      '<input id="rdSlider" type="range" min="1" max="' + data.total + '" value="1" title="' + esc(t('拖动快速跳页')) + '">' +
      '<button id="rdNext" class="rd-nav" title="' + esc(t('下一页 (D / →)')) + '">▶</button>' +
    '</div>';
  $('#rdClose').addEventListener('click', closeReader);
  $('#rdPrev').addEventListener('click', () => go(-1));
  $('#rdNext').addEventListener('click', () => go(1));
  $('#rdSlider').addEventListener('input', e => {
    const n = parseInt(e.target.value, 10) - 1;
    if (reader.mode === 'scroll') {
      if (n !== reader.idx) { reader.idx = n; updateIndicator(); scrollToBlock(n); }
    } else if (n !== reader.idx) showPage(n);
  });
  $('#rdZoom').addEventListener('input', e => {
    reader.zoom = parseInt(e.target.value, 10);
    localStorage.setItem('rd_zoom', reader.zoom);
    $('#rdZoomVal').textContent = reader.zoom + '%';
    applyZoom();
  });
  $('#rdModePage').addEventListener('click', () => setMode('page'));
  $('#rdModeScroll').addEventListener('click', () => setMode('scroll'));
}

function setMode(mode) {
  if (reader.mode === mode) return;
  reader.mode = mode;
  localStorage.setItem('rd_mode', mode);
  applyMode();
}

/* 按当前模式重建舞台并载入当前页（切换模式/重开时保持页码） */
function applyMode() {
  const stage = $('#rdStage');
  if (!stage) return;
  const mp = $('#rdModePage'), ms = $('#rdModeScroll'), zw = $('#rdZoomWrap');
  if (mp) mp.classList.toggle('on', reader.mode === 'page');
  if (ms) ms.classList.toggle('on', reader.mode === 'scroll');
  if (zw) zw.classList.remove('hidden');
  stage.className = 'rd-stage ' + (reader.mode === 'scroll' ? 'rd-scroll' : 'rd-page');
  stage.innerHTML = '<div class="rd-wrap" id="rdWrap"></div>';
  const wrap = $('#rdWrap');
  const hint = $('#rdHint');

  if (reader.mode === 'page') {
    wrap.addEventListener('wheel', onPageWheel, { passive: false });
    wrap.addEventListener('click', e => {
      if (Date.now() - _swipedAt < 400) return;   // 刚完成滑动翻页：忽略紧随的合成 click
      if (e.target.closest('button, input, video')) return;
      const rect = wrap.getBoundingClientRect();
      go(e.clientX > rect.left + rect.width / 2 ? 1 : -1);
    });
    attachSwipe(wrap);
    if (hint) hint.textContent = t('A/D · ←→ · 点击/滑动翻页 | 滚轮缩放');
  } else {
    if (hint) hint.textContent = t('瀑布流连续阅读 · 滚轮向下滚动');
    buildScrollStack(wrap);
    scrollToBlock(reader.idx);
    updateIndicator();
    return;
  }
  showPage(reader.idx);
}

function loadMediaInto(wrap, n) {
  if (isVideoPage(n)) {
    const v = document.createElement('video');
    v.id = 'rdMedia'; v.controls = true; v.loop = true; v.autoplay = true;
    v.playsInline = true; v.style.opacity = '1';
    v.src = pageUrl(reader.group, reader.work, n, reader.ver);
    wrap.appendChild(v);
    const pp = v.play(); if (pp && pp.catch) pp.catch(() => {});
  } else {
    const img = document.createElement('img');
    img.id = 'rdMedia'; img.style.opacity = '1';
    img.addEventListener('load', applyZoom);
    img.src = pageUrl(reader.group, reader.work, n, reader.ver);
    wrap.appendChild(img);
  }
}

/* 3.3.0 触屏滑动翻页（页面模式）：对齐 wnacg 官方 APP 手感——横向快滑翻页，
   竖向滑动/长按/多指缩放不受影响；滑动后 400ms 内抑制合成 click 误翻页 */
let _swipe = null, _swipedAt = 0;

function attachSwipe(wrap) {
  wrap.addEventListener('touchstart', e => {
    if (e.touches.length !== 1) { _swipe = null; return; }
    _swipe = { x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now() };
  }, { passive: true });
  wrap.addEventListener('touchend', e => {
    if (!_swipe) return;
    const t = e.changedTouches && e.changedTouches[0];
    if (!t) { _swipe = null; return; }
    const dx = t.clientX - _swipe.x, dy = t.clientY - _swipe.y;
    const dt = Date.now() - _swipe.t;
    _swipe = null;
    if (dt > 650 || Math.abs(dx) < 50 || Math.abs(dx) < Math.abs(dy) * 1.2) return;
    _swipedAt = Date.now();
    go(dx < 0 ? 1 : -1);      // 左滑 = 下一页（与官方 APP 一致）
  }, { passive: true });
}

/* 页面模式：滚轮缩放 */
function onPageWheel(e) {
  e.preventDefault();
  const step = e.deltaY > 0 ? -10 : 10;
  reader.zoom = Math.min(300, Math.max(30, reader.zoom + step));
  localStorage.setItem('rd_zoom', reader.zoom);
  const zi = $('#rdZoom'), zv = $('#rdZoomVal');
  if (zi) zi.value = reader.zoom;
  if (zv) zv.textContent = reader.zoom + '%';
  applyZoom();
}

/* 依据模式与缩放设置媒体尺寸 */
function applyZoom() {
  const wrap = $('#rdWrap');
  if (!wrap) return;
  const w = Math.round(wrap.clientWidth * reader.zoom / 100) + 'px';
  if (reader.mode === 'scroll') {
    wrap.querySelectorAll('.rd-pageblock img, .rd-pageblock video').forEach(m => {
      m.style.width = w; m.style.height = 'auto';
    });
    return;
  }
  const media = $('#rdMedia');
  if (!media) return;
  if (media.tagName === 'VIDEO') {
    media.style.maxWidth = reader.zoom + '%';
    media.style.maxHeight = reader.zoom + '%';
  } else {
    const h = (wrap.clientHeight || 600) * reader.zoom / 100;
    media.style.height = Math.round(h) + 'px';
    media.style.width = 'auto';
    media.style.maxWidth = 'none';
  }
}

/* ---------- 滚动模式：瀑布流长条（懒加载 + 页码追踪） ---------- */
let rdLoader = null, rdTracker = null;
let _rdTrackRAF = 0;

function disconnectObservers() {
  rdLoader?.disconnect(); rdTracker?.disconnect();
  rdLoader = rdTracker = null;
}

/* 滚动模式当前页追踪（双端对齐安卓）：顶部可见页块为正在读的页；
   下一页块露出自身高度过半 → 翻到下一页。修复末页过矮时中心带永远不被末页穿过、
   进度卡在倒数第二页赖在续读区的问题。 */
function rdTrackScroll() {
  if (_rdTrackRAF) return;
  _rdTrackRAF = requestAnimationFrame(() => {
    _rdTrackRAF = 0;
    const wrap = $('#rdWrap');
    if (!wrap || reader.mode !== 'scroll') return;
    const wr = wrap.getBoundingClientRect();
    const blocks = wrap.children;            // .rd-pageblock，按页码顺序
    let cur = -1;
    for (let i = 0; i < blocks.length; i++) {
      const br = blocks[i].getBoundingClientRect();
      const bo = br.top - wr.top, bh = br.height;
      if (bo + bh <= 0) continue;            // 已完全滚出顶部
      if (bo >= wr.height) break;            // 完全在底部之下（块有序，可停）
      cur = +blocks[i].dataset.n; break;
    }
    if (cur < 0) return;
    const nb = blocks[cur + 1];
    if (nb) {
      const nbr = nb.getBoundingClientRect();
      const nbo = nbr.top - wr.top, nbh = nbr.height;
      const visH = Math.max(0, Math.min(wr.height, nbo + nbh) - Math.max(0, nbo));
      if (nbh > 0 && visH / nbh >= 0.5) cur = cur + 1;
    }
    if (cur !== reader.idx) { reader.idx = cur; updateIndicator(); }
  });
}

function blockEl(n) {
  return $('#rdWrap')?.querySelector(`.rd-pageblock[data-n="${n}"]`);
}

function scrollToBlock(n, anchor) {
  const b = blockEl(n), wrap = $('#rdWrap');
  if (!b || !wrap) return;
  wrap.scrollTop = b.offsetTop - (anchor === 'bottom'
    ? Math.max(0, wrap.clientHeight - b.offsetHeight) : 0);
}

function updateIndicator() {
  const idx = $('#rdIdx');
  if (idx) idx.textContent = reader.idx + 1;
  const sl = $('#rdSlider');
  if (sl) sl.value = reader.idx + 1;
  const pv = $('#rdPrev'), nx = $('#rdNext');
  if (pv) pv.disabled = reader.idx <= 0;
  if (nx) nx.disabled = reader.idx >= reader.total - 1;
  reportReading(false);        // 滚动模式的页码追踪走这里（页面模式走 showPage）
}

function buildScrollStack(wrap) {
  disconnectObservers();
  wrap.innerHTML = '';
  const blocks = [];
  for (let n = 0; n < reader.total; n++) {
    const b = document.createElement('div');
    b.className = 'rd-pageblock'; b.dataset.n = n;
    b.innerHTML = '<div class="rd-ph">…</div>';
    wrap.appendChild(b); blocks.push(b);
  }
  rdLoader = new IntersectionObserver(es => es.forEach(en => {
    if (!en.isIntersecting) return;
    rdLoader.unobserve(en.target);
    const b = en.target;
    b.innerHTML = '';
    loadMediaInto(b, +b.dataset.n);
  }), { root: wrap, rootMargin: '250% 0px' });
  blocks.forEach(b => rdLoader.observe(b));
    // 当前页追踪（双端对齐安卓）：顶部可见页块为正在读的页；下一页露出自身高度过半 → 翻到下一页。
    rdTrackScroll();
    wrap.addEventListener('scroll', rdTrackScroll, { passive: true });
}

function showPage(n) {
  reader.idx = Math.max(0, Math.min(reader.total - 1, n));
  reportReading(false);        // 3.1 进度上报（节流）
  if (reader.mode === 'scroll') {
    updateIndicator(); scrollToBlock(reader.idx); return;
  }
  const wrap = $('#rdWrap');
  if (!wrap) return;
  wrap.innerHTML = '';
  loadMediaInto(wrap, reader.idx);
  $('#rdIdx').textContent = reader.idx + 1;
  const sl = $('#rdSlider');
  if (sl) sl.value = reader.idx + 1;
  $('#rdPrev').disabled = reader.idx <= 0;
  $('#rdNext').disabled = reader.idx >= reader.total - 1;
  preload(reader.idx);
}

/* 预加载相邻页（图片） */
function preload(n) {
  const targets = [n + 1, n + 2, n - 1].filter(i => i >= 0 && i < reader.total);
  for (const i of targets) {
    if (isVideoPage(i)) continue;
    const im = new Image();
    im.src = pageUrl(reader.group, reader.work, i, reader.ver);
  }
}

function go(delta, anchor) {
  if (!reader.open) return;
  const n = reader.idx + delta;
  if (n < 0) { showToast(t('已经是第一页')); return; }
  if (n >= reader.total) { showToast(t('已经是最后一页')); return; }
  if (reader.mode === 'scroll') {
    reader.idx = n; updateIndicator(); scrollToBlock(n, delta < 0 ? 'bottom' : undefined);
    return;
  }
  showPage(n);
}

function closeReader() {
  reportReading(true);         // 退出兜底：把最终位置落盘（进度同步跨端）
  reader.open = false;
  const r = $('#reader');
  if (r) r.classList.add('hidden');
  const m = $('#rdMedia');
  if (m && m.tagName === 'VIDEO') { m.pause(); m.removeAttribute('src'); }
}
