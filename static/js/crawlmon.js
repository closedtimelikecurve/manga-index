/* 本地同人志文库 前端 · crawlmon.js
   清单爬虫的监控面板（3.7.58 立，3.7.59 改为与分区爬虫一致的作品卡）。
   只做"把任务快照画出来 + 全局浮标"；启停与清单仍在 crawl.js。
   仍是 classic script，与其余分片共享同一个全局词法环境（顺序加载，勿调整 index.html 次序）。 */
'use strict';

// 3.6.141 函数化：切语言跟随（理由同 crawlJobStates）。
function crawlPhaseText() {
  return { idle: t('空闲'), lock: t('锁定作品中'), cover: t('准备封面'),
    download: t('集中获取中'), done: t('已结束') };
}

/** 当前选中的任务（胶囊选中项）。 */
function currentCrawlKind() {
  return crawlState.kind || 'wnacg';
}

async function crawlRefreshJob(kind) {
  const d = await api('/api/crawl/job?kind=' + encodeURIComponent(kind || 'wnacg'));
  crawlState.job = d;
  crawlRenderJob(d);
  return d;
}

/**
 * 面板主体。
 *
 * 3.7.61：**只在"卡片集合"变化时重建 DOM**，其余帧只改文本/类名。
 * 以前按 rev 全量重建（下载中 rev 每几百毫秒就变），等于把每张 `<img>` 反复销毁重建；
 * 第二次请求一旦碰上封面代理的空返回/404，新图就被 `onerror` 隐藏 —— 用户看到的
 * 正是"封面出现两秒后消失"。现在图片节点一旦插上就不再动。
 */
function crawlRenderJob(d) {
  const box = $('#crawlMonitor');
  if (!box) return;
  // 3.7.59：离开界面后回来，上次的"已结束"要回到空闲——
  // 只有本次进入页面后亲眼见过它运行，才保留结果。
  if (d && d.running) crawlState.sawRunning = true;
  const show = d && d.total && (d.running || crawlState.sawRunning);
  if (!show) {
    if (crawlState.rev !== 'idle') {
      crawlState.rev = 'idle';
      crawlState.sig = '';
      box.innerHTML = '<div class="cj-head"><b>' + esc(t('🎯 下载监控')) + '</b>' +
        '<span class="sub" style="margin-left:8px">' +
        esc(t('空闲：选好任务后点「▶ 启动」，这里逐部显示锁定到的作品（带封面）与下载进度')) + '</span></div>';
    }
    return;
  }
  const sig = crawlJobSig(d);
  crawlState.rev = d.rev;
  if (crawlState.sig !== sig) {          // 卡片集合变了（锁定出新作品 / 换任务）才重建
    crawlState.sig = sig;
    box.innerHTML = crawlJobHtml(d);
  }
  crawlUpdateJobTick(d);
}

/** 卡片集合指纹：条目数 + 每条的 idx/aid/有无封面。变了才值得重建 DOM。 */
function crawlJobSig(d) {
  return (d.kind || '') + '|' + (d.total || 0) + '|' + (d.items || [])
    .map(it => it.idx + ':' + (it.aid || '')).join(',');
}

/** 百分比：锁定阶段看"已锁定/总数"，爬取阶段看"已处理/总数"。 */
function crawlJobPct(d) {
  if (d.phase === 'cover' && d.covers) {          // 3.7.64：封面阶段看"备好几张"
    return Math.max(0, Math.min(100, Math.round((d.covers_ready || 0) * 100 / d.covers)));
  }
  if (!d.total) return 0;
  const n = d.phase === 'lock' ? (d.locked || 0) : ((d.done || 0) + (d.failed || 0));
  return Math.max(0, Math.min(100, Math.round(n * 100 / d.total)));
}

function crawlJobHtml(d) {
  const pct = crawlJobPct(d);
  return '<div class="cj-head">' +
      '<b id="cjPhase">' + (d.running ? '🎯 ' + esc(crawlPhaseText()[d.phase] || d.phase) : esc(t('✅ 已结束'))) + '</b>' +
      '<span class="sub" style="margin-left:8px">' + esc(d.label || d.kind || '') +
        ' · <span id="cjElapsed"></span></span>' +
      '<span class="cj-count"><b id="cjDone">' + (d.done || 0) + '</b>/<span id="cjTotal">' +
        (d.total || 0) + '</span></span>' +
      '<button type="button" class="back" id="cjCancel" style="' +
        (d.running ? '' : 'display:none') + '">■ ' + esc(t('停止')) + '</button>' +
    '</div>' +
    '<div class="cj-bar"><i id="cjBar" style="width:' + pct + '%"></i></div>' +
    '<div class="cj-stats" id="cjStats"></div>' +
    '<div class="cj-grid" id="cjGrid">' + d.items.map(crawlJobCard).join('') + '</div>';
}

/**
 * 单部作品卡片：与「分区爬虫」查询结果同款（.probe-card / .probe-cover / .probe-title）——
 * 左封面 84×112、右标题四行 + 状态行，网格排列，不再是一行行横条。
 */
function crawlJobCard(it) {
  const label = crawlJobStates()[it.state] || it.state;   // 3.6.140 状态表函数化（切语言跟随）
  const cover = it.cover
    ? '<img class="probe-cover" loading="lazy" alt="" src="/api/crawl/probe/cover?u=' +
      encodeURIComponent(it.cover) + '" onerror="this.classList.add(&#39;err&#39;)">'
    : '<div class="probe-cover ph">🎴</div>';
  return '<div class="probe-card cj-card s-' + esc(it.state) + '" data-idx="' + it.idx + '">' +
    cover +
    '<div class="probe-meta">' +
      '<div class="probe-title">' + esc(it.title || it.entry) + '</div>' +
      '<div class="cj-sub"><span class="cj-badge">' + esc(label) + '</span>' +
        '<span class="cj-note" data-note="' + it.idx + '">' + esc(crawlJobNote(it)) + '</span></div>' +
    '</div></div>';
}

/** 卡片副行：下载中给字节进度，失败给原因，其余给站点/页数。 */
function crawlJobNote(it) {
  if (it.state === 'downloading' && it.bytes) {
    return fmtBytes(it.bytes) + (it.bytes_total ? ' / ' + fmtBytes(it.bytes_total) : '');
  }
  if (it.state === 'downloading') return t('连接中…');
  if (it.state === 'fail' || it.state === 'unmatched') return it.msg || '';
  if (it.state === 'ok') return it.msg || t('已完成');
  if (it.state === 'skip') return it.msg || t('跳过');
  if (it.aid) return 'aid ' + it.aid + (it.pages ? tf(' · %1 页', it.pages) : '');
  return it.msg || '';
}

/** 每秒都会调：只更新会连续变化的文本与类名（耗时/字节/进度条/状态），不重建卡片。 */
function crawlUpdateJobTick(d) {
  const phase = $('#cjPhase');
  if (phase) {
    phase.textContent = d.running ? '🎯 ' + (crawlPhaseText()[d.phase] || d.phase) : t('✅ 已结束');
  }
  const doneEl = $('#cjDone');
  if (doneEl) doneEl.textContent = d.done || 0;
  const cancel = $('#cjCancel');
  if (cancel) cancel.style.display = d.running ? '' : 'none';
  const el = $('#cjElapsed');
  if (el) {
    // 3.6.141：局部变量原名 t 会遮蔽全局翻译函数，改名 txt 并顺带接线
    const txt = d.running ? tf('已运行 %1', probeElapsedText(d.elapsed || 0))
                          : tf('耗时 %1', probeElapsedText(d.elapsed || 0));
    el.textContent = txt + (d.current ? tf(' · 正在处理：%1', d.current) : '');
  }
  const bar = $('#cjBar');
  if (bar) bar.style.width = crawlJobPct(d) + '%';
  const stats = $('#cjStats');
  if (stats) {
    stats.innerHTML = tf('总数 <b>%1</b> · 已锁定 <b>%2</b>', d.total || 0, d.locked || 0) +
      (d.covers ? tf(' · 封面 <b>%1/%2</b>', d.covers_ready || 0, d.covers) : '') +
      tf(' · 成功 <b class="ok">%1</b> · 失败 <b class="bad">%2</b>', d.done || 0, d.failed || 0) +
      (d.skipped ? tf(' · 跳过 %1', d.skipped) : '') +
      (d.message ? '　<span class="sub">' + esc(d.message) + '</span>' : '');
  }
  const grid = $('#cjGrid');
  if (!grid) return;
  (d.items || []).forEach(it => {
    const card = grid.querySelector('[data-idx="' + it.idx + '"]');
    if (!card) return;
    // 状态类名（边框颜色）与徽标文案就地改，不碰 <img>
    const cls = card.className.replace(/(^|\s)s-\S+/g, ' ').trim();
    if (cls !== card.className) card.className = cls + ' s-' + it.state;
    const badge = card.querySelector('.cj-badge');
    if (badge) badge.textContent = crawlJobStates()[it.state] || it.state;
    const n = card.querySelector('.cj-note');
    if (n) n.textContent = crawlJobNote(it);
  });
}

document.addEventListener('click', async (ev) => {
  const btn = ev.target.closest('#cjCancel');
  if (!btn) return;
  try {
    const r = await api('/api/crawl/stop', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind: currentCrawlKind() })
    });
    showToast(r.message || t('已请求停止'));
  } catch (e) { showToast(tf('%1失败：%2', t('停止'), e.message)); }
});

/* ---------- 3.7.58 全局浮标：离开爬虫页也知道任务还在跑 ---------- */
const crawlWatch = { timer: null };

function crawlWatchStart() {
  if (!crawlWatch.timer) crawlWatchTick();
}

async function crawlWatchTick() {
  if (crawlWatch.timer) { clearTimeout(crawlWatch.timer); crawlWatch.timer = null; }
  let jobs = [];
  try { jobs = (await api('/api/crawl/job?all=1')).jobs || []; } catch (e) { /* 静默 */ }
  const run = jobs.filter(j => j.running);
  crawlRenderTicker(run);
  crawlWatch.timer = setTimeout(crawlWatchTick, run.length ? 3000 : 12000);
}

/** 右下角浮标（在分区爬虫浮标之上）：只显示"有任务在跑"，点击进清单爬虫页。 */
function crawlRenderTicker(run) {
  const el = $('#crawlTicker');
  if (!el) return;
  if (!run.length) { el.classList.add('hidden'); return; }
  const j = run[0];
  const done = (j.done || 0) + (j.failed || 0);
  el.classList.remove('hidden');
  el.innerHTML = '🕷 ' + esc(t('清单下载器')) + ' <b>' + done + '/' + (j.total || 0) + '</b>' +
    '<span class="pt-meta">' + (run.length > 1 ? tf('%1 个任务 · ', run.length) : '') +
    probeElapsedText(j.elapsed || 0) + '</span>';
  el.title = (j.label || '') + (j.message ? '：' + j.message : '') + t('（点击查看监控面板）');
}
