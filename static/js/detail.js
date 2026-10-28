/* 本地同人志文库 前端 · detail.js
   社团详情页与「增补信息」表单
   3.6.84 从 static/app.js 拆出：按顶层区块切分，仍是 classic script，
   与其余分片共享同一个全局词法环境（顺序加载，勿调整 index.html 里的 <script> 次序）。 */
'use strict';

/* ---------- 社团详情页 ---------- */
let circleSeq = 0;
async function loadCircle() {
  const seq = ++circleSeq;
  const name = state.circleName;
  $('#statusText').textContent = tf('加载社团：%1', name);
  try {
    const data = await api('/api/circle/' + enc(name));
    // 3.3.0 竞态守卫：快速连续导航时旧响应不得渲染（与 loadSearchWorks 同款守卫）
    if (seq !== circleSeq || state.view !== 'circle' || state.circleName !== name) return;
    state.circleGroup = data.group;
    state.circleWorks = data.works;
    state.circleAuthors = data.authors || [];   // 双向交叉引用：社团→作者聚合
    renderCircle(data.group, data.works);
    restoreScroll();
  } catch (e) {
    if (seq !== circleSeq) return;
    showToast(tf('%1失败：%2', t('加载'), e.message));
    state.circleGroup = null;
    state.circleWorks = null;
    location.hash = '#/';
  }
}

function renderCircle(group, works) {
  hideEmpty(); hideGridEmpty();
  if (!group || typeof group !== 'object') return;   // 防御：group 必须是对象（搜索时来自 state.circleGroup）
  const filtered = works.filter(w => matchesFilter(state.filter, w.name, w.personal,
    (w.tags || []).map(t => t.name).join(' ')));
  // 社团 → 作者 chips（点击跳作者聚合页，展示该作者跨社团的全部作品）
  const authors = state.circleAuthors || [];
  const authorChips = authors.length
    ? '<div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:6px;align-items:center">' +
      '<span style="color:var(--muted);font-size:12px">' + esc(t('该社团作者：')) + '</span>' +
      authors.map(a => '<span class="tag t-personal clickable" data-type="personal" data-name="' + esc(a.name) + '" title="' + esc(t('查看该作者全部作品（跨社团）')) + '">👤 ' + esc(a.name) + esc(tf('（%1）', a.count)) + '</span>').join('') +
      '</div>'
    : '';
  // 社团封面（设为社团封面后在此立即可见）
  const coverHtml = (group.coverGroup && group.coverWork)
    ? '<div style="width:100%;height:128px;overflow:hidden;border-radius:10px;margin:6px 0;background:var(--bg-soft)">' +
      '<img loading="lazy" src="' + coverUrl(group.coverGroup, group.coverWork, group.coverMtime) +
      '" alt="' + esc(t('社团封面')) + '" style="width:100%;height:100%;object-fit:cover" onerror="this.parentNode.style.display=\'none\'"></div>'
    : '';
  // 3.6.11 社团别名登记（与画师页的「笔名别名」对称）：把另一个社团名归并到本社团名下
  // 3.7.54：右上角加「⛏ 爬取该社团」——按社团名到站点搜索、勾选下载、自动入库归区
  const aliasBar = '<div style="margin-top:6px;display:flex;gap:8px;flex-wrap:wrap">' +
    '<button id="btnCircleAlias" class="back" title="' + esc(tf('把另一个社团名归并到「%1」名下（重扫后生效）', group.name)) + '">🔗 ' + esc(t('社团别名')) + '</button>' +
    '<a class="back" style="margin-left:auto" href="#/probe?kind=circle&term=' + enc(group.name) +
    '" title="' + esc(t('按社团名到站点搜索：勾选要下载的作品，下载完自动入库到本社团')) + '">⛏ ' + esc(t('联网获取该社团')) + '</a></div>';
  $('#viewHead').innerHTML =
    '<button class="back" id="btnBack">← ' + esc(t('全部社团')) + '</button>' +
    coverHtml +
    '<h2 title="' + esc(t('长按 / 右键唤出操作菜单（改名/合并）')) + '"><!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-building-2" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z" /> <path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2" /> <path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2" /> <path d="M10 6h4" /> <path d="M10 10h4" /> <path d="M10 14h4" /> <path d="M10 18h4" /> </svg> ' + esc(group.name) + '</h2>' +
    '<span class="sub">' + esc(tf('%1 部作品 · 最新作品更新于 %2', group.workCount, fmtDate(group.coverMtime))) + '</span>' +
    authorChips + aliasBar +
    // 3.6.151：作品列表排序（时间 / 文件大小 / 名称）——查重时按大小排，重复下载的挨在一起
    workSortBarHtml();
  const btnCircleAlias = $('#btnCircleAlias');
  if (btnCircleAlias) btnCircleAlias.addEventListener('click', async () => {
    const alias = prompt(tf('把哪个社团名归并到「%1」？\n\n登记后该社团不再单列，其作品并入本社团（文件不移动，可随时删除别名撤销）。', group.name));
    if (!alias || !alias.trim()) return;
    try {
      const r = await api('/api/author-aliases', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alias: alias.trim(), canonical: group.name, kind: 'circle' }) });
      showToast(r.message || t('已登记'));
      await refresh(true);
    } catch (e) { showToast(tf('%1失败：%2', t('登记'), e.message)); }
  });
  const grid = $('#grid'); grid.className = 'grid'; grid.innerHTML = '';
  if (!filtered.length) { showGridEmpty('<!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-search" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <circle cx="11" cy="11" r="8" /> <path d="m21 21-4.3-4.3" /> </svg> ' + esc(t('没有匹配的作品')), t('换个关键词试试。')); return; }
  const frag = document.createDocumentFragment();
  for (const w of sortWorks(filtered)) frag.appendChild(makeWorkCard(group.name, w, false));
  grid.appendChild(frag);
}

/* ---------- 三级界面：增补信息表单（无修正/展会/社团名/个人名/名称/原作名） ---------- */
function openInfo(group, work) {
  state.infoReturn = location.hash || '#/';
  location.hash = '#/info/' + enc(group || '收件箱') + '/' + enc(work);
}

async function loadInfoForm() {
  const group = state.infoGroup || '收件箱';   // i18n:data 真实社团名
  const work = state.infoWork;
  $('#statusText').textContent = t('增补信息…');
  const url = '/api/parse-info?group=' + enc(group) + '&work=' + enc(work);
  try {
    const info = await api(url);
    renderInfoForm(info);
  } catch (e) {
    // 首次失败：强制重扫一次再重试（兼容 exFAT 目录刷新延迟）
    try {
      state.lib = await api('/api/library?refresh=1');
      updateStatus();
      const info = await api(url);
      renderInfoForm(info);
      return;
    } catch (e2) {
      showToast(tf('%1失败：%2', t('加载'), e2.message));
      location.hash = state.infoReturn || '#/';
    }
  }
}

function renderInfoForm(info) {
  hideEmpty(); hideGridEmpty();
  const group = state.infoGroup || '收件箱';   // i18n:data 真实社团名
  state.infoData = info;                        // 缓存解析结果，供模式切换时重渲染
  state.infoMode = state.infoMode || 'fields';  // 'fields' 逐字段 | 'title' 整标题
  const infoMode = state.infoMode;
  $('#viewHead').innerHTML =
    '<button class="back" id="btnBack">← ' + esc(t('返回')) + '</button>' +
    '<h2><!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-pen-line" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M12 20h9" /> <path d="M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.854z" /> </svg> ' + esc(t('增补信息')) + ' · ' + esc(group) + '</h2>' +
    '<span class="sub">' + (infoMode === 'title'
      ? esc(t('整标题模式：把完整标题整串粘进来，程序自动判定各部分词条、标准化后按社团归档'))
      : esc(t('填写词条（留空则沿用自动解析结果），点击“填写完成”后自动生成规范文件名并归档'))) + '</span>';
  const grid = $('#grid');
  grid.className = 'grid grid-list';
  grid.innerHTML =
    '<div class="info-form">' +
      '<div class="info-file"><!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-file-text" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /> <path d="M14 2v4a2 2 0 0 0 2 2h4" /> <path d="M10 9H8" /> <path d="M16 13H8" /> <path d="M16 17H8" /> </svg> ' + esc(t('所属：')) + esc(group) + '<br>' + esc(info.file) + '</div>' +
      '<label class="info-check"><input type="checkbox" id="if-uncensored"' + (info.uncensored ? ' checked' : '') + '> <span>' + esc(t('无修正（文件名前置 [無修正]）')) + '</span></label>' +
      '<label for="if-event">' + esc(t('展会：')) + '</label>' +
      '<input type="text" id="if-event" value="' + esc(info.event) + '" placeholder="' + esc(t('例如 C101 / FF35')) + '">' +
      '<label for="if-circle">' + esc(t('社团名：')) + '</label>' +
      '<input type="text" id="if-circle" value="' + esc(info.circle) + '" placeholder="' + esc(t('例如 蜂巢 (Apoidea)')) + '">' +
      '<label for="if-personal">' + esc(t('个人名：')) + '</label>' +
      '<input type="text" id="if-personal" value="' + esc(info.personal) + '" placeholder="' + esc(t('画师名（合作作品多名用 & 分隔，如 A & B）')) + '">' +
      '<label for="if-title">' + esc(t('名称：')) + '</label>' +
      '<input type="text" id="if-title" value="' + esc(info.title) + '" placeholder="' + esc(t('作品标题')) + '">' +
      '<label for="if-original">' + esc(t('同人名：')) + '</label>' +
      '<input type="text" id="if-original" value="' + esc(info.original) + '" placeholder="' + esc(t('例如 原神 / Fate')) + '">' +
      '<label for="if-translator">' + esc(t('汉化组：')) + '</label>' +
      '<input type="text" id="if-translator" value="' + esc(info.translator || '') + '" placeholder="' + esc(t('例如 無邪気漢化組（多个用空格分隔，存为 【…】）')) + '">' +
      '<label for="if-otherinfo">' + esc(t('其他信息：')) + '</label>' +
      '<input type="text" id="if-otherinfo" value="' + esc(info.other_info || '') + '" placeholder="' + esc(t('整标题里其余有效内容（语言标记/其他词条，空格分隔）')) + '">' +
      '<div class="info-actions">' +
        '<button id="btnInfoCancel">' + esc(t('取消')) + '</button>' +
        '<button id="btnInfoSave" class="primary">' + esc(t('填写完成')) + '</button>' +
      '</div>' +
    '</div>';
  // ---- 模式切换：逐字段 ↔ 整标题（整标题只留一个输入框，程序自动判定各部分词条）----
  const form = grid.querySelector('.info-form');
  form.insertAdjacentHTML('afterbegin',
    '<div class="info-modes">' +
      '<button type="button" id="modeFields" class="' + (infoMode === 'fields' ? 'on' : '') + '">' + esc(t('逐字段')) + '</button>' +
      '<button type="button" id="modeTitle" class="' + (infoMode === 'title' ? 'on' : '') + '">' + esc(t('整标题')) + '</button>' +
    '</div>');
  if (infoMode === 'title') {
    // 逐字段控件隐藏（保留在 DOM 中，切回来即恢复）
    form.querySelectorAll('label, input, textarea, .info-check')
        .forEach(el => { el.style.display = 'none'; });
    form.querySelector('.info-actions').insertAdjacentHTML('beforebegin',
      '<label for="if-fulltitle">' + esc(t('完整标题（整串粘贴，程序自动判定词条）：')) + '</label>' +
      '<textarea id="if-fulltitle" rows="4" spellcheck="false"></textarea>' +
      '<div class="info-tip">' + esc(t('例：[社团 (画师)] 作品名 (C102) (同人) 【汉化组】')) + '<br>' +
      esc(t('程序会拆出社团 / 画师 / 展会 / 同人 / 汉化组 / 待定词条各段，标准化命名后')) +
      '<b>' + esc(t('自动归档到解析出的社团')) + '</b>' +
      esc(t('（识别不出社团则按规范名留在收件箱）；括号会自动纠错（嵌套 [[…]]、重复词条、空括号都会被收敛）。')) + '</div>');
    $('#if-fulltitle').value = info.base || info.file || '';
    $('#if-fulltitle').focus();
    $('#btnInfoSave').textContent = t('解析并归档');
  }
  $('#modeFields').addEventListener('click', () => {
    state.infoMode = 'fields'; renderInfoForm(state.infoData || info);
  });
  $('#modeTitle').addEventListener('click', () => {
    state.infoMode = 'title'; renderInfoForm(state.infoData || info);
  });
  $('#btnInfoCancel').addEventListener('click', () => { location.hash = state.infoReturn || '#/'; });
  $('#btnInfoSave').addEventListener('click', async () => {
    if (infoMode === 'title') {                 // 整标题模式：整串字符串交给服务端解析+归档
      const full = ($('#if-fulltitle') && $('#if-fulltitle').value || '').trim();
      if (!full) { showToast(t('请输入完整标题')); return; }
      try {
        const d = await api('/api/supplement-title', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ group: group, work: state.infoWork, title: full })
        });
        showToast(d.message);
        location.hash = state.infoReturn || '#/';
      } catch (e) { showToast(tf('%1失败：%2', t('归档'), e.message)); }
      return;
    }
    const fields = {
      uncensored: $('#if-uncensored').checked,
      event: $('#if-event').value.trim(),
      circle: $('#if-circle').value.trim(),
      personal: $('#if-personal').value.trim(),
      title: $('#if-title').value.trim(),
      original: $('#if-original').value.trim(),
      translator: $('#if-translator').value.trim(),
      other_info: $('#if-otherinfo').value.trim(),
    };
    try {
      const d = await api('/api/supplement-info', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group: group, work: state.infoWork, fields: fields })
      });
      showToast(d.message);
      location.hash = state.infoReturn || '#/';
    } catch (e) { showToast(tf('%1失败：%2', t('保存'), e.message)); }
  });
}
