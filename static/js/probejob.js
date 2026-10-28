/* 本地同人志文库 前端 · probejob.js
   分区爬取的任务看板（3.6.111：与「清单爬虫」监控对齐——.cj-head/.cj-bar/.cj-stats/
   .cj-grid 同款外壳 + 封面作品卡 + 指纹更新防封面闪现）。
   旧实现（probe.js 的纯文字行 + 每 2s 整块重建）随本文件退役：整块重建一旦条目带
   <img>，就会复现清单爬虫当年"封面出现两秒后消失"的毛病（见 crawlmon.js 头注）。
   数据/容器/取消：probe.job ← probeWatchTick；#probeJob；/api/crawl/pick/cancel。
   #probeJobElapsed 保留原名：probeclock.js 的本地计时每秒更新它。
   仍是 classic script，与其余分片共享同一个全局词法环境（顺序加载，勿调整 index.html 次序）。 */
'use strict';

let _probeJobSig = '';

/** 卡片集合指纹：条目数 + 每条 aid/有无封面。变了才值得重建 DOM（卡片随之换图）。 */
function probeJobSig(d) {
  return 'p|' + (d.total || 0) + '|' + (d.items || [])
    .map(it => it.aid + ':' + (it.cover ? 1 : 0)).join(',');
}

function probeJobPct(d) {
  if (!d.total) return 0;
  return Math.max(0, Math.min(100,
    Math.round(((d.done || 0) + (d.failed || 0)) * 100 / d.total)));
}

/**
 * 单部作品卡片：与清单爬虫监控卡同结构（.probe-card/.cj-card + .cj-badge/.cj-note）。
 * cover 与清单爬虫不同：picks 自带的是**本站代理地址**（/api/crawl/probe/cover?u=…），
 * 直接作 src 即可；兼容裸图床地址（再包一层代理）。
 */
function probeJobCard(it) {
  const label = probeStateText()[it.state] || it.state;
  const src = !it.cover ? ''
    : (it.cover.startsWith('/') ? it.cover
      : '/api/crawl/probe/cover?u=' + encodeURIComponent(it.cover));
  const cover = src
    ? '<img class="probe-cover" loading="lazy" alt="" src="' + esc(src) +
      '" onerror="this.classList.add(&#39;err&#39;)">'
    : '<div class="probe-cover ph">🎴</div>';
  return '<div class="probe-card cj-card s-' + esc(it.state) + '" data-aid="' + esc(String(it.aid)) + '">' +
    cover +
    '<div class="probe-meta">' +
      '<div class="probe-title">' + esc(it.title || ('aid ' + it.aid)) + '</div>' +
      '<div class="cj-sub"><span class="cj-badge">' + esc(label) + '</span>' +
        '<span class="cj-note" data-note="' + esc(String(it.aid)) + '">' +
          esc(probeItemDetail(it)) + '</span></div>' +
    '</div></div>';
}

function probeJobHtml(d) {
  const pct = probeJobPct(d);
  return '<div class="cj-head">' +
      '<b id="pjPhase">' + (d.running ? esc(t('⛏ 正在获取')) : esc(t('✅ 已结束'))) + '</b>' +
      '<span class="sub" style="margin-left:8px">' + esc(d.term || '') + ' · ' +
        esc(probeSiteLabel(d.site || probe.site)) +
        ' · <span id="probeJobElapsed">' + esc(probeElapsedText(d.elapsed || 0)) + '</span>' +
        (d.queue ? tf(' · 排队 %1 部', d.queue) : '') + '</span>' +
      '<span class="cj-count"><b id="pjDone">' + (d.done || 0) + '</b>/<span id="pjTotal">' +
        (d.total || 0) + '</span></span>' +
      '<button type="button" class="back" id="probeCancel" style="' +
        (d.running ? '' : 'display:none') + '">' + esc(t('取消')) + '</button>' +
    '</div>' +
    '<div class="cj-bar"><i id="pjBar" style="width:' + pct + '%"></i></div>' +
    '<div class="cj-stats" id="pjStats"></div>' +
    '<div class="cj-grid" id="pjGrid">' + (d.items || []).map(probeJobCard).join('') + '</div>';
}

/** 每帧就地更新（状态类/徽标/note/计数/进度条），不碰 <img>。 */
function probeUpdateJobTick(d) {
  const phase = $('#pjPhase');
  // 3.6.141：原文这里写的是「正在爬取」、首帧是「正在获取」——本就不是有意区分，统一为一个 key
  if (phase) phase.textContent = d.running ? t('⛏ 正在获取') : t('✅ 已结束');
  const doneEl = $('#pjDone');
  if (doneEl) doneEl.textContent = d.done || 0;
  const totalEl = $('#pjTotal');
  if (totalEl) totalEl.textContent = d.total || 0;
  const cancel = $('#probeCancel');
  if (cancel) cancel.style.display = d.running ? '' : 'none';
  const bar = $('#pjBar');
  if (bar) bar.style.width = probeJobPct(d) + '%';
  const stats = $('#pjStats');
  if (stats) {
    const cur = probeCurrentItem(d);
    stats.innerHTML = tf('成功 <b class="ok">%1</b> · 失败 <b class="bad">%2</b>', d.done || 0, d.failed || 0) +
      (d.queue ? tf(' · 排队 %1', d.queue) : '') +
      (cur ? tf(' · 正在处理：%1', esc((cur.title || ('aid ' + cur.aid)).slice(0, 24))) : '') +
      (d.message ? '　<span class="sub">' + esc(d.message) + '</span>' : '');
  }
  const grid = $('#pjGrid');
  if (!grid) return;
  (d.items || []).forEach(it => {
    const card = grid.querySelector('[data-aid="' + CSS.escape(String(it.aid)) + '"]');
    if (!card) return;
    const cls = card.className.replace(/(^|\s)s-\S+/g, ' ').trim();
    if (cls !== card.className) card.className = cls + ' s-' + it.state;
    const badge = card.querySelector('.cj-badge');
    if (badge) badge.textContent = probeStateText()[it.state] || it.state;
    const n = card.querySelector('.cj-note');
    if (n) n.textContent = probeItemDetail(it);
  });
}

/** 任务看板主体（同名替换 probe.js 旧实现，调用点不变）。 */
function probeRenderJob() {
  const box = $('#probeJob');
  if (!box) return;
  const j = probe.job;
  if (!j || !(j.running || j.finished)) {
    box.classList.add('hidden');
    box.innerHTML = '';
    _probeJobSig = '';
    return;
  }
  box.classList.remove('hidden');
  const sig = probeJobSig(j);
  if (sig !== _probeJobSig) {              // 卡片集合变了才重建（保 <img> 不闪）
    _probeJobSig = sig;
    box.innerHTML = probeJobHtml(j);
  }
  probeUpdateJobTick(j);
}

document.addEventListener('click', async (ev) => {
  const btn = ev.target.closest('#probeCancel');
  if (!btn) return;
  try {
    const r = await api('/api/crawl/pick/cancel', { method: 'POST' });
    showToast(r.message || t('已请求取消'));
  } catch (e) { showToast(tf('%1失败：%2', t('取消'), e.message)); }
});
