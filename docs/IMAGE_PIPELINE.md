# 产品图片采集与离线修复

图片用于辨认真实手机外观。实现位于 `phone_assistant/images.py`，页面解析接入 `crawler.py`、`official_sources.py` 和 `pipeline.py`。所有图片使用来源页明确给出的地址，不生成商品图，不替用其他型号，也不修改 URL 尺寸字符串来猜高清路径。

## 本轮查明的问题

原 ZOL 产品解析只返回系列、价格和参数链接，忽略 `#big-pic` / `.big-pic img`；参数解析也未读取 `.goods-card__pic img`。系列列表的 80×60 小缩略图因此常成为唯一图片，或在较新同步时覆盖原有较大图片。vivo 官网规格页的产品颜色图未进入原有适配器，目录没有图时型号也一直缺图。

已保存的真实页面能证明：真我 Neo8、Redmi K100 Pro 有 320×240 的产品图地址；荣耀 WIN 参数页有 280×210 的图片地址；vivo X500 的已核验官网规格页有明确产品色图。这些是源页实际链接，不意味着所有手机都存在同等分辨率图片。HTML 的 `width` / `height` 是页面声明的展示尺寸，不能当作下载图片的真实像素。

## 身份、角色与覆盖规则

1. ZOL 只取上述产品主图容器，图片外层链接必须指向当前产品 ID 的详情或图片页；相关机型、广告和样张不参与。
2. 官网图片必须先通过现有正文型号身份校验。目前补充的是 vivo 的 `.color-image-list .color-image-item img`，不泛取页面第一张图片。
3. 只接受明确的 HTTP(S) 地址；排除 logo、图标、二维码和 APP 宣传图。缺图保持未知。
4. 图片角色依次为 `primary`（产品主图）、`catalog`（已识别型号目录图）、`thumbnail`（系列小缩略图）。较低角色不会覆盖较高角色。同角色先比较页面明确的展示尺寸，再使用来源与采集时刻处理同等候选；没有尺寸不编造尺寸。
5. 旧记录没有角色时，只识别既有地址中的明确尺寸标记判断小缩略图；不由该标记生成另一个图片地址。

规范记录中的 `image_url`、`image_role`、`image_width`、`image_height`、`image_source_url`、`image_fetched_at` 是一个图片字段组。`field_sources.image_url` 记录真实图片来源页及其原采集时间。图片字段不参与价格、上市状态或推荐评分计算。

## 已有缓存的修复

先预览，再发布：

```powershell
# 只读扫描现有数据库与保存的响应，不联网
uv run python -m phone_assistant.images --report data/reports/image_replay_preview.json

# 事务发布图片字段，并保存逐型号审计
uv run python -m phone_assistant.images --apply --report data/reports/image_replay.json
```

回放读取 `data/raw/zol-sync-*/html/`、`data/raw/official/` 中成对保存的 HTML 和响应元数据。仅使用成功响应、有真实采集时刻且页面路径身份一致的缓存；同一来源取较新的保存响应。跨来源共用图片只在已核验官网正文与数据库的 `family_key` 完全一致时进行，不复制容量、价格或其他配置字段。

发布在一个 SQLite 事务中只修改图片字段组及 `field_sources.image_url`。逐条比较非图片内容的 SHA-256 摘要，任何变化都中止发布。`price`、规格、状态、`price_fetched_at`、`specs_fetched_at`、`fetched_at`、质量问题和原始快照保持原样；审计检查时刻与来源采集时刻分开记录。再次执行无新图片变化时不会重复改写。

## 重清洗与后续同步

仅改 `phones` 规范记录会在重清洗时丢失补图。因此离线回放还写入独立 `image_overrides` 表，保存图片字段及其真实来源。`Storage._write_phone()` 在原始快照正常清洗合并后应用图片覆盖；覆盖仍接受角色、尺寸与时间比较，不能压过后续取得的更好有效图片。`Storage.reclean()` 重建规范记录时保留该表并重放覆盖。原始 HTTP 缓存、Excel 和 `raw_snapshots` 均不被改写。

正常同步也会读取产品和参数页实际主图，写入新原始快照，再通过同一图片字段合并规则处理。无需每次手动执行离线修复。自动流程与失败队列见 [采集流程](DATA_PIPELINE.md)，其余清洗规则见 [清洗策略](CLEANING_STRATEGY.md)。

前端直接使用 `image_url`。图片请求失败时显示“暂无来源图片”；同型号更新为另一个地址后会重新加载，不把旧 URL 的失败状态留给新图。布局与验收见 [界面恢复记录](UI_RESTORE.md)。

## 2026-10-04 实际发布与边界

离线发布 795 条产品主图，来自 766 个真实来源页；795 条地址均与原图不同。没有新的来源采集或模型请求。364 条页面声明展示尺寸为 320×240，394 条为 260×195（其中实际地址为 280×210），37 条官网色图没有明确尺寸属性。浏览器分别验证了实际下载尺寸，HTML 展示尺寸仍只按展示尺寸记录。

发布前后，全 4428 条记录的非图片字段、5777 个原始快照和数据库 `updated_at` 的 SHA-256 摘要完全一致。对数据库 backup 副本实际重清洗 5777 个快照后，全部图片地址、角色及来源保留，非图片内容和原始快照仍一致。再次全库预览待修改数量为零。

审计位于 `data/reports/image_replay.json`、`image_integrity_before.json`、`image_integrity_after.json`。仍未补主图的 3633 条包括 3433 条历史资料、166 条缺相同产品 ID 主图缓存的 ZOL 记录，以及 34 条尚无已核验规格主图选择器的官网记录；保留已有目录图、缩略图或未知值。该修复不宣称全库都有高清图片。后续正常同步仍按实际页面证据补图，不根据别的容量型号或其他手机猜图。
