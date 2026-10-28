/* 本地同人志文库 前端 · probecards.js
   分区爬虫的「结果卡片」渲染（3.7.61 从 probe.js 拆出：该文件有效代码到 420 行）。
   包含：单卡 HTML（含疑似重复徽标）、整块重画、增量追加、底部操作条、勾选绑定。
   仍是 classic script，与其余分片共享同一个全局词法环境（顺序加载，勿调整 index.html 次序）。 */
'use strict';

/* ---------- 结果卡片 ---------- */
/** 单张卡片。dup 存在时挂一条与收件箱同款的「⚠ 疑似重复」提示。 */
function probeCardHtml(w) {
  const on = probe.sel.has(w.aid);
  const dup = w.dup
    ? '<div class="probe-dup" title="' + esc(w.dup.why || '') + '">' +
      esc(tf('⚠ 疑似重复：与「%1」同内容', w.dup.name || '')) + '</div>'
    : '';
  return '<label class="probe-card' + (on ? ' on' : '') + (w.dup ? ' is-dup' : '') +
    '" data-aid="' + w.aid + '">' +
    '<input type="checkbox" class="probe-cb" data-aid="' + w.aid + '"' + (on ? ' checked' : '') + '>' +
    (w.cover
      ? '<img class="probe-cover" loading="lazy" src="' + esc(w.cover) + '" alt=""' +
        ' onerror="this.classList.add(&#39;err&#39;)">'
      : '<div class="probe-cover ph">🎴</div>') +
    '<div class="probe-meta">' +
      '<div class="probe-title">' + esc(w.title || ('aid ' + w.aid)) + '</div>' +
      '<div class="probe-sub">' + (w.pages ? tf('%1 页 · ', w.pages) : '') + 'aid ' + w.aid + '</div>' +
      dup +
    '</div></label>';
}

function renderProbeResults() {
  const grid = $('#grid');
  grid.className = 'grid probe-grid';
  // 3.6.112：运行中不再隐藏搜索结果——封面卡片墙照常显示，进度看板在页面头部
  //（用户反馈"爬取时就把作品的封面丢掉了"）。
  grid.innerHTML = probeBarHtml() + probe.works.map(probeCardHtml).join('');
  probe.rendered = new Set(probe.works.map(w => w.aid));
  probeBindResults();
  probeRenderJob();
}

/**
 * 只追加新出现的卡片（3.7.61）。
 *
 * 为什么不能每次 `innerHTML =` 重画：重画会把每张 `<img>` 销毁重建，第二次请求一旦
 * 碰上代理的空返回/404，新图就被 onerror 隐藏——用户看到「封面出现两秒后消失」
 * （补全剩余结果正好在两秒后触发）。追加只碰新卡片，已显示的图片节点完全不动。
 * 返回 false 表示当前 DOM 不是本次结果的卡片列表（调用方改为整块重画）。
 */
function probeAppendCards() {
  const grid = $('#grid');
  if (!grid || grid.className.indexOf('probe-grid') < 0 || !probe.rendered) return false;
  const fresh = probe.works.filter(w => !probe.rendered.has(w.aid));
  if (!fresh.length) return true;
  grid.insertAdjacentHTML('beforeend', fresh.map(probeCardHtml).join(''));
  fresh.forEach(w => probe.rendered.add(w.aid));
  probeBindResults();
  probeRenderJob();
  probeSyncBar();
  return true;
}

/** 结果更新后的统一出口：能追加就追加，否则整块重画。 */
function probePaint() {
  if (!probeAppendCards()) renderProbeResults();
}

function probeBarHtml() {
  const n = probe.sel.size;
  return '<div class="probe-bar" id="probeBar">' +
    '<span class="probe-count">' +
      tf('已选 <b id="probeSelN">%1</b> 部 / 共 %2 部', n, probe.works.length) + '</span>' +
    (probe.hasMore || probe.loadingMore
      ? '<button type="button" class="back" id="probeMore">' +
        (probe.loadingMore ? esc(t('加载中…')) : '＋ ' + esc(t('加载更多'))) + '</button>' : '') +
    '<button type="button" class="back" id="probeAll">' + esc(t('全选本页')) + '</button>' +
    '<button type="button" id="probeStart" class="primary"' + (n ? '' : ' disabled') + '>⛏ ' + esc(t('联网获取')) + '</button>' +
    '</div>';
}

function probeBindResults() {
  const grid = $('#grid');
  grid.querySelectorAll('.probe-cb').forEach(cb => cb.addEventListener('change', () => {
    const aid = Number(cb.dataset.aid);
    if (cb.checked) probe.sel.add(aid); else probe.sel.delete(aid);
    cb.closest('.probe-card').classList.toggle('on', cb.checked);
    probeSyncBar();
  }));
  grid.querySelectorAll('.probe-card').forEach(card => card.addEventListener('click', ev => {
    if (ev.target.tagName === 'INPUT') return;         // 点在勾选框上交给 change
    const cb = card.querySelector('.probe-cb');
    cb.checked = !cb.checked;
    cb.dispatchEvent(new Event('change'));
  }));
  const more = $('#probeMore');
  if (more) more.addEventListener('click', () => { probeLoadMore(); });
  $('#probeAll').addEventListener('click', () => {
    // 3.7.61：库里已有的一律不选（与收件箱「一键入库跳过疑似重复」同一套规矩）
    const dups = probe.works.filter(w => w.dup).length;
    const pickable = probe.works.filter(w => !w.dup).map(w => w.aid);
    const allOn = pickable.length > 0 && pickable.every(a => probe.sel.has(a));
    probe.sel = new Set(allOn ? [] : pickable);
    if (!allOn && dups) showToast(tf('已跳过 %1 部库里已有的作品', dups));
    renderProbeResults();
  });
  $('#probeStart').addEventListener('click', probeStart);
}

function probeSyncBar() {
  const n = $('#probeSelN'), btn = $('#probeStart'), go = $('#probeGo');
  const running = !!(probe.job && probe.job.running);
  if (n) n.textContent = probe.sel.size;
  if (btn) btn.disabled = !probe.sel.size || running;
  if (go) go.disabled = running;
}
