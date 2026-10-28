# -*- coding: utf-8 -*-
"""APP 手势边界（3.7.100 定稿返回分流；3.6.152 重划横滑边界）。

## 历史
* 3.7.95~3.7.97：三版 Compose 父层手势全部实测失败（子节点 consume 后父层等不到 slop）。
* 3.7.98：改到 `MainActivity.dispatchTouchEvent`，但停用信号被一长串 UI 状态连坐。
* 3.7.99：稳定，但**左边缘右滑也开抽屉**（两侧系统返回被一刀切）；3.7.100 用
  `BackEventCompat.swipeEdge` 分流修好。
* **3.6.152**：用户先说「中央屏幕手势不实用，删掉」，随即修正——
  「那个将抽屉收回的中央手势值得保留，那个唤起抽屉的中央手势不必留了」。

## 现在的三条边界
1. **唤起抽屉没有手势**：整幅屏幕的左滑不再被拦，入口只有顶栏「⋯」（`onSwipeLeft` 不存在）。
2. **收回抽屉保留手势**：抽屉开着时右滑 → 收回。只在这个状态下拦 MotionEvent
   （`SwipeNav.closeArmed`），其余界面一律透传，绝不与 `LazyVerticalGrid` /
   `PullToRefreshBox` 抢触摸。
3. **返回分流不变**：右边缘开抽屉、左边缘返回、一级页退出；predictive back 必须开启。
"""
import os
import re

PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KT_DIR = os.path.join(PROG_DIR, "android", "app", "src", "main", "java", "com", "biblioteca", "reader")


def _kt_code(name):
    with open(os.path.join(KT_DIR, name + ".kt"), encoding="utf-8") as f:
        src = f.read()
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)//[^\n]*$", "", src)


def _dispatch_body(main):
    """截出 dispatchTouchEvent 的函数体。"""
    body = main[main.index("override fun dispatchTouchEvent("):]
    return body[:body.index("\n    }")]


def test_open_drawer_center_swipe_is_gone():
    """用户 3.6.152：唤起抽屉的中央手势不必留——连开关都不该存在。"""
    nav = _kt_code("GestureNav")
    assert "onSwipeLeft" not in nav, "SwipeNav 还留着「左滑唤起抽屉」的回调"
    main = _kt_code("MainActivity")
    assert "SwipeNav.onSwipeLeft" not in main, "Activity 层还在把左滑接到唤起抽屉上"
    body = _dispatch_body(main)
    assert "appDrawerOpen = true" not in body, "横滑还在开抽屉（用户明确只要「收回」这一条）"
    assert "detectHorizontalDragGestures" not in nav, "又回到 Compose 手势检测（会被子节点吞）"


def test_close_drawer_swipe_is_kept_and_only_armed_when_open():
    """收回抽屉的手势保留：只在抽屉开着时拦触摸，且只认「向右滑」。"""
    main = _kt_code("MainActivity")
    body = _dispatch_body(main)
    head = body[:body.index("when (")]
    assert "if (!SwipeNav.closeArmed) return super.dispatchTouchEvent(ev)" in head, \
        "横滑没有按「抽屉是否开着」收窄，会跟子节点抢触摸"
    assert "SwipeNav.onSwipeRightClose()" in body, "抽屉右滑收回没有接线"
    assert "ACTION_CANCEL" in body and body.index("ACTION_CANCEL") < body.index("onSwipeRightClose"), \
        "触发收回前必须先给子层发 CANCEL（否则滑完顺手点到底下的卡）"
    assert "dx >= limit" in body and "* 1.5" in body, "缺少「向右 + 横向占优」判定"
    assert "SwipeNav.THRESHOLD_DP" in body, "缺少触发阈值"
    frame = main[main.index("fun AppGestureFrame"):]
    frame = frame[:frame.index("Box(Modifier.fillMaxSize())")]
    assert "SwipeNav.closeArmed = appDrawerOpen" in frame, "没有把抽屉开合状态同步给 SwipeNav"
    assert "SwipeNav.onSwipeRightClose = { appDrawerOpen = false }" in frame, "右滑收回的目标不是关抽屉"


def test_back_gesture_edge_is_distinguished():
    """左边缘右滑是系统「返回」，一级界面应当退出应用；右边缘仍开抽屉。"""
    nav = _kt_code("GestureNav")
    assert "BackEventCompat" in nav, "拿不到返回手势的方向（swipeEdge）"
    assert "handleOnBackStarted" in nav, "没有在返回手势开始时记录方向"
    assert "BackEventCompat.EDGE_LEFT" in nav and "BackEventCompat.EDGE_RIGHT" in nav, \
        "没有区分左右边缘"
    body = nav.split("override fun handleOnBackPressed()")[1]
    left = body.split("if (edge == SwipeNav.EDGE_LEFT)")[1].split("} else {")[0]
    assert "s.back()" in left, "左边缘右滑在有上一级时没有返回"
    assert "finish()" in left, "一级界面左边缘右滑没有退出应用（用户明确要求退出）"
    assert "appDrawerOpen" not in left, "左边缘右滑还在开抽屉（用户明确说这是坏消息）"
    right = body.split("} else {")[1]
    assert "appDrawerOpen = true" in right, "右边缘左滑没有开抽屉"
    assert "OnBackPressedCallback" in nav, "没有自己注册返回回调（Compose 的 BackHandler 拿不到 edge）"


def test_back_key_still_opens_drawer_and_never_exits():
    """返回键（拿不到方向，EDGE_UNKNOWN）仍是开抽屉——只有边缘手势才退出。"""
    main = _kt_code("MainActivity")
    nav = _kt_code("GestureNav")
    assert "backArmed" not in main, "又回到\"第二次返回退出\"（用户明确不要）"
    body = nav.split("override fun handleOnBackPressed()")[1]
    key_path = body.split("} else {")[1]
    assert "appDrawerOpen = true" in key_path, "返回键没有开抽屉"
    assert "finish()" not in key_path, "返回键把应用退掉了（不该和边缘手势一起退）"
    frame = main.split("fun AppGestureFrame")[1].split("fun AppContent")[0]
    assert "BackSwipeBridge(s," in frame, "返回手势没有接到分流桥上"


def test_manifest_enables_predictive_back():
    """`handleOnBackStarted` 只在 predictive back 启用时回调，否则左右分流退化成「两侧都开抽屉」。"""
    xml = open(os.path.join(PROG_DIR, "android", "app", "src", "main", "AndroidManifest.xml"),
               encoding="utf-8").read()
    assert 'android:enableOnBackInvokedCallback="true"' in xml, \
        "清单里没有开启 predictive back（拿不到 swipeEdge）"