"""三账号会话统一：清理软删/空壳，把每个会话补齐到所有账号。

设计原则：
- 标题（归一化）作为「同一段对话」的身份；一个标题 = 一个会话族。
- 每个会话族选「正文最大的健康版本」为authoritative源（healthy = 未软删且有正文）。
- 清除所有软删记录、无正文空壳记录（正文与工作区保留，可人工恢复）。
- 缺失该会话族的账号，从authoritative源复制正文+索引（新 sid，内容 id 同步替换）。
- 全程幂等：重复执行不会增生；dry_run 只报告不落盘。

为什么要独立命令而不是复用 smart-merge：
smart-merge 的「防回灌」判据（源是副本且不比目标大 → skip）会阻止把
健康正文补进只有空壳/软删副本的账号，导致三账号永远不一致。整理是
一次性运维动作，规则不同，单独实现，避免污染日常合并逻辑。
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections import defaultdict
from pathlib import Path

from . import client, paths, profiles, sessions


def _title_key(t: object) -> str:
    return " ".join(str(t or "").split()).lower()


def _body_index() -> dict[str, int]:
    """会话 id -> 正文字节数（只收录 >= 50B 的有效正文）。"""
    out: dict[str, int] = {}
    for d in paths.session_body_dirs():
        try:
            for p in d.glob("*.jsonl"):
                try:
                    sz = p.stat().st_size
                except OSError:
                    continue
                if sz >= 50:
                    out[p.stem] = max(sz, out.get(p.stem, 0))
        except OSError:
            continue
    return out


def unify_sessions(dry_run: bool = True) -> dict:
    report: dict = {
        "dry_run": dry_run, "errors": [], "accounts": [],
        "removed_soft_deleted": 0, "removed_empty": 0,
        "copied": [], "restored": [], "snapshots": [],
    }
    if not dry_run and client.is_running():
        report["errors"].append(
            "WorkBuddy 正在运行：整理需写会话数据库，请先结束客户端")
        return report

    uids = [a.uid for a in profiles.list_accounts()]
    uids = [u for u in uids if u]
    if not uids:
        report["errors"].append("没有找到任何账号档案")
        return report
    report["accounts"] = uids

    bodies = _body_index()
    live = sessions._live_conn()
    try:
        cur = live.execute("SELECT * FROM sessions")
        cols_meta = cur.description
        lcols = [d[0] for d in cols_meta]
        rows = [dict(zip(lcols, r)) for r in cur.fetchall()]
        cols = [r[1] for r in live.execute("PRAGMA table_info(sessions)")]
        insert_sql = sessions._session_insert_sql(cols)
        if insert_sql is None:
            report["errors"].append("客户端 sessions 表缺少必需列，拒绝整理")
            return report

        # 按标题分组
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            key = _title_key(r.get("title"))
            if key:
                groups[key].append(r)

        to_delete: list[str] = []      # 要清除的记录 id
        restore_ids: list[str] = []    # 要恢复（清 deleted_at）的记录 id
        authoritative: dict[str, dict] = {}      # title_key -> authoritative行
        per_account: dict[str, set[str]] = defaultdict(set)  # uid -> 已有 title_key

        for key, members in groups.items():
            def is_healthy(m: dict) -> bool:
                return not m.get("deleted_at") and bodies.get(m["id"], 0) >= 50

            # 按账号归拢健康版本
            by_uid: dict[str, list[dict]] = defaultdict(list)
            for m in members:
                if is_healthy(m):
                    by_uid[m.get("user_id")].append(m)

            # 权威 = 全体正文最大的健康版本（用于给缺口账号复制正文）
            all_healthy = [m for ms in by_uid.values() for m in ms]
            src = None
            restore_sid = None
            if all_healthy:
                src = max(all_healthy, key=lambda m: bodies.get(m["id"], 0))
                authoritative[key] = src
            else:
                # 整族无健康版本：若有带正文的软删记录，恢复它（清 deleted_at）
                with_body = [m for m in members if bodies.get(m["id"], 0) >= 50]
                if with_body:
                    src = max(with_body, key=lambda m: bodies.get(m["id"], 0))
                    authoritative[key] = src
                    restore_sid = src["id"]
                    restore_ids.append(restore_sid)
                    report["restored"].append(
                        {"title": src.get("title"), "sid": src["id"][:8],
                         "uid": (src.get("user_id") or "")[:8]})

            # 删除判定（核心：健康副本跨账号各自保留，只清以下三类）：
            #   1) 软删记录（deleted_at 非空，含 -1 空壳）
            #   2) 无正文记录
            #   3) 同一账号内的多个健康副本（只留正文最大的那个）
            for m in members:
                if restore_sid and m["id"] == restore_sid:
                    continue  # 该软删记录将被恢复，不删除
                if m.get("deleted_at") or bodies.get(m["id"], 0) < 50:
                    to_delete.append(m["id"])
                    continue
                # 健康：若同账号还有更大的健康版本，删掉这个较小的
                peers = by_uid.get(m.get("user_id"), [])
                bigger = [p for p in peers if bodies.get(p["id"], 0) > bodies.get(m["id"], 0)]
                # 同大小并列时按 id 排序留一个，避免完全同大小时两份都留
                equal = [p for p in peers
                         if bodies.get(p["id"], 0) == bodies.get(m["id"], 0)
                         and p["id"] != m["id"] and p["id"] < m["id"]]
                if bigger or equal:
                    to_delete.append(m["id"])

            # 登记哪些账号已有健康版本（排除将被删除的）
            for uid in uids:
                ok = any(
                    m.get("user_id") == uid
                    and (is_healthy(m) or m["id"] == restore_sid)
                    and m["id"] not in to_delete
                    for m in members
                )
                if ok:
                    per_account[uid].add(key)

        # 待补清单
        plan_copy = []
        for key, src in authoritative.items():
            src_uid = src.get("user_id")
            src_body = paths.find_session_body(src["id"])
            if src_body is None:
                report["errors"].append(f"authoritative正文丢失: {src['id'][:8]}")
                continue
            for uid in uids:
                if uid == src_uid:
                    continue
                if key in per_account[uid]:
                    continue
                # 该账号已有同标题记录但被列入删除（软删/空壳）→ 用新 sid 补
                plan_copy.append((key, src, uid))

        if dry_run:
            report["planned_delete"] = len(to_delete)
            report["planned_copy"] = len(plan_copy)
            report["planned_titles"] = [
                {"title": authoritative[k].get("title"), "to": u[:8]}
                for k, _s, u in plan_copy[:30]
            ]
            return report

        # ---- 落盘 ----
        live.execute("BEGIN IMMEDIATE")
        try:
            # 1) 删除软删/空壳/冗余记录
            for sid in to_delete:
                live.execute("DELETE FROM sessions WHERE id=?", (sid,))
            report["removed_soft_deleted"] = len(to_delete)

            # 2) 恢复整族软删但有正文的记录
            for sid in restore_ids:
                live.execute(
                    "UPDATE sessions SET deleted_at=NULL WHERE id=?", (sid,))

            # 3) 补齐缺失账号
            stamp = int(time.time() * 1000)
            arch = sessions._conn()
            edition = paths.current_edition()
            for key, src, uid in plan_copy:
                old_sid = src["id"]
                new_sid = str(uuid.uuid4())
                body = paths.find_session_body(old_sid)
                if body is None:
                    report["errors"].append(f"复制时正文丢失: {old_sid[:8]}")
                    continue
                if not sessions._replace_id_in(
                        body, body.parent / f"{new_sid}.jsonl", old_sid, new_sid):
                    report["errors"].append(f"正文复制失败: {old_sid[:8]}")
                    continue
                for suffix in (".meta.json", ".file-rollback.ndjson"):
                    aux = body.parent / f"{old_sid}{suffix}"
                    if aux.is_file():
                        sessions._replace_id_in(
                            aux, aux.parent / f"{new_sid}{suffix}", old_sid, new_sid)
                sessions._copy_ws_dir(old_sid, new_sid)

                rowd = dict(src)
                rowd["id"] = new_sid
                rowd["user_id"] = uid
                rowd["deleted_at"] = None
                if rowd.get("title") and not rowd.get("custom_title"):
                    rowd["custom_title"] = rowd["title"]
                try:
                    live.execute(insert_sql, sessions._session_values(cols, rowd))
                except sqlite3.Error as e:
                    report["errors"].append(f"写索引失败: {e}")
                    continue
                # 档案登记 + 谱系
                arch.execute(
                    "INSERT OR REPLACE INTO session_archive "
                    "(session_id,edition,owner_uid,payload,first_seen,updated_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (new_sid, edition, uid,
                     json.dumps(rowd, ensure_ascii=False, default=str),
                     stamp, stamp))
                arch.execute(
                    "INSERT INTO copy_lineage "
                    "(copy_id,source_sid,source_uid,target_uid,created_at) "
                    "VALUES (?,?,?,?,?)",
                    (new_sid, old_sid, src.get("user_id"), uid, stamp))
                report["copied"].append(
                    {"title": src.get("title"), "to": uid[:8], "sid": new_sid[:8]})
            live.commit()
            arch.commit()
            try:
                live.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
        except Exception:
            live.rollback()
            raise
        finally:
            try:
                arch.close()
            except Exception:
                pass

        # 3) 同步三个快照
        for uid in uids:
            try:
                snap = sessions.sync_sidebar_snapshot(uid)
                report["snapshots"].append({"uid": uid[:8], "ok": bool(snap)})
            except Exception as e:
                report["errors"].append(f"快照同步失败 {uid[:8]}: {e}")
    finally:
        live.close()

    return report
