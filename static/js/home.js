/* 本地同人志文库 前端 · home.js
   首页社团墙与分区（画师/原作）
   3.6.84 从 static/app.js 拆出：按顶层区块切分，仍是 classic script，
   与其余分片共享同一个全局词法环境（顺序加载，勿调整 index.html 里的 <script> 次序）。 */
'use strict';

/* ---------- 过滤 ---------- */
function matchesFilter(q, ...fields) {
  q = q.trim().toLowerCase();
  if (!q) return true;
  return q.split(/\s+/).every(t => fields.some(f => String(f || '').toLowerCase().includes(t)));
}

/* ---------- 首页：社团墙 + 每日推荐 ---------- */
function feedMode() {
  // 3.5.1 喜爱画师已改由右上角「❤ 喜爱」一级入口（#/loved）进入，不再藏在这颗 chip 的第 4 档；
  // 历史上存下来的 'loved' 归一到「全部画师」，免得 chip 显示一个已不存在的分区。
  const m = localStorage.getItem('feed_mode');
  if (m === 'loved') { try { localStorage.setItem('feed_mode', 'artists'); } catch (e) { /* 隐私模式忽略 */ } return 'artists'; }
  return m || 'circles';
}
function feedSort() { return localStorage.getItem('feed_sort') || 'works'; }
function feedSortAsc() { return localStorage.getItem('feed_sort_asc') === '1'; }
function feedSortBarHtml(mode) {
  // 3.6.39 #37：原作分区多一档「创建次序」（后端顺序 = 新建/新归类分区置顶）。
  // 画师视图没有这一档（画师没有"创建次序"概念），保持原两档。
  const isOrig = mode === 'originals';
  const explicit = localStorage.getItem('feed_sort');
  // 画师视图没有"创建次序"档：若全局存着 created，按"作品数量"高亮（行为也是按作品数排）
  const raw = isOrig ? (explicit || 'created') : feedSort();
  const cur = (!isOrig && raw === 'created') ? 'works' : raw;
  const on = m => cur === m ? 'on' : '';
  return '<div class="sort-bar" id="feedSortBar">' +
    '<span class="sort-label">' + esc(t('排序')) + '</span>' +
    (isOrig ? '<button type="button" data-feedsort="created" class="' + on('created') +
      '" title="' + esc(t('按分区创建次序：新建/新归类的分区排最前')) + '">' + esc(t('创建次序')) + '</button>' : '') +
    '<button type="button" data-feedsort="works" class="' + on('works') + '">' + esc(t('作品数量')) + '</button>' +
    '<button type="button" data-feedsort="latest" class="' + on('latest') + '">' + esc(t('最新入库')) + '</button>' +
    // 3.6.42 #45：created 档也有正反序（新→旧 / 旧→新），不再把方向键藏起来
    // 3.6.151 起方向键统一成"箭头固定 ↓，只有文字变"；3.6.152 补齐这里原先漏掉的 ↑/↓ 翻转，
    // 并把「作品数量」与「创建次序/最新入库」分成两套文案（旧版共用"由少到多"，维度对不上）。
    '<button type="button" data-feedsortdir="1" class="dir on">' +
    esc(cur === 'works'
      ? (feedSortAsc() ? t('↓ 由少到多') : t('↓ 由多到少'))
      : (feedSortAsc() ? t('↓ 由旧到新') : t('↓ 由新到旧'))) +
    '</button>' +
    '</div>';
}

function renderHome() {
  const lib = state.lib;
  const fm = feedMode();
  if (!state.filter.trim()) hideSearchWorks();
  // 3.6.93：推荐区不再在这里按"有没有搜索词"预先隐藏——那会让分区视图永久看不到推荐
  // （下面 `fm !== 'circles'` 提前 return，renderRecs 永远轮不到它）。现在只有"没有文库数据"
  // 这种确实无可推荐的情况才收起，其余交给 renderRecs 自己判断（有搜索词/无推荐时才隐藏）。
  if (!lib || !lib.groups.length) { $('#recSection').classList.add('hidden'); showEmpty(); return; }
  hideEmpty();
  const hn = $('#heroName'), hs = $('#heroStats');
  if (hn) hn.innerHTML = '<!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-library" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="m16 6 4 14" /> <path d="M12 6v14" /> <path d="M8 8v12" /> <path d="M4 4v16" /> </svg> ' + (state.config?.name || esc(t('禁书目录 Index')));
  if (hs) {
    const nW = lib.groups.reduce((n, g) => n + g.workCount, 0);
    hs.textContent = tf('%1 个社团 · %2 部作品 · 个人本地文库 · 面板 v%3 · API %4',
      lib.groups.length, nW, state.config.version || '', state.config.apiLevel || 1);
  }
  const label = fm === 'artists' ? t('全部画师') : fm === 'originals' ? t('同人分区')
              : fm === 'loved' ? t('❤ 喜爱画师') : t('全部社团');
  $('#viewHead').innerHTML =
    '<div style="padding:0 20px;display:flex;align-items:center;gap:10px;flex-wrap:wrap">' +
      '<h2 style="padding:0">' + esc(label) + ' <small id="countText"></small></h2>' +
      // 3.5.1 第四档「喜爱画师」已移出循环 → 右上角「❤ 喜爱」专门入口（这里再藏一层纯属重复）
      '<button type="button" id="btnFeedToggle" class="feed-chip" title="' +
        esc(t('点击切换：全部社团 → 全部画师 → 同人分区（喜爱画师请看右上角「❤ 喜爱」）')) + '">' + esc(label) + '</button>' +
    '</div>' +
    (fm === 'circles' ? sortBarHtml() : feedSortBarHtml(fm));
  $('#btnFeedToggle').addEventListener('click', () => {
    const order = ['circles', 'artists', 'originals'];
    localStorage.setItem('feed_mode', order[(order.indexOf(feedMode()) + 1) % order.length]);
    renderHome();
  });
  // 3.6.93：每日推荐在三种首页分区（全部社团 / 全部画师 / 原作分区）里都要显示，
  // 所以渲染必须发生在下面的分区 early-return **之前**。
  renderRecs(lib);
  if (fm !== 'circles') { renderFeedPartition(fm); return; }
  // 「收件箱」不是社团（它的正入口是导航里的「📮 收件箱」页），但这里不做过滤：
  // 3.6.3 起文库里不会再出现这个组——除非用户自己在文库根建了同名目录，那它就该正常显示。
  const groups = sortGroups(lib.groups.filter(g => matchesFilter(state.filter, g.name, g.latestWork)));
  $('#countText').textContent = tf('（%1 个）', groups.length);
  // 搜索时同时检索单独作品（服务端 /api/search：名称/画师/待定/标签/社团全匹配）
  if (state.filter.trim()) loadSearchWorks(state.filter.trim());
  const grid = $('#grid'); grid.className = 'grid'; grid.innerHTML = '';
  if (!groups.length) { showGridEmpty('<!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-search" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <circle cx="11" cy="11" r="8" /> <path d="m21 21-4.3-4.3" /> </svg> ' + esc(t('没有匹配的社团')), t('换个关键词试试。')); return; }
  hideGridEmpty();
  const frag = document.createDocumentFragment();
  for (const g of groups) {
    const d = document.createElement('div');
    d.className = 'circle-card';
    d.dataset.group = g.name;
    d.title = tf('点击进入社团：%1', g.name);
    // 3.2 新作品标亮：社团内有"上次访问后新入库"的作品 → 封面角标"有新"
    const prefix = g.name + '/';
    let newN = 0;
    if (readingHub.loaded) {
      for (const k of readingHub.newKeys) if (k.startsWith(prefix)) newN++;
    }
    // 封面按「封面的物理归属社团」取图（设为社团封面后可能来自交叉引用的作品）
    const cover = g.hasCover
      ? '<img loading="lazy" src="' + coverUrl(g.coverGroup || g.name, g.coverWork || g.latestWork, g.coverVer) + '" alt="" onerror="this.closest(\'.circle-cover\').classList.add(\'noimg\')">'
      : '<div class="ph"><!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-package" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M11 21.73a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73z" /> <path d="M12 22V12" /> <path d="m3.3 7 7.703 4.734a2 2 0 0 0 1.994 0L20.7 7" /> <path d="m7.5 4.27 9 5.15" /> </svg></div>';
    d.innerHTML =
      // 封面区：长按 = 唤出社团操作菜单（data-nocopy 让长按复制不介入）
      '<div class="circle-cover" data-nocopy>' + cover +
        (newN > 0 ? '<span class="rd-badge new" title="' + esc(tf('上次访问后新入库 %1 部', newN)) + '">' + esc(tf('有新 %1', newN)) + '</span>' : '') +
      '</div>' +
      '<div class="circle-meta">' +
        '<div class="circle-name">' + esc(g.name) + '</div>' +
        '<div class="circle-sub">' + esc(tf('%1 部作品 · 最新：%2', g.workCount, g.latestWork)) + '</div>' +
      '</div>';
    frag.appendChild(d);
  }
  grid.appendChild(frag);
}

/* ---------- 3.2.6 首页分区:全部画师 / 原作分区(封面=名下最大作品首图,爱心=喜爱)
              3.3.0 追加第四分区「喜爱画师」——APP 喜爱页的网页对称形态 ---------- */
async function renderFeedPartition(mode) {
  const grid = $('#grid'); grid.className = 'grid'; grid.innerHTML = '';
  hideGridEmpty();
  grid.innerHTML = '<div class="sub" style="grid-column:1/-1;padding:10px">' + esc(t('加载中…')) + '</div>';
  try {
    if (mode !== 'artists' && mode !== 'originals' && mode !== 'loved') return;
    // 3.6.30 回归修复：3.3.0 加「喜爱画师」分区时把这里统一成了 /api/artists
    //（喜爱只需画师列表 + followed 过滤），顺手把原作分区的数据源也砍了 ——
    // 此后首页「原作分区」视图一直在拿**画师列表**当分区渲染（卡片 title 写着
    // "点击进入同人分区"，点进去却是画师名 → 空分区）。3.2.6 原本是对的。
    // 「喜爱」仍走 /api/artists（只有它有 followed）。
    const d = await api(mode === 'originals' ? '/api/originals' : '/api/artists');
    if (state.view !== 'home' || feedMode() !== mode) return;      // 过期结果
    let items = mode === 'originals' ? (d.originals || []) : (d.artists || []);
    if (mode === 'loved') items = items.filter(a => a.followed);
    const f = state.filter.trim().toLowerCase();
    let sorted = items.filter(a => !f || a.name.toLowerCase().includes(f));
    // 3.6.42 #45：原作分区的三档排序
    // - created（默认）：后端已按「分区首次出现时间」新→旧返回；方向键只是翻转。
    // - works / latest：按作品数 / 最近入库，**默认降序**（多者、新者在前）。
    //   此前这里默认是升序（r = ka - kb），而按钮文案写"↓ 由多到少"——
    //   文案与行为相反，用户点"最新入库"看到最老的排最前（报障"逻辑明显有错误"）。
    const explicitSort = localStorage.getItem('feed_sort');
    const isCreated = mode === 'originals' && (!explicitSort || explicitSort === 'created');
    if (isCreated) {
      if (feedSortAsc()) sorted = sorted.slice().reverse();
    } else {
      const key = x => feedSort() === 'latest' ? (x.latest || 0) : x.works;
      sorted = sorted.slice().sort((a, b) => {
        let r = key(b) - key(a);          // 默认降序
        if (feedSortAsc()) r = -r;        // 由少到多 / 由旧到新
        return r !== 0 ? r : a.name.localeCompare(b.name);
      });
    }
    $('#countText').textContent = mode === 'originals'
      ? tf('（%1 个）', sorted.length) : tf('（%1 位）', sorted.length);
    const grid2 = $('#grid');
    if (!grid2) return;
    grid2.innerHTML = '';
    // 3.6.170：同人分区视图首位放一张「新建分区」卡（用户 2026-10-30 要求：
    // 作品卡片形状、封面区中间一个加号、下面是文字）。空分区也照样给，否则新库没处建。
    if (mode === 'originals') grid2.appendChild(newOriginalCard());
    if (!sorted.length) {
      const tip = document.createElement('div');
      tip.className = 'sub';
      tip.style.cssText = 'grid-column:1/-1;padding:10px';
      tip.textContent = mode === 'artists' ? t('还没有画师数据') : mode === 'loved'
          ? t('还没有喜爱的画师——切到「全部画师」，点格子右下角的 ❤ 即可喜爱')
          : t('还没有同人标签——导入时带 (同人名) 的作品会归到这里');
      grid2.appendChild(tip);
      return;
    }
    const frag = document.createDocumentFragment();
    for (const a of sorted) {
      const d2 = document.createElement('div');
      d2.className = 'circle-card';
      d2.title = mode === 'originals'
        ? tf('点击进入同人分区：%1', a.name) : tf('点击打开画师档案：%1', a.name);
      const cover = (a.cover_group && a.cover_work)
        ? '<img loading="lazy" src="' + coverUrl(a.cover_group, a.cover_work, (a.cover_mtime || 0) + '-' + (a.cover_pages || 0)) + '" alt="" onerror="this.closest(\'.circle-cover\').classList.add(\'noimg\')">'
        : '<div class="ph">' + (mode === 'originals' ? '🎴' : '👤') + '</div>';
      const followed = mode === 'loved' ? true : !!a.followed;
      const heart = mode === 'originals' ? '' :
        '<span class="artist-heart' + (followed ? ' on' : '') + '" data-fav="' + esc(a.name) + '" data-loved="' + (followed ? '1' : '0') + '" title="' + esc(followed ? t('取消喜爱') : t('喜爱')) + '">❤</span>';
      d2.innerHTML =
        '<div class="circle-cover">' + cover + heart + '</div>' +
        '<div class="circle-meta">' +
          '<div class="circle-name">' + esc(a.name) + '</div>' +
          '<div class="circle-sub">' + esc(tf('%1 部作品 · %2', a.works, mode === 'originals' ? t('点进分区') : t('点看档案'))) + '</div>' +
        '</div>';
      if (mode === 'originals') d2.dataset.original = a.name;
      else d2.dataset.artist = a.name;
      frag.appendChild(d2);
    }
    grid2.appendChild(frag);
    grid2.querySelectorAll('.artist-heart').forEach(h => h.addEventListener('click', async ev => {
      ev.stopPropagation();
      const name = h.dataset.fav, loved = h.dataset.loved !== '1';
      try {
        const r = await api(loved ? '/api/follow' : '/api/follow/unfollow',
          { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ author: name }) });
        showToast(r.message || t('完成'));
        h.classList.toggle('on', loved);
        h.dataset.loved = loved ? '1' : '0';
        if (mode === 'loved' && !loved) h.closest('.circle-card').remove();   // 喜爱分区里取消 → 移出卡片
      } catch (e) { showToast(tf('%1：%2', t('失败'), e.message)); }
    }));
    // 卡片跳转是 `#grid` 上的**委托**（menu.js）：按 dataset.group / artist / original 分派。
    // 3.6.170 起不再逐卡 addEventListener —— 逐卡绑的那份会被委托覆盖成 `#/circle/undefined`，
    // 画师卡和同人卡因此点不进去（两处逻辑并存时，谁最后写 hash 谁说话）。
  } catch (e) {
    const grid2 = $('#grid');
    if (grid2) grid2.innerHTML = '<div class="sub" style="grid-column:1/-1;padding:10px">' + esc(tf('%1失败：%2', t('加载'), e.message)) + '</div>';
  }
}

/* ---------- 3.6.170 同人分区视图：「新建分区」卡（置顶，作品卡片形状） ----------
   用户在 2026-10-30 提出：同人分区视图没有建新分区的入口，而且要求它就是一张作品卡
   （封面区中间一个加号，下面是文字），排在最前面。
   建的是**空分区**（后端 /api/originals/add 的 `empty:true` 分支）：只往 config 词条库
   落名，不搜作品、不写标签；之后在该分区里「＋ 添加作品」补。 */
function newOriginalCard() {
  const d = document.createElement('div');
  d.className = 'circle-card add-zone';
  d.id = 'btnNewOriginal';
  d.title = t('新建一个空的同人分区（之后在分区里「＋ 添加作品」补作品）');
  d.innerHTML =
    '<div class="circle-cover"><div class="ph">＋</div></div>' +
    '<div class="circle-meta">' +
      '<div class="circle-name">' + esc(t('新建分区')) + '</div>' +
      '<div class="circle-sub">' + esc(t('建一个空的同人分区')) + '</div>' +
    '</div>';
  d.addEventListener('click', createOriginalZone);
  return d;
}

async function createOriginalZone() {
  const name = (prompt(t('新建同人分区：输入分区名（先建一个空分区，之后在分区里点「＋ 添加作品」补作品）'), '') || '').trim();
  if (!name) return;
  try {
    const r = await api('/api/originals/add', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ term: name, empty: true }) });
    showToast(r.existed ? tf('分区「%1」已存在', r.canon) : tf('已新建分区「%1」', r.canon));
    renderFeedPartition('originals');
  } catch (e) { showToast(tf('%1：%2', t('失败'), e.message)); }
}
