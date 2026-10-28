/* 本地同人志文库 前端 · alias.js
   3.7.78：网页端别名登记页（#/aliases）——取代原设置弹窗（用户需求④），
   与 APP「别名登记」同款系统、同一批 API：
   * GET/POST /api/author-aliases（kind=author 笔名 | circle 社团 | original 同人名）
   * POST /api/author-aliases/delete
   * POST /api/originals/rename（original 正名改名，keep_alias=true）
   三类 chips 切换；列表按正名分组、✕ 删除单条。
   3.6.127（用户需求）：与 APP 对齐——
   * 每个正名下方一个「＋」胶囊，点开就地添加该正名的别名（正名预填、不用再手打）；
   * 顶部只留「＋ 新建正名」（原常驻的"正名/别名"双输入框撤掉）；
   * 同人（original）正名行加「✏ 改区名」，与 APP 的改区名一致（零文件操作）。
   仍是 classic script（顺序加载，勿调整次序）。 */
'use strict';

const ALIAS_KINDS = [
  ['author', '👤 '],      // 标签补 t()（chips 渲染时拼）
  ['circle', '🏢 '],
  ['original', '🎴 '],
];
// 3.6.143 函数化：切语言跟随（顶层 const 冻结坑）
function aliasKindLabels() {
  return { author: t('笔名别名'), circle: t('社团别名'), original: t('同人别名') };
}
const aliasPage = {
  kind: 'author',
  data: null,      // {canonical: [alias…]}
  add: null,       // 正在为哪个正名添加别名（'' = 新建正名）
  rename: null,    // 正在改哪个同人区名
  err: '',
};

function renderAliasView() {
  hideEmpty(); hideGridEmpty();
  aliasPage.add = null; aliasPage.rename = null;
  $('#viewHead').innerHTML =
    '<button class="back" id="btnBack">← ' + esc(t('返回')) + '</button>' +
    '<h2>🔗 ' + esc(t('别名登记')) + '</h2>' +
    '<span class="sub">' + esc(t('正名与别名归并：同一个人的多种写法并到一起，列表立即生效')) + '</span>';
  const grid = $('#grid');
  grid.className = 'grid grid-list';
  grid.innerHTML =
    '<div class="panel alias-page">' +
      '<div class="alias-kinds">' + ALIAS_KINDS.map(([k, ico]) =>
        '<button type="button" class="alias-kind' + (aliasPage.kind === k ? ' on' : '') +
        '" data-kind="' + k + '">' + ico + esc(aliasKindLabels()[k]) + '</button>').join('') +
      '</div>' +
      '<div class="alias-tools">' +
        '<button type="button" id="aliasNewCanon" class="alias-plus">＋ ' +
          esc(t('新建正名')) + '</button>' +
      '</div>' +
      '<div id="aliasList" class="alias-list">' +
        '<span class="sub">' + esc(t('加载中…')) + '</span></div>' +
    '</div>';
  grid.querySelectorAll('.alias-kind').forEach(b => b.addEventListener('click', () => {
    if (aliasPage.kind === b.getAttribute('data-kind')) return;
    aliasPage.kind = b.getAttribute('data-kind');
    aliasPage.add = null; aliasPage.rename = null;
    renderAliasView();
  }));
  $('#aliasNewCanon').addEventListener('click', () => aliasOpenAdd(''));
  aliasLoadList();
}

async function aliasLoadList() {
  const box = $('#aliasList');
  if (!box) return;
  try {
    const d = await api('/api/author-aliases?kind=' + aliasPage.kind);
    aliasPage.data = d.canonicals || {};
    aliasPage.err = '';
  } catch (e) {
    aliasPage.data = null;
    aliasPage.err = e.message;
  }
  aliasRenderList();
}

/** 渲染别名树（数据已在 aliasPage.data；增删改后统一走 aliasLoadList 重拉）。 */
function aliasRenderList() {
  const box = $('#aliasList');
  if (!box) return;
  if (aliasPage.err) {
    box.innerHTML = '<span class="sub">' + esc(t('加载失败') + '：' + aliasPage.err) + '</span>';
    return;
  }
  const data = aliasPage.data || {};
  const keys = Object.keys(data).sort();
  if (!keys.length && aliasPage.add === null) {
    box.innerHTML = '<span class="sub">' + esc(t('还没有登记任何别名')) + '</span>';
    return;
  }
  box.innerHTML = keys.map(c => aliasGroupHtml(c, data[c] || [])).join('') +
    (aliasPage.add === '' ? aliasInlineFormHtml('', true) : '');
  box.querySelectorAll('[data-add]').forEach(b => b.addEventListener('click', () => {
    aliasPage.rename = null;
    aliasPage.add = b.getAttribute('data-add');
    aliasRenderList();
  }));
  box.querySelectorAll('[data-rename]').forEach(b => b.addEventListener('click', () => {
    aliasPage.add = null;
    aliasPage.rename = b.getAttribute('data-rename');
    aliasRenderList();
  }));
  box.querySelectorAll('.alias-chip b').forEach(b => b.addEventListener('click', () => {
    aliasDeleteOne(b.getAttribute('data-alias'), b.getAttribute('data-canon'));
  }));
  box.querySelectorAll('.alias-cancel').forEach(b => b.addEventListener('click', () => {
    aliasPage.add = null; aliasPage.rename = null; aliasRenderList();
  }));
  box.querySelectorAll('.alias-submit').forEach(b => b.addEventListener('click', () => {
    const form = b.closest('.alias-inline');
    aliasSubmit(form);
  }));
  const focus = box.querySelector('.alias-inline input');
  if (focus) focus.focus();
}

/** 一组正名：标题（+ 改区名）→ 胶囊 → 「＋ 添加别名」→（可选）内联表单。 */
function aliasGroupHtml(canon, aliases) {
  const renaming = aliasPage.rename === canon;
  return '<div class="alias-group">' +
    '<div class="alias-canon">' + esc(canon) +
      ' <span class="sub">(' + aliases.length + ')</span>' +
      (aliasPage.kind === 'original'
        ? ' <button type="button" class="alias-rename" data-rename="' + esc(canon) + '">✏ ' +
          esc(t('改区名')) + '</button>' : '') +
    '</div>' +
    '<div class="alias-chips">' + aliases.map(a =>
      '<span class="alias-chip">' + esc(a) +
      '<b data-alias="' + esc(a) + '" data-canon="' + esc(canon) + '" title="' +
        esc(t('删除')) + '">✕</b></span>').join('') + '</div>' +
    (renaming ? aliasRenameFormHtml(canon) : '') +
    (aliasPage.add === canon ? aliasInlineFormHtml(canon, false) :
      '<button type="button" class="alias-plus" data-add="' + esc(canon) + '">＋ ' +
        esc(t('添加别名')) + '</button>') +
    '</div>';
}

/** 添加别名的内联表单：正名已预填（新建正名时两个框都可编辑）。 */
function aliasInlineFormHtml(canon, newCanon) {
  return '<div class="alias-inline" data-mode="add">' +
    (newCanon ? '<input class="alias-canon-input" placeholder="' +
      esc(t('正名（归并到这里）')) + '">' : '') +
    '<input class="alias-name-input" placeholder="' + esc(t('别名（要归并掉的那个写法）')) + '">' +
    '<button type="button" class="alias-submit">' + esc(t('登记')) + '</button>' +
    '<button type="button" class="alias-cancel">' + esc(t('取消')) + '</button>' +
    '</div>';
}

/** 改区名表单（仅同人）：正名 = 同人分区名，零文件操作。 */
function aliasRenameFormHtml(canon) {
  return '<div class="alias-inline" data-mode="rename" data-from="' + esc(canon) + '">' +
    '<input class="alias-canon-input" value="' + esc(canon) + '" placeholder="' +
      esc(t('新的同人区名')) + '">' +
    '<button type="button" class="alias-submit">' + esc(t('改名')) + '</button>' +
    '<button type="button" class="alias-cancel">' + esc(t('取消')) + '</button>' +
    '</div>';
}

async function aliasSubmit(form) {
  if (!form) return;
  const val = el => (form.querySelector(el) ? form.querySelector(el).value.trim() : '');
  try {
    if (form.getAttribute('data-mode') === 'rename') {
      const from = form.getAttribute('data-from');
      const to = val('.alias-canon-input');
      if (!to) { showToast(t('请输入完整标题')); return; }
      await api('/api/originals/rename', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ from: from, to: to, keep_alias: true }),
      });
      showToast(t('完成'));
      aliasPage.rename = null;
    } else {
      const canon = aliasPage.add === ''
        ? val('.alias-canon-input') : aliasPage.add;
      const alias = val('.alias-name-input');
      if (!canon || !alias) { showToast(t('请输入完整标题')); return; }
      await api('/api/author-aliases', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ alias: alias, canonical: canon, kind: aliasPage.kind }),
      });
      showToast(t('完成'));
      aliasPage.add = null;
    }
  } catch (e) { showToast(t('失败') + '：' + e.message); return; }
  aliasLoadList();
}

async function aliasOpenAdd(canon) {
  aliasPage.rename = null;
  aliasPage.add = canon;
  aliasRenderList();
}

async function aliasDeleteOne(alias, canon) {
  if (!confirm(t('删除') + '：' + alias + ' → ' + canon + ' ?')) return;
  try {
    await api('/api/author-aliases/delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ alias: alias, canonical: canon, kind: aliasPage.kind }),
    });
    showToast(t('完成'));
    aliasLoadList();
  } catch (e) { showToast(t('失败') + '：' + e.message); }
}
