package com.biblioteca.reader

import android.content.Context
import java.net.URI
import java.util.UUID
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/* ================================================================
   3.6.146 服务器身份校验（TOFU + 挑战-响应）

   二维码只保证"内容对"，不保证"连过去的是上次那台机器"。假服务器能照抄二维码里的
   地址与指纹字符串，但**算不出** `HMAC(secret, nonce)` —— secret 只在首次 claim 时
   下发一次，之后只存在于手机与服务器的 `_state/` 里。

   所以本文件能拦下"配对过一次之后被换成另一台机器"（DNS 劫持、码被替换、地址被改）。
   **首次配对无法判断真假**——那时手里没有 secret 可比对，这是所有 TOFU 方案的固有边界。
   ================================================================ */

private const val PREFS = "biblioteca"
private const val KEY_PREFIX = "pair_sk_"

private fun prefs(ctx: Context) = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

/** 以 `host:port` 为键——一台手机可能连过多台服务器，secret 不能混用。 */
internal fun pairIdentityKey(url: String): String = try {
    val u = URI(url)
    val host = u.host ?: url
    val port = if (u.port > 0) u.port else 8766
    KEY_PREFIX + host + ":" + port
} catch (_: Exception) {
    KEY_PREFIX + url
}

internal fun hasServerIdentity(ctx: Context, url: String): Boolean =
    prefs(ctx).getString(pairIdentityKey(url), "").orEmpty().isNotEmpty()

internal fun clearServerIdentity(ctx: Context, url: String) {
    prefs(ctx).edit().remove(pairIdentityKey(url)).apply()
}

/** 记录服务器的 secret（claim 响应里的 `sk`）。空值不覆盖已有记录。 */
internal fun saveServerIdentity(ctx: Context, url: String, sk: String) {
    if (sk.isNotEmpty()) prefs(ctx).edit().putString(pairIdentityKey(url), sk).apply()
}

internal fun hmacSha256Hex(key: String, msg: String): String {
    val mac = Mac.getInstance("HmacSHA256")
    mac.init(SecretKeySpec(key.toByteArray(Charsets.UTF_8), "HmacSHA256"))
    return mac.doFinal(msg.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
}

/** 校验"这台服务器还是上次那台"。
 *
 *  返回 `null` = 通过（或首次配对，尚无可比对记录）；否则返回给用户看的说明。
 *  网络异常不判为冒充——交给随后的 claim 去报错，避免把"网络抖动"说成"有人在骗你"。 */
internal fun verifyServerIdentity(ctx: Context, url: String): String? {
    val known = prefs(ctx).getString(pairIdentityKey(url), "").orEmpty()
    if (known.isEmpty()) return null
    val nonce = UUID.randomUUID().toString().replace("-", "")
    val (code, body) = try {
        Api.pairAttest(url, nonce)
    } catch (_: Exception) {
        return null
    }
    val proof = body.optString("proof")
    if (code != 200 || proof.isEmpty()) {
        return AppI18n.s("无法验证服务器身份（服务器未响应挑战）。")
    }
    return if (hmacSha256Hex(known, nonce).equals(proof, ignoreCase = true)) null
    else AppI18n.s("服务器身份校验失败：这次连接的服务器与上次记录的不同。若你确实换过服务器，请在设置里清除「服务器身份校验」后重试。")
}
