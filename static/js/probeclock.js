/* 本地同人志文库 前端 · probeclock.js
   3.7.57：分区爬取的本地计时器 + 路由状态同步（从 probe.js 拆出，
   保证单文件有效代码 ≤400）。

   为什么单独一片：服务端 elapsed 每 2s 才随快照回来一次，直接显示会"跳秒"；
   这里让界面每秒自己走，服务端值只做"不能倒退"的正向校准。
   与其余分片共享全局词法环境；加载顺序在 probe.js 之后（函数在调用时才解析）。 */
'use strict';

const probeClock = { base: 0, at: 0, jobId: 0 };

function probeSiteLabel(s) {
  const hit = probeSites().find(p => p[0] === probeSiteOk(s));   // 3.6.141 站点表函数化
  return hit ? hit[1] : 'wnacg';
}

function probeSyncClock(job) {
  if (!job) { probeClock.base = 0; probeClock.at = 0; probeClock.jobId = 0; return; }
  const elapsed = Number(job.elapsed) || 0;
  if (job.id !== probeClock.jobId) {
    probeClock.jobId = job.id;
    probeClock.base = elapsed;
  } else {
    probeClock.base = Math.max(probeClock.base, elapsed);
  }
  probeClock.at = Date.now();
}

function probeElapsedValue() {
  const j = probe.job;
  if (!j) return 0;
  if (!j.running) return Number(j.elapsed) || 0;
  const extra = probeClock.at ? Math.max(0, Math.floor((Date.now() - probeClock.at) / 1000)) : 0;
  return probeClock.base + extra;
}

/** 只更新三个计时文本节点，不整块重绘（每 2s 的列表重绘不应变成每秒一次）。 */
function probeClockTick() {
  if (!probe.job || !probe.job.running) return;
  const text = probeElapsedText(probeElapsedValue());
  ['probeTickerElapsed', 'probeJobElapsed', 'crawlPickElapsed'].forEach(id => {
    const el = $('#' + id);
    if (el) el.textContent = text;
  });
}

/** 把当前 kind/term/site 写回 hash（replaceState，不触发 route）：
 * 任务结束后的 refresh 会按 hash 重渲染；不写回的话会退回旧站点/旧词条。 */
function probeUpdateHash() {
  const qp = new URLSearchParams();
  qp.set('kind', probe.kind);
  if (probe.term) qp.set('term', probe.term);
  qp.set('site', probe.site);
  const next = '#/probe?' + qp.toString();
  if (location.hash !== next) history.replaceState(null, '', next);
}
