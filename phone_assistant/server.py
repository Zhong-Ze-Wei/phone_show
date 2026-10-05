"""本地 FastAPI 服务，同时提供编译后的 React 页面。"""

import argparse
import json
import logging
import threading
from pathlib import Path
from typing import Annotated, Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from openai import APIConnectionError, APIStatusError
from pydantic import BaseModel, Field, field_validator, model_validator

from phone_assistant.advisor import explain
from phone_assistant.assistant import api_error_message
from phone_assistant.chat import ChatStreamingResponse, Persona, prepare_chat_context, stream_chat
from phone_assistant.config import PROJECT_ROOT, Settings
from phone_assistant.recommendation import (
    PRIORITIES, Preferences, family_metadata, family_variants, filter_phones, variant_record,
)
from phone_assistant.storage import Storage

logger = logging.getLogger(__name__)


class FilterRequest(BaseModel):
    budget_min: float = Field(default=0, ge=0, le=10_000_000, allow_inf_nan=False)
    budget_max: float | None = Field(default=None, gt=0, le=10_000_000, allow_inf_nan=False)
    brands: list[str] = Field(default_factory=list, max_length=100)
    os: Literal["all", "Android", "iOS", "HarmonyOS"] = "all"
    priorities: list[Literal["daily", "gaming", "camera", "battery"]] = Field(default_factory=list, max_length=4)
    compact: bool = False
    min_storage: float = Field(default=0, ge=0, le=4096, allow_inf_nan=False)
    include_history: bool = False
    query: str = Field(default="", max_length=160)
    sort: Literal["recommended", "newest", "match", "price_asc", "price_desc"] = "newest"
    purchase_mode: Literal["new", "used"] = "new"

    @model_validator(mode="after")
    def validate_budget(self):
        if self.budget_max is not None and self.budget_max < self.budget_min:
            raise ValueError("最高预算不能低于最低预算。")
        return self

    def preferences(self) -> Preferences:
        return Preferences(**self.model_dump())


class ExplainRequest(BaseModel):
    ids: list[str] = Field(min_length=1)
    preferences: FilterRequest = Field(default_factory=FilterRequest)
    question: str = Field(default="", max_length=1000)


class CompareRequest(BaseModel):
    ids: list[str] = Field(min_length=1)
    preferences: FilterRequest = Field(default_factory=FilterRequest)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1600)
    history: list[ChatMessage] = Field(default_factory=list, max_length=12)
    selected_ids: list[str] = Field(default_factory=list)
    preferences: FilterRequest | None = None
    persona: Persona = "tech"

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("请输入手机选购或技术问题。")
        return value

class SyncRequest(BaseModel):
    mode: Literal["current"] = "current"


class SyncJob:
    """本机单一采集任务，重复点击返回同一个进度。"""

    def __init__(self, storage: Storage):
        self.storage = storage
        self.lock = threading.Lock()
        self.status = {"state": "idle", "stage": "等待更新", "discovered": 0, "completed": 0, "failed": 0, "message": ""}

    def snapshot(self) -> dict:
        with self.lock:
            return self.status.copy()

    def update(self, event: dict) -> None:
        with self.lock:
            self.status.update(event)
            self.status["state"] = "running"

    def start(self) -> dict:
        with self.lock:
            if self.status["state"] == "running":
                return self.status.copy()
            self.status = {"state": "running", "stage": "发现当前在售机型", "discovered": 0, "completed": 0, "failed": 0, "message": "采集完成后自动清洗与校验"}
            status = self.status.copy()
        threading.Thread(target=self.run, name="phone-sync", daemon=True).start()
        return status

    def run(self) -> None:
        from phone_assistant.pipeline import run_sync

        try:
            report = run_sync(storage=self.storage, progress=self.update, force=True)
        except Exception:
            # 后台任务必须收敛到失败状态并记录堆栈，避免界面永久显示正在更新。
            logger.exception("手机数据更新失败")
            with self.lock:
                self.status.update(state="failed", stage="更新失败", message="更新失败，原数据已保留。请查看日志或重新更新。")
            return
        with self.lock:
            unresolved = report.get("unresolved_errors", report.get("errors", []))
            partial = report.get("status") != "complete"
            message = "已完成采集、清洗与质量校验。"
            if partial:
                message = "有效数据已更新，覆盖仍有缺口；详情见数据质量。"
                if unresolved:
                    message += f" {len(unresolved)} 个请求待重试。"
            self.status.update(state="completed", stage="部分完成" if partial else "更新完成", report=report, message=message)


def create_app(storage: Storage | None = None, settings: Settings | None = None, frontend_dir: Path | None = None) -> FastAPI:
    storage = storage or Storage()
    settings = settings or Settings.from_env()
    job = SyncJob(storage)
    app = FastAPI(title="挑一部 · 手机选购工作台", version="0.2.0")
    app.state.storage = storage
    app.state.sync_job = job

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, error: RequestValidationError):
        # 不回传原始输入，避免 NaN/Infinity 让校验错误本身无法编码为 JSON。
        detail = [{key: item[key] for key in ("type", "loc", "msg")} for item in error.errors()]
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.get("/api/meta")
    def meta():
        phones = storage.list_phones()
        common_brands = ["小米", "红米", "华为", "荣耀", "OPPO", "vivo", "iQOO", "一加", "realme", "苹果", "三星", "魅族", "摩托罗拉", "红魔"]
        brands = {phone["brand"] for phone in phones if phone.get("brand")}
        ordered = [brand for brand in common_brands if brand in brands] + sorted(brands.difference(common_brands))
        return {"brands": ordered, "summary": storage.summary(), "priorities": PRIORITIES, "model": settings.model, "api_configured": bool(settings.api_key and settings.api_key != "your-api-key")}

    @app.post("/api/filter")
    @app.post("/api/recommend")
    def filtered_phones(request: FilterRequest):
        return filter_phones(storage.list_phones(), request.preferences())

    @app.get("/api/phones/{phone_id}")
    def detail(phone_id: str):
        phone = storage.get_phone(phone_id)
        if phone is None:
            raise HTTPException(status_code=404, detail="没有找到这款手机。")
        return {"phone": phone}

    @app.get("/api/phones/{phone_id}/variants")
    def variants(phone_id: str, filters: Annotated[FilterRequest, Query()]):
        phone = storage.get_phone(phone_id)
        if phone is None:
            raise HTTPException(status_code=404, detail="没有找到这款手机。")
        key = phone.get("family_key") or phone["id"]
        members = [record for record in storage.list_phones() if (record.get("family_key") or record["id"]) == key]
        preferences = filters.preferences()
        metadata = family_metadata(members, preferences)
        return {"phones": [{**variant_record(record, preferences), **metadata} for record in family_variants(members, preferences)],
            "family_key": key, "family_name": metadata["family_name"]}

    @app.post("/api/compare")
    def comparison(request: CompareRequest):
        preferences = request.preferences.preferences()
        phones = []
        for phone_id in dict.fromkeys(request.ids):
            phone = storage.get_phone(phone_id)
            if phone is None:
                raise HTTPException(status_code=404, detail="对比机型不存在，请重新选择。")
            phones.append(variant_record(phone, preferences))
        return {"phones": phones}

    @app.post("/api/explain")
    def advice(request: ExplainRequest):
        phones = [storage.get_phone(phone_id) for phone_id in dict.fromkeys(request.ids)]
        if any(phone is None for phone in phones):
            raise HTTPException(status_code=404, detail="候选手机已不存在，请重新选择。")
        try:
            return explain(phones, request.preferences.preferences(), request.question, settings)
        except (APIStatusError, APIConnectionError) as error:
            raise HTTPException(status_code=502, detail=api_error_message(error)) from None
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None

    @app.post("/api/chat")
    def chat(request: ChatRequest):
        preferences = request.preferences.preferences() if request.preferences is not None else Preferences()
        try:
            context = prepare_chat_context(storage, request.selected_ids, preferences, request.persona)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from None
        try:
            settings.require_api_key()
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from None
        return ChatStreamingResponse(
            stream_chat(context, preferences, request.message, [item.model_dump() for item in request.history], settings),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/quality")
    def quality():
        phones = storage.list_phones()
        issues = [{"id": phone["id"], "name": phone["name"], **issue} for phone in phones for issue in phone.get("issues", [])]
        latest_report = PROJECT_ROOT / "data" / "reports" / "latest_sync.json"
        report = json.loads(latest_report.read_text(encoding="utf-8")) if latest_report.exists() else None
        official_path = PROJECT_ROOT / "data" / "reports" / "latest_official.json"
        official_report = json.loads(official_path.read_text(encoding="utf-8")) if official_path.exists() else None
        official_coverage = (report or {}).get("official_coverage")
        if not official_coverage and official_report:
            official_coverage = official_report.get("coverage")
        return {"summary": storage.summary(), "issues": issues[:100], "issue_count": len(issues), "report": report, "official_coverage": official_coverage, "official_report": official_report}

    @app.post("/api/sync")
    def start_sync(request: SyncRequest):
        return job.start()

    @app.get("/api/sync")
    def sync_status():
        return job.snapshot()

    frontend_dir = frontend_dir or PROJECT_ROOT / "frontend" / "dist"
    app.mount("/assets", StaticFiles(directory=frontend_dir / "assets", check_dir=False), name="assets")

    @app.get("/", include_in_schema=False)
    def home():
        if not (frontend_dir / "index.html").exists():
            raise HTTPException(status_code=503, detail="前端尚未构建，请运行 npm --prefix frontend run build。")
        return FileResponse(frontend_dir / "index.html", headers={"Cache-Control": "no-cache"})

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="启动挑一部手机选购工作台")
    parser.add_argument("--port", type=int, default=8501)
    arguments = parser.parse_args()
    storage = Storage()
    if not storage.list_phones():
        from phone_assistant.import_legacy import import_legacy

        import_legacy(storage=storage)
    uvicorn.run(create_app(storage), host="127.0.0.1", port=arguments.port, http="h11", ws="none")


if __name__ == "__main__":
    main()
