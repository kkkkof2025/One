import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


VALID_STATUSES = {"pending", "loaded", "error", "manual"}
VALID_REVIEW_STATUSES = {"approved", "needs_review"}
VALIDATION_ALLOWLIST_FILE = "validation_allowlist.json"
CURATION_FILE = "curation.json"
REVIEW_QUEUE_FILE = "review_queue.json"
REVIEW_DECISIONS_FILE = "review_decisions.json"
END_NODES_FILE = "end_nodes.json"
SCAN_STATE_FILE = "scan_state.json"
API_DIR = "api"
VALID_REVIEW_DECISION_STATUSES = {
    "confirmed",
    "curated",
    "allowlisted",
    "ignored",
    "deferred",
}
ALLOWED_NODE_FIELDS = {
    "id",
    "title",
    "children",
    "children_status",
    "data_source",
    "source_provider",
    "source_url",
    "source_page_id",
    "is_leaf",
    "updated_at",
    "last_error",
    "last_fetch_source",
    "last_fetch_sources",
    "last_source_errors",
    "last_checked_at",
    "end_reason",
    "ended_at",
    "fetch_strategy_version",
    "source_relation",
    "quality_score",
    "quality_reasons",
    "quality_version",
    "review_status",
    "manual_review",
    "expansion_priority",
}
ALLOWED_FIELD_PREFIXES = ("manual_",)


class DataValidator:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()
        self.nodes_dir = self.data_dir / "nodes"
        self.root_file = self.data_dir / "root.json"
        self.stats_file = self.data_dir / "stats.json"
        self.history_file = self.data_dir / "growth_history.json"
        self.allowlist_file = self.data_dir / VALIDATION_ALLOWLIST_FILE
        self.curation_file = self.data_dir / CURATION_FILE
        self.review_queue_file = self.data_dir / REVIEW_QUEUE_FILE
        self.review_decisions_file = self.data_dir / REVIEW_DECISIONS_FILE
        self.end_nodes_file = self.data_dir / END_NODES_FILE
        self.scan_state_file = self.data_dir / SCAN_STATE_FILE
        self.api_dir = self.data_dir / API_DIR
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.loaded_files: Dict[Path, Any] = {}
        self.visited_node_files: Set[Path] = set()
        self.id_locations: Dict[str, str] = {}
        self.allowed_duplicate_ids: Dict[str, str] = {}
        self.allowed_duplicate_hits: Set[str] = set()
        self.node_count = 0
        self.pointer_count = 0
        self.load_allowlist()

    def error(self, location: str, message: str) -> None:
        self.errors.append(f"{location}: {message}")

    def warning(self, location: str, message: str) -> None:
        self.warnings.append(f"{location}: {message}")

    def load_json(self, path: Path) -> Optional[Any]:
        resolved = path.resolve()
        if resolved in self.loaded_files:
            return self.loaded_files[resolved]
        try:
            with resolved.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            self.error(self.relative_location(resolved), "文件不存在")
            return None
        except json.JSONDecodeError as exc:
            self.error(
                self.relative_location(resolved),
                f"JSON 解析失败: 第 {exc.lineno} 行第 {exc.colno} 列: {exc.msg}",
            )
            return None
        self.loaded_files[resolved] = data
        return data

    def relative_location(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.data_dir).as_posix()
        except ValueError:
            return path.resolve().as_posix()

    def resolve_data_source(self, source: Any, location: str) -> Optional[Path]:
        if not isinstance(source, str) or not source.strip():
            self.error(location, "`data_source` 必须是非空字符串")
            return None

        path = (self.data_dir / source).resolve()
        try:
            path.relative_to(self.data_dir)
        except ValueError:
            self.error(location, f"`data_source` 指向 data/ 外部: {source}")
            return None

        if path.suffix.lower() != ".json":
            self.error(location, f"`data_source` 不是 JSON 文件: {source}")
            return None
        if not path.exists():
            self.error(location, f"`data_source` 文件不存在: {source}")
            return None
        return path

    def check_unknown_fields(self, node: Dict[str, Any], location: str) -> None:
        for field in node:
            if field in ALLOWED_NODE_FIELDS:
                continue
            if any(field.startswith(prefix) for prefix in ALLOWED_FIELD_PREFIXES):
                continue
            self.warning(location, f"未登记字段 `{field}`，可能存在 schema 漂移")

    def load_allowlist(self) -> None:
        if not self.allowlist_file.exists():
            return

        data = self.load_json(self.allowlist_file)
        location = VALIDATION_ALLOWLIST_FILE
        if data is None:
            return
        if not isinstance(data, dict):
            self.error(location, "校验允许列表必须是 JSON object")
            return

        duplicate_ids = data.get("duplicate_ids", {})
        if not isinstance(duplicate_ids, dict):
            self.error(location, "`duplicate_ids` 必须是 object")
            return

        for node_id, entry in duplicate_ids.items():
            item_location = f"{location}.duplicate_ids.{node_id}"
            if not isinstance(node_id, str) or not node_id.strip():
                self.error(item_location, "允许的重复 ID 必须是非空字符串")
                continue
            if not re.fullmatch(r"Q\d+", node_id):
                self.error(item_location, "允许的重复 ID 必须是 Wikidata QID")
                continue

            if isinstance(entry, str):
                reason = entry.strip()
            elif isinstance(entry, dict):
                reason_value = entry.get("reason")
                reason = reason_value.strip() if isinstance(reason_value, str) else ""
            else:
                self.error(item_location, "允许项必须是字符串或包含 `reason` 的 object")
                continue

            if not reason:
                self.error(item_location, "允许项必须填写非空 `reason`")
                continue

            self.allowed_duplicate_ids[node_id] = reason

    def register_id(self, node_id: Any, location: str) -> None:
        if node_id is None:
            return
        if not isinstance(node_id, str) or not node_id.strip():
            self.error(location, "`id` 必须是非空字符串")
            return

        value = node_id.strip()
        if value != "root" and not re.fullmatch(r"Q\d+", value):
            self.warning(location, f"`id` 不是 root 或 Wikidata QID: {value}")

        previous = self.id_locations.get(value)
        if previous is not None and previous != location:
            if value in self.allowed_duplicate_ids:
                self.allowed_duplicate_hits.add(value)
                return
            self.warning(location, f"重复 ID `{value}`，首次出现于 {previous}")
            return
        self.id_locations[value] = location

    def validate_allowlist_usage(self) -> None:
        for node_id in sorted(self.allowed_duplicate_ids):
            if node_id not in self.allowed_duplicate_hits:
                self.warning(
                    VALIDATION_ALLOWLIST_FILE,
                    f"允许重复 ID `{node_id}` 当前未重复出现，可能可以移除",
                )

    def validate_curation_entry(self, entry: Any, location: str) -> None:
        if isinstance(entry, str):
            if not entry.strip():
                self.error(location, "人工关注原因必须是非空字符串")
            return

        if not isinstance(entry, dict):
            self.error(location, "人工关注项必须是字符串或 object")
            return

        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            self.error(location, "人工关注项必须填写非空 `reason`")

        bonus = entry.get("priority_bonus")
        if bonus is not None and not isinstance(bonus, (int, float)):
            self.error(location, "`priority_bonus` 必须是数字")

        enabled = entry.get("enabled")
        if enabled is not None and not isinstance(enabled, bool):
            self.error(location, "`enabled` 必须是 boolean")

    def validate_curation_map(self, value: Any, location: str, keys_are_qids: bool) -> None:
        if value is None:
            return
        if not isinstance(value, dict):
            self.error(location, "必须是 object")
            return

        for key, entry in value.items():
            item_location = f"{location}.{key}"
            if not isinstance(key, str) or not key.strip():
                self.error(item_location, "人工关注 key 必须是非空字符串")
                continue
            if keys_are_qids and not re.fullmatch(r"Q\d+", key):
                self.error(item_location, "focused_node_ids 的 key 必须是 Wikidata QID")
            self.validate_curation_entry(entry, item_location)

    def validate_curation(self) -> None:
        if not self.curation_file.exists():
            return

        data = self.load_json(self.curation_file)
        if data is None:
            return
        if not isinstance(data, dict):
            self.error(CURATION_FILE, "人工策展文件必须是 JSON object")
            return

        allowed_fields = {"focused_node_ids", "focused_titles", "notes"}
        for field in data:
            if field not in allowed_fields:
                self.warning(CURATION_FILE, f"未登记字段 `{field}`，可能存在 schema 漂移")

        self.validate_curation_map(
            data.get("focused_node_ids"),
            f"{CURATION_FILE}.focused_node_ids",
            True,
        )
        self.validate_curation_map(
            data.get("focused_titles"),
            f"{CURATION_FILE}.focused_titles",
            False,
        )

    def validate_review_queue(self) -> None:
        if not self.review_queue_file.exists():
            return

        data = self.load_json(self.review_queue_file)
        if data is None:
            return
        if not isinstance(data, dict):
            self.error(REVIEW_QUEUE_FILE, "复核队列必须是 JSON object")
            return

        required_fields = {
            "generated_at",
            "threshold",
            "limit",
            "total_candidates",
            "suppressed_items",
            "decision_file",
            "total_items",
            "items",
        }
        for field in required_fields:
            if field not in data:
                self.error(REVIEW_QUEUE_FILE, f"缺少 `{field}`")

        for field in (
            "threshold",
            "limit",
            "total_candidates",
            "suppressed_items",
            "total_items",
        ):
            value = data.get(field)
            if value is not None and not isinstance(value, int):
                self.error(REVIEW_QUEUE_FILE, f"`{field}` 必须是整数")

        decision_file = data.get("decision_file")
        if decision_file is not None and decision_file != REVIEW_DECISIONS_FILE:
            self.error(REVIEW_QUEUE_FILE, f"`decision_file` 必须是 {REVIEW_DECISIONS_FILE}")

        distribution = data.get("reason_distribution")
        if distribution is not None:
            self.validate_review_reason_distribution(distribution)

        items = data.get("items")
        if not isinstance(items, list):
            self.error(REVIEW_QUEUE_FILE, "`items` 必须是数组")
            return

        total_items = data.get("total_items")
        if isinstance(total_items, int) and total_items != len(items):
            self.error(REVIEW_QUEUE_FILE, "`total_items` 必须等于 `items` 长度")

        total_candidates = data.get("total_candidates")
        suppressed_items = data.get("suppressed_items")
        if isinstance(total_candidates, int) and isinstance(total_items, int):
            if total_candidates < total_items:
                self.error(REVIEW_QUEUE_FILE, "`total_candidates` 不能小于 `total_items`")
            if isinstance(suppressed_items, int) and total_candidates < total_items + suppressed_items:
                self.error(
                    REVIEW_QUEUE_FILE,
                    "`total_candidates` 不能小于 `total_items` 与 `suppressed_items` 之和",
                )

        for index, item in enumerate(items):
            location = f"{REVIEW_QUEUE_FILE}.items[{index}]"
            if not isinstance(item, dict):
                self.error(location, "复核项必须是 JSON object")
                continue

            for field in ("title", "path", "location", "review_key", "suggested_action"):
                value = item.get(field)
                if not isinstance(value, str) or not value.strip():
                    self.error(location, f"缺少非空 `{field}`")

            priority = item.get("priority")
            if not isinstance(priority, (int, float)):
                self.error(location, "`priority` 必须是数字")

            quality_score = item.get("quality_score")
            if quality_score is not None and (
                not isinstance(quality_score, (int, float)) or not 0 <= quality_score <= 100
            ):
                self.error(location, "`quality_score` 必须是 0 到 100 之间的数字")

            review_status = item.get("review_status")
            if review_status is not None and review_status not in VALID_REVIEW_STATUSES:
                self.error(
                    location,
                    f"`review_status` 必须是 {sorted(VALID_REVIEW_STATUSES)} 之一",
                )

            quality_reasons = item.get("quality_reasons")
            if quality_reasons is not None and not isinstance(quality_reasons, list):
                self.error(location, "`quality_reasons` 必须是数组")

    def validate_review_reason_distribution(self, distribution: Any) -> None:
        location = f"{REVIEW_QUEUE_FILE}.reason_distribution"
        if not isinstance(distribution, dict):
            self.error(location, "`reason_distribution` 必须是 object")
            return

        total_items = distribution.get("total_items")
        if total_items is not None and not isinstance(total_items, int):
            self.error(location, "`total_items` 必须是整数")

        for field in ("categories", "raw_reasons", "children_statuses"):
            value = distribution.get(field)
            if value is not None and not isinstance(value, list):
                self.error(location, f"`{field}` 必须是数组")

        categories = distribution.get("categories", [])
        if isinstance(categories, list):
            for index, category in enumerate(categories):
                category_location = f"{location}.categories[{index}]"
                if not isinstance(category, dict):
                    self.error(category_location, "原因分类项必须是 object")
                    continue
                for field in ("key", "label"):
                    value = category.get(field)
                    if not isinstance(value, str) or not value.strip():
                        self.error(category_location, f"缺少非空 `{field}`")
                count = category.get("count")
                if not isinstance(count, int) or count < 0:
                    self.error(category_location, "`count` 必须是非负整数")
                sample_keys = category.get("sample_review_keys", [])
                if not isinstance(sample_keys, list) or not all(
                    isinstance(key, str) for key in sample_keys
                ):
                    self.error(category_location, "`sample_review_keys` 必须是字符串数组")

        raw_reasons = distribution.get("raw_reasons", [])
        if isinstance(raw_reasons, list):
            for index, entry in enumerate(raw_reasons):
                entry_location = f"{location}.raw_reasons[{index}]"
                if not isinstance(entry, dict):
                    self.error(entry_location, "原始原因统计项必须是 object")
                    continue
                reason = entry.get("reason")
                if not isinstance(reason, str) or not reason.strip():
                    self.error(entry_location, "缺少非空 `reason`")
                count = entry.get("count")
                if not isinstance(count, int) or count < 0:
                    self.error(entry_location, "`count` 必须是非负整数")

        statuses = distribution.get("children_statuses", [])
        if isinstance(statuses, list):
            for index, entry in enumerate(statuses):
                entry_location = f"{location}.children_statuses[{index}]"
                if not isinstance(entry, dict):
                    self.error(entry_location, "状态统计项必须是 object")
                    continue
                status = entry.get("status")
                if not isinstance(status, str) or not status.strip():
                    self.error(entry_location, "缺少非空 `status`")
                label = entry.get("label")
                if label is not None and not isinstance(label, str):
                    self.error(entry_location, "`label` 必须是字符串")
                count = entry.get("count")
                if not isinstance(count, int) or count < 0:
                    self.error(entry_location, "`count` 必须是非负整数")

    def validate_review_decisions(self) -> None:
        if not self.review_decisions_file.exists():
            return

        data = self.load_json(self.review_decisions_file)
        if data is None:
            return
        if not isinstance(data, dict):
            self.error(REVIEW_DECISIONS_FILE, "复核处理记录必须是 JSON object")
            return

        decisions = data.get("decisions", {})
        if not isinstance(decisions, dict):
            self.error(REVIEW_DECISIONS_FILE, "`decisions` 必须是 object")
            return

        allowed_fields = {"decisions", "notes"}
        for field in data:
            if field not in allowed_fields:
                self.warning(REVIEW_DECISIONS_FILE, f"未登记字段 `{field}`，可能存在 schema 漂移")

        for key, entry in decisions.items():
            location = f"{REVIEW_DECISIONS_FILE}.decisions.{key}"
            if not isinstance(key, str) or not key.strip():
                self.error(location, "复核 key 必须是非空字符串")
                continue
            if not (key.startswith("id:") or key.startswith("location:") or key.startswith("title:")):
                self.error(location, "复核 key 必须以 id:、location: 或 title: 开头")
            if not isinstance(entry, dict):
                self.error(location, "复核处理项必须是 object")
                continue

            status = entry.get("status")
            if status not in VALID_REVIEW_DECISION_STATUSES:
                self.error(
                    location,
                    f"`status` 必须是 {sorted(VALID_REVIEW_DECISION_STATUSES)} 之一",
                )

            reason = entry.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                self.error(location, "复核处理项必须填写非空 `reason`")

            updated_at = entry.get("updated_at")
            if updated_at is not None and not isinstance(updated_at, str):
                self.error(location, "`updated_at` 必须是字符串")

            reviewed_by = entry.get("reviewed_by")
            if reviewed_by is not None and not isinstance(reviewed_by, str):
                self.error(location, "`reviewed_by` 必须是字符串")

    def validate_end_nodes_payload(self, data: Any, location: str) -> None:
        if not isinstance(data, dict):
            self.error(location, "终止节点文件必须是 JSON object")
            return

        for field in ("generated_at", "fetch_strategy_version", "total_items", "items"):
            if field not in data:
                self.error(location, f"缺少 `{field}`")

        total_items = data.get("total_items")
        if total_items is not None and not isinstance(total_items, int):
            self.error(location, "`total_items` 必须是整数")

        items = data.get("items")
        if not isinstance(items, list):
            self.error(location, "`items` 必须是数组")
            return

        if isinstance(total_items, int) and total_items != len(items):
            self.error(location, "`total_items` 必须等于 `items` 长度")

        for index, item in enumerate(items):
            item_location = f"{location}.items[{index}]"
            if not isinstance(item, dict):
                self.error(item_location, "终止节点项必须是 object")
                continue
            for field in ("key", "path", "title", "reason"):
                value = item.get(field)
                if not isinstance(value, str) or not value.strip():
                    self.error(item_location, f"缺少非空 `{field}`")
            node = item.get("node")
            if node is not None and not isinstance(node, dict):
                self.error(item_location, "`node` 必须是 object")

    def validate_end_nodes(self) -> None:
        if not self.end_nodes_file.exists():
            return
        data = self.load_json(self.end_nodes_file)
        self.validate_end_nodes_payload(data, END_NODES_FILE)

    def validate_scan_state(self) -> None:
        if not self.scan_state_file.exists():
            return
        data = self.load_json(self.scan_state_file)
        if not isinstance(data, dict):
            self.error(SCAN_STATE_FILE, "扫描状态文件必须是 JSON object")
            return

        for field in ("updated_at", "fetch_strategy_version", "scan_order"):
            value = data.get(field)
            if value is not None and not isinstance(value, str) and field != "fetch_strategy_version":
                self.error(SCAN_STATE_FILE, f"`{field}` 必须是字符串")

        version = data.get("fetch_strategy_version")
        if version is not None and not isinstance(version, int):
            self.error(SCAN_STATE_FILE, "`fetch_strategy_version` 必须是整数")

        for field in ("candidate_count", "selected_count", "request_count", "max_requests"):
            value = data.get(field)
            if value is not None and not isinstance(value, int):
                self.error(SCAN_STATE_FILE, f"`{field}` 必须是整数")

        exhausted = data.get("exhausted")
        if exhausted is not None and not isinstance(exhausted, bool):
            self.error(SCAN_STATE_FILE, "`exhausted` 必须是 boolean")

    def validate_static_api(self) -> None:
        if not self.api_dir.exists():
            return

        for path in sorted(self.api_dir.rglob("*.json")):
            data = self.load_json(path)
            location = self.relative_location(path)
            if not isinstance(data, (dict, list)):
                self.error(location, "API JSON 必须是 object 或 array")
            if path.name in {"endNode.json", "getEndNode.json"}:
                self.validate_end_nodes_payload(data, location)

    def validate_node(
        self,
        node: Any,
        location: str,
        materialized_path: Optional[Path],
        stack: Set[Path],
        register_current: bool = True,
    ) -> None:
        if not isinstance(node, dict):
            self.error(location, "节点必须是 JSON object")
            return

        if materialized_path is not None:
            materialized_path = materialized_path.resolve()
            if materialized_path in stack:
                self.error(location, "发现 `data_source` 循环引用")
                return
            if materialized_path in self.visited_node_files:
                return
            self.visited_node_files.add(materialized_path)
            stack.add(materialized_path)

        self.node_count += 1
        self.check_unknown_fields(node, location)

        title = node.get("title")
        if not isinstance(title, str) or not title.strip():
            self.error(location, "缺失非空 `title`")

        status = node.get("children_status")
        if status not in VALID_STATUSES:
            self.error(
                location,
                f"`children_status` 必须是 {sorted(VALID_STATUSES)} 之一",
            )

        children = node.get("children")
        if children is not None and not isinstance(children, list):
            self.error(location, "`children` 必须是数组")
            children = []

        review_status = node.get("review_status")
        if review_status is not None and review_status not in VALID_REVIEW_STATUSES:
            self.error(
                location,
                f"`review_status` 必须是 {sorted(VALID_REVIEW_STATUSES)} 之一",
            )

        quality_score = node.get("quality_score")
        if quality_score is not None:
            if not isinstance(quality_score, (int, float)) or not 0 <= quality_score <= 100:
                self.error(location, "`quality_score` 必须是 0 到 100 之间的数字")

        quality_reasons = node.get("quality_reasons")
        if quality_reasons is not None and not isinstance(quality_reasons, list):
            self.error(location, "`quality_reasons` 必须是数组")

        data_source = node.get("data_source")
        if data_source:
            self.pointer_count += 1
            if children:
                self.warning(location, "带 `data_source` 的指针不应同时保存内联 `children`")

            target_path = self.resolve_data_source(data_source, location)
            if target_path is not None:
                target = self.load_json(target_path)
                if isinstance(target, dict):
                    pointer_id = node.get("id")
                    target_id = target.get("id")
                    if pointer_id and target_id and pointer_id != target_id:
                        self.error(
                            location,
                            f"指针 ID `{pointer_id}` 与目标文件 ID `{target_id}` 不一致",
                        )
                    self.register_id(pointer_id or target_id, location)
                    target_location = self.relative_location(target_path)
                    self.validate_node(
                        target,
                        target_location,
                        target_path,
                        stack,
                        register_current=False,
                    )
            if materialized_path is not None:
                stack.discard(materialized_path)
            return

        if register_current:
            self.register_id(node.get("id"), location)

        for index, child in enumerate(children or []):
            self.validate_node(
                child,
                f"{location}.children[{index}]",
                None,
                stack,
                True,
            )

        if materialized_path is not None:
            stack.discard(materialized_path)

    def validate_stats(self) -> None:
        if not self.stats_file.exists():
            self.warning("stats.json", "统计文件不存在，将在下一次增长后生成")
            return
        data = self.load_json(self.stats_file)
        if not isinstance(data, dict):
            self.error("stats.json", "统计文件必须是 JSON object")
            return
        for field in ("generated_at", "total_nodes", "last_added_nodes"):
            if field not in data:
                self.warning("stats.json", f"缺少 `{field}`")

    def validate_history(self) -> None:
        if not self.history_file.exists():
            self.warning("growth_history.json", "历史文件不存在，将在下一次增长后生成")
            return
        data = self.load_json(self.history_file)
        if not isinstance(data, list):
            self.error("growth_history.json", "历史文件必须是 JSON array")
            return
        for index, entry in enumerate(data):
            location = f"growth_history.json[{index}]"
            if not isinstance(entry, dict):
                self.error(location, "历史记录必须是 JSON object")
                continue
            for field in ("run_at", "added_nodes", "total_nodes"):
                if field not in entry:
                    self.error(location, f"缺少 `{field}`")

    def validate_orphan_shards(self) -> None:
        if not self.nodes_dir.exists():
            return
        for path in sorted(self.nodes_dir.glob("*.json")):
            resolved = path.resolve()
            if resolved in self.visited_node_files:
                continue
            self.warning(self.relative_location(resolved), "分片未从 root.json 引用")
            data = self.load_json(resolved)
            self.validate_node(
                data,
                self.relative_location(resolved),
                resolved,
                set(),
            )

    def validate(self) -> int:
        root = self.load_json(self.root_file)
        self.validate_node(root, "root.json", self.root_file.resolve(), set())
        self.validate_orphan_shards()
        self.validate_allowlist_usage()
        self.validate_curation()
        self.validate_review_queue()
        self.validate_review_decisions()
        self.validate_end_nodes()
        self.validate_scan_state()
        self.validate_static_api()
        self.validate_stats()
        self.validate_history()
        return 1 if self.errors else 0

    def report(self) -> None:
        for warning in self.warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
        for error in self.errors:
            print(f"ERROR: {error}", file=sys.stderr)

        checked_files = len(self.loaded_files)
        if self.errors:
            print(
                f"数据校验失败: {len(self.errors)} 个错误，"
                f"{len(self.warnings)} 个警告，检查 {checked_files} 个文件。",
                file=sys.stderr,
            )
        else:
            print(
                f"数据校验通过: {self.node_count} 个节点，"
                f"{self.pointer_count} 个 data_source 指针，"
                f"{checked_files} 个 JSON 文件。"
            )
            if self.warnings:
                print(f"保留 {len(self.warnings)} 个警告供人工检查。")
            if self.allowed_duplicate_hits:
                print(
                    f"已确认 {len(self.allowed_duplicate_hits)} 个重复 ID。"
                )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate One knowledge tree JSON data.")
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Path to the data directory. Default: data",
    )
    args = parser.parse_args()

    validator = DataValidator(Path(args.data_dir))
    exit_code = validator.validate()
    validator.report()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
