package com.biblioteca.reader

import org.json.JSONObject

/** 配对 claim（3.6.144）：用一次性票据换**设备令牌**。
 *
 *  ## 为什么单独一个函数
 *
 *  扫码那一刻 `Api.baseUrl` 还指向旧服务器（首次连接时甚至是空的），而 claim 必须打到
 *  **刚扫到的那台**。所以传绝对地址——`Api.url()` 对 `http(s)://` 开头的路径不拼 `baseUrl`。
 *
 *  ## 返回值
 *
 *  `(httpCode, body)`，让调用方自己区分语义：
 *  * `200` + `token` → 换到设备令牌（`dev-` 开头，长期有效，可单台吊销）
 *  * `410` → 票据过期（默认 120 秒），提示用户回电脑点刷新
 *  * `409` → 票据已被使用（一次性），提示重新生成
 *  * `400` → 票据不认识（扫到别人的码 / 面板重启后票据表已清）
 */
internal fun Api.claimPair(url: String, ticket: String, deviceName: String): Pair<Int, JSONObject> =
    postJsonRaw(url.trimEnd('/') + "/api/pair/claim",
        JSONObject().put("p", ticket).put("n", deviceName))

/** 服务器身份挑战（3.6.146）：发一个随机 nonce，拿回 `HMAC(secret, nonce)`。
 *
 *  为什么要它：二维码只保证"内容对"，不保证"连过去的机器是上次那台"。假服务器
 *  可以照抄指纹字符串，但**算不出 proof**（它没有 secret）。
 *  与 claim 一样用绝对地址——此刻 baseUrl 还是旧的。 */
internal fun Api.pairAttest(url: String, nonce: String): Pair<Int, JSONObject> =
    postJsonRaw(url.trimEnd('/') + "/api/pair/attest", JSONObject().put("n", nonce))
