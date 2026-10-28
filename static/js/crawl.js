/* 本地同人志文库 前端 · crawl.js
   清单爬虫页（3.7.59：原名"爬虫管理"，与分区爬虫彻底分开）
   3.6.84 从 static/app.js 拆出：按顶层区块切分，仍是 classic script，
   与其余分片共享同一个全局词法环境（顺序加载，勿调整 index.html 里的 <script> 次序）。 */
'use strict';

/* ---------- 清单爬虫页 ---------- */
const crawlState = { poll: null, rev: null, kind: 'wnacg', sawRunning: false, sig: '' };
// 任务/条目的阶段文案（与 services/crawl_run.py 的 state 一一对应）。
// 3.6.140 函数化：顶层 const 会在加载期固化 t() 结果，切语言后冻住——与 APP PROBE_SITES 同坑。
// 爬取中→获取中：与 APP CrawlMonitor（3.7.88）的措辞统一。
function crawlJobStates() {
  return { queued: t('待锁定'), locking: t('锁定中'), locked: t('已锁定'),
    downloading: t('获取中'), importing: t('入库中'), ok: t('完成'), fail: t('失败'),
    unmatched: t('未匹配'), skip: t('跳过') };
}
// 任务胶囊（运行中文字变绿）。函数化理由同上。
// 3.6.156：按服务端 /api/config 的 builtinKinds 过滤——公开发行版只带 JM 直连与
// 外接下载器，被剔除的站点适配不出胶囊；老面板没有该字段 → 全部显示。
function builtinKinds() {
  const ks = (window.state && state.config && state.config.builtinKinds) || null;
  return (Array.isArray(ks) && ks.length) ? ks : null;
}

function crawlKindsList() {
  const avail = builtinKinds();
  const all = [
    ['wnacg', t('wnacg 主下载')], ['jm', t('JM 索引')], ['jmdl', t('JM 直连')],
    ['nh', t('N站索引')], ['nhdl', t('N站直连')], ['eh', t('E站直连')],
    ['ext', t('外接下载器')],
  ];
  return avail ? all.filter(kv => avail.includes(kv[0])) : all;
}

function crawlKindName(k) {
  const hit = crawlKindsList().find(function (kv) { return kv[0] === k; });
  return hit ? hit[1] : (k || '');
}

async function crawlCopyText(text, okMsg) {
  if (!text || !text.trim()) { showToast(t('内容为空')); return; }
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
    } else {                                    // 非 https 环境（局域网 IP 访问）兜底
      const t = document.createElement('textarea');
      t.value = text;
      document.body.appendChild(t);
      t.select();
      document.execCommand('copy');
      t.remove();
    }
    showToast(okMsg);
  } catch (e) { showToast(tf('%1失败：%2', t('复制'), e.message)); }
}

/** 胶囊行：运行中的任务文字变绿（3.7.59 取代原来的"状态灯"面板）。 */
function crawlChipsHtml() {
  return crawlKindsList().map(function (kv) {
    const k = kv[0], label = kv[1];
    return '<button type="button" class="crawl-kind' + (crawlState.kind === k ? ' on' : '') +
      '" data-kind="' + k + '" title="' + esc(label) + esc(t('（各自独立，可同时运行）')) + '">' +
      esc(label) + '</button>';
  }).join('');
}

/** 拉五个任务的精简状态：只用来给胶囊上色 + 控启停按钮。 */
async function crawlRefreshChips() {
  const d = await api('/api/crawl/job?all=1');
  const jobs = {};
  (d.jobs || []).forEach(j => { jobs[j.kind] = j; });
  $('#crawlKinds')?.querySelectorAll('.crawl-kind').forEach(el => {
    const running = !!(jobs[el.getAttribute('data-kind')] || {}).running;
    el.classList.toggle('run', running);
  });
  const cur = jobs[crawlState.kind] || {};
  const bStart = $('#btnCrawlStart'), bStop = $('#btnCrawlStop');
  if (bStart) bStart.disabled = !!cur.running;
  if (bStop) bStop.disabled = !cur.running;
  return jobs;
}

function renderCrawl() {
  hideEmpty(); hideGridEmpty();
  clearInterval(crawlState.poll);
  crawlState.sawRunning = false;      // 3.7.59：进页面重置——上次的"已完成"不算本次
  crawlState.rev = null;
  $('#viewHead').innerHTML =
    (isImportOnly() ? '<button class="back" id="btnBack">← ' + esc(t('返回导入')) + '</button>'
                    : '<button class="back" id="btnBack">← ' + esc(t('返回')) + '</button>') +
    '<h2>🕷 ' + esc(t('清单下载器')) + '</h2>' +
    '<span class="sub">' + esc(t('按清单逐条联网获取（词条 / 车号 / ID）｜与「⛏ 搜索下载器」互相独立，可同时运行；')) +
      esc(t('下载落 _inbox，完成后到收件箱确认入库')) + '</span>';
  const grid = $('#grid');
  grid.className = 'grid grid-list';
  grid.innerHTML =
    '<div class="panel" id="crawlMonitor" style="width:100%;max-width:980px;margin:0 auto 12px"></div>' +
    '<div class="panel crawl-panel" style="width:100%;max-width:980px;margin:0 auto">' +
      '<div class="crawl-kinds" id="crawlKinds">' + crawlChipsHtml() + '</div>' +
      '<div class="sub" style="margin-top:8px">' + esc(tf('%1 个任务各自独立、可同时启动（独立清单与断点）；', crawlKindsList().length)) +
        esc(t('运行中的任务胶囊文字变绿。失败词条留在清单里，再启动一次即重试；成功条目跑完自动移除。')) + '</div>' +
      '<div class="info-actions" style="margin-top:10px;flex-wrap:wrap;gap:8px">' +
        '<span>' + esc(t('档位：')) + '<select id="crawlMode">' +
          '<option value="normal">' + esc(t('常规（下限 0.60）')) + '</option>' +
          '<option value="strict">' + esc(t('严格（下限 0.80/中文 0.75）')) + '</option>' +
        '</select></span>' +
        '　' + esc(t('单次上限：')) + '<input id="crawlLimit" type="number" min="0" value="0" style="width:64px" title="' + esc(t('0 = 不限；对 wnacg / N站直连 生效')) + '">' +
        '　<button id="btnCrawlStart" class="primary">▶ ' + esc(t('启动')) + '</button>' +
        '<button id="btnCrawlStop">■ ' + esc(t('停止')) + '</button>' +
        '<button id="btnCrawlCopyList" title="' + esc(t('复制当前任务对应的清单词条（直连=词条+车号两份）')) + '">📋 ' + esc(t('复制词条')) + '</button>' +
      '</div>' +
      '<div id="crawlWnacgWrap">' +
        '<h3 style="margin:14px 0 6px">pending_wnacg' + esc(t('（每行一个词条，# 开头为注释）')) + '</h3>' +          // i18n:data pending_wnacg=磁盘文件名
        '<textarea id="crawlListWnacg" class="doc-editor" style="height:150px" spellcheck="false" placeholder="[社团 (画师)] 标题 …"></textarea>' +   // i18n:data 示例=命名格式记号
      '</div>' +
      '<div id="crawlIndexWrap">' +
        '<h3 style="margin:14px 0 6px">pending_index' + esc(t('（JM / N站索引共享；每行一个数字 ID，N站还支持罗马音/日文词条）')) + '</h3>' +   // i18n:data
        '<textarea id="crawlListIndex" class="doc-editor" style="height:80px" spellcheck="false" placeholder="389745&#10;572360&#10;sample-manga-title-a"></textarea>' +
        '<div class="sub" style="margin-top:4px">' + esc(t('JM：数字车号 → jmcomic 拿标题 → wnacg 转载下载。')) +
          esc(t('N站：ID 直接用；词条走 v2 搜索裁决出 ID → 日文名 → wnacg 转载。')) + esc(t('跑完自动清除已完成条目。')) + '</div>' +
      '</div>' +
      '<div id="crawlJmdlTWrap">' +
        '<h3 style="margin:14px 0 6px">pending_jmdl_titles' + esc(t('（JM 直连专用，每行一个标题词条，走 JM 站内搜索）')) + '</h3>' +   // i18n:data
        '<textarea id="crawlListJmdlT" class="doc-editor" style="height:110px" spellcheck="false" placeholder="[社团 (画师)] 标题 …"></textarea>' +   // i18n:data
      '</div>' +
      '<div id="crawlJmdlIWrap">' +
        '<h3 style="margin:14px 0 6px">pending_jmdl_ids' + esc(t('（JM 直连专用，每行一个数字车号，直接下载）')) + '</h3>' +            // i18n:data
        '<textarea id="crawlListJmdlI" class="doc-editor" style="height:80px" spellcheck="false" placeholder="389745&#10;422866"></textarea>' +
      '</div>' +
      '<div id="crawlNhdlWrap">' +
        '<h3 style="margin:14px 0 6px">pending_nhdl' + esc(t('（N站直连，每行一个数字 ID 或罗马音/日文词条）')) + '</h3>' +      // i18n:data
        '<textarea id="crawlListNhdl" class="doc-editor" style="height:80px" spellcheck="false" placeholder="572360&#10;sample-manga-title-b"></textarea>' +
        '<div class="sub" style="margin-top:4px">' + esc(t('ID 直接用；词条搜索出 ID → 日文名作文件名 → 官方 ZIP 或图片 CDN 自建。')) + '</div>' +
      '</div>' +
      '<div id="crawlEhWrap">' +
        '<h3 style="margin:14px 0 6px">pending_ehdl' + esc(t('（E站直连，每行一个画廊 URL 或标题词条）')) + '</h3>' +            // i18n:data
        '<textarea id="crawlListEh" class="doc-editor" style="height:80px" spellcheck="false" placeholder="https://e-hentai.org/g/123456/abcdef1234/&#10;[社团 (画师)] 标题 …"></textarea>' +   // i18n:data
        '<div class="sub" style="margin-top:4px">' + esc(t('URL 直接下（最稳）；词条走引号短语搜索匹配 → 日文原名作文件名 → ')) +
          esc(t('种子优先（需 aria2c）/ 逐页兜底。强制走代理。')) + '</div>' +
      '</div>' +
      '<div id="crawlExtWrap">' +
        '<h3 style="margin:14px 0 6px">pending_ext' + esc(t('（每行一个 URL 或参数行，原样交给外接工具；# 开头为注释）')) + '</h3>' +   // i18n:data
        '<div class="info-actions" style="margin:0 0 6px">' +
          '<span>' + esc(t('外接工具：')) + '<select id="crawlExtTool"></select></span>' +
          '<span class="sub" id="crawlExtToolMsg"></span>' +
        '</div>' +
        '<textarea id="crawlListExt" class="doc-editor" style="height:80px" spellcheck="false" placeholder="https://gallery.example/g/12345/abcdef/"></textarea>' +
        '<div class="sub" style="margin-top:4px">' + esc(t('外接下载器：清单行原样交给配置的命令行工具（{url}=行内容、{dest}=暂存目录），产物打包 zip 落收件箱。')) + '</div>' +
      '</div>' +
      '<div class="info-actions" style="margin-top:8px">' +
        '<span class="sub" id="crawlListMsg">' + esc(t('编辑后自动保存')) + '</span>' +
      '</div>' +
    '</div>';
  (async () => {
    try {
      const lists = await api('/api/crawl/list');
      const w = $('#crawlListWnacg'), idx = $('#crawlListIndex');
      const jt = $('#crawlListJmdlT'), ji = $('#crawlListJmdlI');
      const nhdl = $('#crawlListNhdl'), eh = $('#crawlListEh');
      if (w) w.value = lists.wnacg || '';
      if (idx) idx.value = lists.index || '';
      if (jt) jt.value = lists.jmdlTitles || '';
      if (ji) ji.value = lists.jmdlIds || '';
      if (nhdl) nhdl.value = lists.nhdlIds || '';
      if (eh) eh.value = lists.ehIds || '';
      const ext = $('#crawlListExt');
      if (ext) ext.value = lists.ext || '';
    } catch (e) { showToast(tf('%1失败：%2', t('清单加载'), e.message)); }
    crawlRefreshChips().catch(() => {});
    crawlRefreshJob(crawlState.kind).catch(() => {});
    crawlRefreshExtTools().catch(() => {});
  })();
  $('#crawlKinds').addEventListener('click', (ev) => {
    const btn = ev.target.closest('.crawl-kind');
    if (!btn) return;
    crawlSelectKind(btn.getAttribute('data-kind'));
  });
  $('#btnCrawlStart').addEventListener('click', () => crawlStartTask());
  $('#btnCrawlStop').addEventListener('click', async () => {
    try {
      const r = await api('/api/crawl/stop', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: crawlState.kind })
      });
      showToast(r.message || t('已停止'));
      crawlRefreshChips().catch(() => {});
      crawlRefreshJob(crawlState.kind).catch(() => {});
    } catch (e) { showToast(tf('%1失败：%2', t('停止'), e.message)); }
  });
  $('#btnCrawlCopyList').addEventListener('click', async () => {
    const kind = crawlState.kind;
    let text = '', label = '';
    // label 只用来说「哪份清单」，而清单的名字就是磁盘上的 .txt 文件名 → 不译（与 APP 同口径，i18n:data）
    if (kind === 'wnacg') { text = $('#crawlListWnacg').value; label = 'pending_wnacg'; }              // i18n:data
    else if (kind === 'jm' || kind === 'nh') {
      text = ($('#crawlListIndex') || { value: '' }).value; label = 'pending_index';                   // i18n:data
    }
    else if (kind === 'nhdl') { text = $('#crawlListNhdl').value; label = 'pending_nhdl'; }      // i18n:data
    else if (kind === 'eh') { text = $('#crawlListEh').value; label = 'pending_ehdl'; }          // i18n:data
    else if (kind === 'ext') { text = ($('#crawlListExt') || { value: '' }).value; label = 'pending_ext'; }   // i18n:data
    else {
      const terms = ($('#crawlListJmdlT') || { value: '' }).value.trim();
      const ids = ($('#crawlListJmdlI') || { value: '' }).value.trim();
      text = (terms ? '【直连词条】\n' + terms : '') + (terms && ids ? '\n\n' : '') + (ids ? '【直连车号】\n' + ids : '');   // i18n:data 粘贴格式记号
      label = t('直连清单（词条+车号）');
    }
    await crawlCopyText(text, label + t('已复制'));
  });
  crawlSyncListVisibility();
  // 清单编辑自动保存（1 秒防抖），退出重进不丢
  let listSaveTimer = null;
  const saveLists = async () => {
    try {
      await api('/api/crawl/list', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          wnacg: $('#crawlListWnacg').value,
          index: ($('#crawlListIndex') || { value: '' }).value,
          jmdlTitles: $('#crawlListJmdlT').value,
          jmdlIds: $('#crawlListJmdlI').value,
          nhdlIds: ($('#crawlListNhdl') || { value: '' }).value,
          ehIds: ($('#crawlListEh') || { value: '' }).value,
          ext: ($('#crawlListExt') || { value: '' }).value
        })
      });
      const m = $('#crawlListMsg');
      if (m) m.textContent = t('已自动保存') + ' ' + new Date().toLocaleTimeString();
    } catch (e) {
      const m = $('#crawlListMsg');
      if (m) m.textContent = tf('%1失败：%2', t('自动保存'), e.message);
    }
  };
  const scheduleListSave = () => {
    clearTimeout(listSaveTimer);
    listSaveTimer = setTimeout(saveLists, 1000);
  };
  ['#crawlListWnacg', '#crawlListIndex', '#crawlListJmdlT', '#crawlListJmdlI', '#crawlListNhdl', '#crawlListEh', '#crawlListExt'].forEach(sel => {
    const el = $(sel);
    if (!el) return;
    el.addEventListener('input', scheduleListSave);
    el.addEventListener('blur', saveLists);
  });
  // 每 1.5 秒刷新胶囊上色 + 监控面板（任务跑在服务端，离开页面也在跑）
  crawlState.poll = setInterval(() => {
    if (state.view !== 'crawl') {
      clearInterval(crawlState.poll);
      crawlState.poll = null;
      return;
    }
    crawlRefreshChips().catch(() => { /* 静默轮询 */ });
    crawlRefreshJob(crawlState.kind).catch(() => { /* 静默轮询 */ });
  }, 1500);
}

/** 切换任务：胶囊高亮 + 只显示该任务的清单 + 重新拉监控。 */
function crawlSelectKind(kind) {
  if (!crawlKindsList().some(function (kv) { return kv[0] === kind; })) return;
  crawlState.kind = kind;
  crawlState.rev = null;
  $('#crawlKinds')?.querySelectorAll('.crawl-kind').forEach(el => {
    el.classList.toggle('on', el.getAttribute('data-kind') === kind);
  });
  crawlSyncListVisibility();
  crawlRefreshChips().catch(() => {});
  crawlRefreshJob(kind).catch(() => {});
}

/** 清单区可见性：索引系（JM/N站）共享同一份清单。 */
function crawlSyncListVisibility() {
  const kind = crawlState.kind;
  const show = (id, on) => { const el = $(id); if (el) el.style.display = on ? '' : 'none'; };
  show('#crawlWnacgWrap', kind === 'wnacg');
  show('#crawlIndexWrap', kind === 'jm' || kind === 'nh');
  show('#crawlJmdlTWrap', kind === 'jmdl');
  show('#crawlJmdlIWrap', kind === 'jmdl');
  show('#crawlNhdlWrap', kind === 'nhdl');
  show('#crawlEhWrap', kind === 'eh');
  show('#crawlExtWrap', kind === 'ext');
}

/** 3.6.155：拉外接下载器工具表填充下拉（未配置时显示引导文案）。 */
async function crawlRefreshExtTools() {
  const sel = $('#crawlExtTool'), msg = $('#crawlExtToolMsg');
  if (!sel) return;
  try {
    const d = await api('/api/crawl/ext/tools');
    const tools = d.tools || [];
    sel.innerHTML = tools.map(x => '<option value="' + esc(x.name) + '">' + esc(x.name) + '</option>').join('');
    if (msg) msg.textContent = tools.length ? '' : t('未配置外接下载器：在 config.json 的 ext_downloaders 里添加工具后重启面板');
  } catch (e) {
    if (msg) msg.textContent = tf('%1失败：%2', t('外接工具'), e.message);
  }
}

/** 启动当前任务（清单取当前可见的那个；jmdl 独占词条 + 车号两份）。 */
async function crawlStartTask() {
  const kind = crawlState.kind;
  const limit = parseInt($('#crawlLimit').value, 10) || 0;
  const strict = $('#crawlMode').value === 'strict';
  const body = { kind: kind, limit: limit, strict: strict };
  if (kind === 'jmdl') {
    body.entries = ($('#crawlListJmdlT') || { value: '' }).value.split('\n');
    body.jmEntries = ($('#crawlListJmdlI') || { value: '' }).value.split('\n');
  } else {
    const id = kind === 'wnacg' ? 'crawlListWnacg'
      : (kind === 'nhdl' ? 'crawlListNhdl'
        : (kind === 'eh' ? 'crawlListEh'
          : (kind === 'ext' ? 'crawlListExt' : 'crawlListIndex')));
    const ta = $('#' + id);
    body.entries = ta ? ta.value.split('\n') : [];
    if (kind === 'ext') body.tool = ($('#crawlExtTool') || { value: '' }).value;
  }
  try {
    const r = await api('/api/crawl/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    showToast(r.message || t('已启动'));
    crawlState.rev = null;             // 新任务一定换了一批卡片
    crawlState.sawRunning = true;
    crawlRefreshChips().catch(() => {});
    crawlRefreshJob(kind).catch(() => {});
  } catch (e) { showToast(tf('%1失败：%2', t('启动'), e.message)); }
}
