# One

`One` 是一个通过 GitHub Actions 定时增长的“万物知识树”项目。它把根目录、数据分片、增长脚本和静态页面放在同一个仓库里，方便人和 AI 持续补充、校验、拆分和展示知识目录。

## 项目目标

- 维护一个从“万物”开始逐步扩展的目录总纲。
- 让 GitHub Actions 每天自动请求公开知识库，增量补充目录节点。
- 使用 JSON 分片保存大树，避免单个文件越来越大。
- 用静态页面直接展示知识树，适合部署到 GitHub Pages。
- 给后续 AI 留下任务记录和项目记忆，降低接手成本。

## 当前工作流

主流程位于 `.github/workflows/grow-and-deploy.yml`：

1. 每天 UTC 00:00 自动运行，也就是北京时间 08:00。
2. 安装 Python 依赖。
3. 运行 `python scripts/grow_json.py`。
4. 如果 `data/` 有变化，自动提交到当前分支。
5. 打包 `index.html` 和 `data/`。
6. 部署到 GitHub Pages。

也可以在 GitHub Actions 页面手动触发，并通过 `max_requests` 控制单次最多请求 Wikidata 的次数。

## 目录结构

```text
.
├── .github/workflows/grow-and-deploy.yml  # 定时增长并部署 GitHub Pages
├── data/
│   ├── root.json                          # 页面和脚本的主数据入口
│   └── nodes/                             # 懒加载子节点分片
├── scripts/grow_json.py                   # Wikidata 增量扩展脚本
├── index.html                             # 静态知识树页面
├── 万物.txt                               # 文本导入示例
├── generate_html_from_txt.py              # 从 万物.txt 生成独立 HTML
├── tree_builder_ml.py                     # 从 万物.txt 生成可分片 JSON
├── dynamic_expand_and_split.py            # 维基百科分类扩展辅助脚本
├── AGENTS.md                              # Agent 任务记录和协作规则
├── MEMORY.md                              # 项目长期记忆和数据约定
└── requirements.txt                       # Python 依赖
```

## 数据模型

`data/root.json` 是入口文件。较大的节点会被拆到 `data/nodes/*.json`，父节点使用 `data_source` 指向子文件。

常用字段：

- `id`: 外部知识库 ID。Wikidata 节点使用 `Q...`。
- `title`: 节点标题。
- `children_status`: 子节点状态，取值为 `pending`、`loaded`、`error` 或 `manual`。
- `children`: 子节点数组。
- `data_source`: 相对 `data/` 的 JSON 路径，用于页面懒加载。
- `is_leaf`: 已确认没有子节点时为 `true`。
- `updated_at`: 自动扩展脚本更新时间。
- `last_error`: 最近一次扩展失败原因。

示例：

```json
{
  "id": "Q1",
  "title": "宇宙",
  "data_source": "nodes/Q1.json",
  "children_status": "pending",
  "is_leaf": false
}
```

## 本地运行

安装依赖：

```bash
python -m pip install -r requirements.txt
```

增长 JSON 数据：

```bash
python scripts/grow_json.py
```

限制单次请求数：

```bash
ONE_MAX_REQUESTS=5 python scripts/grow_json.py
```

本地预览静态页面：

```bash
python -m http.server 8000
```

然后打开 `http://localhost:8000/`。不要直接双击 `index.html`，因为浏览器通常会阻止本地 `fetch()` 读取 JSON。

## GitHub Pages 设置

仓库需要在 GitHub Pages 设置中选择 `GitHub Actions` 作为部署来源。workflow 会上传由 `index.html` 和 `data/` 组成的静态产物。

workflow 需要这些权限：

- `contents: write`：提交自动增长后的 `data/`。
- `pages: write`：发布 GitHub Pages。
- `id-token: write`：使用 GitHub Pages 部署动作。

## 辅助脚本

`generate_html_from_txt.py` 从 `万物.txt` 生成 `output/knowledge_tree.html`，适合做离线静态快照。

`tree_builder_ml.py` 从 `万物.txt` 生成 `output/outline_tree/data.json`，并在超过阈值时拆分 JSON。

`dynamic_expand_and_split.py` 使用中文维基百科分类页做辅助扩展，输出到 `output/wiki_categories/`。主自动化流程不依赖它。

## 环境变量

`scripts/grow_json.py` 支持：

- `ONE_MAX_REQUESTS`: 单次运行最多请求 Wikidata 次数，默认 `20`。
- `ONE_QUERY_LIMIT`: 单个节点最多返回子类数量，默认 `50`。
- `ONE_REQUEST_DELAY`: 请求间隔秒数，默认 `1.0`。
- `ONE_WIKIDATA_ENDPOINT`: Wikidata SPARQL Endpoint。
- `ONE_USER_AGENT`: 请求 User-Agent。

维基百科辅助脚本支持：

- `ONE_WIKI_MAX_DEPTH`
- `ONE_WIKI_MAX_BRANCHES`
- `ONE_WIKI_REQUEST_DELAY`
- `ONE_WIKI_SPLIT_THRESHOLD_MB`

## AI 协作约定

- 先读 `AGENTS.md`，确认当前任务和协作规则。
- 再读 `MEMORY.md`，确认数据 schema、workflow 和历史决策。
- 修改数据结构时同步更新 README、MEMORY 和页面加载逻辑。
- 自动生成的数据尽量只改 `data/`，不要覆盖人工维护的说明文件。

## 已知限制

- Wikidata 的 `P279` 表示“属于某类/子类”，结果适合做目录扩展，但不等于人工精修分类。
- 中文标签缺失时，部分节点可能暂时不会被收入结果。
- 当前扩展策略偏确定性深度优先，后续可以增加优先级队列或质量评分。
- 页面只负责读取已生成的 JSON，不会在浏览器端实时请求 Wikidata。
