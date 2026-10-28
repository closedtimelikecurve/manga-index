/* 本地同人志文库 前端 · inbox.js
   收件箱（提案式入库）
   3.6.84 从 static/app.js 拆出：按顶层区块切分，仍是 classic script，
   与其余分片共享同一个全局词法环境（顺序加载，勿调整 index.html 里的 <script> 次序）。 */
'use strict';

/* ---------- 收件箱（3.1 提案式入库；3.2.1 曾误删渲染函数致页面空白，3.4.2 恢复并补阅读入口） ---------- */
function inboxConfLabel(c) {
  return { high: t('高置信'), mid: t('中置信'), low: t('低置信'), '-': t('不支持的类型') }[c] || c || '';
}

async function loadInbox() {
  const box = $('#inboxList');
  if (!box) return;
  box.innerHTML = '<div class="sub" style="padding:8px">' + esc(t('加载中…（首次会为每个收件文件计算内容哈希，大包稍慢）')) + '</div>';
  try {
    const d = await api('/api/inbox/list');
    renderInboxItems(d);
  } catch (e) {
    box.innerHTML = '<div class="sub" style="padding:8px">' + esc(tf('%1失败：%2', t('加载'), e.message)) + '</div>';
  }
}

/* 下载中断留下的半成品（.part / .part.src）：不是作品、不进收件列表，
   也不会被判定为「已爬取」，但堆着占地方 —— 这里给一个显式清理入口。 */
function renderInboxParts(parts) {
  const box = $('#inboxParts');
  if (!box) return;
  if (!parts.length) { box.classList.add('hidden'); box.innerHTML = ''; return; }
  const total = parts.reduce((n, p) => n + p.size, 0);
  box.classList.remove('hidden');
  box.innerHTML =
    '<div class="panel" style="width:100%;max-width:980px;margin:0 auto 10px;border-color:#ffc86b66">' +
      '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">' +
        '<b>🧹 ' + esc(tf('%1 个下载中断的半成品', parts.length)) + '</b>' +
        '<span class="sub">' + fmtBytes(total) + ' · ' + esc(tf('最新 %1 小时前', parts[0].age_h.toFixed(1))) +
        ' · ' + esc(t('它们不参与入库判定，清理后爬虫会重新下载')) + '</span>' +
        '<button id="btnInboxPurge" style="color:#ff6b8b">' + esc(t('清理（直接删除）')) + '</button>' +
      '</div>' +
      '<div class="sub" style="margin-top:4px">' +
        parts.slice(0, 5).map(p => esc(p.name) + esc(tf('（%1 / %2h）', fmtBytes(p.size), p.age_h.toFixed(1)))).join('　') +
        (parts.length > 5 ? ' …' : '') +
      '</div>' +
    '</div>';
  $('#btnInboxPurge').addEventListener('click', async () => {
    try {
      const r = await api('/api/inbox/purge-parts', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}) });
      showToast(r.message || t('已清理'));
      loadInbox();
    } catch (e) { showToast(tf('%1失败：%2', t('清理'), e.message)); }
  });
}

/* ---------- 收件箱条目：E 站式长条（左封面 / 右上信息 / 右下操作） ----------
   未分类已于 3.6.3 取消：无法归属的作品都收进 _app/_inbox，与爬虫下载品共用同一套
   「提案式入库」流程，因此这里只有一类条目，不再分「待入库」和「未归类」两个区。 */
function inboxRowHtml(it) {
  const p = it.proposal || {};
  const conf = inboxConfLabel(p.confidence);
  const badges = [];
  if (p.dup) badges.push('<span style="color:#ff6b8b">' + esc(tf('⚠ 疑似重复：与「%1」同内容', p.dup.name)) + '</span>');
  if (it.state === 'confirmed') badges.push('<span class="sub">' + esc(t('已入库')) + '</span>');
  if (!it.exists) badges.push('<span style="color:#ffc86b">' + esc(t('文件已消失')) + '</span>');
  if (p.kind === 'unsupported') badges.push('<span style="color:#ffc86b">' + esc(t('不支持的文件类型')) + '</span>');
  // 封面：收件项以伪社团「收件箱/<id>」读取首图（服务端 _inbox_pseudo_work 直接从 zip/文件夹取）
  const canCover = it.exists && p.kind === 'archive';
  const thumb = '<div class="inbox-thumb" id="inboxThumb' + it.id + '">' +
    (canCover
      ? '<img loading="lazy" src="' + coverUrl('收件箱', String(it.id)) + '" alt="" ' +
        'onerror="this.closest(\'.inbox-thumb\').innerHTML=\'<div class=ph>📄</div>\'">'
      : '<div class="ph">📄</div>') +
    '</div>';
  const dest = p.circle ? esc(tf('归档到「%1」', p.circle))
    : (p.bare ? esc(tf('按待定词条「%1」新建档案', p.bare)) : esc(t('未识别出社团，需人工指定')));
  const prop = (p.kind === 'archive' && (p.circle || p.bare))
    ? '<div class="inbox-prop">' + esc(t('提案：')) + dest +
      (p.new_name && p.new_name !== it.name ? '　·　' + esc(t('规范化名：')) + esc(p.new_name) : '') + '</div>'
    : (p.kind === 'archive'
        ? '<div class="inbox-prop">' + dest + ' —— ' + esc(t('可用「增补信息」补全词条，或在下方直接填目标社团')) + '</div>'
        : '');
  const actionable = it.exists && it.state !== 'confirmed' && p.kind === 'archive';
  const isDup = !!p.dup && it.state === 'pending';
  const acts = actionable
    ? '<div class="inbox-actions">' +
        '<button data-act="inbox-read" data-id="' + it.id + '" title="' + esc(t('阅读器内翻页浏览，核验内容后再入库')) + '">📖 ' + esc(t('阅读')) + '</button>' +
        '<button data-act="inbox-info" data-id="' + it.id + '" title="' + esc(t('补全词条/改名，让它可被自动识别')) + '">✏ ' + esc(t('增补信息')) + '</button>' +
        '<input id="inboxC' + it.id + '" placeholder="' + esc(t('目标社团（可改）')) + '" value="' + esc(p.circle || '') + '">' +
        '<button id="inboxGo' + it.id + '" class="primary">' + esc(isDup ? t('仍要入库') : t('✓ 确认入库')) + '</button>' +
        '<button id="inboxDel' + it.id + '" style="color:#ff6b8b">🗑 ' + esc(t('删除')) + '</button>' +
      '</div>'
    : '';
  return '<div class="inbox-row">' + thumb +
    '<div class="inbox-main">' +
      '<div class="inbox-name">' + esc(it.name) + '</div>' +
      '<div class="inbox-meta"><span class="sub">' + fmtBytes(it.size) + ' · ' + conf + '</span>' +
        badges.map(b => '<span>' + b + '</span>').join('') + '</div>' +
      prop + acts +
    '</div>' +
  '</div>';
}

function renderInboxItems(d) {
  const box = $('#inboxList');
  if (!box) return;
  const head = $('#inboxMeta');
  if (head) head.textContent = tf('待确认 %1 项 / 共 %2 项', d.pending, d.total);
  const btnAll = $('#btnInboxAll');
  if (btnAll) btnAll.disabled = !d.pending;
  renderInboxParts(d.parts || []);
  if (!d.items.length) {
    box.innerHTML = '<div class="panel" style="width:100%;max-width:980px;margin:0 auto"><span class="sub">' + esc(t('收件箱是空的——爬虫落盘、手动放入 _app/_inbox/、文库里无法识别词条的作品，以及被解散社团的作品都会汇到这里，补全词条后可一键入库。')) + '</span></div>';
    return;
  }
  box.innerHTML = d.items.map(inboxRowHtml).join('');
  d.items.forEach(it => {
    const go = $('#inboxGo' + it.id);
    if (go) go.addEventListener('click', async () => {
      const circle = ($('#inboxC' + it.id) || {}).value || '';
      const force = !!((it.proposal || {}).dup);
      try {
        const r = await api('/api/inbox/confirm', { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: it.id, circle: circle, force: force }) });
        showToast(r.message || (r.ok ? t('已入库') : t('已跳过')));
        loadInbox();
      } catch (e) { showToast(tf('%1失败：%2', t('入库'), e.message)); }
    });
    const del = $('#inboxDel' + it.id);
    if (del) del.addEventListener('click', async () => {
      if (!confirm(tf('删除收件文件「%1」？（直接删除，不可还原）', it.name))) return;
      try { const r = await api('/api/inbox/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: it.id }) }); showToast(r.message || t('已删除')); loadInbox(); }
      catch (e) { showToast(tf('%1：%2', t('失败'), e.message)); }
    });
  });
}

function renderInbox() {
  hideEmpty(); hideGridEmpty();
  $('#viewHead').innerHTML =
    '<button class="back" id="btnBack">← ' + esc(t('返回')) + '</button>' +
    '<h2>📮 ' + esc(t('收件箱')) + '</h2>' +
    '<span class="sub" id="inboxMeta">' + esc(t('加载中…')) + '</span>';
  const grid = $('#grid');
  grid.className = 'grid grid-list';
  grid.innerHTML =
    '<div class="info-actions" style="width:100%;max-width:980px;margin:0 auto 10px">' +
      '<button id="btnInboxAll" class="primary">⚡ ' + esc(t('一键入库（跳过疑似重复）')) + '</button>' +
      '<button id="btnInboxReload">⟳ ' + esc(t('刷新')) + '</button>' +
      '<span class="sub">' + esc(t('爬虫落盘、手动放入 _app/_inbox/、文库里识别不出词条的作品、被解散社团的作品都汇到这里；')) +
      esc(t('重复内容自动拦截，绝不产生 "(2)" 副本')) + '</span>' +
    '</div>' +
    '<div id="inboxParts" class="hidden" style="width:100%"></div>' +
    '<div id="inboxList" style="width:100%"></div>';
  $('#btnInboxReload').addEventListener('click', loadInbox);
  $('#btnInboxAll').addEventListener('click', async () => {
    try {
      const r = await api('/api/inbox/confirm-all', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      showToast(r.message || t('完成'));
      refresh(true);
      loadInbox();
    } catch (e) { showToast(tf('%1：%2', t('失败'), e.message)); }
  });
  loadInbox();
}
