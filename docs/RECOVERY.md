# 项目恢复记录

恢复日期：2026-10-03。

## 本地现状

`choise_phone` 初始没有 `.git`、依赖声明或可启动的手机主程序。`docs_archive/project_docs` 描述的 `run.py`、采集器与处理器不存在。现存两个 `get_data/*.py` 都是美股财报查询，使用旧 SiliconFlow 配置。

现有手机知识 Markdown 共 62 份，检索排除了项目报告、实施指南等非手机知识内容。`rag_prepared_data.json` 声称有 26 款手机，实际只有 3 条；`rag_qa_dataset.json` 声称 100 条问答，实际 15 条。没有据这些元数据展示覆盖率或准确率。

## GitHub 与原网页调查

通过相邻项目的 Git remote 确认账号为 `Zhong-Ze-Wei`，并使用本机已有 Git 登录只读检查公开、私有仓库与历史。相关仓库：

- [Get_Phone](https://github.com/Zhong-Ze-Wei/Get_Phone)：私有，最新 `main` 已重构为独立爬虫系统。
- [phone_show](https://github.com/Zhong-Ze-Wei/phone_show)：私有，当前为空仓库。
- [RAG_LLM](https://github.com/Zhong-Ze-Wei/RAG_LLM)：通用 LLM 聊天示例，RAG 文件为占位内容，没有本项目的手机问答实现。

`Get_Phone` 最新提交 `e0fa89f72722abbee9002b547365fd1d58eb6668` 的提交说明是“重构为独立爬虫系统 - 移除Web和AI依赖”。历史文档记录的网页使用 Flask、PyMySQL、OpenAI SDK，启动文件是 `phone_recommendation_web/app.py`，端口 5001。

但从最早历史开始，`phone_recommendation_web` 始终以 `160000` Git 指针保存，父仓库没有该目录的实际源码。`377df2c14fefd4a3f758c2c1faea80c87bf65ec4` 指向 `fff50837dd127e510547fc48af1a96f0dfa4ebf0`，删除前的另一版本指向 `eb24be372cd9faeb2f6fd8e359a18b98ac78280d`；本地没有这些子仓库对象或 `.git/modules`。父仓库历史也没有网页服务或模板的 blob。

在 `E:\ZZ's_Code` 中按目录名及关键服务/模板文件名搜索，未找到网页副本。原 MySQL 服务仍安装，但处于停止状态；本次没有启动、修改或迁移数据库。

因此当前入口是根据保留资料补齐的本地浏览与问答页面。原 Flask 页面的完整恢复仍需要子仓库源码。

## 恢复的数据

文件：`data/recovered/phone_specs_export_中文表头.xlsx`。

来源：[Get_Phone 历史提交 e2b472e90b](https://github.com/Zhong-Ze-Wei/Get_Phone/tree/e2b472e90b)，Git blob 为：

```text
7786326b27759e0c5504a3f5d36e5ee74c3f99d8
```

只导出这个数据文件，没有导出旧 `.env`、虚拟环境、可执行文件或其他凭据文件，也没有修改相邻项目。

文件大小 1,797,077 字节，`Sheet1` 包含 4,018 条记录、60 个字段、94 个品牌；记录中的发布年份为 2011–2025。原始单元格值被保留，缺失值不通过模型补造。数据没有重新采集或重新核实。

## API 与环境

使用项目独立 uv 环境，Python 3.13，依赖通过 `pyproject.toml` / `uv.lock` 管理。

统一使用 `https://aiping.cn/api/v1` 和 `DeepSeek-V4.1-Flash`。配置来自 `.env` 或环境变量，源码不保存密钥。已实际检查平台模型列表，简短请求返回“连接成功”，以及用真实模型执行手机对比与网页问答。

参考 [AIPing 文本模型文档](https://aiping.cn/docs/API/text-models)、[模型列表](https://aiping.cn/docs/API/model-list) 和 [错误说明](https://aiping.cn/docs/API/error-handling)。

恢复当时改动位于本地 `fix/restore-aiping` 分支，尚未配置远端或提交。2026-10-04 的独立网页应用发布目标为 [phone_show](https://github.com/Zhong-Ze-Wei/phone_show)，没有覆盖 `Get_Phone` 的爬虫系统；克隆、数据还原与运行步骤以根目录 README 为准。
