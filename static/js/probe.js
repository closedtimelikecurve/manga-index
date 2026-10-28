/* 本地同人志文库 前端 · probe.js
   3.7.54 新增：「按作者 / 社团 / 原作名爬取」的专门界面。
   入口两处：① 直接进 #/probe；② 社团页 / 画师页 / 同人分区页右上角。
   3.7.59 起与「清单爬虫」彻底分开：两边任务互不影响，清单爬虫页不再有这里的入口。
   （带 kind + term 直接预填并自动搜一次）。
   流程：搜索 → 横板卡片（压缩封面 + 标题 + 页数）勾选 → 后台下载 → 自动入库归区。
   与其余分片共享同一个全局词法环境（顺序加载，勿调整 index.html 里的 <script> 次序）。 */
'use strict';

// 3.6.141 函数化：顶层 const 会在加载期固化 t() 结果、切语言冻住（crawlJobStates 同坑第四例）。
function probeKinds() {
  return [
    ['author', '👤 ' + t('画师名')],
    ['circle', '🏢 ' + t('社团名')],
    ['original', '🎴 ' + t('同人名')],
  ];
}
// 3.7.57：顶部不再放"画师/社团/同人"三枚无效 chip（搜索结果都是同一个站点 q 查询，
// kind 只决定入库归区）。改为目标站点切换；kind 仍由入口路由携带，用于自动归区。
// 3.6.156：按服务端 builtinKinds 过滤（公开版只带 JM 直连 → 只有 JM 站点可搜；
// 老面板无该字段 → 全部显示）。站点↔任务底座：wnacg↔wnacg、JM↔jmdl、N站↔nhdl、E站↔eh。
function probeSites() {
  const avail = (window.state && state.config && state.config.builtinKinds) || null;
  const all = [
    ['wnacg', 'wnacg', 'wnacg'],
    ['jmcomic', 'JM', 'jmdl'],
    ['nhentai', t('N站'), 'nhdl'],
    ['ehentai', t('E站'), 'eh'],
  ];
  const ok = (Array.isArray(avail) && avail.length) ? avail : null;
  return ok ? all.filter(p => ok.includes(p[2])) : all;
}
const probe = {
  kind: 'author', term: '', site: 'wnacg', works: [], sel: new Set(),
  busy: false, job: null, timer: null, wasRunning: false, sawRunning: false,
  total: 0, hasMore: false, nextStart: 1, loadingMore: false, domain: '',
};

function probeKindOk(k) { return probeKinds().some(p => p[0] === k) ? k : 'author'; }
function probeSiteOk(s) {
  const sites = probeSites();
  if (sites.some(p => p[0] === s)) return s;
  return sites.length ? sites[0][0] : 'wnacg';   // 公开版默认站点回退到第一个可用站
}

/* ---------- 视图 ---------- */
function renderProbe(kind, term, site) {
  hideEmpty(); hideGridEmpty();
  const prevKey = [probe.kind, probe.term, probe.site].join('\u0000');
  probe.kind = probeKindOk(kind);
  probe.site = probeSiteOk(site);
  probe.term = (term || '').trim();
  probe.sawRunning = false;      // 3.6.112：进页面重置——上次的"已结束"回到空闲（与清单爬虫对齐）
  const same = prevKey === [probe.kind, probe.term, probe.site].join('\u0000');
  if (!same) {                       // 换词条/换站点才清空；重进同一路由保留已搜结果
    probe.works = [];
    probe.sel = new Set();
    probe.hasMore = false;
  }
  renderProbeHead();
  const grid = $('#grid');
  grid.className = 'grid probe-grid';
  if (probe.job && probe.job.running) {
    probeSyncClock(probe.job);
    probe.wasRunning = true;
    renderProbeResults();            // 运行中：只显示顶部进度面板
  } else if (same && probe.works.length) {
    renderProbeResults();            // 任务结束后的 refresh 不清掉已有结果
  } else {
    grid.innerHTML = probeEmptyHint(probe.term
      ? tf('已填入「%1」，点「搜索」才开始查询（不再自动搜）', esc(probe.term))
      : esc(t('选择站点后输入词条，点「搜索」开始：命中后勾选要爬的作品，下载完会自动入库并归到对应分区。')));
  }
  probeWatchStart();          // 进页面就确保看护在跑（全局浮标/进度同步靠它）
}

function probeEmptyHint(text) {
  return '<div class="panel entry-empty" style="grid-column:1/-1">' + text + '</div>';
}

function renderProbeHead() {
  const chips = probeSites().map(([k, label]) =>
    '<button type="button" class="probe-kind' + (probe.site === k ? ' on' : '') +
    '" data-site="' + k + '">' + esc(label) + '</button>').join('');
  $('#viewHead').innerHTML =
    '<button class="back" id="btnBack">← ' + esc(t('返回')) + '</button>' +
    '<h2>⛏ ' + esc(t('搜索下载器')) + ' <span class="sub">' + esc(t('选目标站点 → 输入词条 → 点搜索 → 勾选下载')) + '</span></h2>' +
    '<div class="probe-kinds">' + chips + '</div>' +
    '<div class="probe-form">' +
      '<input id="probeTerm" placeholder="' + esc(tf('在 %1 站内搜索（作者 / 社团 / 同人 / 标题）', probeSiteLabel(probe.site))) +
      '" value="' + esc(probe.term) + '">' +
      '<button id="probeGo" class="primary">' + esc(t('搜索')) + '</button>' +
    '</div>' +
    '<div class="sub" id="probeInfo"></div>' +
    // 3.7.56：进度面板放在视图头（而不是搜索结果底部）——任务一开始就看得见，
    // 没有词条、还没搜出结果时也在；点击右下角浮标回到这里即可看到明细。
    '<div class="probe-monitor probe-job hidden" id="probeJob"></div>';
  $('#btnBack').addEventListener('click', () => { location.hash = '#/crawl'; });
  $('#viewHead').querySelectorAll('.probe-kind').forEach(b => b.addEventListener('click', () => {
    const site = probeSiteOk(b.dataset.site);
    if (site === probe.site) return;
    probe.site = site;
    probe.works = []; probe.sel = new Set(); probe.hasMore = false;
    probe.total = 0; probe.nextStart = 1; probe.info = '';
    probeUpdateHash();
    renderProbeHead();
    $('#grid').className = 'grid probe-grid';
    $('#grid').innerHTML = probeEmptyHint(
      tf('已切换到 <b>%1</b>：输入词条后点「搜索」才开始查询。', esc(probeSiteLabel(site))));
    probeRenderJob();
  }));
  const go = () => {
    probe.term = $('#probeTerm').value.trim();
    if (!probe.term) { showToast(t('先输入词条')); return; }
    probeSearch();
  };
  $('#probeGo').addEventListener('click', go);
  $('#probeTerm').addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
  probeRenderJob();          // 头部重建后立刻恢复当前任务明细（不依赖搜索结果是否已回来）
  probeSyncBar();
}

/* ---------- 搜索（两段式：先首屏、再后台补全） ---------- */
async function probeFetch(term, kind, pages, start) {
  return api('/api/crawl/probe', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ term: term, kind: kind, site: probe.site, pages: pages, start: start }),
  });
}

async function probeSearch() {
  if (probe.busy) return;
  if (probe.job && probe.job.running) { showToast(t('获取进行中，结束后再搜索')); return; }
  probeUpdateHash();
  probe.busy = true;
  probe.works = []; probe.sel = new Set(); probe.hasMore = false;
  const info = $('#probeInfo');
  if (info) info.textContent = tf('搜索中…（%1 站内响应约 2~5 秒）', probeSiteLabel(probe.site));
  try {
    // 第一步只要首屏：wnacg 24 条 / JM 80 条 / N站 25 条，1~2 秒就能看到卡片
    const d = await probeFetch(probe.term, probe.kind, 1, 1);
    if (state.view !== 'probe') return;
    probe.site = probeSiteOk(d.site || probe.site);
    probeUpdateHash();
    probe.works = d.works || [];
    probe.total = d.total || 0;
    probe.domain = d.domain || '';
    probe.hasMore = !!d.hasMore;
    probe.nextStart = d.nextStart || 2;
    probeInfoText();
    if (!probe.works.length) showToast(t('没有命中，换个写法或切到对应站点再试'));
    renderProbeResults();
    // wnacg 维持"首屏后后台补全"；JM/N站页数可能上百，只在用户点「继续加载」时增量抓
    if (probe.hasMore && d.autoLoad !== false) probeLoadRest();
  } catch (e) {
    if (state.view !== 'probe') return;
    showToast(tf('%1失败：%2', t('搜索'), e.message));
    $('#grid').innerHTML = probeEmptyHint(tf('%1失败：%2', t('搜索'), esc(e.message)) +
      '<br><span class="sub">' + esc(t('多半是站点不可达（代理/域名），稍后重试。')) + '</span>');
  } finally { probe.busy = false; }
}

/** 后台补全：首屏出来后立刻把剩下的页一并拉回来（服务端并发翻页，约 2~4 秒）。 */
async function probeLoadRest() {
  if (probe.loadingMore || probe.site !== 'wnacg') return;
  probe.loadingMore = true;
  probeInfoText();
  try {
    const d = await probeFetch(probe.term, probe.kind, 0, 1);
    if (state.view !== 'probe') return;
    probeAppend(d.works || []);
    probe.total = d.total || probe.total;
    probe.hasMore = !!d.hasMore;
    probe.nextStart = d.nextStart || probe.nextStart;
    probeInfoText();
    probePaint();
  } catch (e) { showToast(tf('%1失败：%2', t('补全剩余结果'), e.message)); }
  finally { probe.loadingMore = false; probeInfoText(); }
}

/** 「继续加载」：从第 nextStart 页起增量抓 8 页（不重复拉前面的页）。 */
async function probeLoadMore() {
  if (probe.loadingMore) return;
  probe.loadingMore = true;
  probeInfoText();
  try {
    const d = await probeFetch(probe.term, probe.kind, 8, probe.nextStart);
    if (state.view !== 'probe') return;
    probeAppend(d.works || []);
    probe.hasMore = !!d.hasMore;
    probe.nextStart = d.nextStart || (probe.nextStart + 8);
    probeInfoText();
    probePaint();
  } catch (e) { showToast(tf('%1失败：%2', t('加载更多'), e.message)); }
  finally { probe.loadingMore = false; probeInfoText(); }
}

/** 合并（按 aid 去重、保持顺序、保留已勾选）。 */
function probeAppend(list) {
  const have = new Set(probe.works.map(w => w.aid));
  probe.works = probe.works.concat(list.filter(w => !have.has(w.aid)));
}

function probeInfoText() {
  const el = $('#probeInfo');
  if (!el) return;
  const shown = probe.works.length;
  const of = probe.total ? tf(' / 约 %1', probe.total) : '';
  const tail = probe.loadingMore ? t(' · 正在补全剩余结果…')
    : (probe.hasMore ? t(' · 还有更多，可继续加载') : '');
  el.textContent = shown
    ? tf('站点 %1 · 已显示 %2', probeSiteLabel(probe.site), shown) + of + tail
    : (probe.busy ? tf('搜索中…（%1）', probeSiteLabel(probe.site)) : '');
}

/* ---------- 开始爬取 / 进度 ---------- */
async function probeStart() {
  const picks = probe.works.filter(w => probe.sel.has(w.aid))
    .map(w => ({ aid: w.aid, title: w.title, token: w.token || '', cover: w.cover || '' }));
  if (!picks.length) return;
  try {
    const r = await api('/api/crawl/pick', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ term: probe.term, kind: probe.kind, site: probe.site, picks }),
    });
    if (!r.ok) { showToast(r.message || t('启动失败')); return; }
    probe.job = r.job;
    probeSyncClock(probe.job);
    probe.site = probeSiteOk((r.job && r.job.site) || probe.site);
    probeWatch.wasRunning = !!(r.job && r.job.running);
    showToast(tf('已开始下载 %1 部（离开本页也会继续，右下角有进度浮标）', picks.length));
    probeEmit();
    probeWatchTick();          // 立刻进入 2s 快轮询（空闲看护原本 15s 一轮太慢）
  } catch (e) { showToast(tf('%1失败：%2', t('启动'), e.message)); }
}

/* ---------- 全局看护：任何界面都能看到进度 ----------
   用户报障：从爬虫界面退出后就不知道任务还在不在跑。任务本来就跑在**服务端线程**里，
   界面只是观察者；所以这里不再把轮询绑在某个视图上：
     * 看护循环常驻（运行中 2s、空闲 15s 一轮，空闲间隔足够低耗）；
     * 运行中右下角有浮标（点击回到详情页），任何页面都看得见；
     * 结束的那一瞬间全局提示 + 刷新文库（新作品这时才进索引）。 */
const probeWatch = { timer: null, wasRunning: false, busy: false };

function probeWatchStart() {
  if (!probe.timer) probe.timer = setInterval(probeClockTick, 1000);   // 本地计时
  if (probeWatch.busy || probeWatch.timer) return;   // 单飞：init/进页/起任务重复调用不叠加轮询
  probeWatchTick();
}

async function probeWatchTick() {
  if (probeWatch.busy) return;
  probeWatch.busy = true;
  if (probeWatch.timer) { clearTimeout(probeWatch.timer); probeWatch.timer = null; }
  try {
    const d = await api('/api/crawl/pick/status');
    probeWatchApply(d.job || null);
  } catch (e) { /* 面板重启/瞬时断网：下一轮再试，不打扰用户 */ }
  finally {
    probeWatch.busy = false;
    const running = !!(probe.job && probe.job.running);
    probeWatch.timer = setTimeout(probeWatchTick, running ? 2000 : 15000);
  }
}

function probeWatchApply(job) {
  const prevRunning = probeWatch.wasRunning;
  // 3.6.112：已结束的任务只有"本次进页面后亲眼见过它运行"才保留（与清单爬虫对齐）——
  // 否则退出再进，上次的"已结束"面板还赖在头上。
  probe.job = (job && (job.running || (job.finished && probe.sawRunning))) ? job : null;
  if (probe.job && probe.job.running) probe.sawRunning = true;
  probeSyncClock(probe.job);
  const running = !!(probe.job && probe.job.running);
  probeWatch.wasRunning = running;
  if (prevRunning && !running && probe.job) {
    showToast(tf('搜索下载器结束：成功 %1 · 失败 %2', probe.job.done, probe.job.failed));
    refresh(true);                     // 入库后的新作品/新原作标签这时才在索引里
  }
  probeEmit();
}

/** 把最新进度广播给"此刻存在的"观察者（浮标 / 探针页详情）。 */
function probeEmit() {
  probeRenderTicker();
  const running = !!(probe.job && probe.job.running);
  if (running !== probe.wasRunning) {
    probe.wasRunning = running;
    if (state.view === 'probe') renderProbeResults();   // 起/止任务时切换"结果 ↔ 进度"
  }
  if (state.view === 'probe') {
    probeRenderJob();
    probeSyncBar();               // 任务在别处启动时，本页「开始爬取」按钮也要跟着禁用
  }
  // 3.7.59：清单爬虫页与分区爬虫互相独立，不再互相嵌卡片
}

function probeElapsedText(sec) {
  const s = Math.max(0, Number(sec) || 0);
  if (s < 60) return tf('%1 秒', s);
  const m = Math.floor(s / 60);
  if (m < 60) return tf('%1 分 %2 秒', m, s % 60);
  return tf('%1 时 %2 分', Math.floor(m / 60), m % 60);
}

function probeBytesText(n) {
  n = Math.max(0, Number(n) || 0);
  if (n >= 1073741824) return (n / 1073741824).toFixed(2) + ' GB';
  if (n >= 1048576) return (n / 1048576).toFixed(1) + ' MB';
  return Math.round(n / 1024) + ' KB';
}

/** 正在处理的那一条（下载中/入库中）；没有则 null。 */
function probeCurrentItem(job) {
  return ((job && job.items) || []).find(it =>
    it.state === 'downloading' || it.state === 'importing') || null;
}

/** 条目右侧明细：下载中优先显示字节进度，其余显示服务端消息。
 *  3.6.111 迁至 probejob.js 的是看板渲染；本函数仍被看板卡片与浮标共用，留在此处。 */
function probeItemDetail(it) {
  if (it.state === 'downloading' && it.bytes) {
    const total = it.bytes_total ? ' / ' + probeBytesText(it.bytes_total) : '';
    const pct = it.bytes_total
      ? ' · ' + Math.min(100, Math.round(it.bytes * 100 / it.bytes_total)) + '%' : '';
    return probeBytesText(it.bytes) + total + pct;
  }
  return it.msg || '';
}

/** 右下角进度浮标：只在运行中显示，点击回到详情页。 */
function probeRenderTicker() {
  const el = $('#probeTicker');
  if (!el) return;
  const j = probe.job;
  if (!j || !j.running) { el.classList.add('hidden'); return; }
  const done = (j.done || 0) + (j.failed || 0);
  const pct = j.total ? Math.round(done * 100 / j.total) : 0;
  const cur = probeCurrentItem(j);
  el.classList.remove('hidden');
  el.innerHTML = '<span class="pt-ico">⛏</span> ' +
    (cur ? esc(probeStateText()[cur.state] || t('获取中')) : esc(t('获取中'))) +
    ' <b>' + done + '/' + (j.total || 0) + '</b>' +
    '<span class="pt-meta"><span id="probeTickerElapsed">' + probeElapsedText(probeElapsedValue()) +
    '</span> · ' + pct + '%</span>';
  el.title = (cur ? tf('正在处理：%1；', cur.title || ('aid ' + cur.aid)) : '') + t('点击查看进度');
}

// 3.6.141 函数化：切语言跟随（理由同 crawlJobStates）。
function probeStateText() {
  return { queued: t('排队中'), downloading: t('下载中'), importing: t('入库中'),
    ok: t('已入库'), fail: t('失败'), skip: t('已取消') };
}

/* 3.6.111：任务看板渲染（与清单爬虫监控同款外壳与封面卡）已整体迁至 probejob.js，
   本文件只保留数据拉取与状态（渲染入口由 probejob 接管，调用点不变）。 */
