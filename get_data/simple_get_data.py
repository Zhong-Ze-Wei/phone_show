"""美股财报查询参考助手；纯模型模式，没有实时搜索能力。"""

from __future__ import annotations

import argparse
import datetime

from phone_assistant.config import Settings, create_client


def get_time_context() -> dict[str, str | int]:
    """获取当前日期与季度。"""
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    return {
        "date": now.strftime("%Y-%m-%d"),
        "year": now.year,
        "quarter": (now.month - 1) // 3 + 1,
        "display": f"{now.year}年{now.month}月{now.day}日",
    }


def query_api(prompt: str, *, settings: Settings | None = None) -> str:
    """调用统一配置的 AIPing 模型，生成需要自行核实的参考。"""
    settings = settings or Settings.from_env()
    with create_client(settings) as client:
        response = client.chat.completions.create(
            model=settings.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"你是美股财报查询参考助手。当前时间：{get_time_context()['display']}。\n"
                        "本程序没有实时搜索或网页抓取工具，无法核实最新财报日程。"
                        "所有输出必须标为待核实参考；不要编造日期或来源链接，"
                        "没有可靠信息时直接说明未核实。\n"
                        "识别公司及股票代码，并说明如何在公司投资者关系（IR）官网"
                        "查询最近一次财报与下一次财报公告。"
                        "只有有把握的官网地址才可给出，预期日期必须明确标注为预期。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=1500,
            extra_body={"extra_body": {"enable_thinking": False}},
        )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("模型没有返回文本内容，请检查 AIPing 模型配置。")
    return content


def query_earnings(company: str, *, settings: Settings | None = None) -> str:
    """生成指定公司的财报查询参考。"""
    prompt = (
        f"请提供 {company} 的财报发布时间查询参考"
        f"（当前时间：{get_time_context()['date']}）。"
    )
    return query_api(prompt, settings=settings)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("company", nargs="?", help="公司名称或股票代码，例如 AAPL")
    args = parser.parse_args()
    settings = Settings.from_env()
    settings.require_api_key()

    print("美股财报查询参考助手：无实时搜索，输出需要自行核实。")
    if args.company:
        print(query_earnings(args.company, settings=settings))
        return

    while True:
        company = input("\n输入公司名称/代码（q 退出）：").strip()
        if company.lower() in {"q", "quit", "exit", "退出"}:
            return
        if company:
            print(query_earnings(company, settings=settings))


if __name__ == "__main__":
    main()
