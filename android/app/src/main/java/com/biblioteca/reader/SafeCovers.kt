package com.biblioteca.reader

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/* 3.7.110 内测模式（所有封面换占位图）——AppState 的状态同步与切换。
   单独成文件的原因：AppState.kt 已顶到 500 行有效代码上限（工程纪律 F005），
   这两个方法只是"读服务端/写服务端 + 回写本地镜像"，与 AppState 其它域无关。
   状态字段 `safeCovers` 必须留在 AppState 里（mutableStateOf 的宿主），这里只做扩展。 */

/**
 * 抽屉每次展开都拉一次服务端状态。
 * 状态存在面板侧 config.json，不是本机 SharedPreferences——网页切过之后，
 * 手机端再开抽屉必须看到新值，否则两端显示会打架。
 * 失败静默：网络断了就维持上一次的显示，不弹错（用户此刻只是打开抽屉）。
 */
internal fun AppState.refreshSafeCovers() {
    scope.launch {
        runCatching { withContext(Dispatchers.IO) { Api.fetchSafeCovers() } }
            .onSuccess { safeCovers = it }
    }
}

/** 切开关。失败就退回服务端那侧的真实值，不留下"看起来开了"的假象。 */
internal fun AppState.toggleSafeCovers(on: Boolean) {
    scope.launch {
        runCatching { withContext(Dispatchers.IO) { Api.setSafeCovers(on) } }
            .onSuccess { safeCovers = it }
            .onFailure { safeCovers = Api.safeCovers }
    }
}
