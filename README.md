# NewsFlow - 新闻聚合器

多源新闻聚合静态站，覆盖 **80+ 新闻源**，通过 GitHub Actions 每天早中晚自动更新，部署到 GitHub Pages。

## 覆盖领域

| 分类 | 示例来源 |
|---|---|
| 科技媒体 | TechCrunch, The Verge, Wired, Ars Technica, Engadget, VentureBeat... |
| AI与研究 | OpenAI, Anthropic, DeepMind, arXiv, Hugging Face, Nature... |
| 财经金融 | CNBC, Bloomberg, WSJ, MarketWatch, 华尔街见闻, 财联社, 财新... |
| 创投与VC | Y Combinator, A16Z, First Round Capital, Basecamp... |
| 个人博客 | Paul Graham, Marc Andreessen, Andrew Chen, Stratechery, Sam Altman... |
| 设计与产品 | SVPG, Mind the Product, Frog Design... |
| 开发者社区 | Hacker News, Lobsters, Dev.to, Product Hunt, V2EX, GitHub Blog... |
| 安全 | Krebs on Security, The Hacker News, NIST NVD |
| 综合新闻 | BBC, Reuters, AP News, NYT, The Guardian, Al Jazeera... |
| 中文科技 | 36氪, 少数派, 虎嗅网 |
| 中文热搜 | 微博, 知乎, B站, 百度, 今日头条, 抖音, 澎湃, 凤凰网... |

## 一键部署

### 1. Fork 本仓库

点击右上角 **Fork** 按钮。

### 2. 启用 GitHub Pages

进入你 Fork 后的仓库：

1. **Settings** → **Pages**
2. Source 选择 **Deploy from a branch**
3. Branch 选择 **gh-pages** / **root**
4. 点击 **Save**

### 3. 启用 GitHub Actions

进入 **Actions** 标签页，点击 **I understand my workflows, go ahead and enable them**。

### 4. 首次运行

- 进入 **Actions** → **Build & Deploy NewsFlow**
- 点击 **Run workflow** 手动触发一次
- 等待 2-3 分钟，构建完成后网站即上线

### 5. 访问

网站地址：`https://<你的用户名>.github.io/<仓库名>/`

## 更新频率

GitHub Actions 自动执行，每天 3 次：

| 时间 | 北京时间 | UTC |
|---|---|---|
| 早 | 08:00 | 00:00 |
| 中 | 12:00 | 04:00 |
| 晚 | 20:00 | 12:00 |

也可随时到 Actions 页面手动触发。

## 自定义

### 添加/删除新闻源

编辑 `feeds.yaml`，按照已有格式增删源：

```yaml
- name: "源名称"
  url: "https://example.com/"
  rss: "https://example.com/feed/"
```

没有官方 RSS 的源，可借助 [RSSHub](https://docs.rsshub.app/) 生成：

```yaml
- name: "某平台"
  url: "https://example.com/"
  rss: "https://rsshub.app/example/route"
```

### 修改更新频率

编辑 `.github/workflows/build.yml` 中的 cron 表达式。

### 使用自己的 RSSHub 实例

如果公共 RSSHub 不稳定，可以自建实例，然后批量替换 `feeds.yaml` 中的 `rsshub.app` 为你的域名。

## 本地开发

```bash
pip install -r requirements.txt
python scripts/fetch_news.py
# 生成的页面在 output/index.html
```

## 技术栈

- **Python 3.11** + feedparser + Jinja2
- **GitHub Actions** 定时构建
- **GitHub Pages** 静态部署
- **RSSHub** 为无 RSS 源生成订阅

## License

MIT
