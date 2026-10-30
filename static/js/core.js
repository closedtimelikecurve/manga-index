/* 本地同人志文库 前端 · core.js
   基础工具、全局 state、API 封装、启动与刷新、阅读状态同步
   3.6.84 从 static/app.js 拆出：按顶层区块切分，仍是 classic script，
   与其余分片共享同一个全局词法环境（顺序加载，勿调整 index.html 里的 <script> 次序）。 */
'use strict';

/* 本地同人志文库 前端（原生 JS，前后端分离，后端 Flask API） */
'use strict';
const $ = s => document.querySelector(s);
const enc = encodeURIComponent;

/** 空安全事件绑定（3.6.125）。
 *  事故：3.7.78 删掉设置弹窗 `#modal` 后，`$('#btnPair').addEventListener` 在元素不存在时
 *  返回 null → 抛 TypeError → **同文件后面所有绑定整段不执行**（二维码与别名登记双双打不开）。
 *  凡是"可能不在当前 DOM 里"的元素一律走这里，不要直接 `$('#x').addEventListener`。 */
function on(sel, ev, fn) {
  const el = $(sel);
  if (el) el.addEventListener(ev, fn);
  return el;
}

const state = {
  lib: null, config: null, filter: '',
  view: 'home',            // home | circle | tag | tags | uncat | import | info
  circleName: null, tagType: null, tagName: null,
  circleGroup: null,      // 社团详情 group 对象（搜索重渲染需要 workCount/coverMtime）
  circleWorks: null, tagWorks: null,
  uncatGroup: null, uncatWorks: null,
  tagReturn: null,         // 从标签云页进入 #/tag/… 时记录返回目标
  themeReturn: null,       // 3.6.124 进入 #/theme 前的视图（返回键原路回）
  langReturn: null,        // 3.6.124 进入 #/lang 前的视图
  themeGalleryReturn: null,// 3.6.124 图库三级页固定回 #/theme
  importResults: null,     // 最近一次导入结果（自动刷新后恢复显示）
};

/* ---------- 基础工具 ---------- */
const getToken = () => localStorage.getItem('djc_token') || '';

async function api(path, opts) {
  opts = opts || {};
  opts.headers = Object.assign({}, opts.headers);
  const tk = getToken();
  if (tk) opts.headers['X-Token'] = tk;
  const res = await fetch(path, opts);
  if (res.status === 401) showTokenModal();
  const ct = res.headers.get('content-type') || '';
  if (ct.includes('application/json')) {
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || ('HTTP ' + res.status));
    return data;
  }
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return res;
}

function esc(s) {
  // 3.6.139：转义后再把文件名实体 `&#124;`（旧库对 Windows 禁用字符 | 的编码）还原成 |，
  // 所有 innerHTML 展示路径统一修复。标识符（dataset/hash→API 参数）一律走 dataset 属性
  // 或 enc()，从不经过 esc；作者/社团/标签名实测 0 实体（works.name 独有，见 meta.db）。
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))
    .replace(/&amp;#124;/g, '|');
}

// 属性/纯文本场景（el.title 等 property 赋值不解析实体）的展示名解码；标识符勿用。
function dispName(s) {
  return String(s).replace(/&#124;/g, '|');
}

function showTokenModal() {
  if ($('#tokenModal')) return;
  const el = document.createElement('div');
  el.id = 'tokenModal';
  el.className = 'modal';
  el.innerHTML =
    '<div class="modal-card">' +
      '<h3><!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-lock" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <rect width="18" height="11" x="3" y="11" rx="2" ry="2" /> <path d="M7 11V7a5 5 0 0 1 10 0v4" /> </svg> ' + esc(t('访问令牌')) + '</h3>' +
      '<p style="color:var(--muted);font-size:12.5px">' + esc(t('该文库已开启远程访问保护，请输入访问令牌（与服务端 config.json 的 token 一致）。')) + '</p>' +
      '<input id="tokenInput" type="password" placeholder="' + esc(t('访问令牌')) + '" style="width:100%">' +
      '<div class="modal-acts">' +
        '<button id="tokenSave" class="primary">' + esc(t('保存并刷新')) + '</button>' +
      '</div>' +
    '</div>';
  document.body.appendChild(el);
  $('#tokenSave').addEventListener('click', () => {
    const v = $('#tokenInput').value.trim();
    if (!v) return;
    localStorage.setItem('djc_token', v);
    location.reload();
  });
}

function coverUrl(group, work, ver) {
  return '/cover?group=' + enc(group) + '&work=' + enc(work) +
         (ver ? '&v=' + enc(String(ver)) : '') +
         (state.lib ? '&t=' + (state.lib.scanned_at | 0) : '') +
         /* 3.6.161 内测模式：只是换缓存键，服务端不解析它（见 panel/safecover.py）。
            开关状态一变 URL 就变，浏览器缓存与 Coil 缓存都不会继续用旧封面。 */
         (state.config && state.config.safeCovers ? '&sc=1' : '') +
         (getToken() ? '&token=' + enc(getToken()) : '');
}
/* 3.6.163：给「非 /cover 的封面地址」补内测缓存键。
   探针与清单爬虫的封面走 /api/crawl/probe/cover，真实图响应头是 max-age=604800（7 天），
   而它们的 URL 原先不随内测开关变化——开关打开后，之前看过的封面仍从浏览器缓存取真图，
   表现就是"部分作品的封面没换"。让 URL 跟着开关走即可（服务端不解析 sc，只当缓存键）。 */
function safeCoverUrl(src) {
  if (!src) return src;
  if (!(state.config && state.config.safeCovers)) return src;
  return src + (src.indexOf('?') < 0 ? '?' : '&') + 'sc=1';
}
function pageUrl(group, work, n, ver) {
  return '/page?group=' + enc(group) + '&work=' + enc(work) + '&n=' + n +
         (ver ? '&v=' + enc(String(ver)) : '') +
         (state.lib ? '&t=' + (state.lib.scanned_at | 0) : '') +
         (getToken() ? '&token=' + enc(getToken()) : '');
}
/* ---------- 社团排序（客户端排序，切换即时生效，不重新请求） ----------
   updated=最近**入库**（作品数增加才前进，默认）/ created=档案创建时间 / count=作品数量 /
   size=占用空间（查重用）；desc 新→旧、多→少（默认），asc 反之，同值按名称升序补位。
   洗版不推进 updated 是刻意设计（导入日志会明确提醒）。服务端 sort_groups() 同语义。
   3.6.151：**删掉 touched（最近更新）档**——它与 updated 只差"洗版算不算"，两档并排
   反而让人分不清；存量的 touched 一律按 updated 处理。 */
const SORT_KEY = 'circle_sort', SORT_ASC_KEY = 'circle_sort_asc';
function sortMode() {
  const m = localStorage.getItem(SORT_KEY) || 'updated';
  // touched（3.6.151 删）与 size（3.6.166 删）都按 updated 处理——旧偏好不会卡住排序
  return (m === 'touched' || m === 'size') ? 'updated' : m;
}
function sortIsAsc() { return localStorage.getItem(SORT_ASC_KEY) === '1'; }
function sortGroups(list) {
  const m = sortMode(), asc = sortIsAsc();
  // 3.6.154：时间档按**整秒**比较——首扫同一批新社团的「最近入库」只差几微秒，
  // 不取整的话"同值按名字"的补位永远不会生效，顺序会随扫描顺序抖（与服务端同口径）。
  // 3.6.166：社团排序**没有**文件大小档了（用户要求：大小只在分区内部按作品排）。
  // 存量的 'size' 偏好一律按 updated 处理，旧缓存不会因此排错。
  const key = g => m === 'created' ? Math.round(g.createdAt || 0)
                 : m === 'count' ? (g.workCount || 0)
                 : Math.round(g.updatedAt || 0);
  return list.slice().sort((a, b) => {
    const ka = key(a), kb = key(b);
    if (ka !== kb) return asc ? ka - kb : kb - ka;
    return String(a.name).localeCompare(String(b.name), 'zh-Hans-CN');
  });
}
function sortDirLabel() {
  // 3.6.151：**箭头固定朝下**（表示列表从上到下的方向），只有文字随正/倒序变。
  // 用户明确要求：箭头跟着翻转会让人以为排序维度变了，实际只是顺序反过来。
  const asc = sortIsAsc(), m = sortMode();
  if (m === 'count') return asc ? t('↓ 由少到多') : t('↓ 由多到少');
  return asc ? t('↓ 由旧到新') : t('↓ 由新到旧');
}
function sortBarHtml() {
  const m = sortMode();
  const modes = [['updated', t('最近入库')], ['created', t('创建时间')],
                 ['count', t('作品数量')]];
  return '<div class="sort-bar" id="sortBar">' +
    '<span class="sort-label">' + esc(t('排序')) + '</span>' +
    modes.map(([k, label]) =>
      '<button type="button" data-sort="' + k + '" class="' + (m === k ? 'on' : '') + '">' +
      label + '</button>').join('') +
    '<button type="button" data-sortdir="1" class="dir on" title="' + esc(t('点击切换正序 / 倒序')) + '">' +
    sortDirLabel() + '</button>' +
    '</div>';
}

/* ---------- 作品列表排序（3.6.151）----------
   社团页 / 同人区（原作、展会…）/ 画师页三处作品列表共用同一套偏好与交互：
   time=入库时间（默认，added_at）/ size=**文件大小**（查重用：重复下载的作品体积相近，
   排在一起一眼看得出）/ name=名称。
   箭头固定朝下（与社团排序同一条要求），只有文字随正/倒序变。 */
const WORK_SORT_KEY = 'work_sort', WORK_ASC_KEY = 'work_sort_asc';
function workSortMode() { return localStorage.getItem(WORK_SORT_KEY) || 'time'; }
function workIsAsc() { return localStorage.getItem(WORK_ASC_KEY) === '1'; }

/** 排序作品列表。`get` 适配两种入参形态：直接的 work 对象，或 {work, group} 包装。 */
function sortWorks(list, get) {
  const m = workSortMode(), asc = workIsAsc();
  const w = get || (x => x);
  // 3.6.152：画师页的作品对象没有 name 字段（作品名在 work 上），原先 byName 拿到的
  // 是 undefined 比 undefined 恒等于 0——「名称」档点了什么也不变（文案却变了）。
  const nm = x => String(w(x).name || w(x).work || '');
  const byName = (a, b) => nm(a).localeCompare(nm(b), 'zh-Hans-CN');
  if (m === 'name') {
    const out = list.slice().sort(byName);
    return asc ? out : out.reverse();
  }
  const key = x => m === 'size' ? (w(x).size || 0) : (w(x).added_at || 0);
  return list.slice().sort((a, b) => {
    const ka = key(a), kb = key(b);
    if (ka !== kb) return asc ? ka - kb : kb - ka;
    return byName(a, b);
  });
}

function workDirLabel() {
  const asc = workIsAsc(), m = workSortMode();
  if (m === 'size') return asc ? t('↓ 由小到大') : t('↓ 由大到小');
  if (m === 'name') return asc ? t('↓ A→Z') : t('↓ Z→A');
  return asc ? t('↓ 由旧到新') : t('↓ 由新到旧');
}

function workSortBarHtml() {
  const m = workSortMode();
  const modes = [['time', t('时间')], ['size', t('文件大小')], ['name', t('名称')]];
  return '<div class="sort-bar" id="workSortBar">' +
    '<span class="sort-label">' + esc(t('排序')) + '</span>' +
    modes.map(([k, label]) =>
      '<button type="button" data-wsort="' + k + '" class="' + (m === k ? 'on' : '') + '">' +
      label + '</button>').join('') +
    '<button type="button" data-wsortdir="1" class="dir on" title="' + esc(t('点击切换正序 / 倒序')) + '">' +
    workDirLabel() + '</button>' +
    '</div>';
}

/** 排序偏好变了：只重渲染当前视图（数据已在 state 里，不重新请求）。 */
function rerenderWorksView() {
  if (state.view === 'circle' && state.circleGroup) {
    renderCircle(state.circleGroup, state.circleWorks || []);
  } else if (state.view === 'artist' && state.artistData) {
    renderArtist(state.artistData);
  } else if (state.view === 'tag' && state.tagWorks) {
    renderTag(state.tagType, state.tagName, state.tagWorks);
  }
}

function fmtDate(ts) {
  if (!ts) return '';
  try {
    return new Date(ts * 1000).toLocaleDateString('zh-CN');
  } catch (e) { return ''; }
}

let toastTimer = null;
function showToast(msg) {
  const t = $('#toast');
  t.textContent = msg; t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 2600);
}

/* ---------- 数据 ---------- */
function isImportOnly() {
  return !!(state.config && state.config.importOnly);
}

/* ---------- 面板代码已更新但进程还是旧的 → 顶部提示 + 一键重启 ----------
   Python 只在启动时加载代码，改完 app.py 不重启就不生效（"改了却没生效"栽过两次）。
   服务端 /api/config 的 needsRestart 用"进程启动时刻 vs app.py mtime"判断。 */
let restartPolling = false;
function renderRestartBar() {
  const c = state.config || {};
  let el = $('#restartBar');
  if (!c.needsRestart) { if (el) el.remove(); return; }
  if (!el) {
    el = document.createElement('div');
    el.id = 'restartBar';
    el.style.cssText = 'position:sticky;top:0;z-index:80;display:flex;gap:12px;align-items:center;' +
      'justify-content:center;flex-wrap:wrap;padding:9px 14px;font-size:13px;color:#fff;' +
      'background:linear-gradient(90deg,#7a2f6a,#8a4a1f);border-bottom:1px solid #ffffff2e';
    document.body.insertBefore(el, document.body.firstChild);
  }
  el.innerHTML =
    '<span>' + esc(tf('⚠ 面板代码已更新（磁盘 v%1 / 运行中 v%2），需要重启面板才生效', c.diskVersion || '?', c.version || '?')) + '</span>' +
    '<button id="btnRestartPanel" style="padding:4px 14px;border-radius:999px;cursor:pointer;' +
    'border:1px solid #ffffff88;background:#ffffff26;color:#fff;font-size:13px">' + esc(t('立即重启面板')) + '</button>';
  const btn = $('#btnRestartPanel');
  if (btn) btn.addEventListener('click', restartPanel);
}
async function restartPanel() {
  if (restartPolling) return;
  const el = $('#restartBar');
  try {
    const d = await api('/api/panel/restart', { method: 'POST' });
    showToast(d.message || t('正在重启…'));
  } catch (e) { showToast(tf('%1失败：%2', t('重启'), e.message)); return; }
  restartPolling = true;
  if (el) el.innerHTML = '<span>' + esc(t('⏳ 面板正在重启，稍候自动刷新…')) + '</span>';
  for (let i = 0; i < 40; i++) {
    await new Promise(r => setTimeout(r, 1000));
    try { await api('/api/config'); location.reload(); return; }
    catch (e) { /* 还没起来，继续等 */ }
  }
  restartPolling = false;
  if (el) {
    el.innerHTML = '<span>' + esc(t('⚠ 重启后一直无响应：请用 Index.exe 重新启动面板（或看控制台报错）')) + '</span>';
  }
}

async function init() {
  try {
    state.config = await api('/api/config');
    renderRestartBar();
    // 3.7.56：启动**全局**进度看护——分区爬取跑在服务端线程里，界面只是观察者：
    // 无论当前停在哪个视图，右下角都有浮标，离开爬虫页也不会"失联"。
    if (typeof probeWatchStart === 'function') probeWatchStart();
    // 3.7.58：五个爬取任务同样跑在服务端，离开页面也要能看到"还在跑"
    if (typeof crawlWatchStart === 'function') crawlWatchStart();
    const name = state.config.name || t('我的同人志文库');
    document.title = name + t(' - 本地文库');
    if (state.config.rarAvailable === false) $('#rarNote').classList.remove('hidden');
    if (state.config.pilAvailable === false) $('#pilNote').classList.remove('hidden');
  } catch (e) {
    showToast(tf('无法连接后端：%1', e.message));
    return;
  }
  if (isImportOnly()) {
    // 仅导入模式：不加载文库列表，只渲染「导入文件」与「爬虫管理」两个界面
    document.body.classList.add('import-mode');
    if (!location.hash.startsWith('#/import') && !location.hash.startsWith('#/crawl')) {
      location.hash = '#/import';
    } else route();
    return;
  }
  await refresh(false);
}

let scanPollTimer = null;

async function refresh(force) {
  clearTimeout(scanPollTimer);
  $('#statusText').textContent = t('正在扫描…');
  try {
    const data = await api('/api/library' + (force ? '?refresh=1' : ''));
    if (data.status === 'scanning') {
      // 首次扫描进行中：轮询进度，1 秒后重取（后端此时不同步阻塞）
      $('#statusText').textContent = tf('正在扫描文库… %1/%2', data.done || 0, data.total || 0);
      scanPollTimer = setTimeout(() => refresh(false), 1000);
      return;
    }
    state.lib = data;
    route();
    updateStatus();
    // 3.1/3.2 阅读消费端：已读/新作品状态到达后重渲染一次（角标是增强，失败静默）
    loadReadingHub().then(() => { if (readingHub.loaded) route(); });
  } catch (e) {
    $('#statusText').textContent = t('扫描失败');
    showToast(tf('%1失败：%2', t('扫描'), e.message));
  }
}

/* ---------- 3.1/3.2 阅读消费端：已读角标 / 新作品标亮 / 阅读进度同步 ---------- */
const readingHub = { states: {}, newKeys: new Set(), loaded: false };

async function loadReadingHub() {
  try {
    // mark-seen 先行：返回上一次访问基线（首次为 0 = 没有基线，不把全库当新作品）
    const ms = await api('/api/reading/mark-seen', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const d = await api('/api/reading/summary?since=' + (ms.previous || 0));
    readingHub.states = d.states || {};
    readingHub.newKeys = new Set(d.new_keys || []);
    readingHub.loaded = true;
  } catch (e) { /* 角标失败不影响浏览 */ }
}

function rdStateOf(group, work) { return readingHub.states[group + '/' + work] || null; }
function isNewWork(group, work) { return readingHub.newKeys.has(group + '/' + work); }

/* 阅读进度上报（节流 4s；翻到最后一页置已读，往回翻不清已读；关阅读器时兜底一次） */
const rdReport = { at: 0, timer: null };
function reportReading(force) {
  if (!reader.open || !reader.group) return;
  const now = Date.now();
  const finished = reader.idx >= reader.total - 1;
  if (!force && !finished && now - rdReport.at < 4000) return;
  rdReport.at = now;
  const body = { key: reader.group + '/' + reader.work, last_page: reader.idx };
  if (finished) body.finished = true;
  api('/api/reading/state', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body) }).then(() => {
      // 本地即时更新角标，不必等重拉
      readingHub.states[body.key] = { p: reader.idx, f: finished || (readingHub.states[body.key] || {}).f === true };
    }).catch(() => {});
}

function updateStatus() {
  if (!state.lib) return;
  const nW = state.lib.groups.reduce((n, g) => n + g.workCount, 0);
  $('#statusText').textContent = tf('根目录：%1 ｜ %2 个社团 / %3 部作品 · 扫描 %4 ms',
    state.config ? state.config.root : '', state.lib.groups.length, nW, state.lib.scan_ms);
  renderRestartBar();          // 每次刷新都核对一次"代码是否已更新但没重启"
}
