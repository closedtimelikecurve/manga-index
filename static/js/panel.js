/* 本地同人志文库 前端 · panel.js
   空状态、打开本地文件、全局事件绑定、黑名单与备份管理
   3.6.84 从 static/app.js 拆出：按顶层区块切分，仍是 classic script，
   与其余分片共享同一个全局词法环境（顺序加载，勿调整 index.html 里的 <script> 次序）。 */
'use strict';

/* ---------- 空状态 ---------- */
function showGridEmpty(title, desc) {
  $('#emptyTitle').innerHTML = title;
  $('#emptyDesc').textContent = desc;
  $('#gridEmpty').classList.remove('hidden');
}
function hideGridEmpty() { $('#gridEmpty').classList.add('hidden'); }

function showEmpty() {
  const panel = $('#setupPanel');
  if (state.config && !state.config.rootExists) {
    panel.innerHTML =
      '<h3>' + esc(t('📁 未找到文库根目录')) + '</h3>' +
      '<p>' + esc(t('请填写正确的根目录路径（例如 <code>D:\\同人志</code>），或留空使用程序上级目录')) + '</p>' +
      '<input id="rootInput2" placeholder="例如：D:\\同人志">' +      // i18n:data 路径示例
      '<button class="primary" id="btnSetRoot2" style="width:100%">' + esc(t('保存并扫描')) + '</button>';
  } else if (state.lib && state.lib.groups && !state.lib.groups.length) {
    panel.innerHTML =
      '<h3><!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-folder" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z" /> </svg> ' + esc(t('目录为空')) + '</h3>' +
      '<p>' + esc(t('根目录下未发现社团/作品。建议先运行迁移脚本整理：<br><code>python migrate.py --dry-run</code><br>')) +
      esc(t('目录结构：<code>根目录/(社团名)/(作品).zip</code>')) + '</p>';
  } else {
    panel.innerHTML = '<h3>' + esc(t('⏳ 正在扫描…')) + '</h3><p>' + esc(t('请稍候。')) + '</p>';
  }
  const btn = $('#btnSetRoot2');
  if (btn) btn.addEventListener('click', async () => {
    const root = $('#rootInput2').value.trim();
    if (!root) return;
    try {
      state.config = await api('/api/config', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ root: root })
      });
      const sr = $('#settingsRoot');
      if (sr) sr.value = state.config.root;
      showToast(t('已设置根目录，正在扫描…'));
      await refresh(true);
    } catch (e) { showToast(tf('%1失败：%2', t('设置'), e.message)); }
  });
  $('#setupPanelWrap').classList.remove('hidden');
}
function hideEmpty() { $('#setupPanelWrap').classList.add('hidden'); }

/* ---------- 打开本地文件 ---------- */
function openTarget(group, work, target) {
  api('/api/open', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ group: group, work: work, target: target })
  }).then(d => showToast(d.message || (d.ok ? t('已打开') : t('打开失败'))))
    .catch(e => showToast(tf('%1失败：%2', t('打开'), e.message)));
}

/* ---------- 事件绑定 ---------- */
window.addEventListener('hashchange', route);

let searchTimer = null;
$('#search').addEventListener('input', e => {
  clearTimeout(searchTimer);
  const v = e.target.value;
  searchTimer = setTimeout(() => {
    state.filter = v;
    if (v.trim()) {
      // 升级为独立 hash 路由：搜索结果可由浏览器返回键原路返回
      if (!location.hash.startsWith('#/search')) state._searchReturn = location.hash || '#/';
      location.hash = '#/search?q=' + enc(v.trim());
    } else {
      // 清空搜索：恢复到进入搜索前的视图（避免直接落到首页）
      const back = (state._searchReturn && !state._searchReturn.startsWith('#/search')) ? state._searchReturn : '#/';
      location.hash = back;
    }
  }, 200);
});

$('#btnCrawl').addEventListener('click', () => { location.hash = '#/crawl'; });
// 3.5.1 右上角一级入口：续读 / 喜爱画师（与 APP 底部胶囊的一级界面对齐）
$('#btnResume').addEventListener('click', () => { location.hash = '#/resume'; });
$('#btnLoved').addEventListener('click', () => { location.hash = '#/loved'; });
// 3.2.5 首页/刷新按钮已删：浏览器自带刷新，文库数据随导航自动同步

/* 顶栏维护菜单：词条黑名单 + 备份与恢复（挂 wrench 按钮下方）；清理空文件夹/全库重新归类已移除 */
const ICON_WRENCH = '<!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-wrench" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z" /> </svg>';
const ICON_DB = '<!-- @license lucide-static v0.462.0 - ISC --> <svg class="lucide lucide-database" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" > <ellipse cx="12" cy="5" rx="9" ry="3" /> <path d="M3 5V19A9 3 0 0 0 21 19V5" /> <path d="M3 12A9 3 0 0 0 21 12" /> </svg>';
$('#btnMaint').addEventListener('click', e => {
  e.stopPropagation();
  // 3.6.128（用户需求③）：stopPropagation 会挡住抽屉的"点条目自动收起"，
  // 抽屉（z-index 1800）就一直压在弹窗上面，看起来像"两个弹窗打架"。这里显式收起。
  drawerClose();
  ctxMenu.hide();
  closeAllModals();
  const r = e.currentTarget.getBoundingClientRect();
  ctxMenu.show(r.left, r.bottom + 6, [
    { a: 'bl', label: t('词条黑名单'), icon: ICON_WRENCH, run: () => openBlacklistEditor() },
    { a: 'bk', label: t('备份与恢复'), icon: ICON_DB, run: () => openBackupManager() },
  ], t('文库维护'));
});

/** 关掉所有浮层（维护的两个弹窗互斥；打开一个之前先清掉另一个，避免叠加与重复请求）。 */
function closeAllModals() {
  ctxMenu.hide();
  ['#blModal', '#bkModal', '#pairModal'].forEach(sel => {
    const el = $(sel);
    if (el) el.classList.add('hidden');
  });
}

/* ---- 词条黑名单编辑器（维护菜单入口） ---- */
let blBusy = false;
async function openBlacklistEditor() {
  if (blBusy) return;                 // 连点两次只发一个请求（原先会两个弹窗同时盖上来）
  blBusy = true;
  closeAllModals();
  let d;
  try { d = await api('/api/blacklist'); }
  catch (e) { showToast(tf('%1失败：%2', t('读取'), e.message)); return; }
  finally { blBusy = false; }
  $('#blBuiltin').textContent = (d.builtin || []).join('、');
  $('#blCustom').value = (d.custom || []).join('\n');
  $('#blExempt').value = (d.exempt || []).join('\n');
  $('#blModal').classList.remove('hidden');
}
$('#blCancel').addEventListener('click', () => $('#blModal').classList.add('hidden'));
$('#blModal').addEventListener('click', e => { if (e.target === $('#blModal')) $('#blModal').classList.add('hidden'); });
$('#blSave').addEventListener('click', async () => {
  const custom = $('#blCustom').value.split('\n').map(x => x.trim()).filter(Boolean);
  const exempt = $('#blExempt').value.split('\n').map(x => x.trim()).filter(Boolean);
  try {
    const r = await api('/api/blacklist', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ custom: custom, exempt: exempt }) });
    showToast(r.message || t('已保存'));
    $('#blModal').classList.add('hidden');
    refresh(true);
  } catch (e) { showToast(tf('%1失败：%2', t('保存'), e.message)); }
});

/* ---- 备份与恢复（元数据时间机器，维护菜单入口） ---- */
function fmtStamp(ts) {
  const d = new Date((ts || 0) * 1000);
  return isNaN(d.getTime()) ? t('（未知时间）')
    : d.toLocaleDateString('zh-CN') + ' ' + d.toTimeString().slice(0, 8);
}
function fmtBytes(n) {
  if (n == null || n < 0) return '';
  if (n > 1048576) return (n / 1048576).toFixed(1) + ' MB';
  if (n > 1024) return (n / 1024).toFixed(0) + ' KB';
  return n + ' B';
}
let bkBusy = false;
async function openBackupManager() {
  if (bkBusy) return;                 // 与黑名单同一套互斥：连点不会叠出两个弹窗
  bkBusy = true;
  closeAllModals();
  $('#bkList').innerHTML = '<div style="color:var(--muted)">' + esc(t('加载中…')) + '</div>';
  $('#bkModal').classList.remove('hidden');
  try {
    const d = await api('/api/backup/list');
    renderBackupList(d.backups || []);
  } catch (e) { $('#bkList').innerHTML = ''; showToast(tf('%1失败：%2', t('读取'), e.message)); }
  finally { bkBusy = false; }
}
function renderBackupList(list) {
  const box = $('#bkList');
  if (!list.length) { box.innerHTML = '<div style="color:var(--muted)">' + esc(t('还没有快照——导入 / 改名 / 解散 / 黑名单保存 / 收藏变更时会自动创建。')) + '</div>'; return; }
  box.innerHTML = list.map(b =>
    '<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--line)">' +
    '<div style="flex:1;min-width:0"><div>' + fmtStamp(b.at) + ' <span style="color:var(--muted)">(' + fmtBytes(b.size) + ')</span></div>' +
    (b.note ? '<div style="color:var(--muted);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + String(b.note).replace(/</g, '&lt;') + '</div>' : '') +
    '</div>' +
    '<button data-bkfile="' + String(b.file).replace(/"/g, '&quot;') + '">' + esc(t('恢复')) + '</button>' +
    '</div>').join('');
  box.querySelectorAll('[data-bkfile]').forEach(btn => btn.addEventListener('click', async () => {
    const f = btn.dataset.bkfile;
    if (!confirm(tf('恢复到快照 %1？\n当前状态会先自动快照（恢复操作本身可撤销），恢复后将强制重新扫描。', f))) return;
    try {
      const r = await api('/api/backup/restore', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file: f }) });
      showToast(r.message || t('已恢复'));
      $('#bkModal').classList.add('hidden');
      refresh(true);
    } catch (e) { showToast(tf('%1失败：%2', t('恢复'), e.message)); }
  }));
}
$('#bkClose').addEventListener('click', () => $('#bkModal').classList.add('hidden'));
$('#bkModal').addEventListener('click', e => { if (e.target === $('#bkModal')) $('#bkModal').classList.add('hidden'); });
$('#bkExport').addEventListener('click', () => {
  const tk = getToken();
  window.open('/api/backup/export' + (tk ? '?token=' + encodeURIComponent(tk) : ''));
});

/* 3.7.78 扫码配对：顶栏入口（与收件箱并列）；白底衬托。
   3.6.129：地址由服务端探测「远程进程 + 网卡」决定。没有手机可达的地址时
   **不请求、不显示二维码**，只给提醒——旧版把 request.host 编进码里，
   从 127.0.0.1 打开时手机扫到的是它自己，永远连不上。
   3.6.144（用户需求）：码里改为**一次性票据**（默认 120 秒、绑定即作废），
   过期后**不再自动续期**，换成「已过期 + 中央 ↻」，必须手动点才签新票据。 */
let pairTimer = null;
let pairHasMainToken = true;      // 主令牌现在是可选的（3.6.147），按钮语义随它变

/** 票据到期：停掉倒计时，把码换成「已过期 + 中央 ↻」。
 *  以前是每 60 秒自动重取（码永远有效）；现在票据一次性且有时效，
 *  自动续期会让「过期」永远不成立，所以到期就停，由用户决定何时生成新的。 */
function pairShowExpired() {
  if (pairTimer) { clearInterval(pairTimer); pairTimer = null; }
  $('#pairQrBox').innerHTML =
    '<div class="pair-qr-expired">' +
      '<span class="pair-expired-text">' + esc(t('二维码已过期')) + '</span>' +
      '<button type="button" id="pairRefresh" class="pair-refresh" title="' +
        esc(t('生成新的二维码')) + '">↻</button>' +
      '<span class="pair-expired-hint">' + esc(t('点 ↻ 生成新的二维码')) + '</span>' +
    '</div>';
  $('#pairHint').textContent = '';
  on('#pairRefresh', 'click', refreshPairQr);   // 元素是刚生成的，on() 是直接绑定，必须重绑
}

/** 不可用原因 → 文案（服务端只给 reason 码，翻译留在前端，7 语才对得上）。 */
function pairReasonText(info) {
  if (info.reason === 'not_listening') {
    return t('已检测到远程进程，但没有在该地址上监听到面板：请先在启动器里启动「远程服务」（0.0.0.0:8766），或设置 pair_url 后重启面板');
  }
  if (info.reason === 'tunnel_no_url') {
    return t('已检测到远程进程，但拿不到它的公网地址——请在 config.json 里设置 pair_url 后重启面板');
  }
  return t('未检测到可用的远程连接：手机端访问不到本机回环地址，已停用二维码。请先启动 Tailscale 一类的远程访问进程，或在本机 config.json 里设置 pair_url 后重启面板');
}

/** 链路与服务器指纹（3.6.146）：明文必须显眼，否则用户不知道自己正在裸奔。 */
function pairLinkHtml(info) {
  const link = info.link || '';
  let text, cls;
  if (link.startsWith('tunnel:')) {
    text = tf('经 %1 隧道加密', link.slice(7)); cls = 'ok';
  } else if (link === 'https') {
    text = t('HTTPS 加密'); cls = 'ok';
  } else {
    text = t('HTTP 明文（同网段可能被截获，建议改用 Tailscale）'); cls = 'warn';
  }
  const fp = info.fingerprint
    ? ' · ' + esc(t('服务器指纹')) + '：<code class="pair-fp">' + esc(info.fingerprint) + '</code>'
    : '';
  return '<span class="pair-link-' + cls + '">' + (cls === 'warn' ? '⚠ ' : '🔒 ') +
    esc(text) + '</span>' + fp;
}

/** 不可达时的提示行：候选地址 + 检测到的进程，方便判断该起哪个穿透工具。 */
function pairOfflineHint(info) {
  const parts = [];
  if ((info.tunnels || []).length) {
    parts.push(t('检测到的远程进程') + '：' + info.tunnels.join(' / '));
  }
  parts.push(t('本机候选地址') + '：' + ((info.candidates || []).join('、') || '—'));
  return parts.join(' · ');
}

async function refreshPairQr() {
  if (pairTimer) { clearInterval(pairTimer); pairTimer = null; }
  let info;
  try { info = await api('/api/pair/info'); }
  catch (e) { showToast(t('失败') + '：' + e.message); return; }
  const link = $('#pairLink');
  if (link) link.innerHTML = pairLinkHtml(info);
  pairHasMainToken = info.hasMainToken !== false;
  const rotBtn = $('#pairRotate');
  if (rotBtn) rotBtn.textContent = pairHasMainToken ? t('轮换访问令牌') : t('生成访问令牌');
  if (info.canPair === false) {
    $('#pairQrBox').innerHTML = '<div class="pair-warn">⚠ ' + esc(pairReasonText(info)) + '</div>';
    $('#pairHint').textContent = pairOfflineHint(info);
    return;                                   // 不自动刷新：进程起来后重开本窗口即可
  }
  try {
    const d = await api('/api/pair/qr');
    if (!d.ok) throw new Error(d.message || t('未生成二维码'));
    $('#pairQrBox').innerHTML = '<div class="pair-qr-card">' + d.svg + '</div>';
    const base = (d.url || info.url) + ' · ' + t('手机端 App 设置页「扫码连接」扫这张图即可');
    let left = d.expiresIn || info.ticketTtl || 120;
    const tick = () => {
      if (left <= 0) { pairShowExpired(); return; }
      $('#pairHint').textContent = base + ' · ' + tf('二维码 %1 秒后失效', left);
      left--;
    };
    tick();
    pairTimer = setInterval(tick, 1000);
  } catch (e) { showToast(t('失败') + '：' + e.message); }
}
async function openPairQr() {
  closeAllModals();                    // 3.6.128：与维护弹窗互斥，避免叠在一起
  $('#pairModal').classList.remove('hidden');
  refreshPairQr();
  pairLoadRemote();                    // 3.6.151：远程服务开关
  pairLoadDevices();                   // 3.6.145：已配对设备
}

/* ---------- 远程服务开关（3.6.151）----------
   用户要求在**网页端二维码页**里直接关掉电脑那边的远程服务（0.0.0.0:8766），
   不必跑回启动器。手机端故意不提供：8766 停止后没有任何通路能把手机连回去，
   点了也点不亮，只会被当成 bug（该实现已从 APP 移除）。

   两个必须讲清的事实，界面上直接写出来：
   1. 停止是「先回包、后动手」（后端延迟 1.5s 杀进程），否则响应发不出去；
   2. 如果这一页本身就是远程服务提供的（isSelf），停止 = 当场断开本页。 */
function pairRemoteHtml(st) {
  if (!st) {
    return '<span class="pair-remote-state off">● ' + esc(t('远程服务：状态未知')) + '</span>';
  }
  const on = !!st.running, self = !!st.isSelf;
  const btn = on ? t('停止远程服务') : t('启动远程服务');
  const note = on
    ? (self ? t('本页正由远程服务提供：停止会立即断开本页，需回电脑启动器重新开启')
            : t('停止后手机会立刻断连，需要回电脑启动器重新开启'))
    : t('启动后手机才能通过远程地址访问（需先在电脑上接好远程接入）');
  return '<span class="pair-remote-state ' + (on ? 'on' : 'off') + '">● ' +
      esc(on ? t('远程服务：运行中') : t('远程服务：已停止')) + '</span>' +
    '<button type="button" id="pairRemoteBtn" class="pair-remote-btn' + (on ? ' stop' : '') + '">' +
      esc(btn) + '</button>' +
    '<div class="pair-remote-note">' + esc(note) + '</div>';
}

async function pairLoadRemote() {
  const box = $('#pairRemote');
  if (!box) return;
  let st = null;
  try { st = await api('/api/remote/state'); } catch (e) { st = null; }
  box.innerHTML = pairRemoteHtml(st);
  const btn = $('#pairRemoteBtn');
  if (btn) btn.addEventListener('click', () => pairToggleRemote(st));
}

/** 启/停：服务端只回 code，文案在前端翻（7 语才对得上）。 */
async function pairToggleRemote(st) {
  const on = !!(st && st.running);
  if (on && !confirm(t('确定停止远程服务？手机会立刻断连，需要回电脑启动器重新开启。'))) return;
  const btn = $('#pairRemoteBtn');
  if (btn) { btn.disabled = true; btn.textContent = t('处理中…'); }
  try {
    const d = await api(on ? '/api/remote/stop' : '/api/remote/start', { method: 'POST' });
    const msg = d.code === 'stopping'
      ? tf('远程服务将在 %1 秒后停止', d.delay || 2)
      : { already_stopped: t('远程服务本来就没在运行'),
          starting: t('远程服务正在启动，几秒后可用'),
          already_running: t('远程服务已在运行'),
          self: t('当前就是远程服务进程，无法自启动；请在电脑的面板页操作'),
          spawn_failed: t('启动失败（无法创建子进程）') }[d.code];
    showToast(msg || d.message || t('完成'));
    // 停止要等后端那 1.5 秒过去，否则刷到的还是「仍在运行」
    setTimeout(async () => {
      await pairLoadRemote();
      refreshPairQr();               // 服务状态变了，二维码的可用性跟着变
    }, on ? 2600 : 1200);
  } catch (e) {
    showToast(t('失败') + '：' + e.message);
    pairLoadRemote();
  }
}

/* ---------- 已配对设备（3.6.145） ----------
   为什么单独做这一块：设备令牌的意义就是「哪台泄露只踢哪台」。没有列表与吊销入口，
   这个收益就落不到手上——只能改主令牌把所有设备一起踢掉。 */
function pairDeviceRow(d) {
  const last = d.last
    ? new Date(d.last * 1000).toLocaleString()
    : t('从未使用');
  return '<div class="pair-dev-row">' +
    '<span class="pair-dev-name">📱 ' + esc(d.name) + '</span>' +
    '<span class="pair-dev-meta">' + esc(last) + '</span>' +
    '<button type="button" class="pair-dev-del" data-del="' + esc(d.deviceId) + '">' +
      esc(t('吊销')) + '</button></div>';
}

async function pairLoadDevices() {
  const box = $('#pairDevices');
  if (!box) return;
  let items = [];
  try { items = (await api('/api/pair/devices')).devices || []; }
  catch (e) { box.innerHTML = ''; return; }        // 取不到就不显示，别塞错误条
  box.innerHTML =
    '<div class="pair-dev-head">' + esc(t('已配对设备')) + '</div>' +
    (items.length
      ? items.map(pairDeviceRow).join('')
      : '<div class="pair-dev-empty">' + esc(t('还没有已配对的设备')) + '</div>');
  box.querySelectorAll('.pair-dev-del').forEach(btn => btn.addEventListener('click', async () => {
    const id = btn.getAttribute('data-del');
    if (!confirm(t('确定吊销这台设备？它会立即失去访问权限，需要重新扫码。'))) return;
    try {
      await api('/api/pair/devices/' + encodeURIComponent(id), { method: 'DELETE' });
      showToast(t('吊销完成'));
      pairLoadDevices();
    } catch (e) { showToast(t('失败') + '：' + e.message); }
  }));
}

/** 轮换主令牌：旧令牌立刻失效，但**已扫码的 APP 不受影响**（它们用设备令牌）。 */
async function pairRotateToken() {
  const ask = pairHasMainToken
    ? t('确定轮换访问令牌？其他设备上的网页需要重新输入新令牌；已扫码的 APP 不受影响。')
    : t('当前没有访问令牌：远程网页无法访问（本机与已配对手机不受影响）。生成后请保存新令牌。');
  if (!confirm(ask)) return;
  try {
    const d = await api('/api/config/rotate-token', { method: 'POST' });
    if (!d.ok || !d.token) throw new Error(d.message || t('失败'));
    localStorage.setItem('djc_token', d.token);    // 当前浏览器继续可用
    $('#pairDevices').innerHTML =
      '<div class="pair-rotate-result">' +
        '<div class="pair-rotate-title">' + esc(t('新访问令牌（只显示这一次，请保存）')) + '</div>' +
        '<code id="pairNewToken">' + esc(d.token) + '</code>' +
        '<button type="button" id="pairCopyToken">' + esc(t('复制')) + '</button>' +
      '</div>';
    on('#pairCopyToken', 'click', () => {
      const txt = $('#pairNewToken') ? $('#pairNewToken').textContent : '';
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(txt).then(
          () => showToast(t('已复制')),
          () => showToast(t('复制失败，请手动选中复制')));
      } else showToast(t('复制失败，请手动选中复制'));
    });
  } catch (e) { showToast(t('失败') + '：' + e.message); }
}
function closePairQr() {
  $('#pairModal').classList.add('hidden');
  if (pairTimer) { clearInterval(pairTimer); pairTimer = null; }
}
/* 3.6.125：`#btnPair` 已随 3.7.78 的设置弹窗一起删除，这里不再绑（旧的裸绑会抛
   TypeError，把下面四个绑定全带走——这正是「二维码与别名登记都打不开」的真凶）。 */
on('#btnPairTop', 'click', openPairQr);
on('#pairClose', 'click', closePairQr);
on('#pairModal', 'click', e => { if (e.target === $('#pairModal')) closePairQr(); });
on('#pairRotate', 'click', pairRotateToken);

/* 3.7.78：网页设置功能取消，入口改跳别名登记页（#/aliases，与 APP 同款系统） */
on('#btnSettings', 'click', () => { location.hash = '#/aliases'; });

