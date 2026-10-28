package com.biblioteca.reader

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/* ==========================================================================
   3.7.56 对齐网页 `probeWatch`：分区爬取跑在服务端线程里，APP 只做观察者。

   为什么收进 APP 级状态：旧版轮询绑在探针页的 LaunchedEffect 上——离开页面就没人
   再问状态，从别的设备启动的任务进页面也看不到。现在由 AppEffects 常驻轮询
   （运行中 2s / 空闲 15s，单飞），探针页、爬虫页卡片、全局浮标都读同一份 [job]。
   ========================================================================== */

internal class ProbeWatch {
    var job by mutableStateOf<ProbeJob?>(null)
        private set
    var wasRunning: Boolean = false
        private set
    private var busy = false

    /** 应用一次快照：running 或已结束（finished>0）才保留，避免空闲的空任务覆盖页面。 */
    fun apply(s: AppState, next: ProbeJob?) {
        val j = next?.takeIf { it.running || it.finished > 0 }
        job = j
        val running = j?.running == true
        if (wasRunning && !running && j != null) {
            s.appToast(AppI18n.sf("搜索下载器结束：成功 %1 · 失败 %2", j.done, j.failed))
            s.invalidateHome()                 // 新作品/新原作标签这时才进索引
        }
        wasRunning = running
    }

    /** 单飞轮询：面板重启/瞬时断网只跳过本轮，不打扰用户。 */
    suspend fun tick(s: AppState) {
        if (busy) return
        busy = true
        try {
            apply(s, withContext(Dispatchers.IO) { Api.probeJob() })
        } catch (_: Exception) {
            // 与网页一致：下一轮再试；任务本身在服务端继续跑
        } finally {
            busy = false
        }
    }

    /** 起任务后立刻拉一次，避免等最长 15s 的空闲间隔。 */
    fun kick(s: AppState) { s.scope.launch { tick(s) } }
}

/** 取消分区爬取（当前这一部下完即停），随后刷新快照让界面立即变成"取消中"。 */
fun AppState.cancelProbePick() {
    scope.launch {
        val msg = try {
            withContext(Dispatchers.IO) { Api.probeCancel() }
        } catch (e: Exception) {
            appToast(AppI18n.sf("取消失败：%1", e.message))
            return@launch
        }
        appToast(msg.ifEmpty { AppI18n.s("已请求取消") })
        probeWatch.tick(this@cancelProbePick)
    }
}
