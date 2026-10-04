"""AIPing 配置：环境变量优先于项目根目录的 .env。"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values
from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    api_key: str = field(repr=False)
    base_url: str = "https://aiping.cn/api/v1"
    model: str = "DeepSeek-V4.1-Flash"
    timeout: float = 120.0

    @classmethod
    def from_env(cls) -> "Settings":
        values = {**dotenv_values(PROJECT_ROOT / ".env"), **os.environ}
        return cls(
            api_key=values.get("AIPING_API_KEY", "").strip(),
            base_url=values.get("AIPING_BASE_URL", "https://aiping.cn/api/v1").rstrip("/"),
            model=values.get("AIPING_MODEL", "DeepSeek-V4.1-Flash"),
            timeout=float(values.get("AIPING_TIMEOUT", "120")),
        )

    def require_api_key(self) -> None:
        if not self.api_key or self.api_key == "your-api-key":
            raise ValueError("请在项目根目录 .env 中配置 AIPING_API_KEY。")


def create_client(settings: Settings) -> OpenAI:
    settings.require_api_key()
    return OpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout=settings.timeout,
        max_retries=0,
    )
