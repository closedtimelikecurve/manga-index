#!/usr/bin/env python
"""一次性清理 reading 表的冲突/孤儿键（3.6.14，用户授权执行）。

背景：社团归一（3.6.12）+ 目录外部改名 + 未归类搬收件箱（3.6.3）之后，reading 表里
残留了几条指向不存在位置的旧键——它们经 reading_resume 的 LEFT JOIN 会变成续读
列表里的"幽灵条目"（APP 侧过滤掉，网页续读区仍会显示空社团行）。

处理规则（逐条明确列出，绝不做模糊批量删除）：
  1. 删除：旧社团变体键（page 0，无进度价值，对应作品已在收件箱以新文件重新入库）
  2. 删除：目录改名前的旧键（page 0，作品现以新 key 在库）
  3. 迁移：作品被搬进收件箱后旧键失效 → 改键为「收件箱/<inbox id>」，保留阅读进度
  4. 保留：`收件箱/<id>` 伪键本身合法（磁盘无目录，works 表无行），不是孤儿

用法：python scripts/cleanup_reading_orphans.py [--dry-run]
"""
import os
import sqlite3
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(APP_DIR, "meta.db")

# (旧键, 动作, 新键或 None)
PLAN = [
    # 1. 旧社团名变体「TOZAN BU」（空格）——作品现在收件箱 id=20（同名新文件），旧键 page 0
    ("TOZAN BU/[TOZAN BU (Fujiyama)] 籠絡令嬢メイド堕ち续作", "delete", None),
    # 2. 合作目录改名前的旧键（作品现 key：brand nyu/(COMIC1☆10) [きのこのみ,brand nyu ...]），page 0
    ("きのこのみ、brand nyu/(COMIC1☆10) [きのこのみ、brand nyu (konomi、nyu)] アンチラぱんぱん♥ 【无毒汉化组】 (グランブルーファンタジー)",
     "delete", None),
    # 3. 未分类作品搬进收件箱后旧键失效——作品现在 inbox id=11，迁移保留 59 页进度
    ("未分类/田中くんが僕たちの前で兄妹セックスした日のこと 关于田中君在我们面前兄妹做爱的那一天 【Lithiumの個人サークル (Lithium) 神箭刺蜂汉化】",
     "move", "收件箱/11"),
]


def main():
    dry = "--dry-run" in sys.argv
    if not os.path.exists(DB):
        print("找不到 meta.db：", DB)
        return 1
    con = sqlite3.connect(DB, timeout=30)
    c = con.cursor()
    changed = 0
    for old_key, action, new_key in PLAN:
        row = c.execute("SELECT last_page, finished, last_read_at FROM reading WHERE key=?",
                        (old_key,)).fetchone()
        if not row:
            print(f"[跳过] 旧键不存在（可能已清理）：{old_key[:60]}…")
            continue
        lp, fin, at = row
        if action == "delete":
            if not dry:
                c.execute("DELETE FROM reading WHERE key=?", (old_key,))
            print(f"[删除] page={lp} finished={fin}  {old_key[:60]}…")
        elif action == "move":
            exists = c.execute("SELECT 1 FROM reading WHERE key=?", (new_key,)).fetchone()
            if exists:
                if not dry:
                    c.execute("DELETE FROM reading WHERE key=?", (old_key,))
                print(f"[删除] 新键已存在（{new_key}），旧键舍弃：page={lp}  {old_key[:50]}…")
            else:
                if not dry:
                    c.execute("UPDATE reading SET key=? WHERE key=?", (new_key, old_key))
                print(f"[迁移] page={lp} finished={fin}  → {new_key}")
        changed += 1
    if not dry and changed:
        con.commit()
        print("已提交，integrity_check =", c.execute("PRAGMA integrity_check").fetchone()[0])
    elif dry:
        print("（dry-run，未写入）")
    else:
        print("无改动")
    left = c.execute("SELECT COUNT(*) FROM reading").fetchone()[0]
    print("reading 表现存行数：", left)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
