"""校验用驱动：强制 cn 版本上下文，dry-run 验证 copy 全链路（不写客户端库）。"""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wbswitch import paths, sessions, client, profiles

paths.set_edition("cn")
print("当前版本:", paths.current_edition(), "| 数据根:", paths.workbuddy_dir())
print("客户端库:", paths.db_path(), "存在:", paths.db_path().exists())
print("云端映射库:", paths.edge_sync_db_path())

# 校验专用：临时绕过“客户端运行中”检查（dry_run=True 不会写客户端数据库）
client.is_running = lambda: False

src = "21bd0bce-e13d-48e9-8f68-1e0c20b81168"   # Sunflower
tgt = "db3237c3-dbf6-47fd-b800-81f65b00c255"   # sunflower 2（当前登录）
rep = sessions.copy_sessions(src, tgt, dry_run=True)

print("\n=== copy dry-run 报告 ===")
print(json.dumps({
    "source_uid": rep.source_uid,
    "target_uid": rep.target_uid,
    "planned": rep.planned,
    "would_copy": rep.would_copy,
    "skipped_exists": rep.skipped_exists,
    "skipped_same_root": rep.skipped_same_root,
    "skipped_deleted": rep.skipped_deleted,
    "missing_body": rep.missing_body,
    "failed": rep.failed,
    "errors": rep.errors,
}, ensure_ascii=False, indent=2))
