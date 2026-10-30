import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

// ---- 版号两半各司其职（2026-09-22 起）----
//   versionName：人读的语义版本，**手工**升（改了就升：2.6.0 → 2.6.1 …），决定"这版是什么"。
//   versionCode：机器用的单调构建号，**自动** = yyMMddHH（构建时刻的小时，8 位），免手工维护、
//                天然递增、不会再出现"忘了 +1 导致手机收不到更新"。Android 上限 21 亿，
//                8 位数字（当日 2600 万级）永远到不了顶。
//   需要手工指定时：gradle assembleDebug -Pvc=12345（比如同一小时内要连出两个包）。
//   注意：Gradle Kotlin DSL 里 `java` 会被 JavaPlugin 扩展遮蔽，故 java.* 必须走顶部 import。
val autoVersionCode: Int = (project.findProperty("vc") as String?)?.toIntOrNull()
    ?: SimpleDateFormat("yyMMddHH", Locale.US).format(Date()).toInt()

android {
    namespace = "com.biblioteca.reader"
    compileSdk = 36
    defaultConfig {
        applicationId = "com.biblioteca.reader"
        minSdk = 26
        targetSdk = 36
        // 面板轴与 APP 轴互相独立（分轴版号）：versionName 不再要求等于面板 VERSION/PANEL_VERSION；
        // 与面板的接口兼容性由 APP_API_LEVEL（Api.kt）↔ /api/config 的 apiLevel/minAppApi 判定。
        versionCode = autoVersionCode
        versionName = "3.7.113"
    }
    buildFeatures { compose = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("com.google.zxing:core:3.5.3")   // 3.7.77 扫码配对：QR 解码
    // 3.7.83 实时扫码：取景预览 + ImageAnalysis 逐帧解码（用户要求：摄像头连续识别，
    // 而不是"拍一张照片再识图"）。版本与本机 Gradle 缓存一致，构建不依赖联网。
    implementation("androidx.camera:camera-core:1.6.1")
    implementation("androidx.camera:camera-camera2:1.6.1")
    implementation("androidx.camera:camera-lifecycle:1.6.1")
    implementation("androidx.camera:camera-view:1.6.1")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("io.coil-kt:coil-compose:2.7.0")
    // GIF/动图 WebP 解码：缺此依赖 GIF 只渲染第一帧（Coil 2.x 自动注册动图解码器）
    implementation("io.coil-kt:coil-gif:2.7.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("androidx.media3:media3-exoplayer:1.5.1")
    implementation("androidx.media3:media3-ui:1.5.1")
}
