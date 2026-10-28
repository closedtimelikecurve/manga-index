/* 本地同人志文库 前端 · import.js
   导入文件、个人统计
   3.6.84 从 static/app.js 拆出：按顶层区块切分，仍是 classic script，
   与其余分片共享同一个全局词法环境（顺序加载，勿调整 index.html 里的 <script> 次序）。 */
'use strict';

/* ---------- 导入文件（二级界面：选择文件夹 / 拖拽，自动规范化并建档） ---------- */
function renderImport() {
  hideEmpty(); hideGridEmpty();
  const only = isImportOnly();
  const hint = only ? t('首次导入需先建立词条库，文库较大时可能等待数十秒。') : '';
  const fsa = 'showOpenFilePicker' in window;   // File System Access API：可拿到句柄并删源（Chrome/Edge）
  $('#viewHead').innerHTML =
    (only ? '' : '<button class="back" id="btnBack">← ' + esc(t('返回')) + '</button>') +
    '<h2><!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-download" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /> <polyline points="7 10 12 15 17 10" /> <line x1="12" x2="12" y1="15" y2="3" /> </svg> ' + esc(t('导入文件')) + (only ? ' <em class="import-only-tag">' + esc(t('仅导入模式')) + '</em>' : '') + '</h2>' +
    '<span class="sub">' + esc(t('选择文件夹或拖拽文件进入：系统自动规范化文件名并建档；识别出社团/个人的归入对应档案，有待定词条的按词条建档，完全无法识别的进入「收件箱」。')) + esc(hint) + '</span>';
  const grid = $('#grid');
  grid.className = 'grid grid-list';

  if (only && state.config && !state.config.rootExists) {
    grid.innerHTML =
      '<div class="panel" style="margin:30px auto">' +
        '<h3>' + esc(t('📁 未找到文库根目录')) + '</h3>' +
        '<p>' + esc(t('请填写正确的文库根目录（例如 <code>D:\\同人志</code>），或留空使用程序上级目录。')) + '</p>' +
        '<input id="importOnlyRoot" placeholder="例如：D:\\同人志">' +      // i18n:data 路径示例
        '<button class="primary" id="btnImportOnlyRoot" style="width:100%">' + esc(t('保存并返回导入')) + '</button>' +
      '</div>';
    const btn = $('#btnImportOnlyRoot');
    if (btn) btn.addEventListener('click', async () => {
      const v = $('#importOnlyRoot').value.trim();
      try {
        state.config = await api('/api/config', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ root: v || null })
        });
        showToast(t('根目录已设置'));
        renderImport();
      } catch (e) { showToast(tf('%1失败：%2', t('设置'), e.message)); }
    });
    return;
  }

  grid.innerHTML =
    '<div class="import-zone" id="importZone">' +
      '<div class="import-icon"><!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-folder" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" /> </svg></div>' +
      '<div class="import-text">' + esc(t('将文件或文件夹拖拽到这里<br>或点击下方按钮选择')) + '</div>' +
    '</div>' +
    '<div class="import-btns">' +
      '<button id="btnPickFolder" class="primary">📁 ' + esc(t('选择文件夹（导入后删源）')) + '</button>' +
      '<button id="btnPickFiles"><!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-file-text" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z" /> <path d="M14 2v4a2 2 0 0 0 2 2h4" /> <path d="M10 9H8" /> <path d="M16 13H8" /> <path d="M16 17H8" /> </svg> ' + esc(t('选择文件（导入后删源）')) + '</button>' +
    '</div>' +
    '<div class="sub" style="margin-top:6px">' + (fsa
      ? esc(t('经系统文件选择器打开，<b>导入成功后会自动删除源文件</b>；拖拽仍为复制。'))
      : esc(t('当前浏览器不支持「导入后删源」（需 Chrome / Edge），选择文件 / 文件夹将<b>复制不删源</b>；拖拽同为复制。'))) + '</div>' +
    '<input type="file" id="importInput" multiple hidden>' +
    '<input type="file" id="importFolderInput" webkitdirectory multiple hidden>' +
    '<div id="importProgress" class="import-progress hidden"></div>' +
    '<div id="importResult" class="import-result"></div>';
  const zone = $('#importZone');
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('over'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('over');
    // 优先读取拖入条目（支持整个文件夹，含子目录）
    const entries = (e.dataTransfer.items ? Array.from(e.dataTransfer.items) : [])
      .map(i => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
    if (entries.length) {
      const out = [];
      Promise.all(entries.map(en => collectEntry(en, '', out)))
        .then(() => { if (out.length) doImport(out); });
      return;
    }
    const files = Array.from(e.dataTransfer.files || []);
    if (files.length) doImport(files);
  });
  $('#btnPickFolder').addEventListener('click', () => pickImport('folder'));
  $('#btnPickFiles').addEventListener('click', () => pickImport('files'));
  $('#importInput').addEventListener('change', e => {
    if (e.target.files.length) doImport(Array.from(e.target.files));
    e.target.value = '';
  });
  $('#importFolderInput').addEventListener('change', e => {
    if (e.target.files.length) doImport(Array.from(e.target.files));
    e.target.value = '';
  });
  if (state.importResults) renderImportResults();   // 恢复上次导入结果（重扫重建页面时）
}

/* 递归展开拖入的文件夹条目：File 附加 _relPath（相对路径），供后端按顶层文件夹归并 */
function collectEntry(entry, base, out) {
  return new Promise(resolve => {
    if (!entry) return resolve();
    if (entry.isFile) {
      entry.file(f => { f._relPath = base + entry.name; out.push(f); resolve(); }, () => resolve());
    } else if (entry.isDirectory) {
      const rd = entry.createReader();
      const batch = () => rd.readEntries(es => {
        if (!es.length) return resolve();
        Promise.all(es.map(x => collectEntry(x, base + entry.name + '/', out))).then(batch);
      }, () => resolve());
      batch();
    } else resolve();
  });
}

async function doImport(files) {
  const prog = $('#importProgress');
  const res = $('#importResult');
  prog.classList.remove('hidden');
  prog.textContent = tf('正在导入 %1 个文件…', files.length);
  res.innerHTML = '';
  const fd = new FormData();
  for (const f of files) {
    fd.append('files', f, f.name);
    fd.append('paths', f._relPath || f.webkitRelativePath || f.name);
  }
  try {
    const d = await api('/api/import', { method: 'POST', body: fd });
    prog.classList.add('hidden');
    prog.textContent = '';
    const list = d.results || [];
    state.importResults = { imported: d.imported, list: list };
    renderImportResults();
    if (isImportOnly()) {
      // 仅导入模式：后端不开放文库列表，导入结果直接展示在当前页即可
      $('#statusText').textContent = tf('已导入 %1 个文件，可继续拖入', d.imported);
    } else {
      await refresh(true);
    }
  } catch (e) {
    prog.classList.add('hidden');
    showToast(tf('%1失败：%2', t('导入'), e.message));
  }
}

/* 选择文件 / 文件夹：能用 File System Access API（Chrome/Edge）就走它，
   拿到句柄后导入成功由 importWithDelete() 负责删源；否则回退普通 <input>（仅复制）。 */
async function pickImport(kind) {
  if (window.showOpenFilePicker) {
    try { await importViaFSA(kind); return; }
    catch (e) {
      if (e && e.name === 'AbortError') return;        // 用户在系统选择器里取消
      showToast(tf('系统文件选择器不可用，改用普通选择（不删源）：%1', e.message));
    }
  }
  if (kind === 'folder') $('#importFolderInput').click(); else $('#importInput').click();
}

async function importViaFSA(kind) {
  let items = [];
  if (kind === 'folder') {
    const dir = await window.showDirectoryPicker();     // 返回目录句柄
    items = await collectFsHandles(dir, '');
  } else {
    const hs = await window.showOpenFilePicker({ multiple: true });
    for (const h of hs) {
      const file = await h.getFile();
      items.push({ handle: h, file: file, relPath: file.name });
    }
  }
  if (items.length) await importWithDelete(items);
}

async function collectFsHandles(dir, base) {
  const out = [];
  for await (const [name, h] of dir.entries()) {
    if (h.kind === 'file') {
      const file = await h.getFile();
      out.push({ handle: h, file: file, relPath: base + name });
    } else if (h.kind === 'directory') {
      out.push(...await collectFsHandles(h, base + name + '/'));
    }
  }
  return out;
}

/* 导入并删源：复用 /api/import，成功后仅对状态为「已导入」的源文件调用 handle.remove()。
   重复内容 / 失败 / 跳过均保留源文件，避免误删。 */
async function importWithDelete(items) {
  const prog = $('#importProgress'), res = $('#importResult');
  prog.classList.remove('hidden');
  prog.textContent = tf('正在导入 %1 个文件…', items.length);
  res.innerHTML = '';
  const fd = new FormData();
  for (const it of items) {
    fd.append('files', it.file, it.file.name);
    fd.append('paths', it.relPath || it.file.name);
  }
  try {
    const d = await api('/api/import', { method: 'POST', body: fd });
    prog.classList.add('hidden');
    prog.textContent = '';
    const list = d.results || [];
    state.importResults = { imported: d.imported, list: list };
    renderImportResults();
    const importedRels = new Set(      // i18n:data 已导入=服务端状态字面量（下一行）
      list.filter(x => (x.status || '').startsWith('已导入')).map(x => x.rel || x.file));   // i18n:data
    let deleted = 0, kept = 0;
    for (const it of items) {
      if (!importedRels.has(it.relPath)) continue;
      try {
        if (it.handle && it.handle.remove) { await it.handle.remove(); deleted++; }
        else kept++;
      } catch (e) { kept++; }
    }
    if (deleted) showToast(tf('已导入 %1 个并删除源', deleted) +
      (kept ? tf('；%1 个删源失败已保留', kept) : ''));
    if (isImportOnly()) $('#statusText').textContent = tf('已导入 %1 个文件，可继续拖入', d.imported);
    else await refresh(true);
  } catch (e) {
    prog.classList.add('hidden');
    showToast(tf('%1失败：%2', t('导入'), e.message));
  }
}

/* 渲染导入结果列表（自动重扫会重建导入页，用此函数恢复结果显示） */
function renderImportResults() {
  const res = $('#importResult');
  const r = state.importResults;
  if (!res || !r) return;
  res.innerHTML =
    '<h3 class="import-summary">' + esc(tf('导入结果：%1 个成功', r.imported)) + '</h3>' +
    '<div class="import-results">' +
      r.list.map(x =>
        '<div class="import-item ' + (x.status.indexOf('替换洗版') >= 0 ? 'warn'      // i18n:data 状态字面量
          : x.status.startsWith('已导入') ? 'ok' : 'skip') + '">' +
        esc(x.file) + ' → ' + esc(x.status) + (x.message ? '（' + esc(x.message) + '）' : '') +
        '</div>').join('') +
    '</div>';
}


/* ---------- 个人统计（3.2.1 网页端：总量/已读/收藏 + 入库曲线 + 关注与 Top 画师） ---------- */
function statCard(label, value) {
  return '<div class="stat-card"><div class="stat-label">' + esc(label) + '</div><div class="stat-value">' + esc(value) + '</div></div>';
}

async function loadStats() {
  const box = $('#statsBody');
  if (!box) return;
  try {
    const results = await Promise.all([
      api('/api/stats/overview'),
      api('/api/follows').catch(() => ({ follows: [] })),
    ]);
    renderStatsBody(results[0], results[1].follows || []);
  } catch (e) {
    box.innerHTML = '<div class="sub" style="padding:8px">' + esc(tf('%1失败：%2', t('加载'), e.message)) + '</div>';
  }
}

function renderStatsBody(st, follows) {
  const box = $('#statsBody');
  let html = '<div class="stat-row">' + statCard(t('📚 作品'), st.works) + statCard(t('📄 页数'), st.pages) + statCard(t('🏢 社团'), st.circles) + '</div>';
  html += '<div class="stat-row">' + statCard(t('✅ 已读'), st.finished) + statCard(t('📖 在读'), st.started) + statCard(t('⭐ 收藏'), st.favorites) + '</div>';
  const days = st.by_day || [];
  if (days.length) {
    const maxN = Math.max.apply(null, days.map(d => d.count).concat([1]));
    html += '<h3 class="stat-h">' + esc(tf('📈 入库增长（近 %1 天）', days.length)) + '</h3>' +
      '<div class="stat-chart">' + days.map(d =>
        '<div class="stat-bar" style="height:' + Math.max(4, Math.round(d.count / maxN * 100)) + '%" title="' + esc(d.day) + esc(tf('：入库 %1 部', d.count)) + '"></div>').join('') + '</div>' +
      '<div class="stat-range"><span>' + esc(days[0].day) + '</span><span>' + esc(days[days.length - 1].day) + '</span></div>';
  }
  if ((follows || []).length) {
    html += '<h3 class="stat-h">' + esc(t('❤ 喜爱的画师')) + '</h3><div class="stat-list">' +
      follows.map(f => '<span class="tag t-personal clickable" data-artist="' + esc(f.author) + '" title="' + esc(t('打开画师档案')) + '">👤 ' + esc(f.author) +
        esc(tf('（%1 部', f.works)) + (f.new > 0 ? esc(tf(' · 新 %1', f.new)) : '') + '）</span>').join('') + '</div>';
  }
  const ta = st.top_authors || [];
  if (ta.length) {
    const maxN = Math.max.apply(null, ta.map(t => t.count).concat([1]));
    html += '<h3 class="stat-h">' + esc(tf('🏆 最常看画师 Top%1', ta.length)) + '</h3><div class="stat-top">' +
      ta.map((t, i) => '<div class="stat-toprow">' +
        '<span class="stat-rank">' + (i + 1) + '.</span>' +
        '<span class="stat-name clickable" data-artist="' + esc(t.name) + '" title="' + esc(t('打开画师档案')) + '">' + esc(t.name) + '</span>' +
        '<div class="stat-topbar"><div style="width:' + Math.round(t.count / maxN * 100) + '%"></div></div>' +
        '<span class="sub">' + t.count + '</span></div>').join('') + '</div>';
  }
  box.innerHTML = html;
}

function renderStats() {
  hideEmpty(); hideGridEmpty();
  $('#viewHead').innerHTML =
    '<button class="back" id="btnBack">← ' + esc(t('返回')) + '</button>' +
    '<h2>📊 ' + esc(t('个人统计')) + '</h2>' +
    '<span class="sub">' + esc(t('阅读进度跨端同步 · 点画师名进档案')) + '</span>';
  const grid = $('#grid'); grid.className = 'grid grid-list';
  grid.innerHTML = '<div class="panel" style="width:100%;max-width:980px;margin:0 auto" id="statsBody"><div class="sub" style="padding:8px">' + esc(t('加载中…')) + '</div></div>';
  loadStats();
}
