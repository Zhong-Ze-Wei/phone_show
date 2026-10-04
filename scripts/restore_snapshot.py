"""首次克隆后还原版本快照；已有数据库不会被覆盖。"""

import gzip
import hashlib
import json
import shutil
import zlib
from pathlib import Path


def restore_snapshot(project: Path) -> None:
    database = project / "data" / "phones.sqlite3"
    if database.exists():
        print("已有 data/phones.sqlite3，保留现有数据。")
        return
    snapshot_dir = project / "data" / "snapshots"
    snapshot = snapshot_dir / "phones.sqlite3.gz"
    manifest = json.loads((snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    if hashlib.sha256(snapshot.read_bytes()).hexdigest() != manifest["compressed_sha256"]:
        raise ValueError("数据库快照校验失败；未写入数据库，请重新获取仓库文件。")
    database.parent.mkdir(parents=True, exist_ok=True)
    target = database.open("xb")
    try:
        with target, gzip.open(snapshot, "rb") as source:
            shutil.copyfileobj(source, target)
        if database.stat().st_size != manifest["database_bytes"] or hashlib.sha256(database.read_bytes()).hexdigest() != manifest["database_sha256"]:
            raise ValueError("还原后的数据库校验失败，请重新获取仓库文件。")
    except (OSError, EOFError, zlib.error, ValueError):
        # xb 创建成功后只清理本次文件；并发创建的既有数据库不会进入此分支。
        database.unlink()
        raise
    print(f"已还原 {manifest['phone_count']} 条机型配置及 {manifest['raw_snapshot_count']} 条原始快照；原采集时间保持不变。")


if __name__ == "__main__":
    restore_snapshot(Path(__file__).resolve().parents[1])
