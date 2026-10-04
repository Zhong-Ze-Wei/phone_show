# 挑一部 · 静态产品介绍页

公开入口：<https://zhong-ze-wei.github.io/phone_show/>。介绍页源码：<https://github.com/Zhong-Ze-Wei/phone_show/tree/master/site>。主应用与介绍页位于同一公开仓库，可直接克隆运行。

该目录独立于 Python、React 与模型服务，只包含 HTML、CSS、JavaScript 和展示资产，直接托管到 GitHub Pages。所有本地资源使用 `./` 相对路径，适配 `/phone_show/` 子路径；无需 Node 构建。`.nojekyll` 关闭 Jekyll 处理。

## 本地查看

在项目根目录执行：

```powershell
uv run python -m http.server 8510 --bind 127.0.0.1 --directory site
```

打开 `http://127.0.0.1:8510/`。不要直接用 `file://` 打开，浏览器会阻止读取演示 JSON。

## 演示与事实边界

- 初始示例预算留空。选择 3000、4000 或 8000 元，再切换日常、游戏、拍照、续航，才显示 `assets/demo-data.json` 对应组的真实推荐快照；切换条件时清空旧演示对比。
- 对比最多三部，通过按钮、键盘或 HTML5 拖拽加入右侧整块区域。参数对比仅展示快照中的现有字段，缺失值显示“待核实”；参考报价不是成交价、当前库存或二手行情。
- 手机图片直接使用 JSON 的真实来源 URL；图片失效显示“暂无来源图片”。真实图库、顾问和手机端界面的截图是本地 PNG，全部来自应用实际运行截图，没有生成商品图片。
- 顾问球只打开明确标注的录制示例：`recorded_chat` 来自实际模型请求日志。显示固定文本，不随当前演示预算变化，不假装实时响应。打开、查看录制内容、对比等不会请求 `/api`、调用模型或上传输入。
- 截图切换与放大、预算用途、对比增删、录制对话展开、安装命令复制均可操作。原生 `dialog` 支持 Escape、焦点限制和关闭后返回；`prefers-reduced-motion: reduce` 关闭动画、过渡和平滑滚动。
- 主应用 `phone_show` 为公开仓库，可直接克隆并查看运行说明；同仓库 GitHub Pages 仅发布该目录，不发布数据库、密钥或原始运行日志。

## 主要文件

- `index.html`：介绍内容、真实截图、交互演示与运行说明。
- `styles.css`：浅底排版与深色工作台，以及手机端和减少动态效果样式。
- `demo.js`：只在本地处理选择、比较、截图与录制文本；仅读取静态 JSON。
- `assets/demo-data.json`：候选与录制对话的真实快照，由项目数据生成流程提供，不手改产品事实。
- `assets/*-desktop.png`、`assets/gallery-mobile.png`：可独立托管的真实产品截图副本。
