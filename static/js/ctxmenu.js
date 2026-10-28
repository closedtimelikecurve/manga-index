/* 本地同人志文库 前端 · ctxmenu.js
   右键快捷菜单与维护操作（删除/改名/封面/解散）
   3.6.84 从 static/app.js 拆出：按顶层区块切分，仍是 classic script，
   与其余分片共享同一个全局词法环境（顺序加载，勿调整 index.html 里的 <script> 次序）。 */
'use strict';

/* ---------- 右键快捷菜单（作品卡片 / 推荐卡 / 社团卡 / 社团页头部） ---------- */
const ctxMenu = {
  el: null,
  hide() {
    if (this.el) { this.el.remove(); this.el = null; }
  },
  show(x, y, items, title, sub) {
    this.hide();
    const el = document.createElement('div');
    el.className = 'ctx-menu';
    el.innerHTML =
      '<div class="ctx-title">' + esc(title) + '</div>' +
      (sub ? '<div class="ctx-sub">🏢 ' + esc(sub) + '</div>' : '') +
      '<hr>' +
      items.map(it =>
        '<button data-a="' + it.a + '"' + (it.danger ? ' class="danger"' : '') + '>' + it.icon + ' ' + it.label + '</button>'
      ).join('');
    el.style.left = Math.max(4, Math.min(x, window.innerWidth - 210)) + 'px';
    el.style.top = Math.max(4, Math.min(y, window.innerHeight - 300)) + 'px';
    el.addEventListener('click', e => {
      const b = e.target.closest('button');
      if (!b) return;
      const a = b.dataset.a;
      this.hide();
      items.find(it => it.a === a)?.run();
    });
    document.body.appendChild(el);
    this.el = el;
  },
};

const ICON_READ = '<!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-book-open" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M12 7v14" /> <path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z" /> </svg>';
const ICON_INFO = '<!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-pen-line" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M12 20h9" /> <path d="M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.854z" /> </svg>';
const ICON_IMG = '<!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-image" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <rect width="18" height="18" x="3" y="3" rx="2" ry="2" /> <circle cx="9" cy="9" r="2" /> <path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21" /> </svg>';
const ICON_IMG_OFF = '<!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-image-off" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <line x1="2" x2="22" y1="2" y2="22" /> <path d="M10.41 10.41a2 2 0 1 1-2.83-2.83" /> <line x1="13.5" x2="15.5" y1="13.5" y2="15.5" /> <path d="m18.48 12.895 1.42-4.245a2 2 0 0 0-1.265-2.532L12.4 3.9a2 2 0 0 0-1.935.484l-1.84 1.842" /> <path d="M4.712 5.088 4.165 6.35A2 2 0 0 0 4.18 8.29l1.42 4.245a2 2 0 0 1-1.265 2.532L4 15.32V20a2 2 0 0 0 2 2h12.805" /> </svg>';
const ICON_FOLDER = '<!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-folder" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" /> </svg>';
const ICON_TRASH = '<!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-trash-2" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M3 6h18" /> <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" /> <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" /> <line x1="10" x2="10" y1="11" y2="17" /> <line x1="14" x2="14" y1="11" y2="17" /> </svg>';
const ICON_DISBAND = '<!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-scatter-chart" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <circle cx="4" cy="4" r="2" /> <circle cx="18" cy="6" r="2" /> <circle cx="8" cy="20" r="2" /> <path d="m7.5 5.5 8.5-1" /> <path d="m17 8-7.5 10.5" /> </svg>';
const ICON_OPEN = '<!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-building-2" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z" /> <path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2" /> <path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2" /> <path d="M10 6h4" /> <path d="M10 10h4" /> <path d="M10 14h4" /> <path d="M10 18h4" /> </svg>';

async function apiDeleteWork(group, work) {
  if (!confirm(tf('确定删除作品「%1」？\n\n文件将被直接删除，不可还原。', work))) return;
  try {
    const r = await api('/api/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ group: group, work: work }) });
    showToast(r.message || t('已删除'));
    await refresh(true);
  } catch (e) { showToast(tf('%1失败：%2', t('删除'), e.message)); }
}

async function apiDeleteCircle(group) {
  if (!confirm(tf('确定删除整个社团「%1」？\n\n该社团下的全部作品将一并直接删除（不可还原）。', group))) return;
  try {
    const r = await api('/api/delete-circle', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ group: group }) });
    showToast(r.message || t('已删除'));
    if (state.view === 'circle' && state.circleName === group) location.hash = '#/';
    await refresh(true);
  } catch (e) { showToast(tf('%1失败：%2', t('删除'), e.message)); }
}

async function apiRenameCircle(group) {
  const nn = prompt(tf('输入「%1」的新社团名：\n（若该名称的社团已存在，将自动合并：作品并入其中，文件名不变、绝不覆盖）', group), group);
  if (!nn || nn.trim() === group || !nn.trim()) return;
  try {
    const r = await api('/api/rename-circle', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ group: group, new_name: nn.trim() }) });
    showToast(r.message || t('已改名'));
    if (r.new_name && state.view === 'circle' && state.circleName === group) {
      location.hash = '#/circle/' + enc(r.new_name);
    }
    await refresh(true);
  } catch (e) { showToast(tf('%1失败：%2', t('改名'), e.message)); }
}

/* ---- 原作分区改名 / 移除（3.6.21；3.6.27 起去掉宽松归一）----
   原作名不在文件名里，只活在 DB 标签 + config 词条库：改名只搬标签，零文件操作。
   3.6.27：新名**不做宽松归一**——你输入什么，分区就叫什么（宽松归一只在
   "文件名 → 归入分区"的归档路径生效）。仅写法不同的改名会自动保留旧名为别名，
   保证重扫后文件名里的旧写法仍归到本分区。 */
async function apiRenameOriginal(zone) {
  // 3.7.41：prompt 换成自建对话框——用户要的是"改名栏右侧的小叉"，prompt 里放不了按钮。
  // 旧名默认登记为别名（3.6.41 起不再询问），文案里的"旧名 ×"入口也已随需求撤掉。
  if ($('#origRenameModal')) return;
  const el = document.createElement('div');
  el.id = 'origRenameModal';
  el.className = 'modal';
  el.innerHTML =
    '<div class="modal-card" style="max-width:460px">' +
      '<h3>' + esc(t('✏ 分区改名')) + '</h3>' +
      '<p style="color:var(--muted);font-size:12px;line-height:17px">' + esc(t('只改分区标签，作品文件一律不动（位置/进度/收藏不受影响）。新名按你输入的来、不做归一；旧名会自动登记为别名。')) + '</p>' +
      '<div style="position:relative">' +
        '<input id="origRenameInput" style="width:100%;padding-right:36px" value="' + esc(zone) + '">' +
        '<span id="origRenameClear" title="' + esc(t('清空输入框')) + '" style="position:absolute;right:10px;top:50%;'
        + 'transform:translateY(-50%);cursor:pointer;color:var(--muted);font-size:14px">✕</span>' +
      '</div>' +
      '<div class="modal-acts">' +
        '<button id="origRenameCancel" class="back">' + esc(t('取消')) + '</button>' +
        '<button id="origRenameOk" class="primary">' + esc(t('改名')) + '</button>' +
      '</div>' +
    '</div>';
  document.body.appendChild(el);
  const input = $('#origRenameInput');
  input.focus(); input.select();
  const close = () => el.remove();
  $('#origRenameClear').addEventListener('click', () => { input.value = ''; input.focus(); });
  $('#origRenameCancel').addEventListener('click', close);
  $('#origRenameOk').addEventListener('click', async () => {
    const nn = input.value.trim();
    if (!nn || nn === zone) { close(); return; }
    close();
    try {
      const r = await api('/api/originals/rename', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ from: zone, to: nn, keep_alias: true }) });
      showToast(r.message || t('已改名'));
      if (r.to && state.view === 'tag' && state.tagType === 'original' && state.tagName === zone) {
        location.hash = '#/tag/original/' + enc(r.to);
      }
      await refresh(true);
    } catch (e) { showToast(tf('%1失败：%2', t('改名'), e.message)); }
  });
}

/* 3.6.36 #33：分区内手动添加作品——搜索库内作品（search2）→ 勾选 →
   写 original 标签进本分区（/api/originals/add-works）。只写标签，不动文件。 */
function showAddWorksModal(zone) {
  if ($('#addWorksModal')) return;
  const el = document.createElement('div');
  el.id = 'addWorksModal';
  el.className = 'modal';
  el.innerHTML =
    '<div class="modal-card" style="max-width:540px">' +
      '<h3>' + esc(tf('添加到「%1」', zone)) + '</h3>' +
      '<p style="color:var(--muted);font-size:12.5px">' + esc(t('搜索库内作品（名称/社团/标签），勾选后加入本分区。只写标签，不移动文件、不影响进度与收藏。')) + '</p>' +
      '<input id="awQuery" type="text" placeholder="' + esc(t('搜索作品…')) + '" style="width:100%">' +
      '<div id="awMsg" style="color:#ff5ed0;font-size:12px;min-height:16px;margin-top:4px"></div>' +
      '<div id="awList" style="max-height:300px;overflow:auto;margin:6px 0"></div>' +
      '<div class="modal-acts">' +
        '<button id="awCancel">' + esc(t('取消')) + '</button>' +
        '<button id="awSave" class="primary">' + esc(tf('添加（%1）', 0)) + '</button>' +
      '</div>' +
    '</div>';
  document.body.appendChild(el);
  const listEl = $('#awList'), msgEl = $('#awMsg'), saveEl = $('#awSave');
  const selected = new Set();
  let timer = null;
  const render = (works) => {
    if (!works.length) {
      listEl.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:8px 0">' + esc(t('无结果')) + '</div>';
      return;
    }
    listEl.innerHTML = works.map(h => {
      const k = h.key || (h.group + '/' + h.work);
      return '<label style="display:flex;gap:8px;align-items:center;padding:5px 0;cursor:pointer;border-bottom:1px solid var(--line)">' +
        '<input type="checkbox" data-k="' + esc(k) + '"' + (selected.has(k) ? ' checked' : '') + '>' +
        '<span style="flex:1;min-width:0"><span style="display:block;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(h.work || '') + '</span>' +
        '<span style="display:block;font-size:11px;color:var(--muted)">' + esc(h.group || '') + '</span></span></label>';
    }).join('');
    listEl.querySelectorAll('input[type=checkbox]').forEach(cb => {
      cb.addEventListener('change', () => {
        const k = cb.getAttribute('data-k');
        if (cb.checked) selected.add(k); else selected.delete(k);
        saveEl.textContent = tf('添加（%1）', selected.size);
      });
    });
  };
  $('#awQuery').addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = $('#awQuery').value.trim();
      if (!q) { render([]); return; }
      try {
        const d = await api('/api/search2?q=' + encodeURIComponent(q) + '&limit=50');
        render(d.works || []);
        msgEl.textContent = '';
      } catch (e) { msgEl.textContent = tf('%1失败：%2', t('搜索'), e.message); }
    }, 400);
  });
  $('#awCancel').addEventListener('click', () => el.remove());
  saveEl.addEventListener('click', async () => {
    if (!selected.size) { msgEl.textContent = t('先勾选作品'); return; }
    try {
      const r = await api('/api/originals/add-works', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ zone: zone, keys: Array.from(selected) }) });
      showToast(tf('已添加 %1 部到「%2」', r.added || 0, zone));
      el.remove();
      await refresh(true);
    } catch (e) { msgEl.textContent = tf('%1失败：%2', t('添加'), e.message); }
  });
}

async function apiRemoveOriginal(zone) {
  if (!confirm(tf('移除同人分区「%1」？\n\n· 该分区的 original 标签会被清除，作品本身不受影响（仍在社团/画师页可见）\n· 词条库中的对应词条一并删除，因此重扫不会把它重新长出来', zone))) return;
  try {
    const r = await api('/api/originals/remove', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ term: zone }) });
    showToast(tf('已移除同人分区「%1」（清理 %2 条标签）', zone, r.removed || 0));
    if (state.view === 'tag' && state.tagType === 'original' && state.tagName === zone) location.hash = '#/';
    await refresh(true);
  } catch (e) { showToast(tf('%1失败：%2', t('移除'), e.message)); }
}

async function apiDissolveCircle(group) {  if (!confirm(tf('确定解散社团「%1」？\n\n内部作品将移动到「收件箱」（文件名不变、绝不覆盖）；原社团目录随后整棵直接删除，不留空文件夹（残留文件不可还原）。\n待定词条作品随后可在「增补信息」中整理——待定词条会默认填入「其他信息」一栏。', group))) return;
  try {
    const r = await api('/api/dissolve-circle', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ group: group }) });
    showToast(r.message || t('已解散'));
    if (state.view === 'circle' && state.circleName === group) location.hash = '#/';
    await refresh(true);
  } catch (e) { showToast(tf('%1失败：%2', t('解散'), e.message)); }
}

async function apiRenameArtist(artist) {
  const nn = prompt(tf('输入「%1」的新画师名：\n（名下全部作品的文件名与记录会一起跟随改名；若该名字的画师已存在，将自动合并：作品并入其中，旧名降级为别名）', artist), artist);
  if (!nn || nn.trim() === artist || !nn.trim()) return;
  try {
    const r = await api('/api/artist/rename', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ from: artist, to: nn.trim() }) });
    showToast(r.message || t('已改名'));
    await refresh(true);
  } catch (e) { showToast(tf('%1失败：%2', t('改名'), e.message)); }
}

async function apiDeleteCover(group, work) {
  if (!confirm(tf('确定删除作品「%1」的首页图片？\n\n将从压缩包内物理移除封面页（不可恢复），重扫后首页变为原第二页。', work))) return;
  try {
    const r = await api('/api/delete-cover', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ group: group, work: work }) });
    showToast(r.message || t('已删除首页图片'));
    if (reader.open && reader.group === group && reader.work === work) closeReader();
    await refresh(true);
  } catch (e) { showToast(tf('%1失败：%2', t('删除'), e.message)); }
}

async function apiSetCover(scope, name, group, work) {
  // 把某作品首图设为「所在区域」的封面：社团页操作 → 社团封面；画师页操作 → 画师封面。
  // 跨引用作品同理——scope 跟随当前视图，group 用作品在该视图下的归属社团（find_work 均可命中）。
  try {
    const r = await api('/api/set-cover', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scope: scope, name: name, group: group, work: work }) });
    showToast(r.message || t('已设为封面'));
    await refresh(true);   // public_group 实时重解析覆盖，刷新即见
  } catch (e) { showToast(tf('%1失败：%2', t('设置'), e.message)); }
}

document.addEventListener('click', () => ctxMenu.hide());
document.addEventListener('contextmenu', e => {
  // 3.6.15：全域长按复制已移除；触屏长按只派发系统 contextmenu，由下方分支处理
  //（封面区 → 操作菜单；文字区 → 仅禁原生菜单、不弹我们的浮层）。

  // 画师页页头 → 当前画师菜单（3.6.5：改名/合并，唤出逻辑与社团页一致）
  if (state.view === 'artist' && state.artistName && e.target.closest('#viewHead')) {
    e.preventDefault();
    const a = state.artistName;
    ctxMenu.show(e.clientX, e.clientY, [
      { a: 'ren', label: t('重命名画师（名下作品跟随）'), icon: ICON_INFO, run: () => apiRenameArtist(a) },
    ], a, t('画师'));
    return;
  }
  // 社团页头部 → 当前社团菜单
  if (state.view === 'circle' && state.circleName && e.target.closest('#viewHead')) {
    e.preventDefault();
    const g = state.circleName;
    ctxMenu.show(e.clientX, e.clientY, [
      { a: 'ren', label: t('重命名社团'), icon: ICON_INFO, run: () => apiRenameCircle(g) },
      { a: 'dis', label: t('解散社团（移入收件箱）'), danger: true, icon: ICON_DISBAND, run: () => apiDissolveCircle(g) },
      { a: 'del', label: t('删除该社团'), danger: true, icon: ICON_TRASH, run: () => apiDeleteCircle(g) },
    ], g, t('社团'));
    return;
  }
  // 原作分区页头部 → 当前分区菜单（3.6.21：原作分区终于有了自己的操作栏）
  if (state.view === 'tag' && state.tagType === 'original' && state.tagName
      && e.target.closest('#viewHead')) {
    e.preventDefault();
    const z = state.tagName;
    ctxMenu.show(e.clientX, e.clientY, [
      { a: 'ren', label: t('分区改名（只搬标签，作品不动）'), icon: ICON_INFO, run: () => apiRenameOriginal(z) },
      { a: 'del', label: t('移除该分区（作品不受影响）'), danger: true, icon: ICON_TRASH, run: () => apiRemoveOriginal(z) },
    ], z, t('同人分区'));
    return;
  }
  // 作品卡片 / 推荐卡：操作菜单只在封面区唤出（长按封面），
  // 文字区长按 = 系统选择菜单（全域复制已移除），不弹我们的操作栏。
  const card = e.target.closest('.card, .rec-card');
  if (card && card.dataset.work) {
    e.preventDefault();
    if (!e.target.closest('.cover-wrap, .rec-cover')) return;   // 文字区：只禁原生菜单，不弹我们的
    const group = card.dataset.group || '收件箱', work = card.dataset.work;   // i18n:data 收件箱=真实社团名（标识符）
    const items = [
      { a: 'info', label: t('增补信息'), icon: ICON_INFO, run: () => openInfo(group, work) },
      { a: 'folder', label: t('文件夹'), icon: ICON_FOLDER, run: () => openTarget(group, work, 'folder') },
    ];
    // 设为封面：仅当明确处于「社团页」「画师页」或「原作分区页」时才有归属区域
    //（所在位置决定封面归属）。3.6.19 起原作分区同样支持——APP 端早已有此入口，
    // 网页端此前漏了，导致面板上只能靠手机设。
    if (state.view === 'circle' && state.circleName) {
      items.push({ a: 'setcover', label: t('设为社团封面'), icon: ICON_IMG,
        run: () => apiSetCover('circle', state.circleName, group, work) });
    } else if (state.view === 'artist' && state.artistName) {
      items.push({ a: 'setcover', label: t('设为画师封面'), icon: ICON_IMG,
        run: () => apiSetCover('artist', state.artistName, group, work) });
    } else if (state.view === 'tag' && state.tagType === 'original' && state.tagName) {
      items.push({ a: 'setcover', label: t('设为分区封面'), icon: ICON_IMG,
        run: () => apiSetCover('original', state.tagName, group, work) });
    }
    items.push(
      { a: 'delcover', label: t('删除首页图片（压缩包内移除封面页）'), danger: true, icon: ICON_IMG_OFF, run: () => apiDeleteCover(group, work) },
      { a: 'del', label: t('删除作品'), danger: true, icon: ICON_TRASH, run: () => apiDeleteWork(group, work) },
    );
    ctxMenu.show(e.clientX, e.clientY, items, work, group);
    return;
  }
  // 首页社团卡片：同样只在封面区唤出菜单；社团名文字区长按 = 复制社团名
  const cc = e.target.closest('.circle-card');
  // 原作分区卡片（首页分区视图，dataset.original）：封面区长按 → 分区自己的操作栏（3.6.21）。
  // 必须排在社团分支之前：原作卡只带 dataset.original、不带 dataset.group
  if (cc && cc.dataset.original) {
    e.preventDefault();
    if (!e.target.closest('.circle-cover')) return;
    const z = cc.dataset.original;
    ctxMenu.show(e.clientX, e.clientY, [
      { a: 'ren', label: t('分区改名（只搬标签，作品不动）'), icon: ICON_INFO, run: () => apiRenameOriginal(z) },
      { a: 'del', label: t('移除该分区（作品不受影响）'), danger: true, icon: ICON_TRASH, run: () => apiRemoveOriginal(z) },
    ], z, t('同人分区'));
    return;
  }
  if (cc && cc.dataset.group) {
    e.preventDefault();
    if (!e.target.closest('.circle-cover')) return;
    const g = cc.dataset.group;
    ctxMenu.show(e.clientX, e.clientY, [
      { a: 'ren', label: t('重命名社团'), icon: ICON_INFO, run: () => apiRenameCircle(g) },
      { a: 'dis', label: t('解散社团（移入收件箱）'), danger: true, icon: ICON_DISBAND, run: () => apiDissolveCircle(g) },
      { a: 'del', label: t('删除社团'), danger: true, icon: ICON_TRASH, run: () => apiDeleteCircle(g) },
    ], g, t('社团'));
    return;
  }
  ctxMenu.hide();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') { ctxMenu.hide(); } });
window.addEventListener('blur', () => { ctxMenu.hide(); });

/* ---------- 启动（3.6.22 补回）----------
   3.6.15 删「全局长按复制」时把文件末尾的 init() 一起删掉了（initLongPressCopy 是那次
   要删的，init 是被误伤），结果面板从此不引导：状态栏永远停在 HTML 里的「加载中…」，
   一个请求都不发（已用 DOM 垫片跑 app.js 实测：零请求、零渲染）。
   script 在 </body> 前加载 → 这里 DOM 已就绪，直接调即可（历史版本也是这么写的）。 */
init();
