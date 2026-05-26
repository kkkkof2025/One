# Project Memory

## Stable Facts

- 项目名是 `One`，目标是维护一个可自动扩展、适合 AI 继续加工的“万物知识树”。
- 当前主数据入口是 `data/root.json`。
- 大节点拆到 `data/nodes/*.json`，父节点通过 `data_source` 指向子文件。
- 生长统计写入 `data/stats.json`，历史生长记录写入 `data/growth_history.json`。
- 扫描游标写入 `data/scan_state.json`，终止节点清单写入 `data/end_nodes.json`。
- GitHub Pages 静态接口镜像写入 `data/api/`，其中 `by-id/<id>/node.json` 和 `by-id/<id>/children.json` 是按节点 id 调用的稳定别名。
- 静态接口调用层写入 `data/api/client.js`，外部脚本可用 `OneKnowledgeApi.getChildren("Q1")`、`getNode()`、`getEndNode()` 和 `getScanState()` 读取数据。
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
- 自动扩展主流程采用多来源策略，默认按 Wikidata Query Service、Wikidata API、维基百科分类和 ConceptNet 的顺序尝试，优先使用 QID，减少中文同名词条造成的误匹配。
- 自动扩展不能只查 `P279` 子类；当前策略版本 `4` 会先用 WDQS 查 `P279`、`P31`、`P361`、`P527`、`P2670`，WDQS 受限时回退到 Wikidata API 的直接 `P527` / `P2670` 声明、维基百科分类和 ConceptNet。
- 保留 `万物.txt` 作为人工维护的文本样例和导入来源，但不再让 Pages 部署依赖 `output/knowledge_tree.html`。
- `scripts/grow_json.py` 的请求预算通过 `ONE_MAX_REQUESTS` 控制，默认每次最多请求 5 次；Wikidata 还有单独的最小间隔和 429 冷却。
- 初始根节点是“万物”，种子节点是 Wikidata 的 `Q1`（宇宙）和 `Q3`（生命）。
- 每次运行后统计总节点数，并向 `data/growth_history.json` 追加 `run_at`、`added_nodes`、`total_nodes`，不记录节点详情。
- `data/scan_state.json` 现在还会记录 `source_order`、`available_sources`、`source_request_counts`、`source_outcome_counts`、`source_cooldowns`、`candidate_source_summary` 和 `last_stop_reason`，用于避免限流后重复撞同一来源。

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
- `data/validation_allowlist.json` 记录人工确认过的合法重复 QID；当前允许暗物质、暗能量，以及 M84、M86、本星系群、矩尺座星系团、巨型超大类星体群、寄生等 8 个节点的合法多路径。
- `tests/test_validate_data.py` 覆盖有效分片、坏 JSON、断开的 `data_source`、循环引用、schema 漂移、重复 ID warning 和重复 ID 允许列表。
- `index.html` 顶部新增增长统计、复核队列、搜索、状态过滤、全局路径面包屑、节点来源详情，以及 AI 上下文 Markdown/JSON 复制和下载；导出内容包含当前节点、父路径、子节点摘要和来源字段。
- 页面复核队列支持按复核状态、加载状态和质量原因筛选；每个队列项可以复制 `review_key`，并可点击带入全局搜索。
- 页面复核队列会读取 `review_queue.json` 中的 `decision_file` 和 `reason_distribution`，显示复核队列生成时间、已处理决策数、最近处理时间、被决策隐藏的候选数，以及当前队列的原因分布。

## Decisions Made On 2026-05-14

- 自动增长改为先收集全树可请求候选，再根据 `data/scan_state.json` 的 `last_scan_key` 轮转请求，避免每天从同一批高优先级分支重新扫描。
- 当前抓取策略下成功查询但没有子节点的节点会写入 `data/end_nodes.json`，并在节点上保留 `is_leaf=true`、`end_reason` 和 `ended_at`；不同来源会写入对应的 `*_no_children` 或 `sources_no_children`，抓取策略版本不变时不会再次请求这类节点。
- `scripts/grow_json.py` 会生成 `data/api/` 静态接口镜像：`index.json` 返回路径模板，`root.json` 返回根节点，`by-id/<id>/node.json` 返回节点，`by-id/<id>/children.json` 返回子节点摘要，`by-id/<id>/schedule.json` 返回节点调度状态，`by-id/<id>/index.json` 返回该节点接口索引，`nodes/Q....json` 和 `children/nodes/Q....json` 保留旧镜像路径，`getEndNode.json` 返回终止节点清单。
- 页面读取数据时优先使用 `data/api/by-id/`，缺少接口文件时回退到旧的 `data/api/nodes/*.json`、`data/root.json` 和 `data/nodes/*.json`，以便旧部署仍可打开。
- 页面顶部新增终止节点统计；节点详情工具区可以复制节点接口、子节点接口和终止节点接口 URL。
- `scripts/generate_review_queue.py export` 可以按复核原因和节点状态批量导出 CSV、JSONL 或 Markdown，默认导出 `non_zh_label` 缺中文标签项。
- `review_queue.json` 的每个队列项会包含 `primary_reason` 和 `primary_reason_label`；页面复核队列会优先展示这个首要复核原因。
- 数据校验和质量评分都会把多个 `data_source` 指针视为多个逻辑路径，但不会把指针目标文件额外重复计算；合法多路径通过 `data/validation_allowlist.json` 消除 warning 和质量扣分。

## Decisions Made On 2026-05-22

- 线上 2026-05-22 的 `stats.json` 显示 `total_nodes=193`、最近发布为 `ONE_MAX_REQUESTS=0` 的无请求刷新；停滞主因是之前 WDQS 429 后反复扫同一批 error 节点，且补充来源查空可能过早封存节点。
- `scripts/grow_json.py` 的抓取策略版本升级到 `4`，默认来源顺序为 `wikidata,wikidata_api,wikipedia,conceptnet`；新增 `ONE_WIKIDATA_API_ENDPOINT`，用 Wikidata Action API 读取当前 QID 的直接 `P527` / `P2670` 声明，减少对 WDQS 的单点依赖。
- `fetch_strategy_version` 升级时旧扫描游标会自动失效，下一轮从新策略下的最高优先级候选重新开始；同策略内仍按 `last_scan_key` 轮转，避免重复扫同一批分支。
- 节点新增 `source_no_children` 映射，记录每个已成功查空来源的检查时间；后续扫描会跳过这些来源，但只有所有支持来源都查空时才写入全局终止状态和 `data/end_nodes.json`。
- 旧的 `wikidata_no_children` 叶子会迁移成 `source_no_children.wikidata`，如果新策略下还有 Wikipedia、ConceptNet 或 Wikidata API 可尝试，会重新变为 `pending`，不会继续被当成最终终止节点。
- 429、502、503、504 和超时会写入 `source_cooldowns`；临时来源错误默认只冷却 600 秒，429 默认冷却 3600 秒。节点即使请求失败也会在消耗请求后推进扫描游标，避免下一轮总是卡在同一个分支；手动排查时可用 `ONE_IGNORE_SOURCE_COOLDOWN=1` 清空当前冷却。
- 页面节点详情和 AI 上下文导出会展示 `source_no_children`，静态 API 摘要也保留该字段；v5 起页面也展示 `source_checked`。

## Decisions Made On 2026-05-23

- 线上增长到 `total_nodes=199` 后，连续两次 `max_requests=5` 出现 0 增长；日志显示小预算被同一个低产节点的多个来源和已有子节点的重复结果消耗。
- `scripts/grow_json.py` 的抓取策略版本升级到 `5`，默认来源顺序改为 `wikidata_api,wikipedia,wikidata,conceptnet`，优先使用较轻的 API 和分类补充，降低 WDQS 的等待和限流影响。
- 新增 `ONE_MAX_SOURCES_PER_NODE`，默认 `1`；每轮同一个节点最多尝试 1 个来源，避免 5 次请求预算被一个节点吃完。设为 `0` 可恢复“不限制”，适合人工彻底排查单个节点。
- 节点新增 `source_checked` 映射，记录已经成功检查过的来源；如果某个来源只返回已有子节点，也会被跳过，不再把整个节点提前标成当前策略完成，后续仍可尝试其它来源。
- `data/api/by-id/<id>/` 对非 QID 节点使用 URL 编码后的目录名，避免 Wikipedia / ConceptNet ID 中的冒号、斜杠或中文在 Windows 上写入失败；页面读取 by-id 接口时也会编码 ID。
- `write_static_api()` 改为先写入临时 API 目录，全部成功后再替换 `data/api/`，避免中途异常导致已发布的静态接口镜像被删除一半。

## Decisions Made On 2026-05-24

- 新建的非 QID 节点分片不再只按标题命名，而是使用标题加来源 ID 短哈希，避免 Wikipedia、ConceptNet 等补充来源出现同名节点时写入同一个 `data/nodes/<标题>.json`。
- 为了兼容已有数据，如果旧标题分片已经存在且其中的 `id` 与当前节点一致，`node_file_for()` 会继续返回旧路径，不会主动迁移或复制现有分片。
- `write_static_api()` 会生成 `data/api/client.js`，暴露 `OneKnowledgeApi.getRoot()`、`getNode(node)`、`getChildren(node)` 和 `getEndNode()`；这是 GitHub Pages 上的静态调用层，用来模拟带入参的接口。
- `index.html` 会优先使用 `data/api/client.js` 读取根节点、节点、子节点和终止节点；客户端缺失或请求失败时仍回退到旧的静态 JSON 路径。

## Decisions Made On 2026-05-25

- `scripts/grow_json.py` 的抓取策略版本升级到 `6`，默认来源顺序为 `wikidata_api,wikipedia,wikidata,conceptnet,dbpedia`；DBpedia 放在最后，只作为分类层级备用来源，不提高默认请求预算或频率。
- 新增 `ONE_DBPEDIA_ENDPOINT`，默认使用 `https://dbpedia.org/sparql`；DBpedia 适配器只读取 `Category:* skos:broader <父分类>` 关系，生成 `dbpedia:` 前缀 ID 和 `dbpedia_category` 关系。
- DBpedia 请求继续复用统一的 `ONE_USER_AGENT`、来源冷却、`ONE_MAX_REQUESTS` 和 `ONE_MAX_SOURCES_PER_NODE` 控制；如果 DBpedia 不可用，会像其它来源一样进入冷却，不会阻塞整个增长流程。
- `scripts/grow_json.py` 的抓取策略版本升级到 `7`，候选排序新增 `source_progress`：已经成功检查过部分来源但尚未完成的节点会排在未开始节点前面，避免连续多轮全部预算都花在 `wikidata_api` 这类同一顺位来源上。扫描游标只在没有部分进度候选时继续按 `last_scan_key` 轮转。
- `scripts/grow_json.py` 的抓取策略版本再升级到 `8`，默认开启按候选“下一个可用来源”轮转分发，尽量把同一轮的请求散到不同来源；0 请求刷新也会按 `ONE_SCHEDULE_PREVIEW_REQUESTS` 生成 `candidate_source_summary.next_run_preview`，用于展示下一次正常增长会打哪些来源。`data/stats.json` 还会记录 `growth_efficiency_summary`，包括近几轮新增、请求、零增长连击和来源结果汇总。
- `data/scan_state.json`、`data/stats.json` 和 `data/growth_history.json` 写入 `candidate_source_summary`，包含 `source_progress_counts`、`next_source_counts`、`available_next_source_counts` 和 `blocked_by_cooldown`，用于解释 0 增长到底是来源冷却、候选进度不足，还是补充来源仍可尝试。
- 静态 API 新增 `data/api/getScanState.json` / `scanState.json` / `getStats.json` / `stats.json` / `getNextSchedule.json` / `nextSchedule.json` 和 `OneKnowledgeApi.getScanState()`、`getStats()`、`getNextSchedule()`；首页顶部新增扫描诊断面板，直接展示来源顺序、当前可用来源、候选进度、下个来源、来源结果和冷却状态。

## Decisions Made On 2026-05-26

- 静态 API 新增 `data/api/by-id/<id>/schedule.json` 和 `OneKnowledgeApi.getSchedule(node)`，用于按节点读取支持来源、已查来源、剩余来源、冷却状态、是否终止和下一可请求来源。
- 页面节点详情工具区新增“复制调度接口”，AI 上下文导出中的节点摘要也会带上 `api_schedule`，方便外部按节点调用。

## Data Schema Memory

节点常用字段：

- `id`: 外部知识库 ID。Wikidata 节点使用 `Q...`，补充来源可使用 `wikipedia:`、`conceptnet:` 或 `dbpedia:` 前缀。
- `title`: 展示标题。
- `children_status`: `pending`、`loaded`、`error` 或 `manual`。
- `children`: 子节点数组。
- `data_source`: 相对 `data/` 的 JSON 文件路径，用于懒加载。
- `is_leaf`: 已确认没有子节点时为 `true`。
- `updated_at`: 自动扩展脚本最后更新时间。
- `last_checked_at`: 最近一次请求外部知识库检查该节点的时间。
- `last_error`: 最近一次抓取失败原因。
- `fetch_strategy_version`: 最近一次成功扩展使用的抓取策略版本。
- `end_reason`: 终止原因；当前自动终止值可能是 `wikidata_no_children`、`wikidata_api_no_children`、`wikipedia_no_children`、`conceptnet_no_children`、`dbpedia_no_children` 或 `sources_no_children`。
- `source_no_children`: 已成功检查但没有返回子节点的来源映射；这些来源后续会被跳过，但不代表节点已经全局终止。
- `source_checked`: 已成功检查过的来源映射；这些来源后续会被跳过，避免重复消耗请求预算。
- `ended_at`: 节点被确认为终止节点的时间。
- `source_relation`: 节点来自外部来源的关系类型，例如 `subclass`、`instance`、`part_of`、`has_part`、`wikipedia_category`、`conceptnet_is_a` 或 `dbpedia_category`。
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
- workflow 的 `push` 触发只运行测试、数据校验和 Pages 部署，不运行增长和自动提交，避免 push 部署形成循环提交；定时和手动触发才会请求外部来源并提交生成数据。
- 如果 Wikidata Query Service 返回 429，先确认是不是冷却期内重复请求，再降低 `ONE_MAX_REQUESTS`、增大 `ONE_WIKIDATA_REQUEST_DELAY`，或保留默认 `ONE_SOURCE_ORDER=wikidata_api,wikipedia,wikidata,conceptnet,dbpedia` 让 WDQS 后置，并把 DBpedia 保持为最后备用来源。
- 如果 `树状图` 空白，先检查 jsDelivr 和 unpkg 的 ECharts CDN 是否可访问；页面其他视图不依赖这些 CDN。
- 提交前优先运行 `python -m unittest discover -s tests` 和 `python scripts/validate_data.py`。
- 数据增长后运行 `python scripts/generate_review_queue.py`，再运行 `python scripts/validate_data.py`。
- 只刷新扫描状态、终止节点和静态 API 镜像时，可以运行 `ONE_MAX_REQUESTS=0 python scripts/grow_json.py`，不会请求外部来源。
- 观察增长变慢时，先看 `data/scan_state.json` 的 `candidate_count`、`selected_count`、`exhausted`、`candidate_source_summary`、`source_cooldowns` 和 `max_sources_per_node`，再看节点的 `source_checked` / `source_no_children` 是否只剩少数来源可试，以及 `data/end_nodes.json` 是否持续增加。
- 2026-05-20 排查线上停滞时确认：GitHub Pages 已部署到 2026-05-19 的 Auto-grow 结果，但从 2026-05-13 起 `added_nodes=0`；旧远端脚本没有扫描游标、终止节点清单和来源冷却，会反复请求同一批 `error` 节点并记录 WDQS 429。
- 处理复核队列时先看页面或 `review_queue.json.reason_distribution` 的原因分布，再用页面显示的 `review_key` 调用 `python scripts/review_decision.py mark --key ... --status ... --reason "..."`；需要加入人工关注时加 `--sync-curation`，需要确认合法重复 QID 时加 `--sync-allowlist`。
- 集中处理缺中文标签时，运行 `python scripts/generate_review_queue.py export --reason non_zh_label --format csv --output output/review_missing_zh.csv` 导出表格。
- 如果校验报告出现新的重复 ID warning，先确认它是合法多路径还是数据问题；合法多路径可以写入 `data/validation_allowlist.json` 并补充原因。
- 新的人工关注节点优先通过 `python scripts/curate_node.py focus --id Q... --reason "..."` 写入 `data/curation.json`；只有需要强制覆盖默认排序时才直接改节点的 `expansion_priority`。

_Last updated: 2026-05-26_
