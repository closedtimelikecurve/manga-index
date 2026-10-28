package com.biblioteca.reader

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/* ================================================================
   检查更新（3.7.64 从 AppState 拆出：该文件有效代码到 500 行上限）
   * 自动检查：启动、恢复联网、首页加载成功，三条路都会走到；
   * 手动检查（设置页）：force=true，无视"暂不更新"，且**一定有反馈**；
   * 用扩展函数而不是新类：状态（updateInfo/updateChecking）仍归 AppState。
   ================================================================ */

/** 本机版本（code / name）——检查更新与设置页展示都用它。 */
internal fun AppState.currentVersionCode(): Int = try {
    val pm = ctx.packageManager
    if (android.os.Build.VERSION.SDK_INT >= 28) pm.getPackageInfo(ctx.packageName, 0).longVersionCode.toInt()
    else @Suppress("DEPRECATION") pm.getPackageInfo(ctx.packageName, 0).versionCode
} catch (_: Exception) { 0 }

internal fun AppState.currentVersionName(): String = try {
    ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName ?: ""
} catch (_: Exception) { "" }

/**
 * 检查更新。
 *
 * 3.7.64 两条修正：
 *  * 原来**只有** loadHome 成功后才会调到这里；启动那次首页加载失败/离线就再也不检查了
 *    （用户反馈"没收到更新"）。现在启动与恢复联网都会调一次；
 *  * `force=true` 是设置页的手动检查：无视"暂不更新"的记录，并且**一定有反馈**
 *    （已是最新 / 发现新版本 / 服务器没有包 / 具体错误），不再静默。
 */
internal fun AppState.checkUpdate(force: Boolean = false) {
    if (serverUrl.isEmpty()) { if (force) appToast(AppI18n.s("还没配置服务器地址")); return }
    if (!force && (updateInfo != null || updateChecking)) return
    updateChecking = true
    scope.launch {
        try {
            checkCompat()
            applyUpdateCheck(withContext(Dispatchers.IO) { Api.appVersion() }, force)
        } catch (e: Exception) {
            if (force) appToast(AppI18n.sf("检查更新失败：%1", e.message))
        } finally { updateChecking = false }
    }
}

/** 拿到服务端版本后的判定（手动检查一定有反馈；自动检查只在新版本时弹窗）。 */
private fun AppState.applyUpdateCheck(v: Api.AppVersionInfo?, force: Boolean) {
    val cur = currentVersionCode()
    if (v == null) { if (force) appToast(AppI18n.s("服务器上没有可用的安装包")); return }
    val newer = v.versionCode > cur
    if (newer && (force || v.versionCode > dismissedVersion.intValue)) {
        updateInfo = v
        if (force) appToast(AppI18n.sf("发现新版本 v%1", v.versionName))
        return
    }
    if (force) appToast(AppI18n.sf("已是最新 · 本机 %1(%2)", currentVersionName(), cur) +
        AppI18n.sf(" · 服务器 %1(%2)", v.versionName, v.versionCode))
}
