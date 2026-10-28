# -*- coding: utf-8 -*-
"""3.7.83 双端两条体验修正的守卫：

① 顶部功能栏必须是实色——用户第三次报"还是有透明度"，根因是首页搜索栏用主副色
   0x33 渐变、分区搜索栏干脆没底色（背景图直接透上来）；
② 扫码必须是**实时取景逐帧识别**，不是"拉起相机拍一张照片再识图"。

断言全部针对源码文本（本仓库没有真机/模拟器，UI 行为靠结构守卫 + 编译兜底）。
"""
import os
import re

PROG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KT_DIR = os.path.join(PROG_DIR, "android", "app", "src", "main", "java", "com", "biblioteca", "reader")


def _kt(name):
    with open(os.path.join(KT_DIR, name + ".kt"), encoding="utf-8") as f:
        return f.read()


def _kt_code(name):
    src = _kt(name)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)//[^\n]*$", "", src)


# ---------- ① 顶栏实色 ----------

def test_top_bars_are_tinted_but_opaque():
    """功能栏既要"有颜色"，又不能靠半透明（半透明 = 背景图透上来）。

    3.7.83 一刀切成实色 `CARD_BG`，结果颜色没了、只剩近黑紫底（用户嫌难看）；
    3.7.84 起统一走 `barTint()`：主副色 `compositeOver(CARD_BG)` 后是**不透明**色，
    视觉上等于旧版"染色渐变"，但背景透不过来。所以这里同时守两件事：
    必须用 barTint，且源码里不许再出现 0x33/0x22 这类半透明染色。"""
    common = _kt_code("FeaturesCommon")
    assert "internal fun barTint(" in common, "缺少不透明染色助手"
    assert "compositeOver(CARD_BG)" in common, "barTint 没有压进不透明底色（仍会透）"
    for name in ("FeaturesHome", "RegionSearchBar"):
        code = _kt_code(name)
        assert "barTint(" in code, "%s 的功能栏没上色（会退回近黑紫底）" % name
        assert "copy(alpha = 0x33" not in code and "copy(alpha = 0x22" not in code,             "%s 又用半透明给功能栏染色（背景会透上来）" % name


# ---------- ② 实时扫码 ----------

def test_scan_uses_live_preview_and_frame_analysis():
    scan = _kt_code("QrScannerScreen")
    for token in ("ProcessCameraProvider", "Preview.Builder", "ImageAnalysis.Builder",
                  "setAnalyzer", "STRATEGY_KEEP_ONLY_LATEST"):
        assert token in scan, "实时取景链路缺少：%s" % token
    assert "PlanarYUVLuminanceSource" in scan, "应直接读 Y 平面逐帧解码（省一次整帧转换）"
    assert "unbindAll" in scan, "关掉取景页必须解绑相机，否则灯一直亮"


def test_qr_connect_no_longer_takes_photos():
    """旧的 TakePicture（拍照→落盘→识图）必须消失，改成打开取景层。"""
    qr = _kt_code("QrConnect")
    assert "TakePicture" not in qr, "还在用拍照后识图"
    assert "QrScanScreen" in qr and "Dialog" in qr, "主按钮没有打开实时取景层"
    assert "parsePairPayload" in qr, "配对内容解析被拆散/丢失"


def test_camera_permission_and_dependency_declared():
    manifest = open(os.path.join(PROG_DIR, "android", "app", "src", "main",
                                 "AndroidManifest.xml"), encoding="utf-8").read()
    assert 'android.permission.CAMERA' in manifest, "缺 CAMERA 权限（实时扫码起不来）"
    gradle = open(os.path.join(PROG_DIR, "android", "app", "build.gradle.kts"),
                  encoding="utf-8").read()
    for artifact in ("camera-core", "camera-camera2", "camera-lifecycle", "camera-view"):
        assert "androidx.camera:%s" % artifact in gradle, "缺少 CameraX 依赖：%s" % artifact
