/* 本地同人志文库 前端 · tag.js
   标签全局检索、画师档案、作品卡片
   3.6.84 从 static/app.js 拆出：按顶层区块切分，仍是 classic script，
   与其余分片共享同一个全局词法环境（顺序加载，勿调整 index.html 里的 <script> 次序）。 */
'use strict';

/* ---------- 标签全局检索页 ---------- */
let tagSeq = 0;
async function loadTag() {
  const seq = ++tagSeq;
  const type = state.tagType, tag = state.tagName;
  $('#statusText').textContent = tf('检索标签：%1', tag);
  try {
    const data = await api('/api/works?type=' + enc(type) + '&tag=' + enc(tag));
    if (seq !== tagSeq || state.view !== 'tag' || state.tagType !== type || state.tagName !== tag) return;
    state.tagWorks = data.works;
    state.tagAuthorCircles = data.authorCircles || [];   // 作者页的双向交叉引用（作者→社团分布）
    renderTag(type, tag, data.works);
    restoreScroll();
  } catch (e) {
    if (seq !== tagSeq) return;
    showToast(tf('%1失败：%2', t('检索'), e.message));
    state.tagWorks = null;
    location.hash = '#/';
  }
}

function renderTag(type, tag, works) {
  hideEmpty(); hideGridEmpty();
  const labels = { original:t('同人'), event:t('展会'), personal:t('画师'), group:t('汉化组'), other:t('其他') };
  if (!labels[type]) type = 'other';         // 防御：type 来自 URL hash，白名单外一律归入 other（防 XSS）
  const filtered = works.filter(it => matchesFilter(state.filter, it.work.name, it.work.personal, it.group,
    (it.work.tags || []).map(t => t.name).join(' ')));
  // 作者页头部：所属社团 chips（跨社团聚合的双向引用）+ 笔名别名管理
  let xref = '';
  if (type === 'personal') {
    const ac = state.tagAuthorCircles || [];
    if (ac.length > 1) {
      xref = '<div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:6px;align-items:center">' +
        '<span style="color:var(--muted);font-size:12px">' + esc(t('该作者作品分布于：')) + '</span>' +
        ac.map(c => '<span class="tag t-other clickable" data-xref-circle="' + esc(c.name) + '" title="' + esc(t('进入社团')) + '">' + esc(c.name) + esc(tf('（%1）', c.count)) + '</span>').join('') +
        '</div>';
    }
    xref += '<div style="margin-top:6px;display:flex;gap:8px;flex-wrap:wrap">' +
      '<button id="btnAlias" class="back" title="' + esc(tf('把另一个笔名归并到「%1」名下（重扫后生效）', tag)) + '">🔗 ' + esc(t('笔名别名')) + '</button>' +
      '<a class="back" href="#/artist/' + enc(tag) + '" title="' + esc(t('画师档案：时间线 + 关注')) + '">📖 ' + esc(t('画师档案')) + '</a>' +
      // 3.7.54：右上角「⛏ 爬取该画师」——站点标题里的 `[社团 (作者)]` 会逐字命中
      '<a class="back" style="margin-left:auto" href="#/probe?kind=author&term=' + enc(tag) +
      '" title="' + esc(t('按画师名到站点搜索：勾选要下载的作品，下载完自动入库归区')) + '">⛏ ' + esc(t('联网获取该画师')) + '</a></div>';
  }
  // 3.7.22 #26：原作分区页加「原作别名」入口（与笔名别名同交互；
  // 该写法已建立的分区会整体并入本分区——后端 originals_merge 落地）
  if (type === 'original') {
    // 3.6.27 需求3：头部对齐画师页——列出本分区的**画师标签 + 社团标签**（可点跳转）。
    // 原作分区没有画师页那个"喜爱"键，其余规格一致。
    const ac = {}, cc = {};
    filtered.forEach(it => {
      const ws = it.work;
      const auths = (ws.personals && ws.personals.length) ? ws.personals
        : (ws.personal ? [ws.personal] : []);
      auths.forEach(a => { ac[a] = (ac[a] || 0) + 1; });
      const c = (ws.circle && ws.circle.length) ? ws.circle : it.group;
      if (c) cc[c] = (cc[c] || 0) + 1;
    });
    const aArr = Object.entries(ac).sort((a, b) => b[1] - a[1]);
    const cArr = Object.entries(cc).sort((a, b) => b[1] - a[1]);
    if (aArr.length || cArr.length) {
      xref += '<div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:6px;align-items:center">' +
        aArr.map(([n, c]) => '<span class="tag t-personal clickable" data-type="personal" data-name="' +
          esc(n) + '" title="' + esc(t('查看该作者全部作品（跨社团）')) + '">👤 ' + esc(n) + esc(tf('（%1）', c)) + '</span>').join('') +
        cArr.map(([n, c]) => '<span class="tag t-group clickable" data-type="circle" data-name="' +
          esc(n) + '" title="' + esc(t('进入社团')) + '">🏢 ' + esc(n) + esc(tf('（%1）', c)) + '</span>').join('') +
        '</div>';
    }
    xref += '<div style="margin-top:6px;display:flex;gap:8px;flex-wrap:wrap">' +
      '<button id="btnOrigAddWorks" class="back" title="' + esc(t('搜索库内作品，手动加入本分区（文件名没有同人词条、解析器识别不了的作品用这个；只写标签，不动文件）')) + '">＋ ' + esc(t('添加作品')) + '</button>' +
      '<button id="btnOrigAlias" class="back" title="' + esc(tf('把同人名的其他写法归并到「%1」名下（重扫后生效；该写法已建立的分区会整体并入）', tag)) + '">🔗 ' + esc(t('同人别名')) + '</button>' +
      '<button id="btnOrigRename" class="back" title="' + esc(t('给这个同人分区改名（只搬标签，零文件操作；名字按你输入的来，不做宽松归一；仅写法不同时会自动保留旧名为别名）')) + '">✏ ' + esc(t('分区改名')) + '</button>' +
      '<button id="btnOrigRemove" class="back" title="' + esc(t('移除这个同人分区（作品不动；同时删掉词条库里的对应词条）')) + '">🗑 ' + esc(t('移除分区')) + '</button>' +
      // 3.7.54：右上角「⛏ 爬取该分区」——勾选下载后自动把作品挂到本原作分区
      '<a class="back" style="margin-left:auto" href="#/probe?kind=original&term=' + enc(tag) +
      '" title="' + esc(t('按同人名到站点搜索：勾选要下载的作品，下载完自动入库并挂到本分区')) + '">⛏ ' + esc(t('联网获取该分区')) + '</a></div>';
  }
  $('#viewHead').innerHTML =
    '<button class="back" id="btnBack">← ' + esc(t('返回')) + '</button>' +
    '<h2><!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-tags" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="m15 5 6.3 6.3a2.4 2.4 0 0 1 0 3.4L17 19" /> <path d="M9.586 5.586A2 2 0 0 0 8.172 5H3a1 1 0 0 0-1 1v5.172a2 2 0 0 0 .586 1.414L8.29 18.29a2.426 2.426 0 0 0 3.42 0l3.58-3.58a2.426 2.426 0 0 0 0-3.42z" /> <circle cx="6.5" cy="9.5" r=".5" fill="currentColor" /> </svg> <span class="tag t-' + type + '">' + esc(tag) + '</span>' +
    ' <span class="sub">' + esc(tf('%1标签 · 全局 %2 部作品（跨社团）', labels[type], filtered.length)) + '</span></h2>' + xref +
    // 3.6.151：分区内作品排序（时间 / 文件大小 / 名称）
    workSortBarHtml();
  // 3.7.41：旧名只作**展示标签**——不跳转、不带删除叉，可选中复制。
  // （3.6.41 在这里加的 × 是误解需求：用户要的是"改名输入框右侧的清空叉"，
  //  那个在 APP 改名对话框里；网页端 prompt 无法内嵌按钮，故此处只做展示。）
  if (type === 'original') {
    api('/api/author-aliases?kind=original').then(al => {
      const mine = Object.entries(al.aliases || {})
        .filter(([, c]) => c === tag).map(([a]) => a);
      if (!mine.length) return;
      const box = $('#viewHead');
      if (!box) return;
      const el = document.createElement('div');
      el.style.cssText = 'margin-top:6px;display:flex;gap:6px;flex-wrap:wrap;align-items:center';
      el.innerHTML = '<span style="color:var(--muted);font-size:12px">' + esc(t('旧名')) + '</span>' +
        mine.map(a => '<span class="tag t-original" style="user-select:text">' +
          esc(a) + '</span>').join('');
      box.appendChild(el);
    }).catch(() => { /* 别名列表拿不到不影响主体渲染 */ });
  }
  const btnAlias = $('#btnAlias');
  if (btnAlias) btnAlias.addEventListener('click', async () => {
    const alias = prompt(tf('把哪个笔名归并到「%1」？\n\n输入别名（如旧笔名/译名差异），保存后全库重扫，\n该笔名的所有作品将归并显示到「%1」名下。', tag));
    if (!alias || !alias.trim()) return;
    try {
      const r = await api('/api/author-aliases', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alias: alias.trim(), canonical: tag }) });
      showToast(r.message || t('已登记'));
      await refresh(true);
    } catch (e) { showToast(tf('%1失败：%2', t('登记'), e.message)); }
  });
  // 3.7.22 #26：原作别名登记（kind=original）——后端把别名分区整体并入本分区
  const btnOrigAlias = $('#btnOrigAlias');
  if (btnOrigAlias) btnOrigAlias.addEventListener('click', async () => {
    const alias = prompt(tf('把同人名的哪个写法归并到「%1」？\n\n输入别名（如 FGO → FateGrand Order），保存后该写法的分区\n将整体并入「%1」，作品不移动、进度/收藏不受影响。', tag));
    if (!alias || !alias.trim()) return;
    try {
      const r = await api('/api/author-aliases', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alias: alias.trim(), canonical: tag, kind: 'original' }) });
      showToast(r.message || t('已登记'));
      await refresh(true);
    } catch (e) { showToast(tf('%1失败：%2', t('登记'), e.message)); }
  });
  // 3.6.21：原作分区自己的操作栏（改名 / 移除）——与画师页「重命名」同级
  const btnOrigRename = $('#btnOrigRename');
  if (btnOrigRename) btnOrigRename.addEventListener('click', () => apiRenameOriginal(tag));
  const btnOrigRemove = $('#btnOrigRemove');
  if (btnOrigRemove) btnOrigRemove.addEventListener('click', () => apiRemoveOriginal(tag));
  // 3.6.36 #33：分区内手动添加作品（搜索库内作品 → 勾选 → 写 original 标签）
  const btnOrigAddWorks = $('#btnOrigAddWorks');
  if (btnOrigAddWorks) btnOrigAddWorks.addEventListener('click', () => showAddWorksModal(tag));
  const grid = $('#grid'); grid.className = 'grid'; grid.innerHTML = '';
  if (!filtered.length) { showGridEmpty('<!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-search" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <circle cx="11" cy="11" r="8" /> <path d="m21 21-4.3-4.3" /> </svg> ' + esc(t('没有匹配的作品')), t('换个关键词试试。')); return; }
  const frag = document.createDocumentFragment();
  // 3.6.151：分区内作品列表排序（时间 / 文件大小 / 名称）；入参是 {work, group} 包装
  for (const it of sortWorks(filtered, x => x.work)) frag.appendChild(makeWorkCard(it.group, it.work, true));
  grid.appendChild(frag);
}

/* ---------- 画师档案页（M4）：跨社团作品 + 入库时间线 + 关注 ---------- */
let artistSeq = 0;
async function loadArtist() {
  const seq = ++artistSeq;
  const name = state.artistName;
  $('#statusText').textContent = tf('加载画师：%1', name);
  try {
    const data = await api('/api/artist/' + enc(name));
    if (seq !== artistSeq || state.view !== 'artist' || state.artistName !== name) return;
    state.artistData = data;
    renderArtist(data);
    restoreScroll();
  } catch (e) {
    if (seq !== artistSeq) return;
    showToast(tf('%1失败：%2', t('加载'), e.message));
    location.hash = '#/';
  }
}

function renderArtist(d) {
  hideEmpty(); hideGridEmpty();
  const circles = (d.circles || []).map(c =>
    '<span class="tag t-other clickable" data-xref-circle="' + esc(c.name) + '" title="' + esc(t('进入社团')) + '">🏢 ' + esc(c.name) + esc(tf('（%1）', c.count)) + '</span>').join('');
  const aliases = (d.aliases || []).map(a => '<span class="tag t-personal">' + esc(a) + '</span>').join('');
  // 画师封面（设为画师封面后在此立即可见；无覆盖时回退派生封面，都可能为空）
  const coverHtml = (d.cover_group && d.cover_work)
    ? '<div style="width:100%;height:128px;overflow:hidden;border-radius:10px;margin:6px 0;background:var(--bg-soft)">' +
      '<img loading="lazy" src="' + coverUrl(d.cover_group, d.cover_work, d.cover_mtime) +
      '" alt="' + esc(t('画师封面')) + '" style="width:100%;height:100%;object-fit:cover" onerror="this.parentNode.style.display=\'none\'"></div>'
    : '';
  $('#viewHead').innerHTML =
    '<button class="back" id="btnBack">← ' + esc(t('返回')) + '</button>' +
    coverHtml +
    '<h2 title="' + esc(t('长按 / 右键唤出操作菜单（改名/合并）')) + '">👤 ' + esc(d.author) + (d.author !== d.queried ? ' <span class="sub">（' + esc(d.queried) + '）</span>' : '') +
    ' <span class="sub">' + esc(tf('档案 · %1 部作品 · %2 个社团', d.total, (d.circles || []).length)) + '</span></h2>' +
    '<div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:6px;align-items:center">' +
      '<button id="btnFollow" class="' + (d.is_following ? 'primary' : '') + '">' + (d.is_following ? esc(t('❤ 已喜爱')) : esc(t('🤍 喜爱'))) + '</button>' +
      (aliases ? '<span style="color:var(--muted);font-size:12px">' + esc(t('别名：')) + '</span>' + aliases : '') +
      (circles ? '<span style="color:var(--muted);font-size:12px">' + esc(t('社团：')) + '</span>' + circles : '') +
      '<a class="back" href="#/tag/personal/' + enc(d.author) + '" title="' + esc(t('笔名别名管理 + 按标签检索')) + '">✏ ' + esc(t('别名管理')) + '</a>' +
    '</div>' +
    // 3.6.151：画师页作品排序（时间 / 文件大小 / 名称）
    workSortBarHtml();
  $('#btnFollow').addEventListener('click', async () => {
    try {
      const r = await api(d.is_following ? '/api/follow/unfollow' : '/api/follow',
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ author: d.author }) });
      showToast(r.message || t('完成'));
      loadArtist();      // is_following 翻转；关注时盖 last_seen 基准
    } catch (e) { showToast(tf('%1：%2', t('失败'), e.message)); }
  });
  const grid = $('#grid'); grid.className = 'grid'; grid.innerHTML = '';
  // 3.6.151：改走统一的作品排序（默认按入库时间新→旧，与旧行为一致；新增按大小/名称）
  const works = sortWorks(d.works || []);
  if (!works.length) {
    showGridEmpty(t('没有该画师的作品'), t('可能作品尚未入库，或词条尚未关联到这位画师。'));
    return;
  }
  const frag = document.createDocumentFragment();
  for (const w of works) {
    // 3.6.15 需求3：作品卡片不显示本画师标签，只渲染合作画师（personals 已透传全部作者，滤掉自身）
    const others = (w.personals || []).filter(a => a !== d.author);
    const card = makeWorkCard(w.group,
      { name: w.work, pages: w.pages, hasCover: true, ver: '', personals: others }, true, true);
    if (w.added_at) {
      const tl = document.createElement('div');
      tl.className = 'timeline-date';
      tl.textContent = tf('📥 %1 入库', new Date(w.added_at * 1000).toLocaleDateString(i18nLang()));
      card.appendChild(tl);
    }
    frag.appendChild(card);
  }
  grid.appendChild(frag);
}

/* ---------- 作品卡片 ---------- */
function makeWorkCard(group, w, showGroup, suppressEmptyAuthor) {
  const card = document.createElement('div');
  card.className = 'card';
  card.dataset.group = group;
  card.dataset.work = w.name;
  const cover = w.hasCover
    ? '<img loading="lazy" src="' + coverUrl(group, w.name, w.ver) + '" alt="" onerror="this.closest(\'.cover-wrap\').classList.add(\'noimg\')">'
    : '<div class="ph"><!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-file-text" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /> <path d="M14 2v4a2 2 0 0 0 2 2h4" /> <path d="M10 9H8" /> <path d="M16 13H8" /> <path d="M16 17H8" /> </svg></div>';
  const pages = w.pages ? '<span class="pages">' + esc(tf('%1 页', w.pages)) + '</span>' : '';
  // 3.1/3.2 阅读消费端角标：已读完 ✓ / 读到第 n 页 / 新入库
  const rd = rdStateOf(group, w.name);
  const rdbadge = ((rd && rd.f) ? '<span class="rd-badge done" title="' + esc(t('已读完')) + '">' + esc(t('✓ 已读')) + '</span>'
      : (rd ? '<span class="rd-badge" title="' + esc(tf('上次读到第 %1 页', rd.p + 1)) + '">' + esc(tf('读%1', rd.p + 1)) + '</span>' : ''))
    + (isNewWork(group, w.name) ? '<span class="rd-badge new" title="' + esc(t('上次访问后新入库')) + '">' + esc(t('新')) + '</span>' : '');
  // 作者多值：合作作品每人一个 chip，点击跳作者聚合页（跨社团）；个人名字段归一后展示
  // 3.6.14：画师 chips 从封面上方移入卡片下方标签区，与社团标签并列——长按均直接复制名称
  const authors = (w.personals && w.personals.length ? w.personals : (w.personal ? [w.personal] : []));
  const authorTags = authors.length
    ? authors.map(a => '<span class="tag t-personal clickable" data-type="personal" data-name="' + esc(a) + '" title="' + esc(t('查看该作者全部作品（跨社团）；长按复制名字')) + '">👤 ' + esc(a) + '</span>').join('')
    : (suppressEmptyAuthor ? '' : '<span class="tag t-empty" data-nocopy title="' + esc(t('尚未识别到画师')) + '">' + esc(t('— 未标注画师')) + '</span>');
  const pendingTag = (w.bare && !w.personal) ? '<em class="pending-tag">' + esc(t('待定')) + '</em>' : '';
  // 3.6.14：所属社团由纯文字行改为社团标签（点击进社团页、长按复制社团名），与画师 chips
  // 同区展示；社团页内（showGroup=false）不显示。
  const groupTag = showGroup
    ? '<span class="tag t-group clickable" data-type="circle" data-name="' + esc(group) + '" title="' + esc(t('进入社团；长按复制社团名')) + '">🏢 ' + esc(group) + '</span>'
    : '';
  const tags = (w.tags || []).map(t =>
    '<span class="tag t-' + esc(t.type) + ' clickable" data-type="' + esc(t.type) + '" data-name="' + esc(t.name) + '">' + esc(t.name) + '</span>'
  ).join('');
  card.innerHTML =
    // 封面区：长按 = 唤出操作菜单（data-nocopy 让长按复制不介入，避免两个浮层叠弹）
    '<div class="cover-wrap" data-nocopy title="' + esc(t('点击阅读；长按唤出操作菜单')) + '">' + cover + pages + rdbadge + '<span class="open-img" title="' + esc(t('阅读器翻页浏览')) + '"><!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-book-open" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M12 7v14" /> <path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z" /> </svg></span></div>' +
    '<div class="meta">' +
      '<div class="title" title="' + esc(t('点击阅读全部页面')) + '">' + esc(w.name) + '</div>' +
      '<div class="tag-row card-tags">' + authorTags + groupTag + pendingTag + tags + '</div>' +
      '<div class="acts">' +
        '<button data-act="read" title="' + esc(t('阅读器内翻页浏览全部页面')) + '"><!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-book-open" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M12 7v14" /> <path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z" /> </svg> ' + esc(t('阅读')) + '</button>' +
        '<button data-act="image" title="' + esc(t('用系统默认图片查看器打开首张图片')) + '"><!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-image" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <rect width="18" height="18" x="3" y="3" rx="2" ry="2" /> <circle cx="9" cy="9" r="2" /> <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" /> </svg> ' + esc(t('图片')) + '</button>' +
        '<button data-act="folder" title="' + esc(t('打开作品文件夹 / 压缩包')) + '"><!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-folder" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" /> </svg> ' + esc(t('文件夹')) + '</button>' +
      '</div>' +
    '</div>';
  return card;
}
