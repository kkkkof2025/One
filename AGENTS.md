# Agent Task Log

## Mission

这个仓库维护一个可持续增长的“万物知识树”。Agent 的主要任务是让数据、脚本、GitHub Actions 和静态页面保持一致，使项目可以被后续 AI 继续扩展。

## Current Task Record

- [x] 修复中文编码损坏导致的脚本路径、页面文案和数据标题错误。
- [x] 将两个互相重叠的定时 workflow 收敛为一个增长并部署的 workflow。
- [x] 把主数据入口统一为 `data/root.json`，并使用 `data/nodes/*.json` 做懒加载分片。
- [x] 重写 `scripts/grow_json.py`，优先使用 Wikidata QID 增量扩展目录。
- [x] 修复文本导入相关脚本：`generate_html_from_txt.py`、`tree_builder_ml.py`、`dynamic_expand_and_split.py`。
- [x] 重建 `index.html`，让它直接渲染 JSON 知识树。
- [x] 新增 `MEMORY.md` 记录项目决策和长期记忆。
- [x] 完善 `README.md`，补齐项目定位、结构、运行方式和维护流程。
- [x] 给 `scripts/grow_json.py` 增加离线单元测试，覆盖去重、分片、指针更新和人工内容保留。
- [x] 新增 `scripts/validate_data.py`，校验 JSON、`data_source`、标题、状态枚举、重复 ID 和 schema 漂移。
- [x] 给 `scripts/validate_data.py` 增加离线单元测试，覆盖坏 JSON、循环引用和 schema 漂移。
- [x] 新增 `data/validation_allowlist.json`，记录已人工确认的合法重复 QID。
- [x] 引入节点质量评分、待审状态和扩展优先级排序，减少自动增长噪声。
- [x] 新增 `data/curation.json` 记录人工关注节点，并接入质量评分和默认扩展优先级。
- [x] 新增 `scripts/curate_node.py`，提供人工关注节点的添加、移除和列表查看流程。
- [x] 增强质量评分，加入过度泛化标题、消歧义标题、重复风险、人工复核和人工关注信号。
- [x] 新增 `scripts/generate_review_queue.py` 和 `data/review_queue.json`，生成低质量/待审节点复核清单。
- [x] 新增 `scripts/review_decision.py` 和 `data/review_decisions.json`，记录复核处理结果并过滤已处理队列项。
- [x] 给页面增加复核队列、搜索、状态过滤、全局路径面包屑、节点来源详情和 AI 上下文导出。
- [x] 为页面复核队列增加状态/原因筛选和复制 `review_key` 的按钮。
- [x] 扩展 `scripts/review_decision.py`，让 `curated` 和 `allowlisted` 处理结果可选择同步写入 `data/curation.json` 或 `data/validation_allowlist.json`。
- [x] 在页面复核队列中展示已处理数量和最近处理时间，帮助人工复核时判断队列新鲜度。
- [x] 给 `scripts/review_decision.py list` 增加按状态过滤，便于查看已确认、暂缓或允许列表项。
- [x] 给 `scripts/generate_review_queue.py` 增加原因分布统计，帮助判断下一轮人工复核重点。
- [x] 给自动增长增加扫描游标，下一轮从上次扫描节点后继续，减少重复扫同一批分支。
- [x] 新增 `data/end_nodes.json`，记录当前策略下已确认不可继续扩展的终止节点。
- [x] 新增 `data/api/` 静态接口镜像，提供节点、子节点和终止节点的 GitHub Pages 读取路径。
- [x] 页面改为优先通过静态接口读取数据，并增加终止节点统计和接口 URL 复制按钮。
- [x] 给复核队列增加批量导出命令，支持按原因/状态导出 CSV、JSONL 或 Markdown。
- [x] 在页面复核队列中突出首要复核原因，方便人工先处理同类问题。
- [x] 修正重复 ID 统计，让多个 `data_source` 指针按逻辑路径计数，并补充当前 7 个合法重复 QID 到允许列表。
- [x] 新增 `data/api/by-id/<id>/` 静态接口别名，页面优先按节点 ID 读取节点和子节点。
- [x] 排查线上 2026-05-13 起增长停滞，确认旧脚本反复请求同一批 error 节点；保留 2026-05-15 到 2026-05-19 的 0 新增历史记录。
- [x] 给增长部署 workflow 增加 `push` 触发；push 只测试、校验并部署当前数据，不执行增长和自动提交。
- [x] 增长脚本改为多来源适配器，Wikidata 限流后会记录冷却并回退到维基百科分类和 ConceptNet。
- [x] 给增长脚本加入 429 感知的冷却状态、来源请求统计和静态接口字段补充，避免继续撞同一来源。
- [x] 将抓取策略升级为按来源记录 `source_no_children`，避免单个补充来源查空就把节点永久封存。
- [x] 新增 Wikidata API 直接声明补充来源，并把 502/503/504/超时纳入来源冷却。
- [x] 请求失败后也会推进扫描游标，减少下一轮重复卡在同一批 error 分支。
- [x] 新增 `source_checked` 和 `ONE_MAX_SOURCES_PER_NODE`，默认每轮每节点只尝试 1 个来源，避免小请求预算被单个低产节点耗尽。
- [x] 默认来源顺序调整为 `wikidata_api,wikipedia,wikidata,conceptnet`，让轻量补充来源优先，WDQS 后置。
- [x] 修复非 QID 节点的 `by-id` 静态接口目录编码，并让静态 API 镜像先临时构建再整体替换。
- [x] 新建非 QID 分片文件名加入来源 ID 短哈希，避免不同补充来源的同名节点共用一个 `data/nodes/<标题>.json`。
- [x] 新增 `data/api/client.js` 静态调用层，提供 `getNode`、`getChildren` 和 `getEndNode` 形式的接口调用。
- [x] 页面数据读取优先走 `OneKnowledgeApi` 静态客户端，失败时回退原始 JSON 路径。
- [x] 新增 DBpedia 分类层级备用来源，默认放在来源顺序最后，并沿用请求预算、UA 和来源冷却。
- [x] 调整增长候选调度，优先补完已开始检查的节点，减少连续多轮预算全部消耗在 `wikidata_api`。

## Agent Rules

- 修改数据结构时，先保证 `index.html` 能继续读取旧字段，再迁移数据。
- 自动增长数据时，优先保留已有节点和 `data_source` 指针，不要覆盖人工补充内容。
- 新增外部数据源前，先在 `README.md` 和 `MEMORY.md` 记录来源、字段和限制。
- GitHub Actions 里的定时任务使用 UTC 时间；README 中要同时写清楚北京时间。
- 不要把 API 密钥、Cookie 或账号信息写入仓库。

## Next Useful Work

- 定期复核 `data/validation_allowlist.json`，清理已经不再重复出现的允许项。
- 扩展 `data/curation.json` 的人工关注列表，优先补充主干路径和人工维护过的节点。
- 观察 `data/scan_state.json` 的 `candidate_count`、`exhausted`、`source_cooldowns`、`max_sources_per_node` 和节点的 `source_checked` / `source_no_children`，判断增长慢是候选不足、来源限流，还是当前来源已查空。

_Last updated: 2026-05-25_
