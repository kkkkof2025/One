# Project Memory

## Stable Facts

- 项目名是 `One`，目标是维护一个可自动扩展、适合 AI 继续加工的“万物知识树”。
- 当前主数据入口是 `data/root.json`。
- 大节点拆到 `data/nodes/*.json`，父节点通过 `data_source` 指向子文件。
- 生长统计写入 `data/stats.json`，历史生长记录写入 `data/growth_history.json`。
- 扫描游标写入 `data/scan_state.json`，终止节点清单写入 `data/end_nodes.json`。
- GitHub Pages 静态接口镜像写入 `data/api/`，其中 `by-id/<id>/node.json` 和 `by-id/<id>/children.json` 是按节点 id 调用的稳定别名。
- 人工策展信号写入 `data/curation.json`。
- 校验允许列表写入 `data/validation_allowlist.json`。
- 待复核节点队列写入 `data/review_queue.json`。
- 复核处理结果写入 `data/review_decisions.json`。
- 静态页面 `index.html` 优先读取 `data/api/by-id/` 下的接口式 JSON，再回退到 `data/api/root.json`、`data/api/nodes/*.json` 和原始 `data/root.json` / `data/nodes/*.json`。
- GitHub Actions workflow 是 `.github/workflows/grow-and-deploy.yml`。
- JSON 数据校验脚本是 `scripts/validate_data.py`。
- 离线单元测试位于 `tests/`，当前使用 `python -m unittest discover -s tests` 运行。

## Decisions Made On 2026-05-06

- 第二次或排队运行可能会基于旧的 `main` 提交启动；workflow 现在会在增长前切到 `origin/${GITHUB_REF_NAME}` 的最新状态，并在 push 被拒时 rebase 后重试。

- 取消原来的双 workflow 设计，避免两个定时任务同时修改/部署不同产物。
- 自动扩展主流程改用 Wikidata SPARQL，优先使用 QID，减少中文同名词条造成的误匹配。
- 自动扩展不能只查 `P279` 子类；当前策略版本 `2` 同时查 `P279`、`P31`、`P361`、`P527`、`P2670`，旧策略误判的空叶子会重新抓取。
- 保留 `万物.txt` 作为人工维护的文本样例和导入来源，但不再让 Pages 部署依赖 `output/knowledge_tree.html`。
- `scripts/grow_json.py` 的请求预算通过 `ONE_MAX_REQUESTS` 控制，默认每次最多请求 20 次。
- 初始根节点是“万物”，种子节点是 Wikidata 的 `Q1`（宇宙）和 `Q3`（生命）。
- 每次运行后统计总节点数，并向 `data/growth_history.json` 追加 `run_at`、`added_nodes`、`total_nodes`，不记录节点详情。

## Decisions Made On 2026-05-07

- `index.html` 新增 `树状图` 视图，按需从 ECharts CDN 加载脚本；当前配置优先用 jsDelivr，失败或超时后回退到 unpkg，不影响默认 `云球` 和 `经典树` 视图。
- `树状图` 只主动加载当前选中节点，并显示直接父节点、兄弟层和选中节点下一层；已经展开的兄弟分支会保留，超出节点预算或渲染变慢时再自动收起较旧分支。
- `树状图` 使用 ECharts `tree` series 的纵向布局和 `roam` 缩放/平移；缩放到更小视野时允许更多已加载层，慢渲染时提高最小缩放比例并降低节点预算。
- `scripts/grow_json.py` 引入 `quality_score`、`quality_reasons`、`quality_version` 和 `review_status`；低于阈值的节点进入 `needs_review`，默认不继续自动扩展。
- 自动扩展候选节点现在按 `expansion_priority`、质量分、节点状态、关系类型和深度排序；人工 `expansion_priority` 可以覆盖默认排序。
- `data/curation.json` 记录人工关注节点；`focused_node_ids` 和 `focused_titles` 会提高节点质量分，并通过 `ONE_FOCUS_PRIORITY_BONUS` 或条目级 `priority_bonus` 提高默认扩展优先级。
- `scripts/curate_node.py` 提供人工关注节点的轻量编辑流程：`focus`、`unfocus` 和 `list`。
- 质量评分版本升级到 `3`，新增过度泛化标题、消歧义标题、重复风险、人工复核和人工关注信号；允许列表中的合法重复 ID 会写入 `allowed_duplicate_id:N`，未允许的重复 ID 会写入 `duplicate_id:N` 并扣分。
- workflow 在增长前运行离线测试和现有数据校验，在增长后再次运行数据校验，减少坏 JSON 或 schema 漂移进入 Pages。
- `scripts/validate_data.py` 会检查坏 JSON、断开的 `data_source`、缺失标题、状态枚举、质量字段和 schema 漂移；重复 ID 目前是 warning，不直接失败。
- `scripts/generate_review_queue.py` 会生成 `data/review_queue.json`，收集 `needs_review`、低质量、错误、重复风险、消歧义、过度泛化和缺少中文标签等节点，并给出建议动作；同时写入 `reason_distribution`，汇总缺中文、重复风险、加载错误、低质量分等主要复核原因。
- `scripts/review_decision.py` 会维护 `data/review_decisions.json`；状态为 `confirmed`、`curated`、`allowlisted`、`ignored` 或 `deferred` 的 `review_key` 会从后续复核队列中过滤。显式使用 `--sync-curation` 时，`curated` 会同步写入 `data/curation.json`；显式使用 `--sync-allowlist` 时，`allowlisted` 会同步写入 `data/validation_allowlist.json`。
- `scripts/review_decision.py list --status <status>` 可以按复核处理状态过滤记录；`--status` 可重复使用。
- `data/validation_allowlist.json` 记录人工确认过的合法重复 QID；当前允许暗物质、暗能量，以及 M84、M86、本星系群、矩尺座星系团、巨型超大类星体群等 7 个节点的合法多路径。
- `tests/test_validate_data.py` 覆盖有效分片、坏 JSON、断开的 `data_source`、循环引用、schema 漂移、重复 ID warning 和重复 ID 允许列表。
- `index.html` 顶部新增增长统计、复核队列、搜索、状态过滤、全局路径面包屑、节点来源详情，以及 AI 上下文 Markdown/JSON 复制和下载；导出内容包含当前节点、父路径、子节点摘要和来源字段。
- 页面复核队列支持按复核状态、加载状态和质量原因筛选；每个队列项可以复制 `review_key`，并可点击带入全局搜索。
- 页面复核队列会读取 `review_queue.json` 中的 `decision_file` 和 `reason_distribution`，显示复核队列生成时间、已处理决策数、最近处理时间、被决策隐藏的候选数，以及当前队列的原因分布。

## Decisions Made On 2026-05-14

- 自动增长改为先收集全树可请求候选，再根据 `data/scan_state.json` 的 `last_scan_key` 轮转请求，避免每天从同一批高优先级分支重新扫描。
- 当前抓取策略下成功查询但没有子节点的节点会写入 `data/end_nodes.json`，并在节点上保留 `is_leaf=true`、`end_reason=wikidata_no_children` 和 `ended_at`；抓取策略版本不变时不会再次请求这类节点。
- `scripts/grow_json.py` 会生成 `data/api/` 静态接口镜像：`index.json` 返回路径模板，`root.json` 返回根节点，`by-id/<id>/node.json` 返回节点，`by-id/<id>/children.json` 返回子节点摘要，`by-id/<id>/index.json` 返回该节点接口索引，`nodes/Q....json` 和 `children/nodes/Q....json` 保留旧镜像路径，`getEndNode.json` 返回终止节点清单。
- 页面读取数据时优先使用 `data/api/by-id/`，缺少接口文件时回退到旧的 `data/api/nodes/*.json`、`data/root.json` 和 `data/nodes/*.json`，以便旧部署仍可打开。
- 页面顶部新增终止节点统计；节点详情工具区可以复制节点接口、子节点接口和终止节点接口 URL。
- `scripts/generate_review_queue.py export` 可以按复核原因和节点状态批量导出 CSV、JSONL 或 Markdown，默认导出 `non_zh_label` 缺中文标签项。
- `review_queue.json` 的每个队列项会包含 `primary_reason` 和 `primary_reason_label`；页面复核队列会优先展示这个首要复核原因。
- 数据校验和质量评分都会把多个 `data_source` 指针视为多个逻辑路径，但不会把指针目标文件额外重复计算；合法多路径通过 `data/validation_allowlist.json` 消除 warning 和质量扣分。

## Data Schema Memory

节点常用字段：

- `id`: 外部知识库 ID。Wikidata 节点使用 `Q...`。
- `title`: 展示标题。
- `children_status`: `pending`、`loaded`、`error` 或 `manual`。
- `children`: 子节点数组。
- `data_source`: 相对 `data/` 的 JSON 文件路径，用于懒加载。
- `is_leaf`: 已确认没有子节点时为 `true`。
- `updated_at`: 自动扩展脚本最后更新时间。
- `last_checked_at`: 最近一次请求外部知识库检查该节点的时间。
- `last_error`: 最近一次抓取失败原因。
- `fetch_strategy_version`: 最近一次成功扩展使用的抓取策略版本。
- `end_reason`: 终止原因；当前自动终止值是 `wikidata_no_children`。
- `ended_at`: 节点被确认为终止节点的时间。
- `source_relation`: 节点来自 Wikidata 的关系类型。
- `quality_score`: 自动质量评分，范围 `0` 到 `100`。
- `quality_reasons`: 质量评分原因列表。
- `quality_version`: 质量评分规则版本。
- `review_status`: `approved` 或 `needs_review`。
- `manual_review`: 人工复核标记；用于保留人工判断。
- `expansion_priority`: 人工扩展优先级，可覆盖默认候选排序。

## Maintenance Memory

- 本地预览页面要通过 HTTP 服务打开，直接双击 HTML 会让 `fetch()` 读取 JSON 失败。
- GitHub Actions cron 的 `0 0 * * *` 是 UTC 每天 00:00，也就是北京时间每天 08:00。
- 部署使用 GitHub Pages 官方 artifact 流程，仓库 Pages 设置需要选择 `GitHub Actions` 作为来源。
- workflow 的 `push` 触发只运行测试、数据校验和 Pages 部署，不运行增长和自动提交，避免 push 部署形成循环提交；定时和手动触发才会请求 Wikidata 并提交生成数据。
- 如果 Wikidata Query Service 返回错误，先降低 `ONE_MAX_REQUESTS` 或增加 `ONE_REQUEST_DELAY`。
- 如果 `树状图` 空白，先检查 jsDelivr 和 unpkg 的 ECharts CDN 是否可访问；页面其他视图不依赖这些 CDN。
- 提交前优先运行 `python -m unittest discover -s tests` 和 `python scripts/validate_data.py`。
- 数据增长后运行 `python scripts/generate_review_queue.py`，再运行 `python scripts/validate_data.py`。
- 只刷新扫描状态、终止节点和静态 API 镜像时，可以运行 `ONE_MAX_REQUESTS=0 python scripts/grow_json.py`，不会请求 Wikidata。
- 观察增长变慢时，先看 `data/scan_state.json` 的 `candidate_count`、`selected_count`、`exhausted`，再看 `data/end_nodes.json` 是否持续增加。
- 2026-05-20 排查线上停滞时确认：GitHub Pages 已部署到 2026-05-19 的 Auto-grow 结果，但从 2026-05-13 起 `added_nodes=0`；旧远端脚本没有扫描游标和终止节点清单，会反复请求同一批 `error` 节点并记录 WDQS 429。
- 处理复核队列时先看页面或 `review_queue.json.reason_distribution` 的原因分布，再用页面显示的 `review_key` 调用 `python scripts/review_decision.py mark --key ... --status ... --reason "..."`；需要加入人工关注时加 `--sync-curation`，需要确认合法重复 QID 时加 `--sync-allowlist`。
- 集中处理缺中文标签时，运行 `python scripts/generate_review_queue.py export --reason non_zh_label --format csv --output output/review_missing_zh.csv` 导出表格。
- 如果校验报告出现新的重复 ID warning，先确认它是合法多路径还是数据问题；合法多路径可以写入 `data/validation_allowlist.json` 并补充原因。
- 新的人工关注节点优先通过 `python scripts/curate_node.py focus --id Q... --reason "..."` 写入 `data/curation.json`；只有需要强制覆盖默认排序时才直接改节点的 `expansion_priority`。

_Last updated: 2026-05-20_
