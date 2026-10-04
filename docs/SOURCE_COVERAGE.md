# 手机来源、覆盖范围与持续补采

## 为什么需要多个发现入口

历史 Excel 保留 4018 行配置记录，其发布年份截止 2025。数据恢复、抓取时间和上市时间分别保存，重新导入不会把旧手机变成新机。ZOL 的品牌主列表也不是完整新品集合：2026-10-04 排查时，主列表没有 vivo X500，而同页“手机新品”模块已经有真实链接。采集器现在同时处理主列表、时间排序和新品模块，官网另作独立校验和补充。

补采前只读快照共 4226 条；vivo X500、OPPO Find X10、iPhone 18、iPhone Duo、华为 Mate 90、荣耀 Magic9 均缺。这里的“Duo”仅匹配 Microsoft Surface Duo 2，不能算 Apple 已覆盖。

## 官网适配器

实现位于 `phone_assistant/official_sources.py`。入口 URL 固定，机型链接由每次真实页面内容动态发现，未硬编码 X500、Find X10 或 Magic9 的详情地址。只访问无需登录的普通公开网页，默认超时 20 秒、请求间隔至少 0.6 秒；遇到 HTTP 错误、访问验证或规格结构变化记录错误，不绕过验证，也不发布空规格记录。

| 品牌 | 自动发现入口 | 规格证据 |
| --- | --- | --- |
| vivo / iQOO | [官网首页](https://www.vivo.com.cn/)公开 Nuxt SSR JSON 中的产品 banner；再跟随系列产品页的同系列链接 | 参数页 `.parameter-item/.attr-item`；有明确型号、容量和建议零售价时拆为独立配置 |
| OPPO | [手机目录](https://www.oppo.com/cn/smartphones/)实际产品链接 | 同一产品路径的 `specs/`，读取 SSR 参数项；区分摄像头和视频的相同“后置”标签 |
| Apple | [iPhone 目录](https://www.apple.com.cn/iphone/)实际产品链接及新款徽标 | 技术规格 `.techspecs-row`；Pro 和 Pro Max 按独立列读取，共用参数才共享 |
| 华为 | [手机目录](https://consumer.huawei.com/cn/phones/)实际产品链接 | 规格页 accordion；保留父标题，避免机身尺寸和屏幕尺寸混淆 |
| 荣耀 | [手机目录](https://www.honor.com/cn/phones/)链接、“最新产品”分区和有效新品徽标 | 公开 HTML 的 `data-value` 规格及备注；无需执行商城签名接口 |

规格链接必须与发现的产品标识一致，不能误跟随全局导航里别的手机参数。还会校验正文标题和配置机型与请求型号完全一致；即使 HTTP 200 且 URL 不变，返回其他机型也会记录错误且不入库。机型前缀不能当匹配证据。Apple Pro/Pro Max 只有正文明确两列才允许共页；“非凡大师/ultimate-design”等已确认的中英名称按别名比较。规格页跳转到其他路径或非品牌域名会报错。

vivo 是发现平台，不等于每台手机的品牌。该官网里的 iQOO 型号保留 `brand=iQOO`、`platform=vivo`；来源 ID 仍使用 `official:vivo:...`，避免纠正品牌时生成重复 ID，并与 ZOL 的 iQOO 产品归入同一 family。

## 哪些记录可以叫新品

`current_source=true` 仅说明抓取时出现在官网当前目录。普通目录可能含多年以前的手机。`new_from_source=true` 必须有明确“新款/新品/NEW”徽标、最新产品分区，或 vivo banner 的新品发布标记；不能把任何目录成员都叫新品。徽标过期时间已过去时不采纳。系列页额外发现的兄弟型号不会继承另一个型号的新品徽标。

`new_release_catalog_url`、`catalog_fetched_at` 和 `source_position` 保存真正发现它的目录或系列页证据。`discovered_at` 是发现时间，不是发布时间。日期未知的记录可展示为“官网当前目录，上市日期待核实”，不能用版权年份或抓取年份填上市年。

只有官网明确日期或月份才进入发布日期。年、月、日精度分别保存；例如 vivo 参数页的“2026年9月”只有月精度。发售状态按中国 UTC+8 日期判断。只有“10月23日发售”时保留原文，不推断年份；有完整未来日期仍为 `availability=unknown`，购买链接不能代替已经开售的证据。

已发现的冲突实例：Apple iPhone Duo 官网明确 2026-10-23 发售，而本轮 ZOL 配置记录写 2026-10-16。两份来源都保留，应用按官网来源处理未来发售状态；这一冲突不通过 AI 补写或删原始记录解决。

vivo X500 系列也发现 ZOL 部分配置原文写 2025-09-21，而官网参数明示 2026年9月。规范展示以官网的 2026年9月为准并标记来源冲突，原 ZOL 日期仍保存在原文及 `reported_release`。官网只有月精度，不能把旧来源的“21日”搬来拼出 2026-09-21；同 family 的来源优先只修正有明确证据的发布字段和发售状态，不跨型号套用价格或规格。

## 价格、配置和参数的边界

具体容量价格必须在官网原文中能对应型号和配置。vivo 参数页的“vivo X500（12GB+256GB）：5499.00元”保存为该配置，`price_kind=official_msrp` 表示建议零售价。它不承诺任何电商店铺当天成交价。

起售价只存 `price_from`，具体 `price` 留空。仅给出 RAM/ROM 范围时，不生成笛卡尔积配置，也不把最低价配给任意容量。没有公开价格证据的官网记录仍可用于发现和规格核对。

已采集参数保留原文于 `specs`，完整页面及脚注另存原始 HTML，规范别名只复制已有证据。例如荣耀参数在 `data-value` 属性中的值是公开页面内容。多协议充电、无线充电、反向充电、多镜头像素、颜色相关重量、容量范围等不能无条件取第一个数字；清洗无法明确归属的规范值留空。Apple 未公布的 RAM 或电池容量不从经验推断。像素数量也不能代表拍照质量，镜头配置、防抖和光学变焦仍需检查原文。

记录 ID 为 `official:<品牌>:<产品路径>:<明确配置>`，不会覆盖 ZOL 产品 ID 或历史 Excel 记录。`origin=official`；`specs_source_url/specs_fetched_at`、`price_source_url/price_fetched_at`、`release_source_url/release_fetched_at` 分别追溯实际获取该字段的页面和真实 UTC 时间。规范层保留 `field_sources` 与逐原文字段的 `specs_sources`；具体配置和官方基础型号通过 family 归组比较，而不是删掉任何来源。

## 调用、限额和覆盖报告

```python
from phone_assistant.official_sources import sync_official
from phone_assistant.storage import Storage

# 默认每品牌最多处理 12 个型号页面；可不传 storage 只采集供审查。
report = sync_official(Storage(), max_per_brand=12)

# 可明确继续处理上一次未完成的目录页，而不重新处理前 12 个。
report = sync_official(
    Storage(), brands=["oppo", "honor"], max_per_brand=12,
    offset_per_brand={"oppo": 12, "honor": 12},
)

# 全目录采集不设机型限额，耗时和站点请求量会增加。
# report = sync_official(Storage(), max_per_brand=None)
```

返回 `raws`、`models_discovered`、`records_discovered`、`imported`、`errors`、`coverage`。型号页面数量与配置记录数量不同，不能用 27 条 vivo 配置声称发现 27 款手机。`coverage` 按品牌列出发现数、成功型号数、记录数、`pending`、`next_offset`、实际产品 URL、规格 URL 和错误。`pending>0` 或存在错误都代表覆盖尚未完成。目录更新会改变排序，所以继续偏移适合同一轮补采；日常刷新从当前目录头部重新发现新机。

每轮在 `data/raw/official/<UTC运行标识>/` 写入原始 HTML、页面元数据和带 `raws` 的完整 `report.json`。不会以文件修改时间代替 HTTP 抓取时间。正式同步管线将去掉 `raws` 的摘要写入 `data/reports/latest_official.json`，数据质量页面据此展示官网覆盖；应查看最新报告，而不是把下面首次采集统计当永远最新。

2026-10-04 首轮实际采集（完整证据 `data/raw/official/20261003T172434424385Z/report.json`）：

| 品牌 | 发现型号 URL | 本轮成功型号 | 发布配置记录 | 尚未处理 URL |
| --- | ---: | ---: | ---: | ---: |
| vivo | 8 | 8 | 27 | 0 |
| OPPO | 113 | 12 | 12 | 101 |
| Apple | 5 | 5 | 6 | 0 |
| 华为 | 4 | 4 | 4 | 0 |
| 荣耀 | 137 | 12 | 12 | 125 |
| 合计 | 267 | 41 | 61 | 226 |

首轮 HTTP/解析错误为 0，补齐所核查的最新系列，并不宣称全球品牌、所有旧机或所有商城 SKU 已完整覆盖。官网目录中其他产品数量可能很多；型号数量也不等于唯一产品家族数量。下一轮要补其他品牌时应增加对应官方目录适配器和真实页面测试，不能通过生成型号名称或 AI 猜规格扩充数据量。

正文身份校验升级后，离线重放首次保存的 41 份规格页，对应全部 61 条配置记录均通过；没有新增网络请求。审计报告在 `data/reports/official_identity_audit.json`。发现平台为 vivo 的 iQOO 16 原被误归 vivo，已在相同来源 ID 下追加品牌纠正快照，保留原抓取时间，归组变为 `iqoo:16`；其余记录没有重复导入。原始 HTTP 快照和旧报告仍可追溯，重解析报告保存纠正后的品牌。

验证命令：`uv run --no-sync pytest tests/test_official_sources.py -q`。测试覆盖真实链接发现、新品徽标范围、SKU价格、容量不编造、日期不推断、多列规格、同机规格链接、参数父标题、真实来源时间、失败报告、分页续采和品牌支持范围。
