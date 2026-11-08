"""smart-merge：内容感知合并（复刻版自有功能，已收编进引擎）。

补 copy 的同根源盲区：copy 只认谱系不认内容，反向复制会被同根源防线
全部跳过。本模块对源账号每条会话，先与目标账号的同根源会话比内容
（正文大小优先，同大小比标题），仅在源更新时才复制进目标；复制后
联动 dedupe 让更新版胜出、旧原版进隔离区。

安全模型（与引擎其他写操作一致）：
- dry-run 只读（除 capture 归档快照，幂等）
- 真实运行前自动全量备份；dedupe 自带二次备份
- 客户端运行中拒绝写库
- 逐会话独立处理，单条失败不影响其他
- 重复执行安全：等价内容不会二次复制
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid

from . import client as client_mod
from . import engine, paths, profiles, sessions

# 与 _copy_sessions_bound 完全一致的 INSERT 字面量
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


def _title_of(sid: str, live_rows: dict, titles: dict) -> tuple:
    """会话的（标题, 用户真正改名后的标题）。

    复制副本时会把 title 钉进 custom_title（防客户端发消息重算标题）。
    这种"钉住"不是用户改名：custom_title == title 一律视为未改名。
    否则 _title_of(原创)=(X,"") 永远 != _title_of(副本)=(X,X)，
    每轮同步都会误判"标题变化"→ 同大小也复制 → 无限增殖
    （11/6 事故：同一会话每 3 分钟增殖一条，累计 13 份）。
    """
    row = live_rows.get(sid)
    if row is not None:
        title = str(row.get("title") or "")
        custom = str(row.get("custom_title") or "")
        if custom and custom == title:
            custom = ""
        return (title, custom)
    return (titles.get(sid) or "", "")


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

    # 目标账号：同名会话（去掉空白/大小写差异）→ (sid, updated_at)。
    # 用于拦住"谱系不同但其实是同一段对话"的回灌：早期副本没登记 parent，
    # 只按 root 判断会把更旧的版本当成新会话复制进来，于是列表里一份变两份。
    def _title_key(t: object) -> str:
        return " ".join(str(t or "").split()).lower()

    tgt_titles: dict[str, tuple[str, int]] = {}
    for sid, owner in owner_map.items():
        if owner != target_uid:
            continue
        row = live_rows.get(sid) or {}
        if row.get("deleted_at"):
            continue
        key = _title_key(row.get("title"))
        if not key:
            continue
        try:
            upd = int(row.get("updated_at") or 0)
        except (TypeError, ValueError):
            upd = 0
        if key not in tgt_titles or upd > tgt_titles[key][1]:
            tgt_titles[key] = (sid, upd)

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
            # 谱系上没有对应会话，但目标可能已有同名对话的新版本
            # （早期副本未登记谱系）。目标那份更新 → 说明本地是更新的，
            # 把旧的复制进来只会多一条同名会话，跳过。
            peer = tgt_titles.get(_title_key(row.get("title")))
            if peer and peer[0] != sid:
                try:
                    s_upd = int(row.get("updated_at") or 0)
                except (TypeError, ValueError):
                    s_upd = 0
                if peer[1] >= s_upd:
                    plan.append((sid, "skip", "目标有同名且更新的会话"))
                    continue
            plan.append((sid, "copy", "目标没有同根源会话，纯新增"))
            continue
        s_size = _rank(sid, live_rows)[0]
        t_size = _rank(tgt_sid, live_rows)[0]
        # 源本身是复制品且不比目标大 → 绝不回灌，否则 A→B→A 来回复制，
        # 每轮多一份（11/6 事故的放大路径之一）
        if sid in parent and s_size <= t_size:
            plan.append((sid, "skip", "源本身是副本且不比目标大"))
            continue
        if s_size > t_size:
            plan.append((sid, "copy",
                         f"源正文更大（{s_size // 1024}KB > {t_size // 1024}KB）"))
        elif s_size == t_size:
            # 同大小一律不复制：标题差异最常见的来源就是"副本把 title 钉进
            # custom_title"，把它当变化会每轮复制一份（11/6 事故：同一会话
            # 每 3 分钟增殖一条）。确需同步改名请用「复制会话」手动按钮。
            diff = _title_of(sid, live_rows, titles) != \
                _title_of(tgt_sid, live_rows, titles)
            plan.append((sid, "skip",
                         "标题不同但正文同大小，不复制" if diff
                         else "内容与标题均一致"))
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
    new_sids: list[str] = []
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
            # 标题钉进 custom_title（用户改名槽）：客户端只重算 title（自动
            # 生成槽），不锁的副本在新消息触发重算时会被改写，表现为"改名了"
            if rowd.get("title") and not rowd.get("custom_title"):
                rowd["custom_title"] = rowd["title"]
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
            new_sids.append(new_sid)
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
    if copied and dedupe:
        try:
            rep = sessions.dedupe_sessions(target_uid)
            report["dedupe"] = {
                "groups": rep.groups, "kept": rep.kept, "removed": rep.removed,
                "backup_tag": rep.backup_tag, "quarantine": rep.quarantine,
                "errors": rep.errors,
            }
            # 竞态：复制期间客户端启动了 → 去重被跳过 → 新旧副本并存成"重复会话"
            # （11/6 15:05 事故）。回滚本次复制的可见性，宁可这次不合并，
            # 也不给用户看重复。正文与谱系保留，客户端关闭后可重跑。
            if rep.errors and any("正在运行" in str(e) for e in rep.errors):
                rolled = sessions.soft_delete_sessions(new_sids)
                report["rolled_back"] = rolled
                report["errors"].append(
                    "合并途中 WorkBuddy 启动了，去重无法执行；"
                    f"本次复制的 {rolled} 条已回滚（正文保留），请关闭客户端后重试")
        except Exception as e:  # dedupe 失败不抹掉已成功的复制
            report["errors"].append(f"dedupe 失败: {e}")

    # ---- 客户端侧边栏快照同步：客户端启动时先用快照渲染列表，不补的话
    #      会出现「库里已经有、用户切过去看不到」（11/6 事故）----
    if copied:
        try:
            report["sidebar"] = sessions.sync_sidebar_snapshot(target_uid)
        except Exception as e:
            report["errors"].append(f"侧边栏快照同步失败: {e}")
    return report
