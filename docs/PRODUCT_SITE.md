# 产品介绍页与静态演示

正式地址：[挑一部 · 产品介绍与演示](https://zhong-ze-wei.github.io/phone_show/)。介绍页与主应用统一维护在公开仓库 [Zhong-Ze-Wei/phone_show](https://github.com/Zhong-Ze-Wei/phone_show)，README 顶部提供快捷入口。

`site/` 是介绍页的唯一开发源。[`.github/workflows/pages.yml`](../.github/workflows/pages.yml) 自动发布该目录到主仓库的 GitHub Pages；无需复制到另一个仓库。Pages 产物只包含静态页，主应用源码与版本数据库仍可从同一 GitHub 仓库获取。`.env`、运行日志、虚拟环境和采集缓存保持 Git 忽略。

## 页面与数据边界

介绍页使用纯 HTML、CSS、JavaScript，展示真实界面截图，并提供浏览器内的示例预算、用途切换、手机对比和顾问录制演示。不运行 Python 服务，不调用主应用接口或 AI 模型，不接收模型密钥。页面只读取静态 JSON、样式、脚本和图片资源；手机图片仍可能通过资料来源站加载。

[`site/assets/demo-data.json`](../site/assets/demo-data.json) 是 **2026-10-04 生成的真实推荐结果快照**，保留各机型原有采集时间与来源，生成快照不会刷新报价时间。`cases` 包含 12 组固定示例：最高预算 ¥3,000、¥4,000、¥8,000，分别搭配日常、游戏、拍照、续航四种用途。

示例预算首次留空，用户主动选择后才展示对应分组。脚本中的用途标签、分类与候选价格都用于读取这份固定快照，不执行实时采集，不计算当前行情，也不代表库存、成交价或二手售价。资料缺失时保持未知，不能补成零或用其他机型规格替代。更新快照时需继续标明生成日期、原始来源与参考报价边界。

芯片的展示字段 `chipset` 是规范 API 字段 `soc` 的原值别名；没有从机型名称或介绍文字推测参数。快照保留独立的 `price_fetched_at`、`price_source_url` 和规格来源时间，生成展示文件不会刷新这些时间。发布前已对照当前推荐接口检查 12 组的候选顺序、名称、参考价和来源，并核对 16 个唯一配置的芯片值。

`recorded_chat` 保存两次真实模型回复及对应的两条用户问题。页面必须明确标注“录制示例 · 非实时 AI”：打开、播放或切换演示不会发起新模型请求，固定对话不会随当前示例预算、用途或对比机型变化。播放动效只展示已录制文本，不能称为正在生成的实时回答。真实连续聊天需启动主应用，并由用户明确发送消息后才调用模型。

## 真实截图来源

以下文件来自实际运行的主应用界面，不是生成图片或示意稿；展示页中的副本与对应原图内容一致。

| 展示页资源 | 主应用原图 | 内容 |
| --- | --- | --- |
| `site/assets/gallery-desktop.png` | [`docs/ui-reference/image-gallery-desktop.png`](ui-reference/image-gallery-desktop.png) | 桌面大图手机图库与预览、对比栏 |
| `site/assets/advisor-desktop.png` | [`docs/ui-reference/advisor-workspace-desktop.png`](ui-reference/advisor-workspace-desktop.png) | 展开的顾问聊天工作区 |
| `site/assets/gallery-mobile.png` | [`docs/ui-reference/image-gallery-mobile.png`](ui-reference/image-gallery-mobile.png) | 手机端图库 |

主应用界面更新后，应重新运行并截图，再同步展示页资源；不要让旧截图暗示已经实现的新行为。

## 本地预览与验证

在主应用项目根目录执行：

```powershell
uv run python -m http.server 8503 --bind 127.0.0.1 --directory site
```

打开 [http://127.0.0.1:8503/](http://127.0.0.1:8503/)，按 `Ctrl+C` 停止。这个预览服务只提供静态文件，不需要模型密钥，不会产生 AI 请求。

修改后，在主应用根目录运行：

```powershell
npm run build
npm test
node --check site/demo.js
```

还需用真实浏览器检查桌面与手机宽度：初始预算留空、12 组示例切换、对比增删与最多三台限制、截图切换与放大、来源链接、录制对话标识、键盘操作及减少动效设置。查看网络请求，确认没有 `/api/chat`、`/api/recommend` 或模型请求。

CSS、JavaScript、JSON 和截图使用相对资源路径，例如 `./styles.css`、`./demo.js`、`./assets/gallery-desktop.png`。本地根路径可正常加载并不足以证明上线可用，必须再检查 `/phone_show/` 子目录下的资源；不要将资源路径写成 `/assets/...`。

## 主仓库自动发布

用户已授权将主仓库公开，介绍页迁回同一仓库。GitHub Pages 设置使用 **GitHub Actions** 发布；工作流上传 `site/`，因此不用将产品页塞进现有文档目录，也不上传整个项目。官方步骤见 [使用自定义工作流发布 Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)。

维护流程如下：

1. 在主应用的功能分支编辑 `site/`，完成上述构建、测试、脚本语法检查与真实浏览器验证。
2. 在功能分支提交本次页面更新，切回 `master`，使用 `git merge --no-ff feat/update-product-site` 合并，再执行 `git push origin master`。分支名按本次实际任务调整；每次提交应可独立验证与回滚。
3. `master` 的推送涉及 `site/**` 或 Pages 工作流时，自动执行 **Publish product site**。工作流检查 JS 语法，配置 Pages、上传 `site/` 并部署；不安装应用依赖、不读取模型密钥、不运行采集。
4. 仅修改其他应用模块或文档不会触发部署。需要重发时，可在仓库 Actions 中打开此工作流，点击 **Run workflow**，选择 `master`。
5. 等待工作流成功，再检查正式主页及 CSS、JS、JSON、截图资源，确认相对路径、交互与录制标识正常。报告应记录部署提交与实际网页结果，不能仅根据推送成功判断上线。

页面无需 Node 构建，工作流只有 `contents: read`、`pages: write` 与部署所需的 `id-token: write` 权限。同一时刻仅保留一个有效部署任务。公开页不运行 Python，完整筛选、采集与真实 AI 聊天仍由本地主应用提供。

原 `phone_show-demo` 不再作为产品源码维护，只保留历史与旧网址跳转，避免已分享的链接失效。

## 首次独立演示发布记录（迁移前）

验证日期：**2026-10-04**。公开演示 `master` 提交为 [`8e67dc069551b4595586b3c1bcf546db6602b040`](https://github.com/Zhong-Ze-Wei/phone_show-demo/commit/8e67dc069551b4595586b3c1bcf546db6602b040)，GitHub Pages 的对应构建状态为 **built**，HTTPS 已启用，默认分支为 `master`。

- 实际公开主页 HTTP 200；`index.html`、CSS、JS、JSON、favicon 和三张真实截图共 8 个资源均 HTTP 200。逐文件与本地 `site/` 内容对照一致，仅统一文本换行以消除 Windows 与 Git 的换行差异。
- 本地真实发布子路径和实际公开 URL 分别完成 **46 项浏览器检查**：首次预算留空、12 组示例、键盘加入对比、真正鼠标拖到右侧标题和顾问区域、重复去重、外部文本拒绝、参数与来源、条件变化清空、重置、三种截图放大、对话展开收起、复制完整运行命令及弹窗 Escape／焦点返回。
- 390px 手机视口的卡片、参数弹窗与录制对话均无页面横向溢出；减少动效设置关闭入场与球动画。桌面、手机检查均没有 JavaScript 异常、失败的本站资源、后端或模型请求。
- 公共仓库只有 10 个静态文件，总计 718,310 字节，提交历史独立于私有主项目；逐文件未检出当前配置密钥。主应用仓库仍为私有。
- 本轮主项目 `npm run build`、`npm test` 与 `node --check site/demo.js` 通过，Python 304 项、前端 28 项测试通过。

本机验证报告为 `logs/product-site-local-check.json`、`logs/product-site-public-check.json` 和 `logs/product-site-public-http.json`，不进入 Git。实际线上桌面、手机截图也保存在本机 `logs/product-site-public-*.png`。后续发布仍需访问公开 URL 检查，不能仅凭本地预览或部署 API 响应判断上线成功。
