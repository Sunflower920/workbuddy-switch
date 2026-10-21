#!/usr/bin/env python3
"""smart_merge —— 内容感知合并（WorkBuddy-Switch 复刻版自有模块，不侵入引擎）。

补上游 copy 的同根源盲区：上游只认谱系不认内容，反向复制会被同根源防线
全部跳过。本模块对源账号每条会话，先与目标账号的同根源会话比内容
（正文大小 + updated_at，与引擎 dedupe 的 _rank 同一把尺子），仅在源
更新时才复制进目标；复制后联动引擎 dedupe 让更新版胜出、旧原版进隔离区。

安全模型（与引擎一致）：
- dry-run 只读（除 capture 归档快照，幂等）
- 真实运行前自动全量备份；dedupe 自带二次备份
- 客户端运行中拒绝写库
- 逐会话独立处理，单条失败不影响其他
- 重复执行安全：等价内容不会二次复制（排名不严格大于就跳过）
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import uuid
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]  # 仓库根（wbswitch/ 所在）
sys.path.insert(0, str(ENGINE_DIR))

from wbswitch import client as client_mod, engine, paths, profiles, sessions  # noqa: E402

# 与引擎 _copy_sessions_bound 完全一致的 INSERT 字面量
_INSERT_30 = ("INSERT OR IGNORE INTO sessions VALUES ("
              "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
              "?,?,?,?,?,?,?,?,?,?)")
_INSERT_40 = ("INSERT OR IGNORE INTO sessions VALUES ("
              "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,"
              "?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
_EDGE_SQL = ("INSERT OR REPLACE INTO edge_sync_mapping"
             "(session_id, conversation_id, msg_channel, created_at)"
             " VALUES (?, ?, ?, ?)")
_ARCHIVE_SQL = ("INSERT INTO session_archive"
                "(session_id, owner_uid, payload, first_seen, updated_at, edition)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(session_id, edition) DO UPDATE SET"
                " payload = excluded.payload, updated_at = excluded.updated_at")
_LINEAGE_SQL = ("INSERT INTO copy_lineage"
                "(copy_id, source_sid, source_uid, target_uid, created_at)"
                " VALUES (?, ?, ?, ?, ?)")


def _rank(sid: str, live_rows: dict) -> tuple:
    """与引擎 dedupe._rank 同一把尺子：正文大小优先，其次 updated_at，再 sid。"""
    body = paths.find_session_body(sid)
    size = body.stat().st_size if body else -1
    try:
        upd = int(live_rows.get(sid, {}).get("updated_at") or 0)
    except (TypeError, ValueError):
        upd = 0
    return (size, upd, sid)


def _content_key(sid: str, live_rows: dict) -> tuple:
    """复制决策专用：只看（正文大小, 更新时间），不含 sid 决胜。

    大小与更新时间都一样 = 内容等价，跳过（sid 字符串决胜会把等价对
    随机判成"源更新"，造成无意义复制；sid 决胜只留给引擎 dedupe 内部）。
    """
    return _rank(sid, live_rows)[:2]


def _title_of(sid: str, live_rows: dict, titles: dict) -> tuple:
    """会话的（标题, 自定义标题）——客户端行优先，档案快照兜底。"""
    row = live_rows.get(sid)
    if row is not None:
        return (str(row.get("title") or ""), str(row.get("custom_title") or ""))
    return (titles.get(sid) or "", "")


def _titles(arch: sqlite3.Connection) -> dict:
    out = {}
    try:
        for sid, payload in arch.execute(
                "SELECT session_id, payload FROM session_archive").fetchall():
            try:
                out[str(sid)] = (json.loads(payload).get("title") or "")[:40]
            except Exception:
                out[str(sid)] = ""
    except sqlite3.Error:
        pass
    return out


def smart_merge(source_uid: str, target_uid: str | None = None, *,
                dry_run: bool = False, dedupe: bool = True,
                on_progress=None) -> dict:
    paths.set_edition("cn")  # 本机为国内版

    src_acc = profiles.find_by_uid(source_uid)
    if src_acc is None:
        return {"errors": [f"源账号不存在: {source_uid}"]}
    if not target_uid:
        target_uid = profiles.read_login_uid() or profiles.live_uid()
    if not target_uid:
        return {"errors": ["无法确定目标账号（当前没有登录态）"]}
    if source_uid == target_uid:
        return {"errors": ["源账号与目标账号相同"]}
    tgt_acc = profiles.find_by_uid(target_uid)
    if tgt_acc is not None and tgt_acc.edition != src_acc.edition:
        return {"errors": [
            f"跨版本不支持：{src_acc.name}({src_acc.edition}) -> "
            f"{tgt_acc.name}({tgt_acc.edition})"]}

    if not dry_run and client_mod.is_running():
        return {"errors": [
            "WorkBuddy 正在运行：合并需要写会话数据库与云端映射，请先结束客户端"]}

    # 最新客户端状态入归档（与引擎 copy/dedupe 流程一致；幂等）
    sessions.capture()
    arch = sessions._conn()
    parent = sessions._lineage_parent_map(arch)
    owner_map = sessions.owners()
    titles = _titles(arch)

    live = sessions._live_conn()
    try:
        cur = live.execute("SELECT * FROM sessions")
        lcols = [d[0] for d in cur.description]
        live_rows = {d["id"]: d for d in
                     (dict(zip(lcols, r)) for r in cur.fetchall())}
        cols = [r[1] for r in live.execute("PRAGMA table_info(sessions)")]
        n_cols = sessions._match_sessions_schema(cols)
        if n_cols is None:
            return {"errors": [
                f"客户端 sessions 表 schema 未识别（{len(cols)} 列）—— 请反馈"]}
        insert_sql = _INSERT_30 if n_cols == 30 else _INSERT_40
    except sqlite3.Error as e:
        live.close()
        arch.close()
        return {"errors": [f"读取客户端数据库失败: {e}"]}

    # 目标账号：root -> 排名最高的同根源会话
    tgt_best: dict[str, str] = {}
    for sid, owner in owner_map.items():
        if owner == target_uid:
            root = sessions._root_of(sid, parent)
            if root not in tgt_best or \
                    _rank(sid, live_rows) > _rank(tgt_best[root], live_rows):
                tgt_best[root] = sid

    plan = []
    for sid in sorted(s for s, o in owner_map.items() if o == source_uid):
        row = live_rows.get(sid) or {}
        if row.get("deleted_at"):
            plan.append((sid, "skip", "源会话已删除，不复制"))
            continue
        if paths.find_session_body(sid) is None:
            plan.append((sid, "skip", "找不到正文文件"))
            continue
        root = sessions._root_of(sid, parent)
        tgt_sid = tgt_best.get(root)
        if tgt_sid is None:
            plan.append((sid, "copy", "目标没有同根源会话，纯新增"))
            continue
        s_size = _rank(sid, live_rows)[0]
        t_size = _rank(tgt_sid, live_rows)[0]
        if s_size > t_size:
            plan.append((sid, "copy",
                         f"源正文更大（{s_size // 1024}KB > {t_size // 1024}KB）"))
        elif s_size == t_size:
            # 同大小：标题/自定义标题变了（如改名）才值得复制；
            # 仅 updated_at 变化（打开过、未改内容）视为无变化，跳过
            if _title_of(sid, live_rows, titles) != \
                    _title_of(tgt_sid, live_rows, titles):
                plan.append((sid, "copy", "标题变化（正文同大小）"))
            else:
                plan.append((sid, "skip", "内容与标题均一致"))
        else:
            plan.append((sid, "skip", "目标正文更大"))

    report = {
        "source_uid": source_uid, "target_uid": target_uid,
        "dry_run": dry_run, "planned": len(plan),
        "items": [{"sid": sid, "title": titles.get(sid, ""),
                   "action": act, "reason": why}
                  for sid, act, why in plan],
        "copied": 0, "failed": 0, "backup_tag": "", "dedupe": None,
        "errors": [],
    }

    to_copy = [p for p in plan if p[1] == "copy"]
    if dry_run or not to_copy:
        live.close()
        arch.close()
        return report

    # ---- 备份：即将写客户端数据库，先留全量退路 ----
    info = engine.create_backup(target_uid, source_uid, "before-smart-merge")
    report["backup_tag"] = info.tag

    edge_conn = None
    edge_db = paths.edge_sync_db_path()
    if edge_db is not None:
        try:
            edge_conn = sqlite3.connect(str(edge_db))
            edge_conn.execute("PRAGMA busy_timeout=8000")
            if not edge_conn.execute(
                    "SELECT 1 FROM sqlite_master"
                    " WHERE type='table' AND name='edge_sync_mapping'").fetchone():
                edge_conn.close()
                edge_conn = None
        except sqlite3.Error:
            edge_conn = None

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    edition = paths.current_edition()
    copied = failed = 0
    try:
        for i, (sid, _act, _why) in enumerate(to_copy, 1):
            if on_progress:
                on_progress(i, len(to_copy), sid)
            rowd = dict(live_rows[sid])
            body = paths.find_session_body(sid)
            new_sid = str(uuid.uuid4())
            # ① 正文（内容里的旧 id 全部替换）
            if not sessions._replace_id_in(
                    body, body.parent / f"{new_sid}.jsonl", sid, new_sid):
                failed += 1
                report["errors"].append(f"{sid[:8]}: 正文复制失败")
                continue
            # ② 附属文件
            for suffix in (".meta.json", ".file-rollback.ndjson"):
                aux = body.parent / f"{sid}{suffix}"
                if aux.is_file():
                    sessions._replace_id_in(
                        aux, aux.parent / f"{new_sid}{suffix}", sid, new_sid)
            # ③ 工作区目录
            sessions._copy_ws_dir(sid, new_sid)
            # ④ 客户端索引：新行（新 id + 目标 user_id，其余字段原样）
            rowd["id"] = new_sid
            rowd["user_id"] = target_uid
            try:
                live.execute(insert_sql, [rowd.get(c) for c in cols])
            except sqlite3.Error as e:
                failed += 1
                report["errors"].append(f"{sid[:8]}: 写入会话索引失败（{e}）")
                continue
            # ⑤ 云端映射
            if edge_conn is not None:
                try:
                    edge_conn.execute(
                        _EDGE_SQL,
                        (new_sid, new_sid, f"convmsg:{target_uid}",
                         int(time.time() * 1000)))
                except sqlite3.Error as e:
                    report["errors"].append(
                        f"{new_sid[:8]}: 云端映射注册失败（{e}）")
            # ⑥ 档案登记 + 谱系（新副本的 root 经既有谱系链回溯到原版）
            arch.execute(
                _ARCHIVE_SQL,
                (new_sid, target_uid,
                 json.dumps(rowd, ensure_ascii=False, default=str),
                 stamp, stamp, edition))
            arch.execute(
                _LINEAGE_SQL, (new_sid, sid, source_uid, target_uid, stamp))
            copied += 1
        live.commit()
        arch.commit()
        if edge_conn is not None:
            edge_conn.commit()
        try:
            live.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
    finally:
        try:
            live.close()
        except Exception:
            pass
        try:
            arch.close()
        except Exception:
            pass
        if edge_conn is not None:
            try:
                edge_conn.close()
            except Exception:
                pass

    report["copied"] = copied
    report["failed"] = failed

    # ---- 联动 dedupe：同根源组内保留排名最高（即刚复制的更新版），
    #      旧原版进可恢复隔离区；dedupe 自带二次全量备份 ----
    # 注意：dedupe 要移动文件，托管 Python 带安全删除 shim 可能拦截；
    # 批处理流程改用引擎 exe 的 dedupe（无 shim）时传 --no-dedupe。
    if copied and dedupe:
        try:
            rep = sessions.dedupe_sessions(target_uid)
            report["dedupe"] = {
                "groups": rep.groups, "kept": rep.kept, "removed": rep.removed,
                "backup_tag": rep.backup_tag, "quarantine": rep.quarantine,
                "errors": rep.errors,
            }
        except Exception as e:  # dedupe 失败不抹掉已成功的复制
            report["errors"].append(f"dedupe 失败: {e}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(
        description="内容感知合并：仅当源账号会话比目标同根源会话更新时才复制并入")
    ap.add_argument("--source", required=True, help="源账号 uid")
    ap.add_argument("--target", default="",
                    help="目标账号 uid（默认当前登录账号）")
    ap.add_argument("--dry-run", action="store_true", help="只报告计划，不写入")
    ap.add_argument("--no-dedupe", action="store_true",
                    help="复制后不联动 dedupe（由调用方用引擎 exe 执行，"
                         "避开托管 Python 的安全删除 shim）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    def progress(i, n, sid):
        print(f"  [{i}/{n}] copying {sid[:8]}...", flush=True)

    rep = smart_merge(args.source, args.target or None,
                      dry_run=args.dry_run, dedupe=not args.no_dedupe,
                      on_progress=progress)

    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
        return 0 if not rep["errors"] else 1

    tag = "[dry-run] " if rep["dry_run"] else ""
    n_copy = sum(1 for it in rep["items"] if it["action"] == "copy")
    n_skip = rep["planned"] - n_copy
    print(f"\n{tag}planned={rep['planned']} to_copy={n_copy} "
          f"skipped={n_skip} copied={rep['copied']} failed={rep['failed']}")
    for it in rep["items"]:
        if it["action"] == "copy":
            print(f"  [COPY] {it['title'] or it['sid'][:8]}  ({it['reason']})")
    if rep["backup_tag"]:
        print(f"  backup: {rep['backup_tag']}")
    if rep["dedupe"]:
        d = rep["dedupe"]
        print(f"  dedupe: {d['groups']} groups, removed {d['removed']}, "
              f"quarantine {d['quarantine']}")
    for e in rep["errors"]:
        print(f"  ERROR: {e}")
    print("\nDONE." if not rep["errors"] else "\nDONE with errors.")
    return 0 if not rep["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
