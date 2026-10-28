/* 本地同人志文库 前端 · router.js
   hash 路由、滚动记忆、下拉刷新、过滤
   3.6.84 从 static/app.js 拆出：按顶层区块切分，仍是 classic script，
   与其余分片共享同一个全局词法环境（顺序加载，勿调整 index.html 里的 <script> 次序）。 */
'use strict';

/* ---------- 路由 ---------- */
const scrollMem = {};                    // hash → 离开时的 scrollY（往返导航保留位置）
let _lastHash = location.hash;

function rememberScroll() {
  if (_lastHash !== location.hash) {
    if (_lastHash) scrollMem[_lastHash] = window.scrollY;
    _lastHash = location.hash;
  }
}

function restoreScroll() {
  const y = scrollMem[location.hash];
  if (typeof y !== 'number' || y <= 0) return;
  // 3.7.12：异步渲染的视图（社团/画师/标签/搜索/增补信息）DOM 还没填充完时 scrollTo 会被
  // clamp 到 0——这就是「有些路径返回时回到顶部」的根因（同步渲染的首页不受影响）。
  // 改为逐帧重试：内容高度足够（y <= 可滚上限）才精确定位，最多约 1s 兜底。
  let frames = 0;
  const tick = () => {
    const maxY = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
    if (y <= maxY) {
      window.scrollTo(0, y);
      return;                                 // 已就位（图片 loading=lazy 高度由 CSS 比例锁定，不会再漂）
    }
    if (++frames <= 60) requestAnimationFrame(tick);
    else window.scrollTo(0, maxY);            // 兜底：内容始终比目标短，给到当前最大位置
  };
  requestAnimationFrame(tick);
}

/* ---------- 3.7.12 下拉刷新（触屏）：任何界面到顶下拉即重扫文库 ----------
   与 APP 端 PullToRefresh 对齐；桌面端没有 touch 事件，完全不受影响。
   阅读器 overlay 打开时禁用（横向翻页优先，避免与翻页手势打架）。 */
const _ptr = { startY: 0, active: false, pull: 0, refreshing: false };
let _ptrEl = null;

function _ptrEnsure() {
  if (_ptrEl) return _ptrEl;
  _ptrEl = document.createElement('div');
  _ptrEl.id = 'ptr';
  _ptrEl.className = 'hidden';
  document.body.appendChild(_ptrEl);
  return _ptrEl;
}
function _ptrShow(text, dy) {
  const el = _ptrEnsure();
  el.textContent = text;
  el.classList.remove('hidden');
  el.style.transform = typeof dy === 'number'
    ? 'translateY(' + Math.min(dy * 0.45, 64) + 'px)' : '';
}
function _ptrHide() {
  if (_ptrEl) { _ptrEl.classList.add('hidden'); _ptrEl.style.transform = ''; }
}
document.addEventListener('touchstart', e => {
  if (reader.open || e.touches.length !== 1 || window.scrollY > 0) { _ptr.active = false; return; }
  _ptr.startY = e.touches[0].clientY;
  _ptr.active = true;
  _ptr.pull = 0;
}, { passive: true });
document.addEventListener('touchmove', e => {
  if (!_ptr.active || reader.open || _ptr.refreshing) return;
  const dy = e.touches[0].clientY - _ptr.startY;
  if (dy <= 0) {
    if (_ptr.pull > 0) { _ptr.pull = 0; _ptrHide(); }
    return;
  }
  if (window.scrollY > 0) { _ptr.active = false; _ptrHide(); return; }   // 中途又被滚离顶部：放弃
  e.preventDefault();                   // 到顶下拉：拦下橡皮筋，交给刷新指示器
  _ptr.pull = dy;
  _ptrShow(dy >= 64 ? t('⟲ 释放刷新') : t('↓ 下拉刷新'), dy);
}, { passive: false });
document.addEventListener('touchend', () => {
  if (!_ptr.active) return;
  _ptr.active = false;
  const dy = _ptr.pull;
  _ptr.pull = 0;
  if (dy >= 64 && !reader.open && !_ptr.refreshing) {
    _ptr.refreshing = true;
    _ptrShow(t('⟳ 刷新中…'));
    refresh(true).then(_ptrHide, _ptrHide).then(() => { _ptr.refreshing = false; });
  } else _ptrHide();
}, { passive: true });

let _lastRoute = '';      // 上一个 hash：二级页「原路返回」的锚点（3.6.124）

/** 路由入口：先记来源再交给 _routeInner —— 里面有多处早退（仅导入模式），
 *  锚点更新放在 finally 里才不会漏。 */
function route() {
  const prev = _lastRoute;
  try { _routeInner(prev); } finally { _lastRoute = location.hash || '#/'; }
}

function _routeInner(prev) {
  rememberScroll();
  const h = location.hash;
  if (!h.startsWith('#/search')) state.filter = '';   // 搜索已独立路由，离开搜索即清关键词，避免首页/社团页残留叠加
  if (isImportOnly()) {                      // 仅导入模式：只开放 导入页 与 爬虫管理
    if (h.startsWith('#/probe')) {           // 分区爬取是入库上游（搜索结果 → 勾选 → 落 _app/_inbox）
      const qp = new URLSearchParams(h.slice(h.indexOf('?') + 1));
      state.view = 'probe';
      state.circleName = null; state.tagType = state.tagName = null;
      renderProbe(qp.get('kind') || 'author', qp.get('term') || '', qp.get('site') || 'wnacg');
      hideHomeSections();
      return;
    }
    if (h.startsWith('#/crawl')) {           // 爬虫是入库的上游来源（落盘 _app/_inbox），此模式一并开放
      state.view = 'crawl';
      state.circleName = null; state.tagType = state.tagName = null;
      renderCrawl();
      hideHomeSections();
      return;
    }
    if (!h.startsWith('#/import')) {
      location.hash = '#/import';
      return;
    }
    state.view = 'import';
    state.circleName = null; state.tagType = state.tagName = null;
    renderImport();
    hideHomeSections();
    return;
  }
  // 只有进入 #/tag/… 时保留返回目标；其它视图一律清空，避免“返回标签云”残留
  if (!h.startsWith('#/tag/')) state.tagReturn = null;
  if (h.startsWith('#/info/')) {
    // 通用增补信息：任意社团/收件箱的作品均可 → #/info/社团/作品
    const rest = decodeURIComponent(h.slice('#/info/'.length));
    const i = rest.indexOf('/');
    state.view = 'info';
    state.infoGroup = rest.slice(0, i);
    state.infoWork = rest.slice(i + 1);
    state.circleName = null; state.tagType = state.tagName = null;
    loadInfoForm();
  } else if (h.startsWith('#/uncat/info/')) {
    // 兼容旧路由 → 收件箱
    state.view = 'info';
    state.infoGroup = '收件箱';   // i18n:data 真实社团名（标识符）
    state.infoWork = decodeURIComponent(h.slice('#/uncat/info/'.length));
    state.circleName = null; state.tagType = state.tagName = null;
    loadInfoForm();
  } else if (h.startsWith('#/uncat')) {
    // 3.2.5 未分类已并入收件箱
    location.hash = '#/inbox';
  } else if (h.startsWith('#/inbox')) {
    // 收件箱（3.1 提案式入库：爬虫落盘 / 手动放入 _app/_inbox 的作品确认 + 内容去重）
    state.view = 'inbox';
    state.circleName = null; state.tagType = state.tagName = null;
    renderInbox();
  } else if (h.startsWith('#/import')) {
    state.view = 'import';
    state.circleName = null; state.tagType = state.tagName = null;
    renderImport();
  } else if (h.startsWith('#/artist/')) {
    // M4 画师档案页：跨社团作品 + 入库时间线 + 关注
    state.view = 'artist';
    state.artistName = decodeURIComponent(h.slice('#/artist/'.length));
    state.circleName = null; state.tagType = state.tagName = null;
    loadArtist();
  } else if (h.startsWith('#/circle/')) {
    state.view = 'circle';
    state.circleName = decodeURIComponent(h.slice(9));
    state.tagType = state.tagName = null;
    loadCircle();
  } else if (h.startsWith('#/tag/')) {
    const rest = decodeURIComponent(h.slice(6));
    const i = rest.indexOf('/');
    state.view = 'tag';
    state.tagType = rest.slice(0, i);
    state.tagName = rest.slice(i + 1);
    state.circleName = null;
    loadTag();
  } else if (h.startsWith('#/resume')) {
    // 3.5.1 续读独立视图：右上角「📖 续读」入口（原先只有首页那一条横排，还会残留到其它视图）
    state.view = 'resume';
    state.circleName = null; state.tagType = state.tagName = null;
    renderResumeView();
  } else if (h.startsWith('#/loved')) {
    // 3.5.1 喜爱画师独立视图：右上角「❤ 喜爱」入口（原先要连点 3 次 chip 才到，等于没有）
    state.view = 'loved';
    state.circleName = null; state.tagType = state.tagName = null;
    renderLovedView();
  } else if (h.startsWith('#/stats')) {
    // 3.2.1 个人统计（网页端与 APP 对齐）
    state.view = 'stats';
    state.circleName = null; state.tagType = state.tagName = null;
    renderStats();
  } else if (h.startsWith('#/search')) {
    // 3.6.0 搜索独立 hash 路由：搜索结果可由浏览器返回键原路返回，而非落到首页
    let _sq = '';
    const _si = h.indexOf('?');
    // 3.6.107：URLSearchParams 已经做过一次百分号解码，再 decodeURIComponent 就是
    // **双重解码** —— 查询里只要有一个字面 `%`（如「快感100%」），第二次解码会抛
    // URIError，route() 整个中断，页面既不渲染结果也不报错，看起来就是"搜索失效"。
    if (_si >= 0) _sq = new URLSearchParams(h.slice(_si + 1)).get('q') || '';
    state.view = 'search';
    state.circleName = null; state.tagType = state.tagName = null;
    state.filter = _sq;
    // 3.6.107：输入框正被编辑时**不要回写**。以前每次防抖都执行
    // `$('#search').value = _sq`（_sq 是 trim 过的），后果有两个：
    //   ① 刚敲的空格立刻被吞掉 → 多词查询被粘成一个长串（"エルフ の女王"→"エルフの女王"），
    //      越往后输入越对不上，长标题必然搜成 0 条，正是"输入一定字符后失效"；
    //   ② 输入法合成串被打断、光标被扔到末尾。
    if (document.activeElement !== $('#search')) $('#search').value = _sq;
    renderSearchView(_sq);
  } else if (h.startsWith('#/lang')) {
    // 3.6.116 语言二级界面：8 语言单选，切换即时重绘整站（原抽屉内嵌区块）
    state.view = 'lang';
    state.circleName = null; state.tagType = state.tagName = null;
    // 3.6.124：进入时记来源，返回键原路回（重复 route 调用不覆盖已有锚点）
    state.langReturn = (prev && !prev.startsWith('#/lang')) ? prev : (state.langReturn || '#/');
    renderLangView();
  } else if (h.startsWith('#/aliases')) {
    // 3.7.78 别名登记页（取代网页设置弹窗，与 APP 同款系统）
    state.view = 'aliases';
    state.circleName = null; state.tagType = state.tagName = null;
    renderAliasView();
  } else if (h.startsWith('#/theme/gallery')) {
    // 3.6.118 主题图库三级界面：增删改查 + 「设为背景图 / 设为首页横幅」双槽应用
    state.view = 'themeGallery';
    state.circleName = null; state.tagType = state.tagName = null;
    state.themeGalleryReturn = '#/theme';          // 图库只从主题页进，返回固定回主题页
    renderThemeGalleryView(h.startsWith('#/theme/gallery?hero') ? 'hero' : 'bg');
  } else if (h.startsWith('#/theme')) {
    // 3.6.116 主题二级界面：预设配色 / 取色器 / 本机图库（原抽屉内嵌区块）
    state.view = 'theme';
    state.circleName = null; state.tagType = state.tagName = null;
    // 3.6.124：从哪儿来回哪儿去（抽屉入口打开时 = 当前视图的 hash）
    state.themeReturn = (prev && !prev.startsWith('#/theme')) ? prev : (state.themeReturn || '#/');
    renderThemeView();
  } else if (h.startsWith('#/probe')) {
    // 3.7.54 分区爬取：分区页右上角带 kind+term 进来，只预填；3.7.57 起必须点搜索
    const qp = new URLSearchParams(h.slice(h.indexOf('?') + 1));
    state.view = 'probe';
    state.circleName = null; state.tagType = state.tagName = null;
    renderProbe(qp.get('kind') || 'author', qp.get('term') || '', qp.get('site') || 'wnacg');
  } else if (h.startsWith('#/crawl')) {
    // 爬虫管理（wnacg 定向爬取 / jm ID / 失败重试）
    state.view = 'crawl';
    state.circleName = null; state.tagType = state.tagName = null;
    renderCrawl();
  } else {
    state.view = 'home';
    state.circleName = null; state.tagType = state.tagName = null;
    renderHome();
  }
  hideHomeSections();          // 「随机推荐」只在首页；此前这里漏判还会让「继续阅读」横排残留到二级视图
  if (state.view !== 'search') hideSearchWorks();  // 「匹配的作品」小节仅限搜索/首页搜索时展示（#/search 视图需保留）
  restoreScroll();
  scheduleNavRefresh();
}

/* 首页专属区块（hero / 随机推荐）在离开首页时统一收起。
   3.5.2 修复：此前写法是逐个 addHidden 且漏掉了 #resumeSection，导致「📖 继续阅读」横排挂到
   爬虫、收件箱、统计等视图顶部；3.5.3 该横排已按用户要求整体撤除，续读统一走右上角入口。 */
function hideHomeSections() {
  const leave = state.view !== 'home';
  for (const sel of ['#recSection', '#hero']) {
    const el = $(sel);
    if (el) el.classList.toggle('hidden', leave);
  }
}

/* 每次切换视图后后台同步一次文库数据：服务端有更新（如解散/归档后的重扫）才重渲染，
   滚动位置由 restoreScroll 保持；无变化时不打扰当前页面。
   3.3.0 瘦身：先探轻量 /api/library/meta（rev 没变即零成本返回），变了且扫描完成
   才拉一次全量 /api/library——此前每次导航都拉全量（整库 groups+tags JSON）。 */
let _navRefreshTimer = null;

function scheduleNavRefresh() {
  clearTimeout(_navRefreshTimer);
  _navRefreshTimer = setTimeout(navSyncLib, 80);
}

async function navSyncLib() {
  try {
    const m = await api('/api/library/meta');
    if (!state.lib) return;
    if (m.rev === state.lib.rev && m.scanned_at === state.lib.scanned_at) return;
    if (m.scanning) { _navRefreshTimer = setTimeout(navSyncLib, 1500); return; }   // 重扫进行中，稍后再查
    const d = await api('/api/library');
    if (d.status === 'scanning') { _navRefreshTimer = setTimeout(navSyncLib, 1500); return; }
    if (state.lib && d.scanned_at === state.lib.scanned_at && d.rev === state.lib.rev) return;
    state.lib = d;
    updateStatus();
    route();          // 以新数据重渲染当前视图
  } catch (e) { /* 静默：切换时的后台刷新失败不打扰用户 */ }
}
