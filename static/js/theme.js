/* 本地同人志文库 前端 · theme.js
   3.6.115：主题定制——预设配色 / 自定义主副色（localStorage `djc_theme`）+ 主题背景图。
   3.6.116：升为独立二级界面 `#/theme`（用户要求：不再挤在抽屉里），背景图改「本机图库」：
   图存在服务端 `_state/theme_gallery/`（`/api/theme/gallery`），可选用 / 添加 / 删除 / 恢复默认，
   与 APP 端共用同一份图库。取色用浏览器原生 `input[type=color]`
   （手机上点开就是系统取色盘；3.6.115 已如此，无需手填十六进制）。
   3.6.123：新增「自定义」档——只有自定义档才渲染取色器，预设档主副色只读展示；
   图库请求带 `client=web`（选用按端记录：电脑与手机可选不同图，图库本身共用一份）。
   应用方式 = documentElement 上 setProperty 覆盖 --accent/--accent2/--bg-image。
   仍是 classic script（顺序加载，勿调整 index.html 次序）。 */
'use strict';

// 3.6.143 函数化：顶层 const 会固化 t()（crawlJobStates 同坑第六例）
function themePresets() {
  return [
  ['neon', t('霓虹粉'), '#ff3df2', '#b06bff'],
  ['cyber', t('赛博蓝'), '#4dc9ff', '#7f9cff'],
  ['jade', t('翡翠绿'), '#3dffb8', '#43c6a8'],
  ['amber', t('暖橙'), '#ffb347', '#ff8a5f'],
  ['crimson', t('绯红'), '#ff5e7e', '#ff3d6e'],
  ['violet', t('紫罗兰'), '#b06bff', '#7f5cff'],
  ];
}
const THEME_DEFAULT = ['#ff3df2', '#b06bff'];   // 与 style.css:root 的 --accent/--accent2 一致
const WEB_CLIENT = 'web';                       // 本端的槽位标识（选用按端记录）
const THEME_BG_ALPHA_DEFAULT = 0.20;            // 与 style.css 的 body::before 默认一致（3.6.131）

function themeGet() {
  try { return JSON.parse(localStorage.getItem('djc_theme')) || {}; }
  catch (e) { return {}; }
}

/** @param preset 档 id（6 个预设之一 / 'custom'）——颜色仍由 accent/accent2 决定。
 *  3.6.131：**必须合并**而非整体覆盖——以前这里直接写新对象，换一次配色就会把
 *  背景不透明度（bgOpacity）一起抹掉。 */
function themeSave(preset, accent, accent2) {
  const th = themeGet();
  th.preset = preset;
  th.accent = accent;
  th.accent2 = accent2;
  localStorage.setItem('djc_theme', JSON.stringify(th));
}

/** 背景图不透明度（0..1）：没存过 → 默认值；越界一律夹回（老数据/手改 localStorage 都可能坏）。 */
function themeBgAlpha() {
  const v = themeGet().bgOpacity;
  return (typeof v === 'number' && isFinite(v)) ? Math.max(0, Math.min(1, v)) : THEME_BG_ALPHA_DEFAULT;
}

/** 只改不透明度并立即应用（拖动中调它，实时可见）。 */
function themeSaveBgAlpha(v) {
  const th = themeGet();
  th.bgOpacity = Math.max(0, Math.min(1, v));
  localStorage.setItem('djc_theme', JSON.stringify(th));
  themeApplyBgAlpha();
}

function themeApplyBgAlpha() {
  document.documentElement.style.setProperty('--bg-opacity', String(themeBgAlpha()));
}

/** 当前档：新数据直读；老数据按色对推断；非预设色 → 自定义；全无 → 霓虹粉（= CSS 默认）。 */
function themePresetId() {
  const th = themeGet();
  if (th.preset) return th.preset;
  const hit = themePresets().find(p => p[2] === th.accent && p[3] === th.accent2);
  if (hit) return hit[0];
  if (th.accent || th.accent2) return 'custom';
  return 'neon';
}

function themeBgVersion() { return localStorage.getItem('djc_theme_bg_v') || ''; }

/** 换过背景图就推进版本键：`--bg-image` 的 URL 一变，浏览器与 CSS 缓存自然失效。 */
function themeBumpBg() { localStorage.setItem('djc_theme_bg_v', String(Date.now())); }

/** 当前选用的图库文件名（服务端 active 的镜像；只用于「纯黑」这类无图档的渲染判定）。 */
let themeActiveName = '';

/** 内置「纯黑」条目：选它 = 不要背景图，而不是"把一张黑图半透明铺上去"。 */
const THEME_BLACK_ITEM = 'b00_black.jpg';

function themeApplyBlack() {
  document.body.classList.toggle('bg-black', themeActiveName === THEME_BLACK_ITEM);
}

/** 把当前偏好落到 :root（颜色 + 背景图）。 */
function themeApply() {
  const th = themeGet();
  const rootStyle = document.documentElement.style;
  if (th.accent) rootStyle.setProperty('--accent', th.accent);
  else rootStyle.removeProperty('--accent');
  if (th.accent2) rootStyle.setProperty('--accent2', th.accent2);
  else rootStyle.removeProperty('--accent2');
  const v = themeBgVersion();
  rootStyle.setProperty('--bg-image',
    'url("/api/theme/bg?client=' + WEB_CLIENT + (v ? '&v=' + encodeURIComponent(v) : '') + '")');
  themeApplyBgAlpha();       // 3.6.131：不透明度也是主题的一部分
  themeApplyBlack();
  themeRefreshHero();
}

/** 首页横幅是独立的 <img>（不是 CSS 背景），换图/恢复默认后必须手动换 src，
 *  否则只有主题页的预览变了、首页纹丝不动（用户需求：横幅切换没生效）。 */
function themeRefreshHero() {
  const img = document.querySelector('.hero-img');
  if (img) img.src = '/api/theme/hero?v=' + Date.now();
}

/* ---------- 主题二级界面（#/theme） ---------- */

/** 自定义档：原生取色器（change 即落盘并应用）。 */
function themeSwatchInput(id, label, value, hexId) {
  return '<label class="theme-swatch"><span>' + esc(label) + '</span>' +
    '<input type="color" id="' + id + '" value="' + esc(value) + '">' +
    '<b id="' + hexId + '">' + esc(value) + '</b></label>';
}

/** 预设档：只读展示（色块 + 十六进制），不给 input —— 预设就是预设，不让人改。 */
function themeSwatchRO(label, value) {
  return '<div class="theme-swatch ro"><span>' + esc(label) + '</span>' +
    '<i class="theme-dot" style="background:' + esc(value) + '"></i>' +
    '<b>' + esc(value) + '</b></div>';
}

function renderThemeView() {
  hideEmpty(); hideGridEmpty();
  const cur = themeGet();
  const preset = themePresetId();
  const custom = preset === 'custom';
  const accent = cur.accent || THEME_DEFAULT[0];
  const accent2 = cur.accent2 || THEME_DEFAULT[1];
  $('#viewHead').innerHTML =
    '<button class="back" id="btnBack">← ' + esc(t('返回')) + '</button>' +
    '<h2>🎨 ' + esc(t('主题')) + '</h2>' +
    '<span class="sub">' + esc(t('配色与背景图·双端同步')) + '</span>';
  const grid = $('#grid');
  grid.className = 'grid grid-list';
  grid.innerHTML =
    '<div class="panel theme-page">' +
      '<h3 class="tp-h">' + esc(t('主题色')) + '</h3>' +
      '<div class="theme-presets">' + themePresets().map(p =>
        '<button type="button" class="theme-preset' + (preset === p[0] ? ' on' : '') +
        '" data-preset="' + p[0] + '" data-accent="' + p[2] + '" data-accent2="' + p[3] + '">' +
        '<i style="background:linear-gradient(135deg,' + p[2] + ',' + p[3] + ')"></i>' +
        '<span>' + esc(t(p[1])) + '</span></button>').join('') +
        '<button type="button" class="theme-preset theme-preset--custom' + (custom ? ' on' : '') +
        '" data-preset="custom"><i></i><span>' + esc(t('自定义')) + '</span></button>' +
      '</div>' +
      '<div class="theme-custom">' +
        (custom
          ? themeSwatchInput('themeAccent', t('主色'), accent, 'themeAccentHex') +
            themeSwatchInput('themeAccent2', t('副色'), accent2, 'themeAccent2Hex')
          : themeSwatchRO(t('主色'), accent) + themeSwatchRO(t('副色'), accent2)) +
      '</div>' +
      '<p class="sub theme-hint">' + esc(custom
        ? t('拖动色块调整主色与副色，选完立即生效')
        : t('预设配色不可单独调整，选择「自定义」后可微调')) + '</p>' +
      '<h3 class="tp-h">' + esc(t('背景图')) + '</h3>' +
      '<div class="theme-bg-cur" id="themeBgCur"><span class="sub">' + esc(t('加载中…')) + '</span></div>' +
      '<div class="theme-bg-row">' +
        '<button type="button" id="themeBgOpenGal" class="btn-pill">🖼 ' + esc(t('打开图库')) + '</button>' +
        '<button type="button" id="themeBgReset">' + esc(t('恢复默认')) + '</button>' +
      '</div>' +
      '<h3 class="tp-h">' + esc(t('背景不透明度')) + '</h3>' +
      '<div class="theme-alpha">' +
        '<input type="range" id="themeBgAlpha" min="0" max="100" step="1" value="' +
          Math.round(themeBgAlpha() * 100) + '">' +
        '<b id="themeBgAlphaVal">' + Math.round(themeBgAlpha() * 100) + '%</b>' +
      '</div>' +
      '<span class="sub theme-alpha-hint">' + esc(t('0% 只留底色，100% 显示原图')) + '</span>' +
      '<h3 class="tp-h">' + esc(t('首页横幅')) + '</h3>' +
      '<div class="theme-bg-cur" id="themeHeroCur"><span class="sub">' + esc(t('加载中…')) + '</span></div>' +
      '<div class="theme-bg-row">' +
        '<button type="button" id="themeHeroOpenGal">🖼 ' + esc(t('打开图库')) + '</button>' +
        '<button type="button" id="themeHeroReset">' + esc(t('恢复默认')) + '</button>' +
      '</div>' +
    '</div>';
  bindThemeView();
  themePaintSlots();            // 3.6.118：主题页只画双槽预览，网格在三级图库页
}

/** 拉图库列表一次，把双槽"当前启用"画出来（主题页进入时；背景是本端槽位）。 */
async function themePaintSlots() {
  try {
    const d = await api('/api/theme/gallery?client=' + WEB_CLIENT);
    themePaintCurrent(d.active || '');
    themePaintHero(d.heroActive || '');
  } catch (e) { themePaintCurrent(''); themePaintHero(''); }
}

function bindThemeView() {
  $('.theme-page').querySelectorAll('.theme-preset').forEach(b => b.addEventListener('click', () => {
    const id = b.getAttribute('data-preset');
    if (id === 'custom') {                       // 进自定义：保留当前色，取色器从当前值起步
      const cur = themeGet();
      themeSave('custom', cur.accent || THEME_DEFAULT[0], cur.accent2 || THEME_DEFAULT[1]);
    } else {
      themeSave(id, b.getAttribute('data-accent'), b.getAttribute('data-accent2'));
    }
    themeApply();
    renderThemeView();
  }));
  themeBindSwatch('themeAccent', 'themeAccentHex');
  themeBindSwatch('themeAccent2', 'themeAccent2Hex');
  $('#themeBgOpenGal').addEventListener('click', () => { location.hash = '#/theme/gallery'; });
  $('#themeHeroOpenGal').addEventListener('click', () => { location.hash = '#/theme/gallery?hero'; });
  $('#themeBgReset').addEventListener('click', themeResetBg);
  $('#themeHeroReset').addEventListener('click', themeResetHero);
  // 3.6.131：拖动实时改 --bg-opacity（所见即所得），松手才写 localStorage
  const alpha = $('#themeBgAlpha');
  if (alpha) {
    alpha.addEventListener('input', () => {
      document.documentElement.style.setProperty('--bg-opacity',
        String(Math.max(0, Math.min(1, alpha.value / 100))));
      const val = $('#themeBgAlphaVal');
      if (val) val.textContent = alpha.value + '%';
    });
    alpha.addEventListener('change', () => themeSaveBgAlpha(alpha.value / 100));
  }
}

/** 原生取色器：change 即落盘并应用；改色一律归入「自定义」档（预设被改动就不再是那个预设）。 */
function themeBindSwatch(inputId, hexId) {
  const el = $('#' + inputId);
  if (!el) return;
  el.addEventListener('input', () => { const b = $('#' + hexId); if (b) b.textContent = el.value; });
  el.addEventListener('change', () => {
    const cur = themeGet();
    const accent = inputId === 'themeAccent' ? el.value : (cur.accent || THEME_DEFAULT[0]);
    const accent2 = inputId === 'themeAccent' ? (cur.accent2 || THEME_DEFAULT[1]) : el.value;
    themeSave('custom', accent, accent2);
    themeApply();
  });
}

function themeCellHtml(it, active) {
  const on = it.name === active;
  const title = it.title ? t(it.title) : '';
  return '<div class="theme-cell' + (on ? ' on' : '') + '" data-name="' + esc(it.name) +
    '" title="' + esc(title || t('点击选用')) + '">' +
    '<img src="/api/theme/gallery/' + encodeURIComponent(it.name) + '?v=' + Math.round(it.mtime || 0) +
      '" alt="' + esc(title) + '" loading="lazy">' +
    (it.builtin ? '<span class="theme-cell-builtin">' + esc(t('内置')) + '</span>' : '') +
    (on ? '<span class="theme-cell-tag">' + esc(t('使用中')) + '</span>' : '') +
    (it.builtin ? '' :
      '<button type="button" class="theme-cell-del" data-del="' + esc(it.name) + '" title="' +
      esc(t('删除')) + '">✕</button>') + '</div>';
}

/** 拉图库列表并渲染；"当前启用"以**本端槽位**为准（图库共用、选用各记各的）。 */
async function themeLoadGallery() {
  const box = $('#themeGallery');
  if (!box) return;
  try {
    const d = await api('/api/theme/gallery?client=' + WEB_CLIENT);
    const items = d.items || [];
    const onGalleryPage = state.view === 'themeGallery';
    const active = onGalleryPage
      ? (themeGallery.slot === 'hero' ? (d.heroActive || '') : (d.active || ''))
      : (d.active || '');
    box.innerHTML = items.length
      ? items.map(it => themeCellHtml(it, active)).join('')
      : '<span class="sub">' + esc(t('图库还是空的：点「添加图片」把电脑上的图存进来')) + '</span>';
    if (!onGalleryPage) themePaintCurrent(active);
    box.querySelectorAll('.theme-cell').forEach(cell => {
      cell.addEventListener('click', ev => {
        if (ev.target.closest('.theme-cell-del')) return;
        themeSelect(cell.getAttribute('data-name'), themeGallerySlot());
      });
    });
    box.querySelectorAll('.theme-cell-del').forEach(b => b.addEventListener('click', ev => {
      ev.stopPropagation();
      themeDelete(b.getAttribute('data-del'));
    }));
  } catch (e) {
    box.innerHTML = '<span class="sub">' + esc(t('加载失败') + '：' + e.message) + '</span>';
  }
}

/** 「当前背景」预览行：本端选用的那张，或内置默认图。 */
function themePaintCurrent(active) {
  themeActiveName = active || '';       // 先记下来：纯黑判定与有没有预览容器无关
  themeApplyBlack();
  const box = $('#themeBgCur');
  if (!box) return;
  box.innerHTML = '<img src="/api/theme/bg?client=' + WEB_CLIENT + '&v=' + Date.now() + '" alt="">' +
    '<span>' + (active ? esc(t('使用中') + '：' + active) : esc(t('默认背景图'))) + '</span>';
}

/** 3.6.118 「当前横幅」预览行（与背景预览同构）。 */
function themePaintHero(active) {
  const box = $('#themeHeroCur');
  if (!box) return;
  box.innerHTML = '<img src="/api/theme/hero?v=' + Date.now() + '" alt="">' +
    '<span>' + (active ? esc(t('使用中') + '：' + active) : esc(t('默认横幅'))) + '</span>';
}

async function themeResetHero() {
  try {
    await api('/api/theme/hero', { method: 'DELETE' });
    themePaintHero('');
    themeRefreshHero();
    showToast(t('完成'));
  } catch (e) { showToast(t('失败') + '：' + e.message); }
}

async function themeSelect(name, slot) {
  // 3.6.118 slot：'bg'（默认，背景图）/ 'hero'（首页横幅）——三级图库页按当前模式应用
  // 3.6.123 背景按端记录：body 带 client=web，只改本端槽位，不动 APP 的选择。
  const target = slot === 'hero' ? '/api/theme/hero' : '/api/theme/bg';
  const body = slot === 'hero' ? { name: name } : { name: name, client: WEB_CLIENT };
  try {
    await api(target, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (slot !== 'hero') { themeActiveName = name; themeBumpBg(); themeApply(); }
    else { themeRefreshHero(); themePaintHero(name); }   // 横幅：首页 <img> 立刻换
    if (state.view === 'themeGallery') themeLoadGallery();
    showToast(t('完成'));
  } catch (e) { showToast(t('失败') + '：' + e.message); }
}

async function themeDelete(name) {
  if (!confirm(t('要从图库删掉这张图吗？') + '\n\n' + name)) return;
  try {
    await api('/api/theme/gallery/' + encodeURIComponent(name), { method: 'DELETE' });
    themeBumpBg();
    themeApply();
    themeLoadGallery();
    showToast(t('完成'));
  } catch (e) { showToast(t('失败') + '：' + e.message); }
}

async function themeUploadFile(file) {
  if (file.size > 8 * 1024 * 1024) { showToast(t('失败') + '：> 8MB'); return; }
  try {
    const buf = await file.arrayBuffer();
    const d = await api('/api/theme/gallery', {
      method: 'POST',
      headers: { 'Content-Type': file.type || 'image/jpeg' },
      body: buf,
    });
    showToast(t('完成'));
    if (d && d.name) await themeSelect(d.name, themeGallerySlot());
    else themeLoadGallery();
  } catch (e) { showToast(t('失败') + '：' + e.message); }
}

async function themeResetBg() {
  try {
    await api('/api/theme/bg?client=' + WEB_CLIENT, { method: 'DELETE' });
    themeActiveName = '';
    themeBumpBg();
    themeApply();
    themePaintCurrent('');
    themeLoadGallery();
    showToast(t('完成'));
  } catch (e) { showToast(t('失败') + '：' + e.message); }
}

themeApply();

/* ---------- 3.6.118 主题图库三级界面（#/theme/gallery）：自由增删改查 + 双槽应用 ---------- */

const themeGallery = { slot: 'bg' };   // 'bg' = 设为背景图；'hero' = 设为首页横幅

function themeGallerySlot() { return state.view === 'themeGallery' ? themeGallery.slot : 'bg'; }

function renderThemeGalleryView(slot) {
  hideEmpty(); hideGridEmpty();
  themeGallery.slot = slot === 'hero' ? 'hero' : 'bg';
  const hero = themeGallery.slot === 'hero';
  $('#viewHead').innerHTML =
    '<button class="back" id="btnBack">← ' + esc(t('返回')) + '</button>' +
    '<h2>🖼 ' + esc(t('图库')) + '</h2>' +
    '<span class="sub">' + esc(t('点击图片将其设为当前选中槽位')) + '</span>';
  const grid = $('#grid');
  grid.className = 'grid grid-list';
  grid.innerHTML =
    '<div class="panel theme-page">' +
      '<div class="theme-gal-mode">' +
        '<span class="sub">' + esc(t('点击图片设为')) + '</span>' +
        '<button type="button" class="gal-mode' + (hero ? '' : ' on') + '" data-slot="bg">🖼 ' + esc(t('背景图')) + '</button>' +
        '<button type="button" class="gal-mode' + (hero ? ' on' : '') + '" data-slot="hero">🌄 ' + esc(t('首页横幅')) + '</button>' +
      '</div>' +
      '<div class="theme-gallery" id="themeGallery"><span class="sub">' + esc(t('加载中…')) + '</span></div>' +
      '<div class="theme-bg-row">' +
        '<input type="file" id="themeGalFile" accept="image/jpeg,image/png,image/webp" class="hidden">' +
        '<button type="type" id="themeGalAdd" class="btn-pill">＋ ' + esc(t('添加图片')) + '</button>' +
      '</div>' +
    '</div>';
  grid.querySelectorAll('.gal-mode').forEach(b => b.addEventListener('click', () => {
    if (themeGallery.slot === b.getAttribute('data-slot')) return;
    renderThemeGalleryView(b.getAttribute('data-slot'));
  }));
  $('#themeGalAdd').addEventListener('click', () => $('#themeGalFile').click());
  $('#themeGalFile').addEventListener('change', e => {
    const f = e.target.files && e.target.files[0];
    if (f) themeUploadFile(f);
    e.target.value = '';
  });
  themeLoadGallery();
}
