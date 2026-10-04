# README 版式维护

README 先提供可点击的在线封面、一句产品价值和紧凑导航，再以真实截图解释图库、顾问和手机端。四条首次运行命令保持展开；高级启动、详细推荐、CLI、API、模块表和历史说明使用折叠区块，原有业务与数据边界仍可查阅。

参考 [Excalidraw README](https://github.com/excalidraw/excalidraw/blob/master/README.md) 的链接封面、`picture` 和真实产品截图，以及 [Supabase README](https://github.com/supabase/supabase/blob/master/README.md) 的简明入口与功能、文档连接方式。参考的是组织方式，未复制其图片、文案或许可证声明。

维护时遵循以下规则：

- 封面由外层 `<a>` 链接到 `https://zhong-ze-wei.github.io/phone_show/`；`<picture>` 的深色来源使用 `banner-dark.svg`，默认 `<img>` 使用 `banner-light.svg`，两版均为 1280 × 360，并保留说明点击目的的 `alt`。源码在 `docs/readme-assets/`，由同仓库 Pages 工作流复制到发布产物的 `assets/`，README 引用正式 Pages 图片地址。GitHub 官方支持 [`picture` 与主题切换](https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/quickstart-for-writing-on-github)。
- 功能图使用实际运行截图：原图在 `docs/ui-reference/`，展示副本在 `site/assets/`。README 通过正式 Pages 地址加载，减少对这里连接不稳定的 GitHub 原图域名的依赖；点击后到现有 Pages 区块或真实文档。截图更新后同时核对说明；手机端图保持约 260 像素宽，不用多列表格承载截图。
- 导航指向真实章节；改标题后同步核对锚点。徽章只展示实际 `pages.yml` 工作流状态，不添加未经证实的许可证、覆盖率或实时数据标记。
- `<details>` 中保留原说明，`<summary>` 后与结束标签前留空行，保证 Markdown 代码块、列表与表格正常解析。语法依据是 [GitHub 折叠区块文档](https://docs.github.com/en/get-started/writing-on-github/working-with-advanced-formatting/organizing-information-with-collapsed-sections)。
- 发布前检查 GitHub 实际渲染的深浅主题、封面点击、截图链接、手机宽度、导航与折叠内容。在线页仍是数据快照与录制演示，完整应用在本地运行；版式不得改变这一边界。
