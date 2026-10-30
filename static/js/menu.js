/* 本地同人志文库 前端 · menu.js
   键盘快捷键与标签/画师点击委托
   3.6.84 从 static/app.js 拆出：按顶层区块切分，仍是 classic script，
   与其余分片共享同一个全局词法环境（顺序加载，勿调整 index.html 里的 <script> 次序）。 */
'use strict';

document.addEventListener('keydown', e => {
  if (reader.open) {                                   // 阅读器内按键翻页
    if (e.key === 'Escape') { closeReader(); return; }
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === 'PageDown' || e.key === ' ' || e.key === 'd' || e.key === 'D') {
      e.preventDefault(); go(1); return;
    }
    if (e.key === 'ArrowLeft' || e.key === 'ArrowUp' || e.key === 'PageUp' || e.key === 'a' || e.key === 'A') {
      e.preventDefault(); go(-1); return;
    }
    if (e.key === 'Home') { e.preventDefault(); showPage(0); return; }
    if (e.key === 'End') { e.preventDefault(); showPage(reader.total - 1); return; }
    return;
  }
  if (e.key === 'Escape') { const m = $('#modal'); if (m) m.classList.add('hidden'); }
  if (e.key === '/' && document.activeElement !== $('#search')) { e.preventDefault(); $('#search').focus(); }
});

/* 画师链接 / 标签 chips 的跳转（#grid 与 #viewHead 共用——社团页「该社团作者」chips
   渲染在头部 #viewHead 里，原先只有 #grid 绑了监听，点了没反应）。返回是否已处理。 */
function handleTagOrArtistClick(e) {
  const artistLink = e.target.closest('[data-artist]');
  if (artistLink) { location.hash = '#/artist/' + enc(artistLink.dataset.artist); return true; }
  const xref = e.target.closest('[data-xref-circle]');   // 作者页头部"所属社团"chips → 进入社团
  if (xref) { location.hash = '#/circle/' + enc(xref.dataset.xrefCircle); return true; }
  const tag = e.target.closest('.tag.clickable');
  if (tag) {
    if (tag.dataset.type === 'personal') {          // 画师词条 → 画师档案页（M4）
      location.hash = '#/artist/' + enc(tag.dataset.name);
      return true;
    }
    if (tag.dataset.type === 'circle') {            // 3.6.14 社团标签 → 社团页（与 data-xref-circle 同）
      location.hash = '#/circle/' + enc(tag.dataset.name);
      return true;
    }
    if (state.view !== 'tag') state.tagReturn = null;   // 从卡片进入时回首页；标签页内跳转保留返回目标
    location.hash = '#/tag/' + tag.dataset.type + '/' + enc(tag.dataset.name);
    return true;
  }
  return false;
}

// 搜索结果的「匹配的画师」区：chips 不在 #grid 里，单独绑一份同样的跳转逻辑
(() => {
  const sec = $('#searchAuthorsSection');
  if (sec) sec.addEventListener('click', handleTagOrArtistClick);
})();

/* 卡片点击 → 阅读/社团/标签/画师档案(委托到 #grid) */
$('#grid').addEventListener('click', e => {
  if (handleTagOrArtistClick(e)) return;
  const inboxRead = e.target.closest('[data-act="inbox-read"]');
  if (inboxRead) { openReader('收件箱', inboxRead.dataset.id); return; }   // 3.4.2 收件箱先读后入库；收件箱=真实社团名 i18n:data
  const inboxInfo = e.target.closest('[data-act="inbox-info"]');
  if (inboxInfo) { openInfo('收件箱', inboxInfo.dataset.id); return; }   // 补全词条后即可自动识别社团；收件箱=真实社团名 i18n:data
  const circle = e.target.closest('.circle-card');
  if (circle) {
    // 3.6.170 修正：分区视图（全部画师 / 同人分区 / 喜爱）的卡片**也是** `.circle-card`
    // （复用同一套样式），但它们没有 `dataset.group`，只有 `dataset.artist` / `dataset.original`。
    // 这里从前无条件 `location.hash = '#/circle/' + enc(circle.dataset.group)`，
    // 于是点画师卡/同人卡会跳到 `#/circle/undefined` → 前端找不到该社团 → 踢回首页，
    // 表现就是「画师页和同人分区点不进去」（APP 是原生渲染，所以只有网页端有）。
    // 现在按卡上的标识分派，社团卡行为不变。
    if (circle.dataset.group) { location.hash = '#/circle/' + enc(circle.dataset.group); return; }
    if (circle.dataset.artist) { location.hash = '#/artist/' + enc(circle.dataset.artist); return; }
    if (circle.dataset.original) { location.hash = '#/tag/original/' + enc(circle.dataset.original); return; }
  }
  // 3.7.10 续读页等区域内的 .rec-card 也渲染在 #grid 里（原先只有首页 #recRow 有委托，
  // 续读页卡片点击无反应——顺手修复）：点击即继续阅读
  const rec = e.target.closest('.rec-card');
  if (rec && rec.dataset.work) { openReader(rec.dataset.group, rec.dataset.work); return; }
  const card = e.target.closest('.card');
  if (!card) return;
  const g = card.dataset.group, w = card.dataset.work;
  if (e.target.closest('[data-act="folder"]')) return openTarget(g, w, 'folder');
  if (e.target.closest('[data-act="image"]')) return openTarget(g, w, 'image');
  if (e.target.closest('[data-act="read"]')) return openReader(g, w);
  if (e.target.closest('.cover-wrap')) return openReader(g, w);
  if (e.target.closest('.title')) return openReader(g, w);
});
/* 搜索结果作品卡片：与 #grid 同款跳转，但默认进详情页（hash 路由），保证浏览器返回回到搜索页 */
$('#searchWorksGrid').addEventListener('click', e => {
  if (handleTagOrArtistClick(e)) return;
  const card = e.target.closest('.card');
  if (!card) return;
  const g = card.dataset.group, w = card.dataset.work;
  if (e.target.closest('[data-act="folder"]')) return openTarget(g, w, 'folder');
  if (e.target.closest('[data-act="image"]')) return openTarget(g, w, 'image');
  // 阅读/封面/标题/默认：进详情页（hash 可返回）；详情页内再点「阅读」进阅读器
  openInfo(g, w);
});
$('#recRow').addEventListener('click', e => {
  const card = e.target.closest('.rec-card');
  if (!card) return;
  openReader(card.dataset.group, card.dataset.work);
});
$('#viewHead').addEventListener('click', e => {
  // 头部里的画师/标签 chips（如社团页「该社团作者」）与 #grid 共用跳转逻辑
  if (handleTagOrArtistClick(e)) return;
  // 社团排序：点维度切维度、点方向键切正/倒序（本地记住，重渲染即时生效）
  const sortBtn = e.target.closest('[data-sort]');
  if (sortBtn && state.view === 'home') {
    localStorage.setItem(SORT_KEY, sortBtn.dataset.sort);
    renderHome();
    return;
  }
  if (e.target.closest('[data-sortdir]') && state.view === 'home') {
    localStorage.setItem(SORT_ASC_KEY, sortIsAsc() ? '0' : '1');
    renderHome();
    return;
  }
  const fsBtn = e.target.closest('[data-feedsort]');
  if (fsBtn && state.view === 'home') {
    localStorage.setItem('feed_sort', fsBtn.dataset.feedsort);
    renderHome();
    return;
  }
  if (e.target.closest('[data-feedsortdir]') && state.view === 'home') {
    localStorage.setItem('feed_sort_asc', feedSortAsc() ? '0' : '1');
    renderHome();
    return;
  }
  // 3.6.151：作品列表排序（社团页 / 同人区 / 画师页共用）——改完就地重渲染，不发请求
  const wsBtn = e.target.closest('[data-wsort]');
  if (wsBtn) {
    localStorage.setItem(WORK_SORT_KEY, wsBtn.dataset.wsort);
    rerenderWorksView();
    return;
  }
  if (e.target.closest('[data-wsortdir]')) {
    localStorage.setItem(WORK_ASC_KEY, workIsAsc() ? '0' : '1');
    rerenderWorksView();
    return;
  }
  if (!e.target.closest('#btnBack')) return;
  // 3.6.124：主题 / 语言 / 图库三级页按进入前的视图原路返回（原先一律跳首页）
  if (state.view === 'themeGallery') { location.hash = state.themeGalleryReturn || '#/theme'; return; }
  if (state.view === 'theme') { location.hash = state.themeReturn || '#/'; return; }
  if (state.view === 'lang') { location.hash = state.langReturn || '#/'; return; }
  if (state.view === 'info') { location.hash = state.infoReturn || '#/'; return; }
  if (state.view === 'tag') { location.hash = state.tagReturn || '#/'; state.tagReturn = null; return; }
  location.hash = '#/';
});
$('#btnImport').addEventListener('click', () => { location.hash = '#/import'; });
$('#btnInbox').addEventListener('click', () => { location.hash = '#/inbox'; });
$('#btnStats').addEventListener('click', () => { location.hash = '#/stats'; });
