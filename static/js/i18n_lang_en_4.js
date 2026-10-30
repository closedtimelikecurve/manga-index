/* 本地同人志文库 前端 · i18n_lang_en_4.js
   3.6.151 第 4 片：远程服务开关（网页「扫码配对」页）+ 作品列表排序档位
   （时间 / 文件大小 / 名称，查重用）。与 _2 / _3 一样是 classic script，加载顺序在 _3 之后。
   English，23 条。 */
'use strict';

Object.assign(I18N_PACKS['en'], {
  "远程服务：状态未知": "Remote service: status unknown",
  "远程服务：运行中": "Remote service: running",
  "远程服务：已停止": "Remote service: stopped",
  "启动远程服务": "Start remote service",
  "停止远程服务": "Stop remote service",
  "处理中…": "Working…",
  "远程服务将在 %1 秒后停止": "The remote service stops in %1 s",
  "远程服务本来就没在运行": "The remote service wasn't running",
  "远程服务正在启动，几秒后可用": "The remote service is starting — ready in a few seconds",
  "远程服务已在运行": "The remote service is already running",
  "当前就是远程服务进程，无法自启动；请在电脑的面板页操作": "This page IS the remote service, so it can't start itself — do it from the panel on the PC",
  "启动失败（无法创建子进程）": "Start failed (couldn't spawn the process)",
  "停止后手机会立刻断连，需要回电脑启动器重新开启": "Stopping cuts the phone off immediately — start it again from the launcher on the PC",
  "本页正由远程服务提供：停止会立即断开本页，需回电脑启动器重新开启": "This page is served by the remote service: stopping it disconnects this page at once — start it again from the PC launcher",
  "启动后手机才能通过远程地址访问（需先在电脑上接好远程接入）": "The phone can reach the remote address only after this is running (set up remote access on the PC first)",
  "确定停止远程服务？手机会立刻断连，需要回电脑启动器重新开启。": "Stop the remote service? The phone loses connection immediately; start it again from the PC launcher.",
  "时间": "Time",
  "文件大小": "File size",
  "名称": "Name",
  "↓ 由小到大": "↓ Small to large",
  "↓ 由大到小": "↓ Large to small",
  "↓ 由旧到新": "↓ Old to new",
  "↓ 由少到多": "↓ Few to many",
  /* 3.6.161 内测模式（封面统一换成占位图；抽屉开关，双端共用） */
  "内测模式": "Safe covers",
  "内测模式：所有封面统一换成占位图（截图 / 录屏用，不动任何文件）": "Safe covers: replace every cover with one placeholder image (for screenshots or screen recording; no files are touched)",
  "内测模式已开启：封面已换成占位图": "Safe covers on: every cover now shows the placeholder",
  "内测模式已关闭": "Safe covers off",
  "内测模式已开启：封面已换成占位图（仅网页）": "Safe covers on: every cover now shows the placeholder (web only)",
  "内测模式已关闭（仅网页）": "Safe covers off (web only)",
  "切换失败": "Switch failed",
  "新建一个空的同人分区（之后在分区里「＋ 添加作品」补作品）": "Create an empty doujin zone (add works later with “＋ Add works” inside the zone)",
  "新建分区": "New zone",
  "建一个空的同人分区": "Create an empty zone",
  "新建同人分区：输入分区名（先建一个空分区，之后在分区里点「＋ 添加作品」补作品）": "New doujin zone: enter a name (an empty zone is created first; add works inside it afterwards with “＋ Add works”)",
  "分区「%1」已存在": "Zone “%1” already exists",
  "已新建分区「%1」": "Created zone “%1”",
});
