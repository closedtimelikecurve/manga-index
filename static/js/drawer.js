/* 本地同人志文库 前端 · drawer.js
   3.6.115：右侧抽屉（对齐 APP）——顶栏 ☰ 唤起，功能入口全部收进抽屉。
   3.6.116：语言与主题不再内嵌（挤在抽屉里手机上没法用），改各自独立二级界面
   `#/lang`（见 static/js/i18n.js）与 `#/theme`（见 static/js/theme.js），抽屉里只留入口。
   仍是 classic script（顺序加载，勿调整 index.html 次序）。 */
'use strict';

function drawerOpen() {
  $('#drawer').classList.add('open');
  $('#drawer').setAttribute('aria-hidden', 'false');
  $('#drawerMask').classList.remove('hidden');
  // 3.6.161：每次开抽屉按服务端最新状态对齐开关（手机端改过 → 网页这里也要跟上）
  if (typeof syncSafeCoversBtn === 'function') syncSafeCoversBtn();
}

function drawerClose() {
  $('#drawer').classList.remove('open');
  $('#drawer').setAttribute('aria-hidden', 'true');
  $('#drawerMask').classList.add('hidden');
}

function drawerToggle() {
  if ($('#drawer').classList.contains('open')) drawerClose();
  else drawerOpen();
}

$('#btnMenu').addEventListener('click', drawerToggle);
$('#drawerMask').addEventListener('click', drawerClose);
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') drawerClose();
});
/* 点功能条目后自动收起（跳转/弹窗前先收，避免盖住模态框）。
   3.6.161：开关类条目不收——用户点了开关还想看到状态变化，抽屉被收走等于没反馈。 */
$('#drawer').addEventListener('click', e => {
  if (e.target.closest('.drawer-items button:not(.drawer-switch)')) drawerClose();
});
/* 搜索下载器是新增的全局入口（原顶栏没有） */
$('#btnProbe').addEventListener('click', () => { location.hash = '#/probe'; });
/* 3.6.116：语言 / 主题各自独立成二级界面（原先内嵌在抽屉里） */
$('#btnLang').addEventListener('click', () => { location.hash = '#/lang'; });
$('#btnTheme').addEventListener('click', () => { location.hash = '#/theme'; });

/* ---------- 3.6.161 内测模式：所有封面统一换成占位图 ----------
   状态存在服务端 config.json 的 `safe_covers`，**不在浏览器本地**：双端抽屉要显示同一个
   状态，也只有服务端能同时管住网页与 APP 的封面出口（见 panel/safecover.py）。

   切换后必须让封面 URL 变（coverUrl 追加 `&sc=1`）并重渲染：浏览器对 `/cover?...`
   有 1 小时图片缓存，不换 URL 会继续显示旧封面，看起来像"开关没生效"。 */
function safeCoversOn() {
  return !!(state.config && state.config.safeCovers);
}

function syncSafeCoversBtn() {
  const btn = $('#btnSafeCovers');
  if (btn) btn.setAttribute('aria-checked', safeCoversOn() ? 'true' : 'false');
}

async function toggleSafeCovers() {
  const btn = $('#btnSafeCovers');
  const next = !safeCoversOn();
  if (btn) btn.disabled = true;
  try {
    state.config = await api('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // 3.6.162：各端独占——只切网页这一端，手机端保持它自己的设置
      body: JSON.stringify({ safe_covers: next, safe_covers_scope: 'web' }),
    });
    showToast(next ? t('内测模式已开启：封面已换成占位图（仅网页）')
                   : t('内测模式已关闭（仅网页）'));
    route();                    // 重渲染当前视图，封面带新 URL 重新取
  } catch (e) {
    showToast(t('切换失败') + '：' + (e && e.message ? e.message : e));
  } finally {
    if (btn) btn.disabled = false;
    syncSafeCoversBtn();
  }
}

$('#btnSafeCovers').addEventListener('click', toggleSafeCovers);
syncSafeCoversBtn();
