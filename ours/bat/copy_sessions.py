"""Copy Sunflower's sessions to sunflower 2 as independent copies.

Both accounts keep their own copy afterwards. Requires the WorkBuddy
client to be fully quit (the tool refuses to run while it holds the DB).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 仓库根

from wbswitch import paths, sessions

SRC = "21bd0bce-e13d-48e9-8f68-1e0c20b81168"   # Sunflower
TGT = "db3237c3-dbf6-47fd-b800-81f65b00c255"   # sunflower 2 (current login)

paths.set_edition("cn")   # this machine runs the CN edition


def progress(i, n, sid):
    print(f"  [{i}/{n}] {sid[:8]}...", flush=True)


def main():
    print("Copying sessions: Sunflower to sunflower 2 (independent copies)")
    print()
    rep = sessions.copy_sessions(SRC, TGT, on_progress=progress)
    print()
    print(f"RESULT: copied={rep.copied} failed={rep.failed} "
          f"skipped_deleted={rep.skipped_deleted} missing_body={rep.missing_body}")
    if rep.backup_tag:
        print(f"Backup created: {rep.backup_tag}")
    for e in rep.errors:
        print(f"ERROR: {e}")
    print()
    if rep.ok():
        print("DONE - success. You can reopen WorkBuddy now.")
        return 0
    print("DONE - finished with errors. Screenshot this window.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
