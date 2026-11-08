# -*- coding: utf-8 -*-
"""文件操作的安全封装。

Windows 上 WorkBuddy 客户端运行时会**字节锁定**它正在用的文件
（SQLite 的 `-shm` / `-wal` 最典型），此时 `shutil.copy2` 直接抛
`[WinError 33] 另一个程序已锁定文件的一部分，进程无法访问。`，
整个换号流程就会中止在半路。

这里统一收敛三类操作，避免每个模块各写一套：
- `copy_file` / `replace_atomic`：加锁重试（客户端释放锁是毫秒级的）；
- `snapshot_sqlite`：活动数据库的正确快照方式（在线备份，绝不复制 `-shm`）；
- `copy_tree`：逐文件容错复制，个别文件被占用只跳过并上报，不中断整体。

任何一处都不要"直接 copy 一个正在被客户端使用的文件"。
"""

from __future__ import annotations

import errno
import os
import shutil
import sqlite3
import time
from pathlib import Path

# Windows: 5=拒绝访问 32=共享冲突 33=字节锁冲突 1224=用户映射中的打开文件
_LOCK_WINERRORS = {5, 32, 33, 1224}
_LOCK_ERRNOS = {errno.EACCES, errno.EBUSY, errno.EAGAIN}


def is_lock_error(exc: BaseException) -> bool:
    """是否为"文件被占用"类错误（值得重试，而不是真的坏了）。"""
    if isinstance(exc, PermissionError):
        return True
    winerror = getattr(exc, "winerror", None)
    if winerror in _LOCK_WINERRORS:
        return True
    return getattr(exc, "errno", None) in _LOCK_ERRNOS


def retry_locked(fn, *args, attempts: int = 10, first_delay: float = 0.05,
                 max_delay: float = 0.4, **kwargs):
    """执行 fn，遇到"文件被占用"时退避重试；非占用类错误立即抛出。"""
    attempts = max(1, int(attempts))
    delay = first_delay
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except OSError as e:
            if not is_lock_error(e):
                raise
            last = e
            if i == attempts - 1:
                break
            time.sleep(delay)
            delay = min(max_delay, delay * 2)
    assert last is not None
    raise last


def copy_file(src: Path, dst: Path, *, attempts: int = 10) -> None:
    """复制单个文件（带占用重试，保留元数据）。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    retry_locked(shutil.copy2, str(src), str(dst), attempts=attempts)


def replace_atomic(tmp: Path, dst: Path, *, attempts: int = 12) -> None:
    """原子替换（带占用重试）——客户端可能短暂持有目标文件。"""
    retry_locked(os.replace, str(tmp), str(dst), attempts=attempts)


def copy_tree(src: Path, dst: Path, *, attempts: int = 5) -> list[str]:
    """逐文件容错复制目录树。

    返回被跳过的文件（相对路径）。被客户端占用且重试后仍失败的文件
    不中断整体流程 —— 备份里少一个 storage 缓存文件，远好过整个换号失败。
    """
    skipped: list[str] = []
    src = Path(src)
    dst = Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target_root = dst if rel == "." else dst / rel
        for name in files:
            s = Path(root) / name
            d = target_root / name
            try:
                d.parent.mkdir(parents=True, exist_ok=True)
                copy_file(s, d, attempts=attempts)
            except OSError:
                skipped.append(str(Path(rel) / name))
    return skipped


def _snapshot_online(src_db: Path, dst_db: Path) -> None:
    """用 SQLite 在线备份 API 做一致性快照（WAL 内容合并进单文件）。"""
    dst_db.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst_db.with_name(dst_db.name + ".tmp")
    tmp.unlink(missing_ok=True)

    src_conn = sqlite3.connect(
        "file:" + Path(src_db).as_posix() + "?mode=ro", uri=True, timeout=8
    )
    try:
        dst_conn = sqlite3.connect(str(tmp), timeout=8)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    replace_atomic(tmp, dst_db)


def _snapshot_by_copy(src_db: Path, dst_db: Path) -> None:
    """兜底：文件级复制。复制 db + -wal（一致性所需），**跳过 -shm**。

    `-shm` 只是内存映射的共享状态，备份里毫无用处，而它恰恰是客户端
    字节锁的持有者 —— 复制它必然 WinError 33。
    """
    copy_file(src_db, dst_db)
    for suffix in ("-wal",):
        s = Path(str(src_db) + suffix)
        if s.exists():
            try:
                copy_file(s, Path(str(dst_db) + suffix))
            except OSError:
                pass


def snapshot_sqlite(src_db: Path, dst_db: Path, *, attempts: int = 4) -> None:
    """安全快照一个**可能正在被客户端使用**的 SQLite 库。

    优先在线备份（不会碰到 `-shm` 的锁）；在线备份失败（例如库被独占）
    再退化为文件复制。两条路都失败才抛错。
    """
    last: BaseException | None = None
    for i in range(max(1, attempts)):
        try:
            _snapshot_online(src_db, dst_db)
            return
        except (OSError, sqlite3.Error) as e:
            last = e
            time.sleep(0.08 * (i + 1))
    try:
        _snapshot_by_copy(src_db, dst_db)
    except OSError:
        if last is not None:
            raise last
        raise


def describe(exc: BaseException) -> str:
    """给用户看的简短错误描述（不带 traceback）。"""
    text = str(exc).strip().replace("\n", " ")
    return text[:200] if text else exc.__class__.__name__
