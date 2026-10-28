# 安卓客户端构建指南

源码位于 `_app/android/`，目标 Android 16（API 36），最低支持 Android 8.0。

## 前置条件

1. **Android Studio**（Ladybug 2024.2 或更新版本，内置 JDK 17）
2. 手机端安装 **Tailscale**（Google Play / https://tailscale.org/download），登录与电脑相同的账号
3. 电脑端 Tailscale 已登录（安装后点击任务栏图标 → Log in，浏览器完成授权）
4. 电脑上 `tailscale ip -4` 得到本机虚拟 IP（形如 100.x.y.z）

## 构建环境（项目内就地编译）

工具链随项目存放在 `android/toolchain/`（android-sdk / gradle-8.11.1 / jdk17；
项目路径 `D:\<文库根>\_app` 为纯 ASCII，AGP 可直接编译，`android/local.properties`
指向 toolchain 内的 sdk）。无需再同步源码到外部副本：

```bat
:: 编译（在 D:\<文库根>\_app\android 下执行）
set JAVA_HOME=D:\<文库根>\_app\android\toolchain\jdk17
D:\<文库根>\_app\android\toolchain\gradle-8.11.1\bin\gradle.bat -p D:\<文库根>\_app\android assembleDebug
:: 产物 D:\<文库根>\_app\android\app\build\outputs\apk\debug\app-debug.apk

:: 派发更新：改名放入 app_releases（末段数字 = versionCode）
copy /Y app\build\outputs\apk\debug\app-debug.apk "D:\<文库根>\_app\app_releases\Index-v<版本>-<versionCode>.apk"
```

## 构建 APK

1. Android Studio → **Open** → 选择 `_app/android` 文件夹
2. 首次打开若提示缺 Gradle Wrapper：菜单 **File → Sync Project with Gradle Files**，
   或在 AS 内置终端执行 `gradle wrapper --gradle-version 8.11.1`（AS 会自动下载对应发行版）
3. **Build → Build App Bundle(s) / APK(s) → Build APK(s)**，产物在 `app/build/outputs/apk/debug/`
4. 传到手机安装（或 USB 调试直接运行）

## App 内配置

1. 首页会先进入「服务器设置」：
   - 服务器地址：`http://<电脑的Tailscale IP>:8766`（v2.3 起远程服务独立进程，专用端口 8766）
   - 访问令牌：`_app/config.json` 里的 `token` 字段（未设置可留空）
2. 保存后进入社团墙 → 点社团 → 点作品 → 阅读器（左右滑动翻页，webm 动态页自动播放）

## 使用流程（一次性）

```
电脑：tailscale login（浏览器授权）
手机：Tailscale App 连接同一账号 → 开关打开
电脑：双击 Index.exe「远程访问模式」卡（自动拉起 Tailscale 并以 0.0.0.0 启动服务），
      或 Index.exe「远程直连」卡 / 命令行 python app.py --host 0.0.0.0
```

> 鉴权：远程模式启动时若 `config.json` 未设置 `token`，程序会**自动生成**强随机令牌
> 并写回 config.json（面板状态栏与控制台均会提示）。手机端「服务器设置」填入该令牌即可。
> 本机 127.0.0.1 模式无需令牌。

## 常见问题

- **连接失败**：确认手机和电脑 Tailscale 都已连接（App 图标变绿）；`ping <电脑Tailscale IP>` 测试
- **401**：App 内令牌与 `_app/config.json` 的 `token` 不一致
- **图片加载慢**：第一次访问没有磁盘缓存，浏览过的页面会缓存
