/* 本地同人志文库 前端 · i18n.js
   3.6.115：多语言框架。key = 简体中文原文（基准语言，无需字典）；
   语言包数据 3.6.116 起按语言拆成 i18n_lang_*.js（每片一句 I18N_PACKS['xx'] = {…}），
   本文件只负责**先建空壳**，缺译自动回退 key 本身。
   语言偏好 localStorage `djc_lang`；首次进入按 navigator.language 预填（非库内语言 → English）。
   静态 DOM 用 data-i18n（textContent）/ data-i18n-ph（placeholder）标注，i18nApplyDom() 扫描替换；
   动态字符串直接 t("…")。仍是 classic script（顺序加载，勿调整 index.html 次序）。
   3.6.116：语言从抽屉内嵌区块升为独立二级界面 `#/lang`（renderLangView）。 */
'use strict';

/* 语言包容器：必须在这里先声明（i18n_lang_*.js 随后按序写入自己的语言）。
   3.6.116 前是 `const I18N_PACKS = { …7 种语言… }`，一个文件顶到 .js 代码行预算。 */
const I18N_PACKS = {};

/* 支持的语言（label 用各自语言显示） */
const I18N_LANGS = [   // i18n:data 语言名按各自语言显示（设计如此，不进字典）
  ['zh-CN', '简体中文'],   // i18n:data
  ['zh-Hant', '繁體中文'],   // i18n:data
  ['en', 'English'],
  ['ja', '日本語'],   // i18n:data
  ['ko', '한국어'],
  ['ru', 'Русский'],
  ['th', 'ไทย'],
  ['vi', 'Tiếng Việt'],
];

function i18nDetect() {
  const n = String(navigator.language || 'zh-CN').toLowerCase();
  if (n.startsWith('zh')) {
    return (n.includes('tw') || n.includes('hk') || n.includes('mo') || n.includes('hant'))
      ? 'zh-Hant' : 'zh-CN';
  }
  for (const pre of ['ja', 'ko', 'ru', 'th', 'vi', 'en']) {
    if (n.startsWith(pre)) return pre;
  }
  return 'en';                       // 非库内语言 → 英语
}

function i18nLang() {
  const v = localStorage.getItem('djc_lang');
  if (v === 'zh-CN' || (v && typeof I18N_PACKS === 'object' && I18N_PACKS[v])) return v;
  return i18nDetect();
}

function t(key) {
  if (!key) return key || '';               // 3.6.117：空 key 不进包查询
  const lang = i18nLang();
  if (lang === 'zh-CN') return key;
  const pack = (typeof I18N_PACKS === 'object') ? I18N_PACKS[lang] : null;
  return (pack && pack[key]) || key;  // 缺译回退简中原文
}

/** 扫描 data-i18n（textContent）/ data-i18n-ph（placeholder）/ data-i18n-title（title）并替换。
 *  3.6.117 事故修复：布尔简写 `data-i18n`（无值）会让 getAttribute 返回空串，
 *  此前直接 textContent = t('') = '' ——首帧就把全站静态文字清空（用户报障
 *  "抽屉功能键都不显示字"的真凶）。现在空属性时用元素自身文字当 key，双保险。
 *  3.6.126：补 title —— 抽屉/顶栏按钮的悬浮提示此前只能写死中文，换语言也不变。 */
/** 模板翻译：把 %1..%9 换成参数（与 APP 的 `AppI18n.sf` 同语义）。
 *
 *  3.6.132：中文常把"操作 + 失败 + 原因"拼在一句里，逐段 t() 会把语序拧坏
 *  （日语要把动词放句末、俄语的冒号前后顺序也不同）。改成整句模板只翻一次，
 *  语言自己决定占位符的位置。没有对应译文时 t() 回退成 key 本身，仍可读。 */
function tf(key, ...args) {
  return t(key).replace(/%([1-9])/g, (m, i) => {
    const v = args[Number(i) - 1];
    return v === undefined || v === null ? '' : String(v);
  });
}

function i18nApplyDom(root) {
  const scope = root || document;
  scope.querySelectorAll('[data-i18n]').forEach(el => {
    const k = el.getAttribute('data-i18n') || el.textContent.trim();
    if (k) el.textContent = t(k);
  });
  scope.querySelectorAll('[data-i18n-ph]').forEach(el => {
    const k = el.getAttribute('data-i18n-ph') || el.placeholder;
    if (k) el.placeholder = t(k);
  });
  scope.querySelectorAll('[data-i18n-title]').forEach(el => {
    const k = el.getAttribute('data-i18n-title') || el.title;
    if (k) el.title = t(k);
  });
}

/** 切换语言：持久化 + 静态 DOM 替换 + 重绘当前视图（动态文案）。
 *  3.6.116：语言页自身也是视图，route() 会把 #/lang 重画成新语言（含勾选位置）。 */
function setLang(code) {
  localStorage.setItem('djc_lang', code);
  document.documentElement.lang = code;
  i18nApplyDom();
  try {
    if (typeof route === 'function') route();          // 当前视图的动态文案重绘
  } catch (e) { /* 视图未就绪时忽略 */ }
}

/* ---------- 3.6.116：语言二级界面（#/lang）----------
   用户要求：语言、主题各自独立成页，不再挤在抽屉里。每行 = 本语言名 + 语言代码 + 选中勾；
   点整行即切换（setLang 持久化并即时重绘整站文案）。 */
function langRenderPage() {
  const box = $('#langPage');
  if (!box) return;
  const cur = i18nLang();
  box.innerHTML =
    '<p class="sub">' + esc(t('界面语言说明')) + '</p>' +
    I18N_LANGS.map(([code, label]) =>
      '<button type="button" class="lang-row' + (code === cur ? ' on' : '') +
      '" data-lang="' + code + '"><span class="lang-name">' + esc(label) + '</span>' +
      '<span class="lang-code">' + esc(code) + '</span>' +
      (code === cur ? '<span class="lang-ck">✓</span>' : '') + '</button>').join('');
  box.querySelectorAll('.lang-row').forEach(b => b.addEventListener('click', () => {
    setLang(b.getAttribute('data-lang'));
  }));
}

function renderLangView() {
  hideEmpty(); hideGridEmpty();
  $('#viewHead').innerHTML =
    '<button class="back" id="btnBack">← ' + esc(t('返回')) + '</button>' +
    '<h2>🌐 ' + esc(t('语言')) + '</h2>' +
    '<span class="sub">' + esc(t('切换后立即生效')) + '</span>';
  const grid = $('#grid');
  grid.className = 'grid grid-list';
  grid.innerHTML = '<div class="panel" id="langPage"></div>';
  langRenderPage();
}

/* 启动：按偏好/系统语言应用 */
document.documentElement.lang = i18nLang();
i18nApplyDom();
