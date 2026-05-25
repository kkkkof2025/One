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

1. 每天 UTC 00:00 自动运行，也就是北京时间 08:00；推送到 `main` 时也会运行一次部署流程。
2. 安装 Python 依赖。
3. 运行离线单元测试。
4. 校验现有 JSON 数据。
5. 定时或手动触发时运行 `python scripts/grow_json.py`，按 Wikidata API、维基百科分类、Wikidata Query Service、ConceptNet 和 DBpedia 分类的顺序尝试增长。
6. 定时或手动触发时运行 `python scripts/generate_review_queue.py` 生成复核队列。
7. 定时或手动触发时再次校验生成后的 JSON 数据。
8. 定时或手动触发时如果 `data/` 有变化，自动提交到当前分支。
9. 打包 `index.html` 和 `data/`。
10. 部署到 GitHub Pages。

推送触发只部署当前仓库里的 `index.html` 和 `data/`，不会请求外部来源，也不会提交派生数据，避免部署流程形成循环提交。也可以在 GitHub Actions 页面手动触发，并通过 `max_requests` 控制单次最多请求外部来源的次数，通过 `max_sources_per_node` 控制单个节点本轮最多尝试几个来源，或用 `source_order` 临时跳过不可用来源。

增长脚本不会只依赖单一“子类”关系。当前会先用 Wikidata API 读取直接 `P527` / `P2670` 声明，再尝试维基百科分类、Wikidata Query Service 的 `P279`（subclass of）、`P31`（instance of）、`P361`（part of）、`P527`（has part）和 `P2670`（has parts of the class），最后把 ConceptNet 和 DBpedia 分类作为低优先级补充来源；如果某个来源限流或 5xx，会记录来源冷却并让后续节点尝试其它来源。旧策略误判为空叶子的节点会迁移为 `source_no_children.wikidata`，只跳过已查空来源，仍允许补充来源继续尝试。

增长脚本会先收集当前所有可扩展候选节点，再根据 `data/scan_state.json` 里的 `last_scan_key` 从上次结束位置之后继续轮转请求，避免每天都从同一批高优先级分支开头扫描。默认每个节点每轮只尝试 1 个来源，防止 5 次预算被同一个低产节点吃完；已经查过部分来源但还没完成的节点会优先继续尝试下一个来源，避免所有候选都先消耗在同一个低产来源上。成功检查过的来源会写入 `source_checked`，没有返回子节点的来源还会写入 `source_no_children`。只有当前策略里的支持来源都检查完且没有子节点后，节点才会写入 `data/end_nodes.json`，并标记 `is_leaf`、`end_reason` 和 `ended_at`。

当 `fetch_strategy_version` 升级时，旧扫描游标会自动失效，下一轮会从新策略下的最高优先级候选重新开始，避免新策略仍被旧游标卡在低收益分支后面。

## 目录结构

```text
.
├── .github/workflows/grow-and-deploy.yml  # 定时增长并部署 GitHub Pages
├── data/
│   ├── root.json                          # 页面和脚本的主数据入口
│   ├── stats.json                         # 当前总节点数和最近一次增长统计
│   ├── growth_history.json                # 历史生长记录
│   ├── scan_state.json                    # 自动增长扫描游标和候选统计
│   ├── end_nodes.json                     # 已确认不可继续扩展的终止节点
│   ├── curation.json                      # 人工关注节点和策展信号
│   ├── validation_allowlist.json           # 数据校验允许列表
│   ├── review_queue.json                  # 待人工复核节点队列
│   ├── api/                               # GitHub Pages 静态 API 形式的数据镜像
│   │   └── by-id/                         # 按节点 id 暴露的稳定接口别名
│   └── nodes/                             # 懒加载子节点分片
├── scripts/grow_json.py                   # 多来源增量扩展脚本
├── scripts/validate_data.py               # JSON 数据校验脚本
├── scripts/curate_node.py                 # 人工关注节点维护脚本
├── scripts/generate_review_queue.py       # 生成待复核节点队列
├── scripts/review_decision.py             # 记录复核处理结果
├── tests/                                 # 离线单元测试
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

`data/stats.json` 保存当前总节点数、最近一次新增节点数、终止节点数、请求数和统计生成时间。`data/growth_history.json` 按运行时间追加历史记录，记录新增节点、总节点、请求数、候选数和终止节点数，不记录节点详情。

`data/scan_state.json` 保存自动增长的扫描游标、候选数量、请求数量、来源顺序和来源冷却状态。它让下一次运行从 `last_scan_key` 后面继续，而不是每次从同一批节点重新开始；如果某个来源被限流，脚本会先记录冷却时间，下次优先跳过它。

`data/end_nodes.json` 保存已经通过当前抓取策略确认没有可扩展子节点的节点清单。页面和后续脚本可以直接读取它，避免把终止节点混入下一轮扫描。`source_no_children` 只表示某个来源已查空，不等同于全局终止。

`data/api/` 是面向 GitHub Pages 的静态接口镜像。它不是真正的后端服务，但路径设计成接口形式，方便页面和外部脚本调用：

- `data/api/index.json`: 返回可用接口和路径模板。
- `data/api/client.js`: 浏览器或脚本可加载的静态调用层，暴露 `OneKnowledgeApi.getNode()`、`getChildren()` 和 `getEndNode()`。
- `data/api/root.json`: 返回根节点。
- `data/api/by-id/root/node.json`: 返回根节点的按 id 接口别名。
- `data/api/by-id/Q1/node.json`: 返回指定节点完整数据。
- `data/api/by-id/Q1/children.json`: 返回指定节点的子节点摘要。
- `data/api/by-id/Q1/index.json`: 返回指定节点的接口索引，包含节点、子节点和旧路径回退信息。
- `data/api/nodes/Q1.json`: 保留旧节点镜像路径。
- `data/api/children/nodes/Q1.json`: 保留旧子节点镜像路径。
- `data/api/getEndNode.json`: 返回终止节点清单，等价于 `data/api/endNode.json`。

`by-id` 接口对普通 QID 保持原样，例如 `Q1`；如果节点 ID 来自 Wikipedia、ConceptNet 或 DBpedia，包含冒号、斜杠或中文等特殊字符，目录名会使用 URL 编码，页面会自动按编码后的路径读取。

新建的非 QID 分片会在标题后追加来源 ID 的短哈希，例如 `寄生-xxxxxxxxxxxx.json`。这可以避免 Wikipedia、ConceptNet 和 DBpedia 等补充来源出现同名节点时写入同一个 `data/nodes/<标题>.json`；已经存在且 ID 匹配的旧标题分片会继续沿用，不做破坏性迁移。

外部页面可以直接加载静态调用层，不需要知道具体目录编码规则：

```html
<script src="https://kkkkof2025.github.io/One/data/api/client.js"></script>
<script>
  OneKnowledgeApi.getChildren("Q1").then(console.log);
  OneKnowledgeApi.getEndNode().then(console.log);
</script>
```

在 Node.js 或其它脚本环境中，也可以传入 `baseUrl` 和自定义 `fetch`：`OneKnowledgeApi.getNode("Q1", { baseUrl: "https://kkkkof2025.github.io/One/data/api/" })`。

`data/validation_allowlist.json` 保存人工确认过的校验例外。当前用于记录合法重复 QID，例如同一个 Wikidata 节点合理地出现在多条分类路径中；没有进入允许列表的新重复 ID 仍会作为 warning 报告。

`data/curation.json` 保存人工关注节点。增长脚本会把其中的 `focused_node_ids` 和 `focused_titles` 作为策展信号，提高对应节点的质量分和默认扩展优先级；单个节点上的 `expansion_priority` 仍然是更强的人工覆盖。

`data/review_queue.json` 保存待复核节点队列，由 `scripts/generate_review_queue.py` 生成。队列会收集 `needs_review`、低质量、错误、重复风险、消歧义、过度泛化和缺少中文标签等节点，并给出建议动作；同时写入 `reason_distribution`，按缺中文、重复风险、加载错误、低质量分等维度统计当前队列主要原因。

`data/review_decisions.json` 保存复核处理结果。队列项中的 `review_key` 可以用于记录确认、暂缓、已加入人工关注或已加入允许列表等状态；被记录的节点会从后续复核队列中隐藏。使用显式同步参数时，`curated` 可同时写入 `data/curation.json`，`allowlisted` 可同时写入 `data/validation_allowlist.json`。

维护人工关注节点：

```bash
python scripts/curate_node.py focus --id Q1 --reason "主干节点" --priority-bonus 24
python scripts/curate_node.py focus --title "人工节点" --reason "人工策展"
python scripts/curate_node.py unfocus --id Q1
python scripts/curate_node.py list
```

常用字段：

- `id`: 外部知识库 ID。Wikidata 节点使用 `Q...`，Wikipedia / ConceptNet / DBpedia 补充节点会使用带来源前缀的 ID。
- `title`: 节点标题。
- `children_status`: 子节点状态，取值为 `pending`、`loaded`、`error` 或 `manual`。
- `children`: 子节点数组。
- `data_source`: 相对 `data/` 的 JSON 路径，用于页面懒加载。
- `is_leaf`: 已确认没有子节点时为 `true`。
- `updated_at`: 自动扩展脚本更新时间。
- `last_checked_at`: 最近一次请求外部知识库检查该节点的时间。
- `last_error`: 最近一次扩展失败原因。
- `fetch_strategy_version`: 最近一次成功扩展使用的抓取策略版本。
- `end_reason`: 终止原因。常见自动终止值包括 `wikidata_no_children`、`wikidata_api_no_children`、`wikipedia_no_children`、`conceptnet_no_children`、`dbpedia_no_children` 和 `sources_no_children`。
- `source_no_children`: 已成功检查但没有返回子节点的来源映射，key 是来源名，value 是检查时间；这些来源后续会被跳过。
- `source_checked`: 已成功检查过的来源映射，key 是来源名，value 是检查时间；即使该来源只返回了已有子节点，也会被记录，避免后续重复消耗请求预算。
- `source_provider`: 节点来自哪个外部来源，例如 `wikidata`、`wikidata_api`、`wikipedia`、`conceptnet`、`dbpedia`。
- `ended_at`: 节点被确认为终止节点的时间。
- `source_relation`: 节点来自外部来源的哪类关系，例如 `subclass`、`instance`、`part_of`、`has_part`、`wikipedia_category`、`conceptnet_is_a`、`dbpedia_category`。
- `source_url`: 节点对应的外部来源 URL。
- `last_fetch_source` / `last_fetch_sources`: 最近一次成功检查过的来源。
- `quality_score`: 自动计算的节点质量分，范围 `0` 到 `100`。
- `quality_reasons`: 质量评分原因列表。
- `quality_version`: 质量评分规则版本。
- `review_status`: `approved` 或 `needs_review`。低质量节点默认不会继续自动扩展。
- `manual_review`: 人工确认标记；配合 `review_status` 保留人工判断。
- `expansion_priority`: 人工指定扩展优先级，可覆盖默认排序。

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

如果只想刷新终止节点、扫描状态和静态 API 镜像，不请求外部来源：

```bash
ONE_MAX_REQUESTS=0 python scripts/grow_json.py
```

限制单次请求数：

```bash
ONE_MAX_REQUESTS=5 python scripts/grow_json.py
```

运行离线测试：

```bash
python -m unittest discover -s tests
```

校验 JSON 数据：

```bash
python scripts/validate_data.py
```

生成复核队列：

```bash
python scripts/generate_review_queue.py
```

批量导出缺少中文标签的复核项：

```bash
python scripts/generate_review_queue.py export --reason non_zh_label --format csv --output output/review_missing_zh.csv
python scripts/generate_review_queue.py export --reason non_zh_label --format md --output output/review_missing_zh.md
```

记录复核处理：

```bash
python scripts/review_decision.py mark --key id:Q55621538 --status confirmed --reason "暂时接受英文星表名"
python scripts/review_decision.py mark --key id:Q14013 --status deferred --reason "等待人工补中文标题"
python scripts/review_decision.py mark --key id:Q1 --status curated --reason "主干节点" --sync-curation --priority-bonus 24
python scripts/review_decision.py mark --key id:Q79925 --status allowlisted --reason "合法多路径" --sync-allowlist
python scripts/review_decision.py remove --key id:Q14013
python scripts/review_decision.py list
python scripts/review_decision.py list --status deferred
```

本地预览静态页面：

```bash
python -m http.server 8000
```

然后打开 `http://localhost:8000/`。不要直接双击 `index.html`，因为浏览器通常会阻止本地 `fetch()` 读取 JSON。

页面包含三种视图：

- `云球`：围绕当前节点展示子节点和兄弟节点。
- `经典树`：使用 DOM 列表按需展开 JSON 分片。
- `树状图`：打开该视图时按需加载 ECharts，只渲染当前直接父层、兄弟层和选中节点的下一层；缩放到更小视野时允许展示更多已加载层，渲染变慢时会自动收起较旧分支。

页面顶部提供增长统计、终止节点数量、复核队列、搜索、状态过滤、全局路径面包屑、当前节点来源信息，以及 AI 上下文导出功能。当前节点工具区可以复制节点接口、子节点接口和终止节点接口 URL。复核队列支持按状态/原因筛选，显示已处理数量、最近处理时间和原因分布，并突出每条复核项的首要原因；每项可复制 `review_key` 供 `scripts/review_decision.py` 使用。AI 上下文可以复制或下载为 Markdown/JSON，包含当前节点、父路径、子节点摘要、静态接口路径、`data_source`、`source_provider`、`id`、`source_relation`、状态和更新时间。

## GitHub Pages 设置

仓库需要在 GitHub Pages 设置中选择 `GitHub Actions` 作为部署来源。workflow 会上传由 `index.html` 和 `data/` 组成的静态产物。推送到 `main` 会立即部署当前数据；每日定时和手动触发会先执行增长，再部署增长后的数据。

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

- `ONE_MAX_REQUESTS`: 单次运行最多请求来源次数，默认 `5`。
- `ONE_QUERY_LIMIT`: 单个节点最多返回子类数量，默认 `50`。
- `ONE_REQUEST_DELAY`: 非 Wikidata 来源之间的请求间隔秒数，默认 `5.0`。
- `ONE_WIKIDATA_REQUEST_DELAY`: Wikidata 两次请求之间的最小间隔秒数，默认 `65.0`。
- `ONE_GROWTH_HISTORY_LIMIT`: `data/growth_history.json` 最多保留多少条历史记录，默认 `365`。
- `ONE_WIKIDATA_ENDPOINT`: Wikidata SPARQL Endpoint。
- `ONE_WIKIDATA_API_ENDPOINT`: Wikidata Action API。
- `ONE_WIKIPEDIA_API_ENDPOINT`: 维基百科 API。
- `ONE_CONCEPTNET_API_ENDPOINT`: ConceptNet API。
- `ONE_DBPEDIA_ENDPOINT`: DBpedia SPARQL Endpoint。
- `ONE_USER_AGENT`: 请求 User-Agent。
- `ONE_SOURCE_ORDER`: 来源顺序，默认 `wikidata_api,wikipedia,wikidata,conceptnet,dbpedia`。
- `ONE_MAX_SOURCES_PER_NODE`: 单次运行中同一个节点最多尝试几个来源，默认 `1`；设为 `0` 表示不限制，适合人工彻底排查单个节点。
- `ONE_SOURCE_COOLDOWN_SECONDS`: 发生 429 或 5xx 临时错误后的默认冷却秒数，默认 `3600`。
- `ONE_TRANSIENT_SOURCE_COOLDOWN_SECONDS`: 发生 5xx 或超时等临时错误后的冷却秒数，默认 `600`。
- `ONE_IGNORE_SOURCE_COOLDOWN`: 设为 `1` / `true` / `yes` 时忽略并清空当前冷却状态，适合手动排查网络问题后刷新状态。
- `ONE_QUALITY_REVIEW_THRESHOLD`: 低于该质量分的节点会进入 `needs_review`，默认 `45`。
- `ONE_PRIORITY_SCAN_LIMIT`: 每层参与优先级排序的候选节点数，默认 `1000`。
- `ONE_FOCUS_PRIORITY_BONUS`: 人工关注节点默认扩展优先级加分，默认 `18`。
- `ONE_REVIEW_QUEUE_LIMIT`: 复核队列最多保留多少个节点，默认 `200`。
- `ONE_REVIEW_QUEUE_THRESHOLD`: 进入复核队列的质量分阈值，默认跟 `ONE_QUALITY_REVIEW_THRESHOLD` 一致。

GitHub Actions 定时运行建议保持 `ONE_MAX_REQUESTS` 在 `1` 到 `5` 之间，并保留默认的 Wikidata 冷却时间。需要手动补数据时可以在 workflow 手动触发里临时调高，但不建议长期大批量请求公共 SPARQL 服务。

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

## 已完成维护项

- 页面已支持搜索、状态过滤、全局路径面包屑、节点来源详情，以及 Markdown/JSON AI 上下文复制和下载。
- `scripts/validate_data.py` 已能检查坏 JSON、断开的 `data_source`、缺失标题、状态枚举、质量字段、重复 ID 和 schema 漂移。
- `tests/test_grow_json.py` 已覆盖去重、分片、指针更新、人工内容保留、质量评分和扩展优先级。
- `tests/test_validate_data.py` 已覆盖有效分片、坏 JSON、断开的 `data_source`、循环引用、schema 漂移、重复 ID warning 和重复 ID 允许列表。
- `tests/test_curate_node.py` 已覆盖人工关注节点的添加、移除和 QID 格式检查。
- `scripts/grow_json.py` 已引入质量评分、待审状态和优先级排序；低质量节点默认不继续自动扩展，人工 `expansion_priority` 可以覆盖。
- `data/curation.json` 已记录人工关注节点，并接入质量评分和默认扩展优先级。
- `scripts/curate_node.py` 已提供人工关注节点的轻量编辑流程。
- 质量评分已纳入过度泛化标题、消歧义标题、重复风险、人工复核和人工关注信号。
- `scripts/generate_review_queue.py` 已生成 `data/review_queue.json`，汇总待人工复核节点和建议动作。
- `scripts/generate_review_queue.py export` 已支持按原因/状态批量导出 CSV、JSONL 或 Markdown，默认导出缺少中文标签的复核项。
- `scripts/review_decision.py` 已记录复核处理结果，并让后续复核队列跳过已处理节点；`curated` / `allowlisted` 处理可显式同步到人工关注或重复 ID 允许列表，`list --status` 可按状态查看记录。
- 重复 ID 统计已按逻辑路径计数，多个 `data_source` 指针会被识别为多路径；当前合法多路径记录在 `data/validation_allowlist.json`。
- 页面已展示 `data/review_queue.json` 的复核队列，并可点击队列项带入搜索、按状态/原因筛选、复制 `review_key`、查看已处理数量、最近处理时间和原因分布。
- workflow 已在增长前运行离线测试和数据校验，并在增长后再次校验。
- `scripts/grow_json.py` 已新增扫描游标、终止节点清单和 `data/api/` 静态接口镜像；页面会优先通过接口式路径读取节点、子节点和终止节点。
- `scripts/grow_json.py` 已把终止判断改为按来源记录 `source_checked` 和 `source_no_children`；某个补充来源查空不会直接封存节点，旧 Wikidata 叶子会重新开放给补充来源。
- `scripts/grow_json.py` 已新增 DBpedia 分类层级作为最后备用来源，继续受请求预算、来源冷却和单节点来源上限控制。
- `scripts/grow_json.py` 的候选排序已改为优先补完已开始检查的节点，让同一节点尽快从 `wikidata_api` 轮到 Wikipedia、WDQS、ConceptNet 或 DBpedia，而不是把全部候选先过一遍同一来源。

## To-do

- 定期复核 `data/validation_allowlist.json`，移除已经不再重复出现的允许项。
- 扩展 `data/curation.json` 的人工关注列表，优先补充主干路径和人工维护过的节点。
- 观察 `data/scan_state.json` 的 `candidate_count`、`exhausted`、`source_cooldowns`、`source_request_counts` 和 `max_sources_per_node`，如果长期为 0，再考虑增加新的数据关系或人工种子节点。

## 已知限制

- Wikidata 的 `P279` 表示“属于某类/子类”，结果适合做目录扩展，但不等于人工精修分类。
- DBpedia 备用来源只读取分类层级的 `skos:broader` 关系，适合补洞，不作为高置信主干来源。
- 中文标签缺失时，部分节点可能暂时不会被收入结果。
- 当前质量评分仍是启发式规则，不能替代人工策展；`needs_review` 节点需要人工抽查。
- 页面只负责读取已生成的 JSON，不会在浏览器端实时请求 Wikidata。
- `树状图` 视图依赖 ECharts CDN，并配置了 jsDelivr 和 unpkg 两个加载地址；CDN 不可用时不会影响 `云球` 和 `经典树` 视图。
