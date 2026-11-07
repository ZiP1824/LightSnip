# 发布与搜索信息

## 仓库信息

- 名称：`LightSnip`
- 简介：`轻截 LightSnip：免费开源 Windows 截图软件，支持滚动长截图、OCR文字识别、贴图、马赛克涂抹、截图翻译、多屏截图和快捷键设置。Free open-source screenshot tool.`
- Website：`https://zip1824.github.io/LightSnip/`
- Topics：`screenshot`、`screenshot-tool`、`screen-capture`、`scrolling-screenshot`、`long-screenshot`、`ocr`、`annotation`、`image-pinning`、`mosaic`、`translation`、`free-software`、`open-source`、`windows`、`pyside6`、`python`、`screen-recorder`、`multi-monitor`、`portable`、`chinese`、`clipboard`

## 首次发布

仓库包含 Windows 构建工作流。推送源文件到 `main` 后会运行测试、生成绿色版，并发布 `VERSION` 指定的 Release。也可以在 Actions 页面手动运行 **Windows build and release**。发布资产包括 ZIP 和 SHA256SUMS.txt。

若 GitHub 组织或账号策略限制工作流写入，请在仓库 Actions 设置中允许所需的 contents 写权限。不要将任何个人访问令牌写入源文件。

## 启用功能介绍页

在仓库 **Settings → Pages** 中选择 **Deploy from a branch → main → /docs**，保存。部署完成后再把网站地址填到仓库 About 中。

`docs/index.html` 包含中文页面标题、描述、canonical、Open Graph、Twitter card 和 SoftwareApplication 结构化数据；站点还提供 robots.txt 与 sitemap.xml。页面与 README 以真实功能描述覆盖截图、长截图、OCR、贴图、马赛克及翻译等查询。

这些设置帮助 GitHub 和搜索引擎理解项目，不保证排名、即时收录或每个关键词都能搜到。搜索引擎收录和站长工具验证由相应服务控制。
