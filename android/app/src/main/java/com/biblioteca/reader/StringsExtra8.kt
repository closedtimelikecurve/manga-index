package com.biblioteca.reader

/** 3.7.89 语言包批次三（二）：统计页（7 key × 7 语）。
 *
 *  六张数字卡的标题（作品 / 页数 / 社团 / 已读 / 在读 / 收藏）+ 喜爱画师行的新作徽标 `新 %1`。
 *  `%1` 是数字，位置按语言可移（en `New %1`、ru `Новых: %1`）。纯数据，无逻辑。 */
internal val I18N_EXTRA8: Map<String, Map<String, String>> = mapOf(
    "zh-Hant" to mapOf(
        "作品" to "作品",
        "页数" to "頁數",
        "社团" to "社團",
        "已读" to "已讀",
        "在读" to "在讀",
        "收藏" to "收藏",
        "新 %1" to "新 %1"
    ),
    "en" to mapOf(
        "作品" to "Works",
        "页数" to "Pages",
        "社团" to "Circles",
        "已读" to "Read",
        "在读" to "In progress",
        "收藏" to "Favorites",
        "新 %1" to "New %1"
    ),
    "ja" to mapOf(
        "作品" to "作品",
        "页数" to "ページ数",
        "社团" to "サークル",
        "已读" to "読了",
        "在读" to "読書中",
        "收藏" to "お気に入り",
        "新 %1" to "新着 %1"
    ),
    "ko" to mapOf(
        "作品" to "작품",
        "页数" to "페이지 수",
        "社团" to "서클",
        "已读" to "읽음",
        "在读" to "읽는 중",
        "收藏" to "즐겨찾기",
        "新 %1" to "새 %1"
    ),
    "ru" to mapOf(
        "作品" to "Работы",
        "页数" to "Страницы",
        "社团" to "Круги",
        "已读" to "Прочитано",
        "在读" to "Читаю",
        "收藏" to "Избранное",
        "新 %1" to "Новых: %1"
    ),
    "th" to mapOf(
        "作品" to "ผลงาน",
        "页数" to "จำนวนหน้า",
        "社团" to "วง",
        "已读" to "อ่านแล้ว",
        "在读" to "กำลังอ่าน",
        "收藏" to "รายการโปรด",
        "新 %1" to "ใหม่ %1"
    ),
    "vi" to mapOf(
        "作品" to "Tác phẩm",
        "页数" to "Số trang",
        "社团" to "Nhóm",
        "已读" to "Đã đọc",
        "在读" to "Đang đọc",
        "收藏" to "Yêu thích",
        "新 %1" to "Mới %1"
    )
)