package com.biblioteca.reader

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import androidx.activity.BackEventCompat
import androidx.activity.OnBackPressedCallback
import androidx.activity.compose.LocalOnBackPressedDispatcherOwner
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext

/**
 * 手势接线（3.7.99 建立，3.6.152 按用户修正重划边界）。
 *
 * 3.6.152 第一稿把整幅屏幕横滑**全删**了（用户当时说"中央屏幕手势不实用"）；
 * 随后用户修正：「那个将抽屉收回的中央手势值得保留，那个唤起抽屉的中央手势不必留了」。
 * 于是现在的边界是：
 * * **唤起抽屉**：没有手势，只走顶栏「⋯」——屏幕中间的左滑不再被拦；
 * * **收回抽屉**：保留。抽屉开着时向右滑 = 把抽屉推回去，与抽屉从右侧滑出的方向一致。
 *
 * 实现上仍由 `MainActivity.dispatchTouchEvent` 在子树之前拿 MotionEvent（Compose 父层
 * 抢不过 `LazyVerticalGrid` 的滚动与 `PullToRefreshBox` 的嵌套滚动，3.7.95~3.7.97 三次实测），
 * 但**只在抽屉开着时**（[closeArmed]）才跟踪，其余时间一律透传，不跟任何子节点抢触摸。
 *
 * 系统返回另走一条路：[BackSwipeBridge] 用 `BackEventCompat.swipeEdge` 判方向——
 * 右边缘开抽屉、左边缘返回、一级页退出。
 */
object SwipeNav {
    /** 抽屉是否开着。**只有**此时 Activity 层才跟踪横滑（其余界面直接透传）。 */
    @Volatile
    var closeArmed: Boolean = false

    /** 抽屉开着时向右滑 → 收回抽屉。 */
    @Volatile
    var onSwipeRightClose: () -> Unit = {}

    /** 触发阈值：48dp。远大于系统 touch slop，竖滑不会误触。 */
    const val THRESHOLD_DP: Float = 48f

    /** 最近一次返回来自哪条边（由 [BackSwipeBridge] 写入，`handleOnBackPressed` 消费）。 */
    const val EDGE_UNKNOWN = 0
    const val EDGE_LEFT = 1
    const val EDGE_RIGHT = 2
    @Volatile
    var backEdge: Int = EDGE_UNKNOWN
}

/**
 * 返回手势/返回键的桥接：区分左右边缘。
 *
 * * **右边缘左滑**（`EDGE_RIGHT`）→ 开抽屉（用户明确要这个方向）；
 * * **左边缘右滑**（`EDGE_LEFT`）→ 就是系统的"返回"：有上一级就回去，一级页**直接退出应用**
 *   （用户 3.7.100 明确要求：一级界面左边缘右滑应当退出，而不是什么都不做——
 *   这正是 Android 的标准语义，先前为了防误触改成"不动作"，反而让返回手势失灵）；
 * * **拿不到方向**（硬件/导航栏返回键、或 Android 13 以下没有 predictive back）→ 开抽屉，
 *   与 3.7.99 行为一致（按键返回开抽屉是用户已接受的行为，不跟着边缘一起退出）。
 *
 * 注意注册时机：[DisposableEffect] 在 `content()` 之前执行，所以 `AppDrawer` 里那个
 * `BackHandler(enabled = appDrawerOpen)` 会后注册、优先级更高——抽屉开着时返回先关抽屉。
 */
@Composable
internal fun BackSwipeBridge(s: AppState, enabled: Boolean) {
    val owner = LocalOnBackPressedDispatcherOwner.current ?: return
    val activity = LocalContext.current.findActivity()
    val cb = remember(owner, activity) {
        object : OnBackPressedCallback(false) {
            override fun handleOnBackStarted(backEvent: BackEventCompat) {
                SwipeNav.backEdge = when (backEvent.swipeEdge) {
                    BackEventCompat.EDGE_LEFT -> SwipeNav.EDGE_LEFT
                    BackEventCompat.EDGE_RIGHT -> SwipeNav.EDGE_RIGHT
                    else -> SwipeNav.EDGE_UNKNOWN
                }
            }

            override fun handleOnBackPressed() {
                val edge = SwipeNav.backEdge
                SwipeNav.backEdge = SwipeNav.EDGE_UNKNOWN
                if (edge == SwipeNav.EDGE_LEFT) {
                    // 左边缘右滑 = 系统"返回"：有上一级就回去，一级页退出应用
                    if (s.navStack.size > 1) s.back() else activity?.finish()
                } else {
                    appDrawerOpen = true                   // 右边缘 / 返回键：开抽屉
                }
            }
        }
    }
    SideEffect { cb.isEnabled = enabled }
    DisposableEffect(owner) {
        owner.onBackPressedDispatcher.addCallback(cb)
        onDispose { cb.remove() }
    }
}

/** 从 Compose 的 Context 找宿主 Activity（中间可能套着 ContextThemeWrapper 等，要逐层剥）。 */
private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}
