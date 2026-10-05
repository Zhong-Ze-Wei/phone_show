"""Run the earliest recovered UI separately, using a copy of current phone data."""

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVISION = "958741d"
PREVIEW_ROOT = PROJECT_ROOT / "logs" / "historical-preview" / REVISION


def prepare_preview() -> None:
    if not PREVIEW_ROOT.exists():
        subprocess.run(["git", "worktree", "add", "--detach", str(PREVIEW_ROOT), REVISION], cwd=PROJECT_ROOT, check=True)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PREVIEW_ROOT, text=True).strip()
    expected = subprocess.check_output(["git", "rev-parse", REVISION], cwd=PROJECT_ROOT, text=True).strip()
    if actual != expected:
        raise ValueError("历史工作目录不是指定的 2026-10-04 恢复版。")
    subprocess.run(["uv", "sync", "--locked", "--no-dev", "--project", str(PREVIEW_ROOT)], check=True)
    if not (PREVIEW_ROOT / "frontend" / "dist" / "index.html").exists():
        npm = shutil.which("npm")
        subprocess.run([npm, "ci"], cwd=PREVIEW_ROOT / "frontend", check=True)
        subprocess.run([npm, "run", "build"], cwd=PREVIEW_ROOT / "frontend", check=True)


def copy_current_data() -> dict:
    source = PROJECT_ROOT / "data" / "phones.sqlite3"
    if not source.is_file():
        raise FileNotFoundError("请先按 README 还原或更新当前手机数据库。")
    target = PREVIEW_ROOT / "data" / "phones.sqlite3"
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as current:
        with closing(sqlite3.connect(target)) as preview:
            current.backup(preview)
            if preview.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("历史预览数据库副本完整性检查失败。")
            counts = {table: preview.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("phones", "raw_snapshots", "image_overrides")}
    metadata = {"revision": REVISION, "version_date": "2026-10-04", "type": "recovered_ui",
        "original_flask_source_available": False, "data": "current_database_copy", "counts": counts}
    (PREVIEW_ROOT / "preview-info.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def serve_preview(port: int) -> None:
    sys.path.insert(0, str(PREVIEW_ROOT))
    os.chdir(PREVIEW_ROOT)
    from dotenv import dotenv_values
    from fastapi import Request
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn
    from phone_assistant.server import create_app
    from phone_assistant.storage import Storage

    for key, value in dotenv_values(PROJECT_ROOT / ".env").items():
        if key.startswith("AIPING_") and value is not None:
            os.environ.setdefault(key, value)
    app = create_app(Storage(PREVIEW_ROOT / "data" / "phones.sqlite3"))

    @app.middleware("http")
    async def disable_old_crawler(request: Request, call_next):
        if request.method == "POST" and request.url.path == "/api/sync":
            return JSONResponse(status_code=409, content={"detail": "这是历史界面对照的数据副本，请在 8501 当前版更新资料，再重启历史预览。"})
        return await call_next(request)

    @app.get("/api/preview-info")
    def preview_info():
        return json.loads((PREVIEW_ROOT / "preview-info.json").read_text(encoding="utf-8"))

    @app.get("/history/", include_in_schema=False)
    def historical_reference():
        return FileResponse(PROJECT_ROOT / "scripts" / "historical_reference.html")

    app.mount("/history/images", StaticFiles(directory=PROJECT_ROOT / "docs" / "ui-reference"), name="historical-images")
    uvicorn.run(app, host="127.0.0.1", port=port, http="h11", ws="none")


def main() -> None:
    parser = argparse.ArgumentParser(description="并行运行 2026-10-04 恢复版，并查看 2025 原界面截图。")
    parser.add_argument("--port", type=int, default=8502)
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口必须为 1 到 65535。")
    if args.serve:
        serve_preview(args.port)
        return
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", args.port)) == 0:
            parser.error(f"端口 {args.port} 已被占用；先停止该预览，或用 --port 指定空闲端口。")
    prepare_preview()
    metadata = copy_current_data()
    print(f"2026-10-04 恢复版：{REVISION}；当前资料副本 {metadata['counts']['phones']} 条。", flush=True)
    print(f"可运行恢复版 http://127.0.0.1:{args.port}/ | 2025 原版截图 http://127.0.0.1:{args.port}/history/", flush=True)
    python = PREVIEW_ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    os.execv(str(python), [str(python), str(Path(__file__).resolve()), "--serve", "--port", str(args.port)])


if __name__ == "__main__":
    main()
