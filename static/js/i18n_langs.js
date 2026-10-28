/* 本地同人志文库 前端 · i18n_langs.js
   3.6.116：语言包按语言拆成 i18n_lang_*.js（本片之前的 7 个分片），本片只做收尾——
   分片就位后再应用一次 DOM 替换（i18n.js 的首次 apply 时语言包尚未加载）。 */
'use strict';

/* 语言包就位后再应用一次（i18n.js 的首次 apply 时本包尚未加载） */
i18nApplyDom();
