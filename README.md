# 挑一部 · 手机选购工作台

使用 Python、uv、SQLite、FastAPI 和 React 的本地手机选购工作台，支持来源采集、自动清洗、预算筛选、图片预览、三机对比及 DeepSeek 流式顾问。

安装 uv 和 Node.js 22.12 或更新版本后，在项目目录执行：

```powershell
uv run python scripts/restore_snapshot.py
.\start.ps1
```

打开 http://127.0.0.1:8501/，填写自己的预算开始选择。AI 密钥通过 `.env.example` 配置；未配置时本地筛选与比较仍可用。

来源、推荐、聊天和验证规则见 `docs/`。原始历史 Excel 和可还原数据库快照位于 `data/`；密钥和运行缓存不提交。
