/* 本地同人志文库 前端 · search.js
   首页搜索、推荐、续读与喜爱视图
   3.6.84 从 static/app.js 拆出：按顶层区块切分，仍是 classic script，
   与其余分片共享同一个全局词法环境（顺序加载，勿调整 index.html 里的 <script> 次序）。 */
'use strict';

/* ---------- 首页搜索：匹配的作品（服务端检索，防竞态序号守卫） ---------- */
let searchWorksSeq = 0;
async function loadSearchWorks(q) {
  const seq = ++searchWorksSeq;
  try {
    const d = await api('/api/search?q=' + enc(q));
    if (seq !== searchWorksSeq || (state.view !== 'home' && state.view !== 'search')) return;   // 过期结果或已离开首页/搜索
    const works = d.works || [];
    const dropped = d.dropped || [];       // 3.6.108：宽松档丢掉的"库里没有的词"
    renderSearchAuthors(d.authors || []);
    const sec = $('#searchWorksSection');
    const grid = $('#searchWorksGrid');
    if (!works.length) {
      // 3.6.107：以前整块隐藏 —— 用户分不清"没匹配"和"搜索坏了 / 还在转"。
      // 多关键词之间是「同时包含」关系（AND），一条对不上就是 0 条，所以这里要明说。
      $('#searchWorksCount').textContent = t('（0 部）');
      grid.innerHTML = '<div class="sub" style="padding:10px 4px;line-height:1.7">'
        + esc(t('没有匹配的作品。')) + '<br>'
        + esc(t('多个关键词是「同时包含」关系，任一关键词不存在就会 0 条 —— 可以试着减少关键词，或只输入标题里连续的一段。')) + '</div>';
      sec.classList.remove('hidden');
      return;
    }
    $('#searchWorksCount').textContent = tf('（%1 部%2）', works.length,
      (works.length >= 200 ? t('，已截断') : '') + droppedNote(dropped));
    grid.innerHTML = '';
    const frag = document.createDocumentFragment();
    for (const it of works) frag.appendChild(makeWorkCard(it.group, it.work, true));
    grid.appendChild(frag);
    sec.classList.remove('hidden');
  } catch (e) {
    $('#searchWorksSection').classList.add('hidden');
    $('#searchAuthorsSection').classList.add('hidden');
  }
}

/* 3.6.108 宽松档说明：把"库里一次都没出现、已被忽略"的词列出来（最多 3 个，长的截断）。
   粘贴整条作品名时常见（`.zip`、写法不同的汉化组标记），列出来用户才知道为什么命中变宽。 */
function droppedNote(dropped) {
  if (!dropped || !dropped.length) return '';
  const shown = dropped.slice(0, 3)
    .map(t => (t.length > 14 ? t.slice(0, 14) + '…' : t)).join('、');
  return ' ' + tf('· 已忽略库里没有的词：%1', esc(shown))
    + (dropped.length > 3 ? ' ' + tf('等 %1 个', dropped.length) : '');
}

/* 3.7.4 搜索结果里的「匹配的画师」：点 chip 直达画师档案页（跨社团全部作品） */
function renderSearchAuthors(authors) {
  const sec = $('#searchAuthorsSection');
  if (!sec) return;
  if (!authors.length) { sec.classList.add('hidden'); return; }
  const total = authors.reduce((n, a) => n + (a.count || 0), 0);
  $('#searchAuthorsCount').textContent = tf('（%1 位 · %2 部作品%3）', authors.length, total,
    authors.length >= 30 ? t('，已截断') : '');
  // 3.6.x：画师结果渲染为带封面的 circle-card（复用全局 .tag.clickable 委托跳画师档案），
  // 不再只是一行文字占位符；无封面时退化为 👤 头像占位。
  $('#searchAuthorsGrid').innerHTML = authors.map(a => {
    const cover = (a.cover_group && a.cover_work)
      ? '<img loading="lazy" src="' + coverUrl(a.cover_group, a.cover_work, (a.cover_mtime || 0) + '-' + (a.cover_pages || 0)) + '" alt="" onerror="this.closest(\'.circle-cover\').classList.add(\'noimg\')">'
      : '<div class="ph">👤</div>';
    return '<div class="circle-card tag clickable" data-type="personal" data-name="' + enc(a.name) +
      '" title="' + esc(tf('打开画师档案：%1', a.name)) + '">'
      + '<div class="circle-cover">' + cover + '</div>'
      + '<div class="circle-meta">'
      + '<div class="circle-name">' + esc(a.name) + '</div>'
      + '<div class="circle-sub">' + esc(tf('%1 部作品 · %2', a.count || 0, t('点看档案'))) + '</div>'
      + '</div></div>';
  }).join('');
  sec.classList.remove('hidden');
}

function hideSearchWorks() {
  ++searchWorksSeq;
  const sec = $('#searchWorksSection');
  if (sec) sec.classList.add('hidden');
  const asec = $('#searchAuthorsSection');
  if (asec) asec.classList.add('hidden');
}

/* 3.6.0 搜索视图渲染：隐藏首页专属区块与社团墙，仅展示搜索结果；可经 hash 返回 */
function renderSearchView(q) {
  hideHomeSections();                       // view!=='home' → 收起 hero/随机推荐
  $('#grid').classList.add('hidden');      // 隐藏首页社团墙
  $('#gridEmpty').classList.add('hidden');
  $('#viewHead').innerHTML = q && q.trim()
    ? '<h2>🔍 ' + esc(t('搜索：')) + esc(q.trim()) + '</h2>'
    : '<h2>🔍 ' + esc(t('搜索')) + '</h2><span class="sub">' + esc(t('输入关键词搜索社团 / 作品 / 画师')) + '</span>';
  if (q && q.trim()) loadSearchWorks(q.trim());
  else hideSearchWorks();
}

function renderRecs(lib) {
  const recs = lib.recommendations || [];
  if (!recs.length || state.filter.trim()) { $('#recSection').classList.add('hidden'); return; }
  $('#recSection').classList.remove('hidden');
  $('#recDate').textContent = t('每次刷新 / 重新扫描后换一批');
  const row = $('#recRow'); row.innerHTML = '';
  for (const r of recs) {
    const g = lib.groups.find(x => x.name === r.group);
    if (!g) continue;
    const d = document.createElement('div');
    d.className = 'rec-card';
    d.dataset.group = r.group;
    d.dataset.work = r.work;
    d.title = tf('点击在阅读器中打开：%1', dispName(r.work));
    d.innerHTML =
      // 封面区：长按 = 唤出操作菜单（data-nocopy 让长按复制不介入）
      '<div class="rec-cover" data-nocopy><img loading="lazy" src="' + coverUrl(r.group, r.work) + '" alt="" onerror="this.closest(\'.rec-cover\').classList.add(\'noimg\')"><span class="rec-badge">' + esc(t('随机推荐')) + '</span></div>' +
      '<div class="rec-meta">' +
        '<div class="rec-name">' + esc(r.work) + '</div>' +
        '<div class="rec-sub"><!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-building-2" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z" /> <path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2" /> <path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2" /> <path d="M10 6h4" /> <path d="M10 10h4" /> <path d="M10 14h4" /> <path d="M10 18h4" /> </svg> ' + esc(r.group) + (r.pages ? ' · ' + esc(tf('%1 页', r.pages)) : '') + '</div>' +
      '</div>';
    row.appendChild(d);
  }
}

/* ---------- 3.5.2 续读独立视图（#/resume）：右上角「📖 续读」一级入口 ----------
   取 /api/reading/resume（已排除读完），一次给到 100 条并带进度条。
   3.5.3：首页原先那条「继续阅读」横排已按用户要求撤掉，续读只留这一个入口 ——
   信息集中在入口页里，首页不必再重复一片概览。
   3.7.10：新增「区域内搜索框」——只筛选本页已加载的在读作品（作品名/社团名），
   与 APP 端续读页同款；输入即滤，无匹配时给对应空态。 */
async function renderResumeView() {
  hideEmpty(); hideGridEmpty();
  $('#viewHead').innerHTML =
    '<button class="back" id="btnBack">← ' + esc(t('返回')) + '</button>' +
    '<h2>📖 ' + esc(t('继续阅读')) + '</h2>' +
    '<input class="region-search" id="resumeSearch" placeholder="' + esc(t('筛选在读的作品 / 社团…')) + '">' +
    '<span class="sub">' + esc(t('读过但没读完的作品 · 按最近阅读排序 · 进度跨端同步')) + '</span>';
  const grid = $('#grid');
  grid.className = 'grid';
  grid.innerHTML = '<div class="panel entry-empty" style="grid-column:1/-1">' + esc(t('加载中…')) + '</div>';
  let items = [];
  try {
    const d = await api('/api/reading/resume?limit=100');
    items = d.items || [];
  } catch (e) {
    grid.innerHTML = '<div class="panel entry-empty" style="grid-column:1/-1">' + esc(tf('%1失败：%2', t('加载'), e.message)) + '</div>';
    return;
  }
  if (state.view !== 'resume') return;          // 期间已切走：丢弃过期结果
  const searchBox = $('#resumeSearch');
  const paint = () => {
    // 3.7.10 过滤：作品名/社团名包含即命中（忽略大小写）；顺手剔除 group/work 为空的残留记录
    const q = (searchBox.value || '').trim().toLowerCase();
    const shown = items.filter(it => it.work &&
      (!q || it.work.toLowerCase().includes(q) || (it.group || '').toLowerCase().includes(q)));
    if (!shown.length) {
      grid.innerHTML = '<div class="panel entry-empty" style="grid-column:1/-1">' +
        (q ? esc(tf('没有匹配「%1」的在读作品。', q))
           : esc(t('还没有读了一半的书。')) + '<br><span class="sub">'
             + esc(t('在首页随便翻开一部，读上几页，它就会出现在这里。')) + '</span>') + '</div>';
      return;
    }
    // 3.6.138（用户需求③）：续读卡片改回标准作品卡规格——3.5.2 起借用了每日推荐的
    // 16:9 横版 rec-card，3/4 竖版封面被裁成一条横幅，视觉上比正常作品卡小一圈。
    // 现改用 .card（与社团页/标签页同一规格）直接铺进 #grid；点击、长按、标签跳转
    // 全部走 menu.js 的 #grid 既有委托，不需要新绑事件。
    grid.innerHTML = '';
    const frag = document.createDocumentFragment();
    for (const it of shown) {
      const el = document.createElement('div');
      el.className = 'card';
      el.dataset.group = it.group || '收件箱';   // i18n:data 真实社团名（标识符）
      el.dataset.work = it.work;
      el.title = tf('点击继续阅读：%1', dispName(it.work));
      const pct = it.pages ? Math.max(2, Math.min(100, Math.round(((it.last_page || 0) + 1) / it.pages * 100))) : 0;
      el.innerHTML =
        // 封面区：长按 = 唤出操作菜单（data-nocopy 让长按复制不介入）
        '<div class="cover-wrap" data-nocopy>' +
          '<img loading="lazy" src="' + coverUrl(it.group, it.work) + '" alt="" onerror="this.closest(\'.cover-wrap\').classList.add(\'noimg\')">' +
          '<span class="rec-badge">' + esc(tf('读到 %1 / %2', (it.last_page || 0) + 1, it.pages || '?')) + '</span>' +
        '</div>' +
        '<div class="meta">' +
          '<div class="title">' + esc(it.work) + '</div>' +
          // 3.6.15 需求1：续读卡片标签化 —— 社团标签（可点进社团）+ 合作画师标签（可点进画师档案）
          '<div class="tag-row card-tags">' +
            ((it.group && it.group !== '收件箱')
              ? '<span class="tag t-group clickable" data-type="circle" data-name="' + esc(it.circle || it.group) + '" title="' + esc(t('进入社团')) + '">🏢 ' + esc(it.circle || it.group) + '</span>'
              : '') +
            (it.personals || []).map(a => '<span class="tag t-personal clickable" data-type="personal" data-name="' + esc(a) + '" title="' + esc(t('查看该作者全部作品（跨社团）')) + '">👤 ' + esc(a) + '</span>').join('') +
          '</div>' +
          '<div class="resume-bar"><div style="width:' + pct + '%"></div></div>' +
        '</div>';
      frag.appendChild(el);
    }
    grid.appendChild(frag);
  };
  searchBox.addEventListener('input', paint);
  paint();
}

/* ---------- 3.5.1 喜爱画师独立视图（#/loved）：右上角「❤ 喜爱」一级入口 ----------
   数据取 /api/follows（作品数 + 自上次查看以来的新作品数）；卡片沿用首页「全部画师」分区
   的样式，点 ❤ 直接取消喜爱。原先这里没有入口，要连点 3 次 chip 才切得到。 */
/* ---------- 3.5.1 喜爱画师独立视图（#/loved）：右上角「❤ 喜爱」一级入口 ----------
   数据取 /api/follows（作品数）；卡片沿用首页「全部画师」分区的样式，点 ❤ 直接取消喜爱。
   原先这里没有入口，要连点 3 次 chip 才切得到。
   3.7.10：① 新增区域内搜索框（只筛选本页已加载的喜爱画师，与 APP 端同款）；
   ② 移除左上角「有新 N」计数红点——用户明确该系统不需要红点。 */
async function renderLovedView() {
  hideEmpty(); hideGridEmpty();
  $('#viewHead').innerHTML =
    '<button class="back" id="btnBack">← ' + esc(t('返回')) + '</button>' +
    '<h2>❤ ' + esc(t('喜爱的画师')) + '</h2>' +
    '<input class="region-search" id="lovedSearch" placeholder="' + esc(t('筛选喜爱的画师…')) + '">' +
    '<span class="sub">' + esc(t('点卡片进画师档案 · 点 ❤ 取消喜爱')) + '</span>';
  const grid = $('#grid');
  grid.className = 'grid';
  grid.innerHTML = '<div class="panel entry-empty" style="grid-column:1/-1">' + esc(t('加载中…')) + '</div>';
  let follows = [];
  try {
    const d = await api('/api/follows');
    follows = d.follows || [];
  } catch (e) {
    grid.innerHTML = '<div class="panel entry-empty" style="grid-column:1/-1">' + esc(tf('%1失败：%2', t('加载'), e.message)) + '</div>';
    return;
  }
  if (state.view !== 'loved') return;
  if (!follows.length) {
    grid.innerHTML = '<div class="panel entry-empty" style="grid-column:1/-1">' +
      esc(t('还没有喜爱的画师。')) + '<br><span class="sub">' +
      esc(t('在首页切到「全部画师」，或打开任意画师档案，点卡片右下角的 ❤ 就会收藏到这里。')) + '</span></div>';
    return;
  }
  const searchBox = $('#lovedSearch');
  const paint = () => {
    // 3.7.10 过滤：画师名包含即命中（忽略大小写）
    const q = (searchBox.value || '').trim().toLowerCase();
    const shown = q ? follows.filter(f => f.author.toLowerCase().includes(q)) : follows;
    if (!shown.length) {
      grid.innerHTML = '<div class="panel entry-empty" style="grid-column:1/-1">' + esc(tf('没有匹配「%1」的喜爱画师。', q)) + '</div>';
      return;
    }
    grid.innerHTML = '';
    const frag = document.createDocumentFragment();
    for (const f of shown) {
      const card = document.createElement('div');
      card.className = 'circle-card';
      card.dataset.artist = f.author;             // #grid 全局委托据此跳画师档案
      card.title = tf('点击打开画师档案：%1', f.author);
      const cover = (f.cover_group && f.cover_work)
        ? '<img loading="lazy" src="' + coverUrl(f.cover_group, f.cover_work, (f.cover_mtime || 0) + '-' + (f.cover_pages || 0)) + '" alt="" onerror="this.closest(\'.circle-cover\').classList.add(\'noimg\')">'
        : '<div class="ph">👤</div>';
      card.innerHTML =
        '<div class="circle-cover">' + cover +
          '<span class="artist-heart on" data-unfav="' + esc(f.author) + '" title="' + esc(t('取消喜爱')) + '">❤</span>' +
        '</div>' +
        '<div class="circle-meta">' +
          '<div class="circle-name">' + esc(f.author) + '</div>' +
          '<div class="circle-sub">' + esc(tf('%1 部作品', f.works || 0)) + '</div>' +
        '</div>';
      frag.appendChild(card);
    }
    grid.appendChild(frag);
    grid.querySelectorAll('[data-unfav]').forEach(h => h.addEventListener('click', async ev => {
      ev.stopPropagation();                       // 别让冒泡触发"打开画师档案"
      const card = h.closest('.circle-card');
      try {
        const r = await api('/api/follow/unfollow',
          { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ author: h.dataset.unfav }) });
        showToast(r.message || t('已取消喜爱'));
        if (card) card.remove();
      } catch (e) { showToast(tf('%1：%2', t('失败'), e.message)); }
    }));
  };
  searchBox.addEventListener('input', paint);
  paint();
}
