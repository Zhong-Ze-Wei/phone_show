"""采集、质量检查、选机推荐与历史资料检索入口。"""

import argparse
import json
import math
import sys

from openai import APIConnectionError, APIStatusError

from phone_assistant.assistant import DATA_NOTICE, PhoneAssistant, api_error_message
from phone_assistant.config import Settings, create_client
from phone_assistant.catalog import PhoneCatalog
from phone_assistant.knowledge import KnowledgeBase
from phone_assistant.recommendation import Preferences, recommend
from phone_assistant.storage import Storage


def main() -> None:
    parser = argparse.ArgumentParser(description="更新手机数据、自动清洗并按需求选手机")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="检查本地数据和配置，不请求 API")
    commands.add_parser("check-api", help="检查模型列表并发送一次简短测试请求")
    commands.add_parser("import-legacy", help="将原始 Excel 导入为可追溯的历史数据")
    commands.add_parser("quality", help="查看规范记录覆盖率、缺失值与异常计数")
    commands.add_parser("clean", help="按当前清洗规则重算原始快照，不请求网络")
    sync = commands.add_parser("sync", help="采集在售机型与版本，自动清洗、校验并保存")
    sync_mode = sync.add_mutually_exclusive_group()
    sync_mode.add_argument("--force", action="store_true", help="重新开始一批，不使用上批检查点")
    sync_mode.add_argument("--resume", action="store_true", help="接续未完成批次，保留原响应时间")
    sync.add_argument("--limit", type=int, help="限制详情条数，用于小批验证；不声称全覆盖")
    sync.add_argument("--delay", type=float, default=0.9, help="每次来源请求最小间隔，默认0.9秒")
    sync.add_argument("--latest", action="store_true", help="仅核对官网和品牌新品入口并补采详情，不刷新历史目录")
    choose = commands.add_parser("recommend", help="按参考价预算与需求推荐，不请求模型")
    choose.add_argument("--budget", type=float, help="可选最高预算，省略时不限金额")
    choose.add_argument("--min-budget", type=float, default=0)
    choose.add_argument("--brand", action="append", default=[])
    choose.add_argument("--priority", action="append", choices=["daily", "gaming", "camera", "battery"], default=[])
    choose.add_argument("--storage", type=float, default=0, help="最低容量，默认不限")
    choose.add_argument("--compact", action="store_true")
    choose.add_argument("--history", action="store_true")
    choose.add_argument("--query", default="")
    choose.add_argument("--sort", choices=["recommended", "newest", "match", "price_asc", "price_desc"], default="recommended", help="默认综合需求、预算余量、上市时效与品牌偏好")
    choose.add_argument("--purchase-mode", choices=["new", "used"], default="new", help="used 仅放宽机型年龄偏好，不提供二手行情")
    search = commands.add_parser("search", help="仅检索本地资料，不请求 API")
    search.add_argument("question")
    ask = commands.add_parser("ask", help="检索旧 Markdown 和 Excel 的历史问答；新版选机用 recommend 或网页")
    ask.add_argument("question")
    arguments = parser.parse_args()
    try:
        settings = Settings.from_env()
        if arguments.command in {"import-legacy", "quality", "clean", "sync", "recommend"}:
            storage = Storage()
            if arguments.command == "import-legacy":
                from phone_assistant.import_legacy import import_legacy

                result = import_legacy(storage=storage)
            elif arguments.command == "quality":
                result = storage.summary()
            elif arguments.command == "clean":
                result = storage.reclean()
            elif arguments.command == "sync":
                from phone_assistant.pipeline import run_sync

                if arguments.limit is not None and arguments.limit < 1:
                    raise ValueError("--limit 必须大于零。")

                def progress(event):
                    print(f"{event.get('stage', '')}: {event.get('completed', 0)}/{event.get('discovered', 0)}；失败 {event.get('failed', 0)}", file=sys.stderr, flush=True)

                result = run_sync(storage=storage, progress=progress, resume=arguments.resume,
                    force=arguments.force or not arguments.resume, limit=arguments.limit, delay=arguments.delay,
                    latest_only=arguments.latest)
            else:
                if not all(math.isfinite(value) for value in (arguments.budget, arguments.min_budget, arguments.storage) if value is not None):
                    raise ValueError("预算和存储容量必须是有限数值。")
                if arguments.min_budget < 0 or (arguments.budget is not None and (arguments.budget <= 0 or arguments.budget < arguments.min_budget)):
                    raise ValueError("预算范围无效。")
                if not 0 <= arguments.storage <= 4096:
                    raise ValueError("存储容量必须在 0 至 4096GB 之间。")
                result = recommend(storage.list_phones(), Preferences(
                    budget_min=arguments.min_budget, budget_max=arguments.budget,
                    brands=arguments.brand, priorities=arguments.priority or ["daily"],
                    min_storage=arguments.storage, compact=arguments.compact,
                    include_history=arguments.history, query=arguments.query, sort=arguments.sort,
                    purchase_mode=arguments.purchase_mode,
                ), limit=10)
                display_fields = ("id", "name", "brand", "price", "price_from", "score", "recommendation_score", "ranking_breakdown", "ranking_reasons", "soc", "battery_mah", "storage_gb", "release_date", "release_year", "release_month", "reasons", "tradeoffs", "discovery_reasons", "discovery_status", "catalogue_reasons", "catalogue_codes", "catalogue_status", "catalogue_variant_count", "recommendation_eligible", "source_url", "fetched_at")
                result["phones"] = [{key: phone.get(key) for key in display_fields} for phone in result["phones"]]
                result["discovery"]["phones"] = [{key: phone.get(key) for key in display_fields} for phone in result["discovery"]["phones"][:10]]
                result["discovery"]["returned"] = len(result["discovery"]["phones"])
                result["catalogue"]["phones"] = [{key: phone.get(key) for key in display_fields} for phone in result["catalogue"]["phones"]]
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if arguments.command == "sync" and result["status"] == "partial":
                raise SystemExit(2)
            return
        if arguments.command == "check-api":
            with create_client(settings) as client:
                models = {model.id for model in client.models.list()}
                if settings.model not in models:
                    raise ValueError(f"平台模型列表中未找到 {settings.model}。")
                response = client.chat.completions.create(
                    model=settings.model,
                    messages=[{"role": "user", "content": "请只回复：连接成功"}],
                    max_tokens=32,
                    extra_body={"extra_body": {"enable_thinking": False}},
                )
                if not response.choices[0].message.content:
                    raise ValueError("请求完成但没有正文，API 检查未通过。")
                print(f"模型：{response.model}\n回答：{response.choices[0].message.content}")
            return

        knowledge = KnowledgeBase()
        catalog = PhoneCatalog()
        if arguments.command == "status":
            print(json.dumps({
                "knowledge": knowledge.stats,
                "catalog": catalog.stats,
                "normalized": Storage().summary(),
                "api": {"base_url": settings.base_url, "model": settings.model, "key_configured": bool(settings.api_key and settings.api_key != "your-api-key")},
                "data_notice": DATA_NOTICE,
            }, ensure_ascii=False, indent=2))
            return

        if arguments.command == "search":
            sources = knowledge.search(arguments.question)
            print("\n\n".join(
                f"[{index}] {result.chunk.title}\n{result.chunk.source}\n{result.chunk.content}"
                for index, result in enumerate(sources, start=1)
            ) or "没有找到相关资料。")
            return

        answer = PhoneAssistant(knowledge, settings, catalog=catalog).ask(arguments.question)
        print(answer.content)
        if answer.sources:
            print("\n资料来源：")
            for index, result in enumerate(answer.sources, start=1):
                print(f"[{index}] {result.chunk.source} · {result.chunk.title}")
    except (APIStatusError, APIConnectionError) as error:
        print(api_error_message(error), file=sys.stderr)
        raise SystemExit(1) from None
    except (ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
