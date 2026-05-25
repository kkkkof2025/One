import json
import os
import re
import math
import shutil
import time
import tempfile
import hashlib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib import parse, request

try:
    from SPARQLWrapper import JSON, SPARQLWrapper
except ImportError:  # pragma: no cover - optional dependency for offline tests
    JSON = "JSON"

    class SPARQLWrapper:  # type: ignore[override]
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "SPARQLWrapper is required for Wikidata growth; install requirements.txt first."
            )


DATA_DIR = Path("data")
NODES_DIR = DATA_DIR / "nodes"
ROOT_FILE = DATA_DIR / "root.json"
STATS_FILE = DATA_DIR / "stats.json"
GROWTH_HISTORY_FILE = DATA_DIR / "growth_history.json"
CURATION_FILE = DATA_DIR / "curation.json"
VALIDATION_ALLOWLIST_FILE = DATA_DIR / "validation_allowlist.json"
END_NODES_FILE = DATA_DIR / "end_nodes.json"
SCAN_STATE_FILE = DATA_DIR / "scan_state.json"
API_DIR = DATA_DIR / "api"
API_BY_ID_SUBDIR = "by-id"

QUERY_LIMIT = int(os.environ.get("ONE_QUERY_LIMIT", "50"))
MAX_REQUESTS = int(os.environ.get("ONE_MAX_REQUESTS", "5"))
MAX_SOURCES_PER_NODE = int(os.environ.get("ONE_MAX_SOURCES_PER_NODE", "1"))
REQUEST_DELAY = float(os.environ.get("ONE_REQUEST_DELAY", "5.0"))
WIKIDATA_REQUEST_DELAY = float(os.environ.get("ONE_WIKIDATA_REQUEST_DELAY", "65.0"))
HISTORY_LIMIT = int(os.environ.get("ONE_GROWTH_HISTORY_LIMIT", "365"))
WIKIDATA_ENDPOINT = os.environ.get(
    "ONE_WIKIDATA_ENDPOINT", "https://query.wikidata.org/sparql"
)
WIKIDATA_API_ENDPOINT = os.environ.get(
    "ONE_WIKIDATA_API_ENDPOINT", "https://www.wikidata.org/w/api.php"
)
WIKIPEDIA_API_ENDPOINT = os.environ.get(
    "ONE_WIKIPEDIA_API_ENDPOINT", "https://zh.wikipedia.org/w/api.php"
)
CONCEPTNET_API_ENDPOINT = os.environ.get(
    "ONE_CONCEPTNET_API_ENDPOINT", "https://api.conceptnet.io"
)
USER_AGENT = os.environ.get(
    "ONE_USER_AGENT", "OneKnowledgeTree/0.2 (scheduled GitHub Actions)"
)
DEFAULT_FOCUS_PRIORITY_BONUS = int(os.environ.get("ONE_FOCUS_PRIORITY_BONUS", "18"))
SOURCE_ORDER = [
    source.strip().lower()
    for source in os.environ.get(
        "ONE_SOURCE_ORDER", "wikidata_api,wikipedia,wikidata,conceptnet"
    ).split(",")
    if source.strip()
]
KNOWN_SOURCES = {"wikidata", "wikidata_api", "wikipedia", "conceptnet"}
SOURCE_COOLDOWN_SECONDS = int(os.environ.get("ONE_SOURCE_COOLDOWN_SECONDS", "3600"))
TRANSIENT_SOURCE_COOLDOWN_SECONDS = int(
    os.environ.get("ONE_TRANSIENT_SOURCE_COOLDOWN_SECONDS", "600")
)
HTTP_TIMEOUT = float(os.environ.get("ONE_HTTP_TIMEOUT", "30"))
IGNORE_SOURCE_COOLDOWN = os.environ.get("ONE_IGNORE_SOURCE_COOLDOWN", "").lower() in {
    "1",
    "true",
    "yes",
}

VALID_STATUSES = {"pending", "loaded", "error", "manual"}
VALID_REVIEW_STATUSES = {"approved", "needs_review"}
KNOWN_RELATIONS = {
    "subclass",
    "instance",
    "part_of",
    "has_part",
    "has_parts_of_class",
    "wikipedia_category",
    "conceptnet_is_a",
    "seed",
    "manual",
}
RELATION_QUALITY = {
    "subclass": 18,
    "has_part": 14,
    "part_of": 10,
    "has_parts_of_class": 8,
    "instance": 2,
    "wikipedia_category": 8,
    "conceptnet_is_a": 6,
    "seed": 20,
    "manual": 20,
}
RELATION_PRIORITY = {
    "subclass": 22,
    "has_part": 18,
    "part_of": 12,
    "has_parts_of_class": 10,
    "instance": 4,
    "wikipedia_category": 10,
    "conceptnet_is_a": 8,
    "seed": 24,
    "manual": 20,
}
QUALITY_SCORE_VERSION = 3
QUALITY_REVIEW_THRESHOLD = int(os.environ.get("ONE_QUALITY_REVIEW_THRESHOLD", "45"))
PRIORITY_SCAN_LIMIT = int(os.environ.get("ONE_PRIORITY_SCAN_LIMIT", "1000"))
FETCH_STRATEGY_VERSION = 5
BROAD_TITLES = {
    "事物",
    "对象",
    "物件",
    "实体",
    "概念",
    "类别",
    "分类",
    "类型",
    "集合",
    "系统",
    "列表",
    "entity",
    "object",
    "concept",
    "category",
    "type",
    "list",
}
BROAD_TITLE_PREFIXES = ("所有", "各种", "其他", "未分类")
CurationEntry = Dict[str, Any]
CURATION_CACHE: Optional[Dict[str, Any]] = None
DUPLICATE_ID_COUNTS: Dict[str, int] = {}
ALLOWED_DUPLICATE_IDS: Set[str] = set()
request_count = 0
nodes_added_this_run = 0
nodes_scanned_this_run = 0
failed_requests_this_run = 0
unchanged_requests_this_run = 0
end_nodes_marked_this_run = 0
scan_candidate_count = 0
scan_exhausted = False
last_scan_key_this_run = ""
last_scan_title_this_run = ""
run_stop_reason = ""
source_request_counts: Dict[str, int] = {}
source_cooldowns_this_run: Dict[str, Dict[str, Any]] = {}
last_source_request_at: Dict[str, float] = {}


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def parse_utc(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def source_order() -> List[str]:
    ordered = [source for source in SOURCE_ORDER if source in KNOWN_SOURCES]
    return ordered or ["wikidata"]


def source_request_delay(source: str) -> float:
    if source == "wikidata":
        return WIKIDATA_REQUEST_DELAY
    return REQUEST_DELAY


def wait_for_source_slot(source: str) -> None:
    delay = source_request_delay(source)
    if delay <= 0:
        return
    previous = last_source_request_at.get(source)
    if previous is None:
        return
    remaining = delay - (time.monotonic() - previous)
    if remaining > 0:
        print(f"  等待 {source} 请求间隔: {remaining:.1f}s")
        time.sleep(remaining)


def remember_source_request(source: str) -> None:
    last_source_request_at[source] = time.monotonic()
    source_request_counts[source] = source_request_counts.get(source, 0) + 1


def retry_after_seconds(exc: Exception) -> Optional[int]:
    headers = getattr(exc, "headers", None)
    if headers is None:
        return None
    value = headers.get("Retry-After") if hasattr(headers, "get") else None
    if value is None:
        return None
    text = str(value).strip()
    if text.isdigit():
        return max(0, int(text))
    try:
        retry_at = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    seconds = int((retry_at.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds())
    return max(0, seconds)


def is_rate_limit_error(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "status", None)
    message = str(exc).lower()
    return (
        code == 429
        or "http error 429" in message
        or "too many requests" in message
        or "rate-limit" in message
        or "rate limit" in message
        or "rate-limiting" in message
    )


def is_transient_source_error(exc: Exception) -> bool:
    code = getattr(exc, "code", None) or getattr(exc, "status", None)
    message = str(exc).lower()
    return (
        code in {500, 502, 503, 504}
        or "http error 500" in message
        or "http error 502" in message
        or "http error 503" in message
        or "http error 504" in message
        or "temporarily unavailable" in message
        or "timed out" in message
        or "timeout" in message
    )


def register_source_cooldown(
    source: str, exc: Exception, reason: str = "rate_limited"
) -> None:
    fallback_seconds = (
        TRANSIENT_SOURCE_COOLDOWN_SECONDS
        if reason == "transient_error"
        else SOURCE_COOLDOWN_SECONDS
    )
    retry_after = retry_after_seconds(exc) or fallback_seconds
    occurred_at = now_utc()
    cooldown_until = (
        datetime.now(timezone.utc).replace(microsecond=0)
        + timedelta(seconds=retry_after)
    ).isoformat().replace("+00:00", "Z")
    source_cooldowns_this_run[source] = {
        "source": source,
        "reason": reason,
        "occurred_at": occurred_at,
        "retry_after_seconds": retry_after,
        "cooldown_until": cooldown_until,
        "last_error": str(exc)[:500],
    }


def active_source_cooldowns(previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if IGNORE_SOURCE_COOLDOWN:
        return {}
    previous = previous or load_scan_state()
    cooldowns: Dict[str, Any] = {}
    now = datetime.now(timezone.utc)
    previous_cooldowns = previous.get("source_cooldowns", {})
    if isinstance(previous_cooldowns, dict):
        for source, entry in previous_cooldowns.items():
            if not isinstance(entry, dict):
                continue
            until = parse_utc(entry.get("cooldown_until"))
            if until is not None and until > now:
                cooldowns[source] = entry
    cooldowns.update(source_cooldowns_this_run)
    return cooldowns


def source_in_cooldown(source: str, scan_state: Optional[Dict[str, Any]] = None) -> bool:
    if IGNORE_SOURCE_COOLDOWN:
        return False
    cooldown = active_source_cooldowns(scan_state).get(source)
    if not isinstance(cooldown, dict):
        return False
    until = parse_utc(cooldown.get("cooldown_until"))
    return until is not None and until > datetime.now(timezone.utc)


def available_sources(scan_state: Optional[Dict[str, Any]] = None) -> List[str]:
    return [
        source
        for source in source_order()
        if not source_in_cooldown(source, scan_state)
    ]


def source_no_children_map(node: Dict[str, Any]) -> Dict[str, Any]:
    data = node.get("source_no_children")
    return data if isinstance(data, dict) else {}


def source_no_children_sources(node: Dict[str, Any]) -> Set[str]:
    return {
        str(source).strip().lower()
        for source in source_no_children_map(node)
        if str(source).strip()
    }


def source_checked_map(node: Dict[str, Any]) -> Dict[str, Any]:
    data = node.get("source_checked")
    return data if isinstance(data, dict) else {}


def source_checked_sources(node: Dict[str, Any]) -> Set[str]:
    return {
        str(source).strip().lower()
        for source in source_checked_map(node)
        if str(source).strip()
    }


def source_done_sources(node: Dict[str, Any]) -> Set[str]:
    return source_checked_sources(node).union(source_no_children_sources(node))


def mark_source_checked(
    node: Dict[str, Any], sources: List[str], checked_at: str
) -> None:
    if not sources:
        return
    data = dict(source_checked_map(node))
    for source in sources:
        clean_source = str(source).strip().lower()
        if clean_source:
            data[clean_source] = checked_at
    if data:
        node["source_checked"] = data


def mark_source_no_children(
    node: Dict[str, Any], sources: List[str], checked_at: str
) -> None:
    if not sources:
        return
    data = dict(source_no_children_map(node))
    for source in sources:
        clean_source = str(source).strip().lower()
        if clean_source:
            data[clean_source] = checked_at
    if data:
        node["source_no_children"] = data


def clear_source_no_children(node: Dict[str, Any]) -> None:
    node.pop("source_no_children", None)


def clear_source_checked(node: Dict[str, Any]) -> None:
    node.pop("source_checked", None)


def source_supported_for_node(source: str, node: Dict[str, Any]) -> bool:
    title = str(node.get("title", "")).strip()
    if source == "wikidata":
        return build_wikidata_query(node) is not None
    if source == "wikidata_api":
        return is_qid(node.get("id"))
    if source in {"wikipedia", "conceptnet"}:
        return bool(title)
    return False


def supported_sources_for_node(node: Dict[str, Any]) -> List[str]:
    return [
        source
        for source in source_order()
        if source_supported_for_node(source, node)
    ]


def all_sources_exhausted(node: Dict[str, Any]) -> bool:
    supported_sources = supported_sources_for_node(node)
    if not supported_sources:
        return False
    done_sources = source_done_sources(node)
    return all(source in done_sources for source in supported_sources)


def legacy_no_children_sources(node: Dict[str, Any]) -> List[str]:
    reason = str(node.get("end_reason", "") or "").strip()
    if reason == "sources_no_children":
        return supported_sources_for_node(node)
    suffix = "_no_children"
    if reason.endswith(suffix):
        source = reason[: -len(suffix)].strip().lower()
        if source in KNOWN_SOURCES and source_supported_for_node(source, node):
            return [source]
    return []


def normalize_source_no_children(node: Dict[str, Any]) -> bool:
    checked_at = (
        node.get("ended_at")
        or node.get("last_checked_at")
        or node.get("updated_at")
        or now_utc()
    )
    data: Dict[str, Any] = {}
    changed = False
    for source, value in source_no_children_map(node).items():
        clean_source = str(source).strip().lower()
        if not clean_source or clean_source not in KNOWN_SOURCES:
            changed = True
            continue
        data[clean_source] = value if isinstance(value, str) and value.strip() else checked_at

    if not data:
        legacy_sources = legacy_no_children_sources(node)
        if legacy_sources:
            data = {source: checked_at for source in legacy_sources}
            changed = True

    if data:
        if node.get("source_no_children") != data:
            node["source_no_children"] = data
            changed = True
    elif node.pop("source_no_children", None) is not None:
        changed = True

    if (
        data
        and node.get("is_leaf") is True
        and node.get("children_status") == "loaded"
    ):
        if all_sources_exhausted(node):
            if int(node.get("fetch_strategy_version", 0) or 0) < FETCH_STRATEGY_VERSION:
                node["fetch_strategy_version"] = FETCH_STRATEGY_VERSION
                changed = True
        else:
            node["children_status"] = "pending"
            node["is_leaf"] = False
            clear_end_state(node)
            changed = True

    return changed


def normalize_source_checked(node: Dict[str, Any]) -> bool:
    checked_at = (
        node.get("last_checked_at")
        or node.get("updated_at")
        or node.get("ended_at")
        or now_utc()
    )
    data: Dict[str, Any] = {}
    changed = False
    for source, value in source_checked_map(node).items():
        clean_source = str(source).strip().lower()
        if not clean_source or clean_source not in KNOWN_SOURCES:
            changed = True
            continue
        data[clean_source] = value if isinstance(value, str) and value.strip() else checked_at

    for source, value in source_no_children_map(node).items():
        clean_source = str(source).strip().lower()
        if clean_source and clean_source in KNOWN_SOURCES and clean_source not in data:
            data[clean_source] = value if isinstance(value, str) and value.strip() else checked_at
            changed = True

    if data:
        if node.get("source_checked") != data:
            node["source_checked"] = data
            changed = True
    elif node.pop("source_checked", None) is not None:
        changed = True
    return changed


def source_can_fetch(source: str, node: Dict[str, Any]) -> bool:
    if source in source_done_sources(node):
        return False
    return source_supported_for_node(source, node)


def can_fetch_from_any_source(node: Dict[str, Any]) -> bool:
    return any(source_can_fetch(source, node) for source in source_order())


class GrowthRunPaused(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_json_array(path: Path) -> List[Any]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else []


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix="tmp-",
            suffix=".json",
            delete=False,
        ) as f:
            tmp_path = Path(f.name)
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix="tmp-",
            suffix=".txt",
            delete=False,
        ) as f:
            tmp_path = Path(f.name)
            f.write(text)
            if not text.endswith("\n"):
                f.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def is_qid(value: Any) -> bool:
    return bool(re.fullmatch(r"Q\d+", str(value or "")))


def safe_slug(text: Any, fallback: str = "node") -> str:
    slug = re.sub(r'[\\/*?:"<>|]', "", str(text or "")).strip()
    slug = re.sub(r"\s+", "-", slug)
    return (slug[:80] or fallback).strip(".")


def external_node_file_slug(node: Dict[str, Any]) -> str:
    node_id = str(node.get("id", "")).strip()
    title_slug = safe_slug(node.get("title"), fallback="external")[:48]
    digest = hashlib.sha1(node_id.encode("utf-8")).hexdigest()[:12]
    return f"{title_slug}-{digest}"


def node_file_for(node: Dict[str, Any]) -> Path:
    node_id = str(node.get("id", "")).strip()
    if is_qid(node_id):
        return NODES_DIR / f"{node_id}.json"
    if node_id:
        legacy_path = NODES_DIR / f"{safe_slug(node.get('title'))}.json"
        legacy_data = load_json(legacy_path)
        if isinstance(legacy_data, dict) and str(legacy_data.get("id", "")).strip() == node_id:
            return legacy_path
        return NODES_DIR / f"{external_node_file_slug(node)}.json"
    return NODES_DIR / f"{safe_slug(node.get('title'))}.json"


def data_relative_path(path: Path) -> str:
    return path.relative_to(DATA_DIR).as_posix()


def child_key(node: Dict[str, Any]) -> str:
    node_id = str(node.get("id", "")).strip()
    if node_id:
        return f"id:{node_id}"
    return f"title:{node.get('title', '')}"


def has_cjk(text: Any) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", str(text or "")))


def load_curation() -> Dict[str, Any]:
    global CURATION_CACHE
    if CURATION_CACHE is not None:
        return CURATION_CACHE

    data = load_json(CURATION_FILE)
    CURATION_CACHE = data if isinstance(data, dict) else {}
    return CURATION_CACHE


def load_allowed_duplicate_ids() -> Set[str]:
    data = load_json(VALIDATION_ALLOWLIST_FILE)
    if not isinstance(data, dict):
        return set()
    duplicate_ids = data.get("duplicate_ids", {})
    if not isinstance(duplicate_ids, dict):
        return set()
    return {node_id for node_id in duplicate_ids if is_qid(node_id)}


def collect_duplicate_id_counts(root: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    visited_files: Set[Path] = set()

    def register_node_id(node_id: Any) -> None:
        value = str(node_id or "").strip()
        if is_qid(value):
            counts[value] = counts.get(value, 0) + 1

    def visit(
        node: Any,
        materialized_path: Optional[Path] = None,
        register_current: bool = True,
    ) -> None:
        if not isinstance(node, dict):
            return

        if materialized_path is not None:
            resolved = materialized_path.resolve()
            if resolved in visited_files:
                return
            visited_files.add(resolved)

        data_source = node.get("data_source")
        if data_source:
            target_path = DATA_DIR / str(data_source)
            target = load_json(target_path)
            if isinstance(target, dict):
                register_node_id(node.get("id") or target.get("id"))
                visit(target, target_path, register_current=False)
                return

        if register_current:
            register_node_id(node.get("id"))

        for child in node.get("children", []):
            visit(child)

    visit(root, ROOT_FILE)
    return counts


def prepare_quality_context(root: Dict[str, Any]) -> None:
    global DUPLICATE_ID_COUNTS, ALLOWED_DUPLICATE_IDS
    DUPLICATE_ID_COUNTS = collect_duplicate_id_counts(root)
    ALLOWED_DUPLICATE_IDS = load_allowed_duplicate_ids()


def normalize_curation_entry(entry: Any) -> Optional[CurationEntry]:
    if isinstance(entry, str) and entry.strip():
        return {"reason": entry.strip()}
    if not isinstance(entry, dict):
        return None
    if entry.get("enabled") is False:
        return None
    return entry


def curation_focus_entry(node: Dict[str, Any]) -> Optional[CurationEntry]:
    data = load_curation()
    node_id = str(node.get("id", "")).strip()
    title = str(node.get("title", "")).strip()

    focused_ids = data.get("focused_node_ids", {})
    if node_id and isinstance(focused_ids, dict):
        entry = normalize_curation_entry(focused_ids.get(node_id))
        if entry is not None:
            return entry

    focused_titles = data.get("focused_titles", {})
    if title and isinstance(focused_titles, dict):
        entry = normalize_curation_entry(focused_titles.get(title))
        if entry is not None:
            return entry

    return None


def curation_priority_bonus(node: Dict[str, Any]) -> int:
    entry = curation_focus_entry(node)
    if entry is None:
        return 0
    bonus = entry.get("priority_bonus")
    if isinstance(bonus, (int, float)):
        return int(bonus)
    return DEFAULT_FOCUS_PRIORITY_BONUS


def is_broad_title(title: str) -> bool:
    normalized = title.strip().lower()
    if normalized in BROAD_TITLES:
        return True
    return any(title.startswith(prefix) for prefix in BROAD_TITLE_PREFIXES)


def quality_metadata(node: Dict[str, Any]) -> Dict[str, Any]:
    title = str(node.get("title", "")).strip()
    relation = str(node.get("source_relation", "")).strip()
    status = str(node.get("children_status", "")).strip()
    score = 35
    reasons: List[str] = []

    if node.get("id") == "root":
        score = 100
        reasons.append("root")
    elif is_qid(node.get("id")):
        score += 20
        reasons.append("qid")
    elif node.get("id"):
        score += 8
        reasons.append("external_id")
    else:
        score -= 12
        reasons.append("missing_id")

    if title:
        if has_cjk(title):
            score += 16
            reasons.append("zh_label")
        else:
            score -= 10
            reasons.append("non_zh_label")

        if 2 <= len(title) <= 24:
            score += 8
            reasons.append("good_title_length")
        elif len(title) > 48:
            score -= 18
            reasons.append("long_title")
        elif len(title) == 1:
            score -= 6
            reasons.append("short_title")

        if is_broad_title(title):
            score -= 10
            reasons.append("broad_title")

        if "消歧义" in title or "disambiguation" in title.lower():
            score -= 20
            reasons.append("disambiguation")
    else:
        score -= 25
        reasons.append("missing_title")

    if relation:
        score += RELATION_QUALITY.get(relation, -4)
        reasons.append(f"relation:{relation}")
    elif node.get("id") != "root":
        score -= 4
        reasons.append("missing_relation")

    if status == "loaded":
        score += 4
        reasons.append("loaded")
    elif status == "error":
        score -= 12
        reasons.append("fetch_error")

    if node.get("is_leaf") is True:
        score -= 2
        reasons.append("leaf")

    if node.get("manual_review") is True:
        score += 8
        reasons.append("manual_review")

    focus_entry = curation_focus_entry(node)
    if focus_entry is not None:
        score += 10
        reasons.append("curated_focus")

    node_id = str(node.get("id", "")).strip()
    duplicate_count = DUPLICATE_ID_COUNTS.get(node_id, 0)
    if duplicate_count > 1:
        if node_id in ALLOWED_DUPLICATE_IDS:
            reasons.append(f"allowed_duplicate_id:{duplicate_count}")
        else:
            score -= min(20, 8 + (duplicate_count - 2) * 4)
            reasons.append(f"duplicate_id:{duplicate_count}")

    children = node.get("children")
    if isinstance(children, list) and children:
        score += min(10, int(math.log2(len(children) + 1) * 4))
        reasons.append("has_children")

    score = max(0, min(100, score))
    review_status = "needs_review" if score < QUALITY_REVIEW_THRESHOLD else "approved"
    return {
        "quality_score": score,
        "quality_reasons": reasons,
        "quality_version": QUALITY_SCORE_VERSION,
        "review_status": review_status,
    }


def apply_quality_metadata(node: Dict[str, Any]) -> bool:
    if node.get("review_status") == "approved" and node.get("manual_review") is True:
        return False

    metadata = quality_metadata(node)
    changed = False
    for key, value in metadata.items():
        if node.get(key) != value:
            node[key] = value
            changed = True
    return changed


def expansion_priority(node: Dict[str, Any], depth: int = 0) -> float:
    manual_priority = node.get("expansion_priority")
    if isinstance(manual_priority, (int, float)):
        return float(manual_priority)

    if node.get("review_status") == "needs_review":
        return -1000.0

    score = float(node.get("quality_score", quality_metadata(node)["quality_score"]))
    relation = str(node.get("source_relation", "")).strip()
    status = node.get("children_status")

    if status == "pending":
        score += 28
    elif status == "error":
        score += 12
    elif status == "loaded" and int(node.get("fetch_strategy_version", 0) or 0) < FETCH_STRATEGY_VERSION:
        score += 20

    score += RELATION_PRIORITY.get(relation, 0)
    score += curation_priority_bonus(node)
    if node.get("manual_review") is True:
        score += 8
    score -= depth * 4
    if node.get("is_leaf") is True:
        score -= 50
    return score


def node_identity(node: Dict[str, Any], path: Optional[Path] = None) -> str:
    if path is not None:
        return f"path:{path.resolve().as_posix()}"
    node_id = str(node.get("id", "")).strip()
    if node_id:
        return f"id:{node_id}"
    return f"title:{str(node.get('title', '未命名')).strip()}"


def scan_key(node: Dict[str, Any], path: Optional[Path] = None) -> str:
    node_id = str(node.get("id", "")).strip()
    if node_id:
        return f"id:{node_id}"
    if path is not None:
        try:
            return f"source:{data_relative_path(path)}"
        except ValueError:
            return f"path:{path.resolve().as_posix()}"
    title = str(node.get("title", "")).strip()
    if title:
        return f"title:{title}"
    return "node:unknown"


def load_scan_state() -> Dict[str, Any]:
    data = load_json(SCAN_STATE_FILE)
    return data if isinstance(data, dict) else {}


def scan_state_strategy_version(scan_state: Dict[str, Any]) -> int:
    try:
        return int(scan_state.get("fetch_strategy_version", 0) or 0)
    except (TypeError, ValueError):
        return 0


def cursor_from_scan_state(scan_state: Dict[str, Any]) -> str:
    if scan_state_strategy_version(scan_state) < FETCH_STRATEGY_VERSION:
        return ""
    return str(scan_state.get("last_scan_key", "") or "")


def save_scan_state(
    *,
    last_scan_key: str,
    last_scan_title: str,
    candidate_count: int,
    selected_count: int,
    exhausted: bool,
) -> None:
    previous = load_scan_state()
    preserve_previous_cursor = (
        scan_state_strategy_version(previous) >= FETCH_STRATEGY_VERSION
    )
    state = {
        "updated_at": now_utc(),
        "fetch_strategy_version": FETCH_STRATEGY_VERSION,
        "scan_order": "priority-depth-first-cursor-v1",
        "last_scan_key": last_scan_key
        or (previous.get("last_scan_key", "") if preserve_previous_cursor else ""),
        "last_scan_title": last_scan_title
        or (previous.get("last_scan_title", "") if preserve_previous_cursor else ""),
        "candidate_count": candidate_count,
        "selected_count": selected_count,
        "request_count": request_count,
        "max_requests": MAX_REQUESTS,
        "max_sources_per_node": MAX_SOURCES_PER_NODE,
        "exhausted": exhausted,
        "source_order": source_order(),
        "available_sources": available_sources(previous),
        "source_request_counts": source_request_counts,
        "source_cooldowns": active_source_cooldowns(previous),
        "last_stop_reason": run_stop_reason,
    }
    save_json(SCAN_STATE_FILE, state)


def current_strategy_leaf(node: Dict[str, Any]) -> bool:
    strategy_version = int(node.get("fetch_strategy_version", 0) or 0)
    if node.get("is_leaf") is not True or node.get("children_status") != "loaded":
        return False
    if source_no_children_map(node):
        return all_sources_exhausted(node)
    return strategy_version >= FETCH_STRATEGY_VERSION


def clear_end_state(node: Dict[str, Any]) -> None:
    node.pop("end_reason", None)
    node.pop("ended_at", None)


def mark_end_state(node: Dict[str, Any]) -> None:
    if current_strategy_leaf(node):
        no_children_sources = sorted(source_no_children_sources(node))
        if all_sources_exhausted(node):
            if len(no_children_sources) == 1:
                node["end_reason"] = f"{no_children_sources[0]}_no_children"
            else:
                node["end_reason"] = "sources_no_children"
        elif not source_no_children_map(node):
            node["end_reason"] = "wikidata_no_children"
        else:
            clear_end_state(node)
            return
        node["ended_at"] = node.get("updated_at") or now_utc()
    else:
        clear_end_state(node)


def apply_end_metadata(node: Dict[str, Any]) -> bool:
    previous = (node.get("end_reason"), node.get("ended_at"))
    mark_end_state(node)
    return previous != (node.get("end_reason"), node.get("ended_at"))


def api_relative_path(path: Path) -> str:
    return data_relative_path(path)


def api_node_file(path: Path) -> Path:
    return API_DIR / api_relative_path(path)


def api_children_file(path: Path) -> Path:
    return API_DIR / "children" / api_relative_path(path)


def api_node_id(node: Dict[str, Any]) -> str:
    return str(node.get("id", "")).strip()


def api_by_id_slug(identifier: str) -> str:
    return parse.quote(identifier, safe="")


def api_by_id_dir(identifier: str) -> Path:
    return API_DIR / API_BY_ID_SUBDIR / api_by_id_slug(identifier)


def api_by_id_node_file(identifier: str) -> Path:
    return api_by_id_dir(identifier) / "node.json"


def api_by_id_children_file(identifier: str) -> Path:
    return api_by_id_dir(identifier) / "children.json"


def api_by_id_index_file(identifier: str) -> Path:
    return api_by_id_dir(identifier) / "index.json"


def api_end_node_file(name: str = "endNode.json") -> Path:
    return API_DIR / name


def compact_node_summary(node: Dict[str, Any]) -> Dict[str, Any]:
    summary = {
        "title": node.get("title", "未命名"),
        "children_count": len(node.get("children", []))
        if isinstance(node.get("children"), list)
        else 0,
    }
    for field in (
        "id",
        "data_source",
        "source_provider",
        "source_relation",
        "source_url",
        "children_status",
        "is_leaf",
        "end_reason",
        "ended_at",
        "quality_score",
        "quality_version",
        "review_status",
        "updated_at",
        "last_checked_at",
        "last_error",
        "last_fetch_source",
        "last_fetch_sources",
        "last_source_errors",
        "source_no_children",
        "source_checked",
    ):
        if node.get(field) is not None:
            summary[field] = node[field]
    return summary


def compact_api_children(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    children = node.get("children")
    if not isinstance(children, list):
        return []
    summaries = []
    for child in children:
        if not isinstance(child, dict):
            continue
        summary = compact_node_summary(child)
        data_source = child.get("data_source")
        if data_source:
            target = load_json(DATA_DIR / str(data_source))
            if isinstance(target, dict):
                target_summary = compact_node_summary(target)
                target_summary["data_source"] = data_source
                relation = child.get("source_relation", target.get("source_relation"))
                if relation is not None:
                    target_summary["source_relation"] = relation
                summary.update(target_summary)
        summaries.append(summary)
    return summaries


def collect_tree_nodes(
    node: Dict[str, Any],
    path: Path,
    visited: Optional[Set[Path]] = None,
    ancestor_ids: Optional[Set[str]] = None,
):
    if visited is None:
        visited = set()
    if ancestor_ids is None:
        ancestor_ids = set()

    resolved = path.resolve()
    if resolved in visited:
        return
    visited.add(resolved)
    yield node, path

    next_ancestor_ids = set(ancestor_ids)
    node_id = str(node.get("id", "")).strip()
    if node_id:
        next_ancestor_ids.add(node_id)

    for child in node.get("children", []):
        if not isinstance(child, dict):
            continue
        child_id = str(child.get("id", "")).strip()
        if child_id and child_id in next_ancestor_ids:
            continue
        child_path = None
        if child.get("data_source"):
            child_path = DATA_DIR / str(child["data_source"])
        else:
            child_path = node_file_for(child)

        child_data = load_json(child_path)
        if isinstance(child_data, dict):
            yield from collect_tree_nodes(
                child_data,
                child_path,
                visited,
                next_ancestor_ids,
            )
        else:
            yield child, child_path


def collect_end_nodes(root: Dict[str, Any], path: Path) -> List[Dict[str, Any]]:
    end_nodes: List[Dict[str, Any]] = []
    for node, node_path in collect_tree_nodes(root, path):
        if current_strategy_leaf(node):
            end_nodes.append(
                {
                    "key": scan_key(node, node_path),
                    "path": api_relative_path(node_path),
                    "title": node.get("title", "未命名"),
                    "node": compact_node_summary(node),
                    "reason": node.get("end_reason", "wikidata_no_children"),
                }
            )
    end_nodes.sort(key=lambda item: (item["title"], item["key"]))
    return end_nodes


def static_api_client_js() -> str:
    return """(function (global) {
  "use strict";

  var CLIENT_BASE_URL = (function () {
    if (typeof document !== "undefined") {
      var script = document.currentScript;
      if (script && script.src) return new URL("./", script.src).href;
    }
    if (typeof location !== "undefined") {
      return new URL("data/api/", location.href).href;
    }
    return "https://kkkkof2025.github.io/One/data/api/";
  })();

  function defaultBaseUrl() {
    return CLIENT_BASE_URL;
  }

  function apiUrl(path, options) {
    var baseUrl = options && options.baseUrl ? options.baseUrl : defaultBaseUrl();
    return new URL(path, baseUrl).href;
  }

  function nodeId(node) {
    if (typeof node === "string") return node.trim();
    if (node && typeof node === "object") return String(node.id || "").trim();
    return "root";
  }

  function unwrapNodePayload(payload) {
    if (payload && payload.endpoint === "node" && payload.node) return payload.node;
    return payload;
  }

  async function fetchJson(path, options) {
    var fetchImpl = options && options.fetch ? options.fetch : global.fetch;
    if (typeof fetchImpl !== "function") {
      throw new Error("fetch is not available");
    }
    var response = await fetchImpl(apiUrl(path, options), {
      cache: options && options.cache ? options.cache : "no-cache"
    });
    if (!response.ok) throw new Error("HTTP " + response.status);
    return response.json();
  }

  async function getIndex(options) {
    return fetchJson("index.json", options);
  }

  async function getRoot(options) {
    return unwrapNodePayload(await fetchJson("by-id/root/node.json", options));
  }

  async function getNode(node, options) {
    var id = nodeId(node);
    if (!id) throw new Error("node id is required");
    return unwrapNodePayload(
      await fetchJson("by-id/" + encodeURIComponent(id) + "/node.json", options)
    );
  }

  async function getChildren(node, options) {
    var id = nodeId(node);
    if (!id) throw new Error("node id is required");
    return fetchJson("by-id/" + encodeURIComponent(id) + "/children.json", options);
  }

  async function getEndNode(options) {
    return fetchJson("getEndNode.json", options);
  }

  var api = {
    apiUrl: apiUrl,
    fetchJson: fetchJson,
    getIndex: getIndex,
    getRoot: getRoot,
    getNode: getNode,
    getChildren: getChildren,
    getEndNode: getEndNode
  };

  global.OneKnowledgeApi = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : window);
"""


def write_static_api(root: Dict[str, Any]) -> Dict[str, Any]:
    global API_DIR

    original_api_dir = API_DIR
    staging_dir = original_api_dir.parent / f".{original_api_dir.name}.build-{os.getpid()}"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    API_DIR = staging_dir

    try:
        total_nodes = 0
        end_nodes = collect_end_nodes(root, ROOT_FILE)
        generated_at = now_utc()

        for node, path in collect_tree_nodes(root, ROOT_FILE):
            total_nodes += 1
            identifier = api_node_id(node)
            node_payload = {
                "endpoint": "node",
                "source": api_relative_path(path),
                "node": node,
            }
            save_json(api_node_file(path), node_payload)

            children_payload = {
                "endpoint": "children",
                "source": api_relative_path(path),
                "node": compact_node_summary(node),
                "children": compact_api_children(node),
                "child_count": len(node.get("children", []))
                if isinstance(node.get("children"), list)
                else 0,
            }
            save_json(api_children_file(path), children_payload)

            if identifier:
                alias_index_payload = {
                    "endpoint": "index",
                    "id": identifier,
                    "source": api_relative_path(path),
                    "node": "node.json",
                    "children": "children.json",
                    "legacy_node": f"../../{api_relative_path(path)}",
                    "legacy_children": f"../../children/{api_relative_path(path)}",
                }
                save_json(api_by_id_node_file(identifier), node_payload)
                save_json(api_by_id_children_file(identifier), children_payload)
                save_json(api_by_id_index_file(identifier), alias_index_payload)

        end_payload = {
            "endpoint": "endNode",
            "generated_at": generated_at,
            "fetch_strategy_version": FETCH_STRATEGY_VERSION,
            "total_items": len(end_nodes),
            "items": end_nodes,
        }
        save_json(api_end_node_file("endNode.json"), end_payload)
        save_json(api_end_node_file("getEndNode.json"), end_payload)
        save_json(api_end_node_file("index.json"), {
            "endpoint": "index",
            "root": "root.json",
            "client": "client.js",
            "client_global": "OneKnowledgeApi",
            "client_methods": ["getRoot", "getNode", "getChildren", "getEndNode"],
            "node": "<relative data path, e.g. root.json or nodes/Q1.json>",
            "children": "children/<relative data path>",
            "by_id": "by-id/<id>/index.json",
            "by_id_node": "by-id/<id>/node.json",
            "by_id_children": "by-id/<id>/children.json",
            "getEndNode": "getEndNode.json",
            "endNode": "endNode.json",
        })
        save_text(API_DIR / "client.js", static_api_client_js())

        if original_api_dir.exists():
            shutil.rmtree(original_api_dir)
        staging_dir.rename(original_api_dir)
        API_DIR = original_api_dir
        return {
            "total_nodes": total_nodes,
            "end_nodes": end_nodes,
            "end_payload": end_payload,
        }
    except Exception:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        API_DIR = original_api_dir
        raise


def normalize_node(node: Dict[str, Any]) -> bool:
    changed = False

    if "title" not in node:
        node["title"] = "未命名"
        changed = True

    if "children" not in node or not isinstance(node["children"], list):
        node["children"] = []
        changed = True

    if "fetch_done" in node:
        node["children_status"] = "loaded" if node.pop("fetch_done") else "pending"
        changed = True

    if node.get("children_status") not in VALID_STATUSES:
        node["children_status"] = "loaded" if node["children"] else "pending"
        changed = True

    if node["children_status"] == "loaded" and not node["children"]:
        if node.get("is_leaf") is not True:
            node["is_leaf"] = True
            changed = True
    elif node.get("is_leaf") is True:
        node["is_leaf"] = False
        changed = True

    changed = normalize_source_no_children(node) or changed
    changed = normalize_source_checked(node) or changed

    review_status = node.get("review_status")
    if review_status is not None and review_status not in VALID_REVIEW_STATUSES:
        node.pop("review_status", None)
        changed = True

    changed = apply_quality_metadata(node) or changed
    return changed


def pointer_from_node(node: Dict[str, Any], path: Path) -> Dict[str, Any]:
    pointer: Dict[str, Any] = {
        "title": node.get("title", "未命名"),
        "data_source": data_relative_path(path),
        "children_status": node.get("children_status", "pending"),
        "is_leaf": bool(node.get("is_leaf", False)),
    }
    if node.get("id"):
        pointer["id"] = node["id"]
    if node.get("fetch_strategy_version"):
        pointer["fetch_strategy_version"] = node["fetch_strategy_version"]
    for field in (
        "source_provider",
        "source_relation",
        "source_url",
        "quality_score",
        "quality_version",
        "review_status",
        "updated_at",
        "last_checked_at",
        "end_reason",
        "ended_at",
        "last_error",
        "last_fetch_source",
        "last_fetch_sources",
        "last_source_errors",
        "source_no_children",
        "source_checked",
    ):
        if node.get(field) is not None:
            pointer[field] = node[field]
    return pointer


def sparql_literal(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def build_wikidata_query(node: Dict[str, Any]) -> Optional[str]:
    node_id = str(node.get("id", "")).strip()
    title = str(node.get("title", "")).strip()

    if is_qid(node_id):
        return f"""
SELECT DISTINCT ?item ?itemLabel ?relation WHERE {{
  {{
    ?item wdt:P279 wd:{node_id} .
    BIND("subclass" AS ?relation)
  }}
  UNION
  {{
    ?item wdt:P31 wd:{node_id} .
    BIND("instance" AS ?relation)
  }}
  UNION
  {{
    ?item wdt:P361 wd:{node_id} .
    BIND("part_of" AS ?relation)
  }}
  UNION
  {{
    wd:{node_id} wdt:P527 ?item .
    BIND("has_part" AS ?relation)
  }}
  UNION
  {{
    wd:{node_id} wdt:P2670 ?item .
    BIND("has_parts_of_class" AS ?relation)
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "zh". }}
}}
ORDER BY ?relation ?itemLabel
LIMIT {QUERY_LIMIT}
"""

    if title:
        return f"""
SELECT DISTINCT ?item ?itemLabel ?relation WHERE {{
  ?parent rdfs:label {sparql_literal(title)}@zh .
  {{
    ?item wdt:P279 ?parent .
    BIND("subclass" AS ?relation)
  }}
  UNION
  {{
    ?item wdt:P31 ?parent .
    BIND("instance" AS ?relation)
  }}
  UNION
  {{
    ?item wdt:P361 ?parent .
    BIND("part_of" AS ?relation)
  }}
  UNION
  {{
    ?parent wdt:P527 ?item .
    BIND("has_part" AS ?relation)
  }}
  UNION
  {{
    ?parent wdt:P2670 ?item .
    BIND("has_parts_of_class" AS ?relation)
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "zh". }}
}}
ORDER BY ?relation ?itemLabel
LIMIT {QUERY_LIMIT}
"""

    return None


def fetch_wikidata_children(
    node: Dict[str, Any], blocked_ids: Optional[Set[str]] = None
) -> List[Dict[str, Any]]:
    query = build_wikidata_query(node)
    if not query:
        return []
    blocked_ids = blocked_ids or set()

    sparql = SPARQLWrapper(WIKIDATA_ENDPOINT)
    sparql.setReturnFormat(JSON)
    sparql.addCustomHttpHeader("User-Agent", USER_AGENT)
    sparql.setQuery(query)

    results = sparql.query().convert()
    children: List[Dict[str, Any]] = []
    seen = set()

    for result in results.get("results", {}).get("bindings", []):
        item = result.get("item", {}).get("value", "")
        node_id = item.rsplit("/", 1)[-1] if item else ""
        label = result.get("itemLabel", {}).get("value", "").strip()

        if not label or label == node.get("title"):
            continue
        if node_id and node_id in blocked_ids:
            continue
        if node_id and node_id == str(node.get("id", "")).strip():
            continue
        if label.startswith("Q") and label[1:].isdigit():
            continue

        key = node_id or label
        if key in seen:
            continue
        seen.add(key)

        child: Dict[str, Any] = {
            "title": label,
            "children_status": "pending",
            "is_leaf": False,
            "source_provider": "wikidata",
        }
        if is_qid(node_id):
            child["id"] = node_id
            child["source_url"] = f"https://www.wikidata.org/wiki/{node_id}"
        relation = result.get("relation", {}).get("value", "").strip()
        if relation:
            child["source_relation"] = relation
        children.append(child)

    return children


def fetch_json_url(url: str) -> Dict[str, Any]:
    http_request = request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with request.urlopen(http_request, timeout=HTTP_TIMEOUT) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    return data if isinstance(data, dict) else {}


def wikidata_label_from_entity(entity: Dict[str, Any], fallback: str = "") -> str:
    labels = entity.get("labels", {})
    if not isinstance(labels, dict):
        return fallback
    for language in ("zh", "zh-hans", "zh-cn", "en"):
        label_entry = labels.get(language)
        if isinstance(label_entry, dict):
            value = str(label_entry.get("value", "")).strip()
            if value:
                return value
    return fallback


def fetch_wikidata_api_entities(ids: List[str], props: str) -> Dict[str, Any]:
    if not ids:
        return {}
    params = {
        "action": "wbgetentities",
        "ids": "|".join(ids),
        "props": props,
        "languages": "zh|zh-hans|zh-cn|en",
        "format": "json",
        "formatversion": "2",
    }
    url = f"{WIKIDATA_API_ENDPOINT}?{parse.urlencode(params)}"
    data = fetch_json_url(url)
    entities = data.get("entities", {})
    return entities if isinstance(entities, dict) else {}


def wikidata_claim_entity_id(claim: Dict[str, Any]) -> str:
    mainsnak = claim.get("mainsnak")
    if not isinstance(mainsnak, dict):
        return ""
    datavalue = mainsnak.get("datavalue")
    if not isinstance(datavalue, dict):
        return ""
    value = datavalue.get("value")
    if not isinstance(value, dict):
        return ""
    entity_id = str(value.get("id", "")).strip()
    return entity_id if is_qid(entity_id) else ""


def fetch_wikidata_api_children(
    node: Dict[str, Any], blocked_ids: Optional[Set[str]] = None
) -> List[Dict[str, Any]]:
    node_id = str(node.get("id", "")).strip()
    if not is_qid(node_id):
        return []
    blocked_ids = blocked_ids or set()
    limit = max(1, min(QUERY_LIMIT, 50))
    entities = fetch_wikidata_api_entities([node_id], "claims")
    entity = entities.get(node_id)
    if not isinstance(entity, dict):
        return []

    claims = entity.get("claims", {})
    if not isinstance(claims, dict):
        return []

    relation_properties = {
        "P527": "has_part",
        "P2670": "has_parts_of_class",
    }
    child_relations: Dict[str, str] = {}
    child_ids: List[str] = []
    for property_id, relation in relation_properties.items():
        values = claims.get(property_id, [])
        if not isinstance(values, list):
            continue
        for claim in values:
            if not isinstance(claim, dict):
                continue
            child_id = wikidata_claim_entity_id(claim)
            if not child_id or child_id == node_id or child_id in blocked_ids:
                continue
            if child_id not in child_relations:
                child_relations[child_id] = relation
                child_ids.append(child_id)
            if len(child_ids) >= limit:
                break
        if len(child_ids) >= limit:
            break

    if not child_ids:
        return []

    label_entities = fetch_wikidata_api_entities(child_ids, "labels")
    children: List[Dict[str, Any]] = []
    for child_id in child_ids:
        child_entity = label_entities.get(child_id)
        label = child_id
        if isinstance(child_entity, dict):
            label = wikidata_label_from_entity(child_entity, child_id)
        if not label or label == child_id or label == node.get("title"):
            continue
        children.append(
            {
                "id": child_id,
                "title": label,
                "children_status": "pending",
                "is_leaf": False,
                "source_provider": "wikidata_api",
                "source_relation": child_relations[child_id],
                "source_url": f"https://www.wikidata.org/wiki/{child_id}",
            }
        )
    return children


def fetch_wikipedia_children(
    node: Dict[str, Any], blocked_ids: Optional[Set[str]] = None
) -> List[Dict[str, Any]]:
    title = str(node.get("title", "")).strip()
    if not title:
        return []
    blocked_ids = blocked_ids or set()
    limit = max(1, min(QUERY_LIMIT, 50))
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": f"Category:{title}",
        "cmtype": "subcat",
        "cmlimit": str(limit),
        "format": "json",
        "formatversion": "2",
    }
    url = f"{WIKIPEDIA_API_ENDPOINT}?{parse.urlencode(params)}"
    data = fetch_json_url(url)
    members = data.get("query", {}).get("categorymembers", [])
    if not isinstance(members, list):
        return []

    children: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for member in members:
        if not isinstance(member, dict):
            continue
        raw_title = str(member.get("title", "")).strip()
        if not raw_title:
            continue
        label = raw_title.removeprefix("Category:").strip()
        if not label or label == title:
            continue
        page_id = member.get("pageid")
        source_id = f"wikipedia:zh:Category:{label}"
        if source_id in blocked_ids:
            continue
        if source_id in seen:
            continue
        seen.add(source_id)
        child: Dict[str, Any] = {
            "id": source_id,
            "title": label,
            "children_status": "pending",
            "is_leaf": False,
            "source_provider": "wikipedia",
            "source_relation": "wikipedia_category",
            "source_url": f"https://zh.wikipedia.org/wiki/Category:{parse.quote(label)}",
        }
        if page_id is not None:
            child["source_page_id"] = page_id
        children.append(child)
    return children


def conceptnet_node_id(title: str) -> str:
    normalized = re.sub(r"\s+", "_", title.strip())
    return f"/c/zh/{normalized}"


def fetch_conceptnet_children(
    node: Dict[str, Any], blocked_ids: Optional[Set[str]] = None
) -> List[Dict[str, Any]]:
    title = str(node.get("title", "")).strip()
    if not title:
        return []
    blocked_ids = blocked_ids or set()
    limit = max(1, min(QUERY_LIMIT, 50))
    parent_id = conceptnet_node_id(title)
    params = {
        "end": parent_id,
        "rel": "/r/IsA",
        "limit": str(limit),
    }
    url = f"{CONCEPTNET_API_ENDPOINT.rstrip('/')}/query?{parse.urlencode(params)}"
    data = fetch_json_url(url)
    edges = data.get("edges", [])
    if not isinstance(edges, list):
        return []

    children: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        start = edge.get("start")
        if not isinstance(start, dict):
            continue
        language = str(start.get("language", "")).strip()
        if language and language != "zh":
            continue
        label = str(start.get("label", "")).strip()
        concept_id = str(start.get("@id", "")).strip()
        if not label or label == title or not concept_id:
            continue
        source_id = f"conceptnet:{concept_id}"
        if source_id in blocked_ids:
            continue
        if source_id in seen:
            continue
        seen.add(source_id)
        children.append(
            {
                "id": source_id,
                "title": label,
                "children_status": "pending",
                "is_leaf": False,
                "source_provider": "conceptnet",
                "source_relation": "conceptnet_is_a",
                "source_url": f"https://conceptnet.io{concept_id}",
            }
        )
    return children


def fetch_children_from_source(
    source: str, node: Dict[str, Any], blocked_ids: Optional[Set[str]] = None
) -> List[Dict[str, Any]]:
    if source == "wikidata":
        return fetch_wikidata_children(node, blocked_ids)
    if source == "wikidata_api":
        return fetch_wikidata_api_children(node, blocked_ids)
    if source == "wikipedia":
        return fetch_wikipedia_children(node, blocked_ids)
    if source == "conceptnet":
        return fetch_conceptnet_children(node, blocked_ids)
    return []


def fetch_children_from_sources(
    node: Dict[str, Any],
    blocked_ids: Optional[Set[str]] = None,
    scan_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    global request_count

    supported_sources = supported_sources_for_node(node)
    candidates = [
        source
        for source in available_sources(scan_state)
        if source in supported_sources and source_can_fetch(source, node)
    ]
    if not candidates:
        remaining_sources = [
            source
            for source in supported_sources
            if source not in source_done_sources(node)
        ]
        if not remaining_sources:
            return {
                "children": [],
                "source": "",
                "checked_sources": [],
                "source_errors": {},
                "complete": True,
            }
        if all(source_in_cooldown(source, scan_state) for source in remaining_sources):
            raise GrowthRunPaused("node_sources_in_cooldown")
        raise GrowthRunPaused("no_available_source")

    if MAX_SOURCES_PER_NODE > 0:
        candidates = candidates[:MAX_SOURCES_PER_NODE]

    successful_sources: List[str] = []
    source_errors: Dict[str, str] = {}
    saw_rate_limit = False
    saw_transient_error = False
    for source in candidates:
        if request_count >= MAX_REQUESTS:
            raise GrowthRunPaused("request_budget_exhausted")

        wait_for_source_slot(source)
        request_count += 1
        remember_source_request(source)
        print(f"[{request_count}/{MAX_REQUESTS}] 查询({source}): {node.get('title')}")

        try:
            children = fetch_children_from_source(source, node, blocked_ids)
        except Exception as exc:
            if is_rate_limit_error(exc):
                saw_rate_limit = True
                register_source_cooldown(source, exc, "rate_limited")
                print(f"  {source} 触发限流: {exc}")
                continue
            if is_transient_source_error(exc):
                saw_transient_error = True
                source_errors[source] = str(exc)
                register_source_cooldown(source, exc, "transient_error")
                print(f"  {source} 暂时不可用，已进入冷却: {exc}")
                continue
            source_errors[source] = str(exc)
            print(f"  {source} 查询失败: {exc}")
            continue

        successful_sources.append(source)
        if children:
            done_sources = source_done_sources(node).union(successful_sources)
            complete = all(source in done_sources for source in supported_sources)
            return {
                "children": children,
                "source": source,
                "checked_sources": successful_sources,
                "source_errors": source_errors,
                "complete": complete,
            }
        print(f"  {source} 未发现子节点")

    if successful_sources:
        exhausted_sources = source_done_sources(node).union(successful_sources)
        complete = (
            not source_errors
            and not saw_rate_limit
            and all(source in exhausted_sources for source in supported_sources)
        )
        return {
            "children": [],
            "source": successful_sources[-1],
            "checked_sources": successful_sources,
            "source_errors": source_errors,
            "complete": complete,
        }
    if saw_rate_limit or saw_transient_error:
        if not available_sources(scan_state):
            raise GrowthRunPaused("all_sources_in_cooldown")
        raise GrowthRunPaused("node_sources_unavailable")
    if source_errors:
        detail = "; ".join(f"{source}: {error}" for source, error in source_errors.items())
        raise RuntimeError(detail)
    raise GrowthRunPaused("no_available_source")


def merge_children(
    existing: List[Dict[str, Any]], fetched: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], int]:
    merged: List[Dict[str, Any]] = []
    positions: Dict[str, Dict[str, Any]] = {}
    added = 0

    for child in existing:
        if not isinstance(child, dict):
            continue
        normalize_node(child)
        merged.append(child)
        positions[child_key(child)] = child

    for child in fetched:
        if not isinstance(child, dict):
            continue
        normalize_node(child)
        key = child_key(child)
        current = positions.get(key)
        if current is None:
            merged.append(child)
            positions[key] = child
            added += 1
            continue

        for field in ("id", "title", "source_provider", "source_relation", "source_url"):
            if child.get(field) and not current.get(field):
                current[field] = child[field]

    return merged, added


def materialize_child(child: Dict[str, Any]) -> Tuple[Dict[str, Any], Path, bool]:
    changed = False

    if child.get("data_source"):
        path = DATA_DIR / str(child["data_source"])
        child_data = load_json(path)
        if child_data is None:
            child_data = {
                "id": child.get("id"),
                "title": child.get("title", "未命名"),
                "children_status": child.get("children_status", "pending"),
                "children": child.get("children", []),
            }
            for field in ("source_provider", "source_relation", "source_url", "source_page_id"):
                if child.get(field) is not None:
                    child_data[field] = child[field]
            normalize_node(child_data)
            save_json(path, child_data)
            changed = True
        elif normalize_node(child_data):
            save_json(path, child_data)
            changed = True
        pointer = pointer_from_node(child_data, path)
        if child != pointer:
            child.clear()
            child.update(pointer)
            changed = True
        return child_data, path, changed

    path = node_file_for(child)
    child_data = load_json(path)
    if child_data is None:
        child_data = {
            "id": child.get("id"),
            "title": child.get("title", "未命名"),
            "children_status": child.get("children_status", "pending"),
            "children": child.get("children", []),
        }
        for field in ("source_provider", "source_relation", "source_url", "source_page_id"):
            if child.get(field) is not None:
                child_data[field] = child[field]
        normalize_node(child_data)
        save_json(path, child_data)
        changed = True
    elif normalize_node(child_data):
        save_json(path, child_data)
        changed = True

    pointer = pointer_from_node(child_data, path)
    if child != pointer:
        child.clear()
        child.update(pointer)
        changed = True

    return child_data, path, changed


def materialize_inline_children(node: Dict[str, Any]) -> bool:
    changed = False
    for child in list(node.get("children", [])):
        if not isinstance(child, dict):
            continue
        child_data, child_path, pointer_changed = materialize_child(child)
        changed = changed or pointer_changed
        pointer = pointer_from_node(child_data, child_path)
        if child != pointer:
            child.clear()
            child.update(pointer)
            changed = True
    return changed


def sanitize_cyclic_children(
    node: Dict[str, Any], ancestor_ids: Optional[Set[str]] = None
) -> bool:
    children = node.get("children")
    if not isinstance(children, list):
        return False

    blocked_ids = set(ancestor_ids or set())
    current_id = str(node.get("id", "")).strip()
    if current_id:
        blocked_ids.add(current_id)

    changed = False
    kept: List[Any] = []
    for child in children:
        if not isinstance(child, dict):
            kept.append(child)
            continue
        child_id = str(child.get("id", "")).strip()
        if child_id and child_id in blocked_ids:
            changed = True
            continue
        kept.append(child)

    if changed:
        node["children"] = kept
    return changed


def should_fetch(node: Dict[str, Any]) -> bool:
    if node.get("id") == "root":
        return False

    if current_strategy_leaf(node):
        return False

    manual_priority = isinstance(node.get("expansion_priority"), (int, float))
    if node.get("review_status") == "needs_review" and not manual_priority:
        return False

    if not can_fetch_from_any_source(node):
        return False

    status = node.get("children_status")
    if status in {"pending", "error"} and not node.get("is_leaf"):
        return True

    strategy_version = int(node.get("fetch_strategy_version", 0) or 0)
    return status == "loaded" and strategy_version < FETCH_STRATEGY_VERSION


def collect_fetch_candidates(
    data: Dict[str, Any],
    file_path: Path,
    depth: int = 0,
    candidates: Optional[List[Dict[str, Any]]] = None,
    visited: Optional[Set[Path]] = None,
    parent_node: Optional[Dict[str, Any]] = None,
    parent_path: Optional[Path] = None,
    pointer_ref: Optional[Dict[str, Any]] = None,
    ancestor_ids: Optional[Set[str]] = None,
) -> bool:
    global nodes_scanned_this_run, scan_candidate_count

    if candidates is None:
        candidates = []
    if visited is None:
        visited = set()
    if ancestor_ids is None:
        ancestor_ids = set()

    changed = normalize_node(data)
    changed = apply_end_metadata(data) or changed
    changed = sanitize_cyclic_children(data, ancestor_ids) or changed
    resolved = file_path.resolve()
    if resolved in visited:
        return changed
    visited.add(resolved)

    if should_fetch(data):
        candidates.append(
            {
                "node": data,
                "file_path": file_path,
                "parent_node": parent_node,
                "parent_path": parent_path,
                "pointer_ref": pointer_ref,
                "depth": depth,
                "priority": expansion_priority(data, depth),
                "scan_key": scan_key(data, file_path),
                "title": data.get("title", "未命名"),
                "ancestor_ids": set(ancestor_ids),
            }
        )
        scan_candidate_count += 1

    next_ancestor_ids = set(ancestor_ids)
    node_id = str(data.get("id", "")).strip()
    if node_id:
        next_ancestor_ids.add(node_id)

    for child in prioritized_children(list(data.get("children", [])), depth + 1):
        if not isinstance(child, dict):
            continue
        child_id = str(child.get("id", "")).strip()
        if child_id and child_id in next_ancestor_ids:
            continue
        nodes_scanned_this_run += 1
        child_data, child_path, pointer_changed = materialize_child(child)
        changed = changed or pointer_changed

        child_changed = collect_fetch_candidates(
            child_data,
            child_path,
            depth + 1,
            candidates,
            visited,
            data,
            file_path,
            child,
            next_ancestor_ids,
        )
        if child_changed:
            save_json(child_path, child_data)
            changed = True

        pointer = pointer_from_node(child_data, child_path)
        if child != pointer:
            child.clear()
            child.update(pointer)
            changed = True

    return changed


def sort_scan_candidates(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ordered = sorted(
        candidates,
        key=lambda item: (-float(item.get("priority", 0.0)), item.get("depth", 0), item.get("scan_key", "")),
    )
    return ordered


def rotate_candidates(candidates: List[Dict[str, Any]], cursor: str) -> List[Dict[str, Any]]:
    if not cursor:
        return candidates
    for index, candidate in enumerate(candidates):
        if candidate.get("scan_key") == cursor:
            return candidates[index + 1 :] + candidates[: index + 1]
    return candidates


def process_fetch_candidate(
    candidate: Dict[str, Any], scan_state: Optional[Dict[str, Any]] = None
) -> bool:
    global request_count, nodes_added_this_run, failed_requests_this_run
    global unchanged_requests_this_run, end_nodes_marked_this_run
    global last_scan_key_this_run, last_scan_title_this_run, run_stop_reason

    node = candidate["node"]
    file_path = candidate["file_path"]
    pointer_ref = candidate.get("pointer_ref")
    ancestor_ids = set(candidate.get("ancestor_ids") or set())
    request_count_before = request_count

    def remember_candidate_position() -> None:
        global last_scan_key_this_run, last_scan_title_this_run
        last_scan_key_this_run = candidate.get("scan_key", "")
        last_scan_title_this_run = str(candidate.get("title", "") or "")

    try:
        outcome = fetch_children_from_sources(node, ancestor_ids, scan_state)
        fetched_children = outcome["children"]
        node["children"], added = merge_children(node.get("children", []), fetched_children)
        cyclic_pruned = sanitize_cyclic_children(node, ancestor_ids)
        materialized_children = materialize_inline_children(node)
        nodes_added_this_run += added
        if added == 0:
            unchanged_requests_this_run += 1
        node["updated_at"] = now_utc()
        node["last_checked_at"] = node["updated_at"]
        node.pop("last_error", None)
        node["last_fetch_source"] = outcome.get("source", "")
        checked_sources = outcome.get("checked_sources", [])
        node["last_fetch_sources"] = checked_sources
        source_errors = outcome.get("source_errors") or {}
        if source_errors:
            node["last_source_errors"] = source_errors
        else:
            node.pop("last_source_errors", None)
        if checked_sources:
            mark_source_checked(node, checked_sources, node["last_checked_at"])
        if checked_sources and not fetched_children:
            mark_source_no_children(node, checked_sources, node["last_checked_at"])
        complete = bool(outcome.get("complete")) or all_sources_exhausted(node)
        has_children = len(node["children"]) > 0
        if fetched_children or has_children:
            node["children_status"] = "loaded"
            if complete:
                node["fetch_strategy_version"] = FETCH_STRATEGY_VERSION
            elif int(node.get("fetch_strategy_version", 0) or 0) >= FETCH_STRATEGY_VERSION:
                node["fetch_strategy_version"] = FETCH_STRATEGY_VERSION - 1
            node["is_leaf"] = False
            clear_end_state(node)
        else:
            node["children_status"] = "loaded" if complete else "pending"
            if complete:
                node["fetch_strategy_version"] = FETCH_STRATEGY_VERSION
            elif int(node.get("fetch_strategy_version", 0) or 0) >= FETCH_STRATEGY_VERSION:
                node["fetch_strategy_version"] = FETCH_STRATEGY_VERSION - 1
            node["is_leaf"] = len(node["children"]) == 0 and complete
        mark_end_state(node)
        if node.get("end_reason"):
            end_nodes_marked_this_run += 1
        apply_quality_metadata(node)
        changed = True
        save_json(file_path, node)
        if pointer_ref is not None:
            pointer = pointer_from_node(node, file_path)
            if pointer_ref != pointer:
                pointer_ref.clear()
                pointer_ref.update(pointer)
                parent_node = candidate.get("parent_node")
                parent_path = candidate.get("parent_path")
                if isinstance(parent_node, dict) and isinstance(parent_path, Path):
                    save_json(parent_path, parent_node)
        remember_candidate_position()
        print(
            f"  新增节点: {added}，当前子类: {len(node['children'])}，"
            f"来源: {node.get('last_fetch_source')}"
        )
        return changed
    except GrowthRunPaused as exc:
        if request_count > request_count_before:
            remember_candidate_position()
        if exc.reason in {"node_sources_in_cooldown", "node_sources_unavailable"}:
            print(f"  跳过当前节点: {exc.reason}")
            return False
        run_stop_reason = exc.reason
        print(f"  暂停本轮增长: {exc.reason}")
        return False
    except Exception as exc:
        failed_requests_this_run += 1
        node["children_status"] = "error"
        node["last_error"] = str(exc)
        node["updated_at"] = now_utc()
        node["last_checked_at"] = node["updated_at"]
        clear_end_state(node)
        apply_quality_metadata(node)
        changed = True
        save_json(file_path, node)
        if pointer_ref is not None:
            pointer = pointer_from_node(node, file_path)
            if pointer_ref != pointer:
                pointer_ref.clear()
                pointer_ref.update(pointer)
                parent_node = candidate.get("parent_node")
                parent_path = candidate.get("parent_path")
                if isinstance(parent_node, dict) and isinstance(parent_path, Path):
                    save_json(parent_path, parent_node)
        if request_count > request_count_before:
            remember_candidate_position()
        print(f"  查询失败: {exc}")
        return changed


def prioritized_children(
    children: List[Dict[str, Any]], depth: int
) -> List[Dict[str, Any]]:
    valid_children = [
        (index, child)
        for index, child in enumerate(children)
        if isinstance(child, dict)
    ]
    if PRIORITY_SCAN_LIMIT > 0:
        sortable = valid_children[:PRIORITY_SCAN_LIMIT]
        tail = valid_children[PRIORITY_SCAN_LIMIT:]
    else:
        sortable = valid_children
        tail = []

    sortable.sort(
        key=lambda item: (-expansion_priority(item[1], depth), item[0])
    )
    return [child for _, child in sortable + tail]


def process_node_data(
    data: Dict[str, Any],
    file_path: Path,
    depth: int = 0,
    ancestor_ids: Optional[Set[str]] = None,
) -> bool:
    global request_count, nodes_added_this_run, nodes_scanned_this_run
    global failed_requests_this_run, unchanged_requests_this_run, end_nodes_marked_this_run

    if ancestor_ids is None:
        ancestor_ids = set()

    changed = normalize_node(data)
    changed = apply_end_metadata(data) or changed
    changed = sanitize_cyclic_children(data, ancestor_ids) or changed

    if request_count < MAX_REQUESTS and should_fetch(data):
        try:
            outcome = fetch_children_from_sources(data, ancestor_ids, load_scan_state())
            fetched_children = outcome["children"]
            data["children"], added = merge_children(data["children"], fetched_children)
            cyclic_pruned = sanitize_cyclic_children(data, ancestor_ids)
            materialized_children = materialize_inline_children(data)
            nodes_added_this_run += added
            if added == 0:
                unchanged_requests_this_run += 1
            data["updated_at"] = now_utc()
            data["last_checked_at"] = data["updated_at"]
            data.pop("last_error", None)
            data["last_fetch_source"] = outcome.get("source", "")
            checked_sources = outcome.get("checked_sources", [])
            data["last_fetch_sources"] = checked_sources
            source_errors = outcome.get("source_errors") or {}
            if source_errors:
                data["last_source_errors"] = source_errors
            else:
                data.pop("last_source_errors", None)
            if checked_sources:
                mark_source_checked(data, checked_sources, data["last_checked_at"])
            if checked_sources and not fetched_children:
                mark_source_no_children(data, checked_sources, data["last_checked_at"])
            complete = bool(outcome.get("complete")) or all_sources_exhausted(data)
            has_children = len(data["children"]) > 0
            if fetched_children or has_children:
                data["children_status"] = "loaded"
                if complete:
                    data["fetch_strategy_version"] = FETCH_STRATEGY_VERSION
                elif int(data.get("fetch_strategy_version", 0) or 0) >= FETCH_STRATEGY_VERSION:
                    data["fetch_strategy_version"] = FETCH_STRATEGY_VERSION - 1
                data["is_leaf"] = False
                clear_end_state(data)
            else:
                data["children_status"] = "loaded" if complete else "pending"
                if complete:
                    data["fetch_strategy_version"] = FETCH_STRATEGY_VERSION
                elif int(data.get("fetch_strategy_version", 0) or 0) >= FETCH_STRATEGY_VERSION:
                    data["fetch_strategy_version"] = FETCH_STRATEGY_VERSION - 1
                data["is_leaf"] = complete
            mark_end_state(data)
            if data.get("end_reason"):
                end_nodes_marked_this_run += 1
            changed = apply_quality_metadata(data) or materialized_children or cyclic_pruned or changed
            changed = True
            print(f"  新增节点: {added}，当前子类: {len(data['children'])}")
        except GrowthRunPaused as exc:
            print(f"  暂停本轮增长: {exc.reason}")
            return changed
        except Exception as exc:
            failed_requests_this_run += 1
            data["children_status"] = "error"
            data["last_error"] = str(exc)
            data["updated_at"] = now_utc()
            data["last_checked_at"] = data["updated_at"]
            clear_end_state(data)
            changed = apply_quality_metadata(data) or changed
            changed = True
            print(f"  查询失败: {exc}")

    next_ancestor_ids = set(ancestor_ids)
    node_id = str(data.get("id", "")).strip()
    if node_id:
        next_ancestor_ids.add(node_id)

    for child in prioritized_children(list(data.get("children", [])), depth + 1):
        if request_count >= MAX_REQUESTS:
            break
        nodes_scanned_this_run += 1
        child_id = str(child.get("id", "")).strip()
        if child_id and child_id in next_ancestor_ids:
            continue
        child_strategy_version = int(child.get("fetch_strategy_version", 0) or 0)
        if child.get("is_leaf") is True and child_strategy_version >= FETCH_STRATEGY_VERSION:
            continue

        child_data, child_path, pointer_changed = materialize_child(child)
        changed = changed or pointer_changed

        child_changed = process_node_data(
            child_data,
            child_path,
            depth + 1,
            next_ancestor_ids,
        )
        if child_changed:
            save_json(child_path, child_data)
            changed = True

        pointer = pointer_from_node(child_data, child_path)
        if child != pointer:
            child.clear()
            child.update(pointer)
            changed = True

    return changed


def count_tree_nodes(node: Dict[str, Any], path: Optional[Path] = None, visited=None) -> int:
    if visited is None:
        visited = set()

    identity = node_identity(node, path)
    if identity in visited:
        return 0
    visited.add(identity)

    total = 1
    for child in node.get("children", []):
        if not isinstance(child, dict):
            continue

        child_path = None
        child_node = child
        if child.get("data_source"):
            child_path = DATA_DIR / str(child["data_source"])
            loaded = load_json(child_path)
            if loaded is not None:
                child_node = loaded

        total += count_tree_nodes(child_node, child_path, visited)

    return total


def record_growth_history(
    total_nodes: int, end_node_count: int, append_history: bool = True
) -> None:
    history = load_json_array(GROWTH_HISTORY_FILE)
    entry = {
        "run_at": now_utc(),
        "added_nodes": nodes_added_this_run,
        "total_nodes": total_nodes,
        "requests": request_count,
        "scanned_nodes": nodes_scanned_this_run,
        "candidate_nodes": scan_candidate_count,
        "unchanged_requests": unchanged_requests_this_run,
        "failed_requests": failed_requests_this_run,
        "end_nodes_marked": end_nodes_marked_this_run,
        "end_node_count": end_node_count,
        "source_request_counts": source_request_counts,
        "max_sources_per_node": MAX_SOURCES_PER_NODE,
        "stop_reason": run_stop_reason,
    }
    if append_history:
        history.append(entry)

    if HISTORY_LIMIT > 0 and len(history) > HISTORY_LIMIT:
        history = history[-HISTORY_LIMIT:]

    if append_history or not GROWTH_HISTORY_FILE.exists():
        save_json(GROWTH_HISTORY_FILE, history)
    save_json(
        STATS_FILE,
        {
            "generated_at": entry["run_at"],
            "total_nodes": total_nodes,
            "last_added_nodes": nodes_added_this_run,
            "last_request_count": request_count,
            "last_scanned_nodes": nodes_scanned_this_run,
            "last_candidate_nodes": scan_candidate_count,
            "last_unchanged_requests": unchanged_requests_this_run,
            "last_failed_requests": failed_requests_this_run,
            "last_end_nodes_marked": end_nodes_marked_this_run,
            "last_source_request_counts": source_request_counts,
            "max_sources_per_node": MAX_SOURCES_PER_NODE,
            "last_stop_reason": run_stop_reason,
            "end_node_count": end_node_count,
            "history_entries": len(history),
            "history_file": GROWTH_HISTORY_FILE.relative_to(DATA_DIR).as_posix(),
            "end_nodes_file": END_NODES_FILE.relative_to(DATA_DIR).as_posix(),
            "scan_state_file": SCAN_STATE_FILE.relative_to(DATA_DIR).as_posix(),
            "static_api_root": API_DIR.relative_to(DATA_DIR).as_posix(),
        },
    )


def default_root() -> Dict[str, Any]:
    return {
        "id": "root",
        "title": "万物",
        "children_status": "loaded",
        "children": [
            {
                "id": "Q1",
                "title": "宇宙",
                "data_source": "nodes/Q1.json",
                "children_status": "pending",
                "is_leaf": False,
            },
            {
                "id": "Q3",
                "title": "生命",
                "data_source": "nodes/Q3.json",
                "children_status": "pending",
                "is_leaf": False,
            },
        ],
    }


def bootstrap_root_files(root: Dict[str, Any]) -> bool:
    changed = False
    for child in root.get("children", []):
        if not isinstance(child, dict):
            continue
        _, _, pointer_changed = materialize_child(child)
        changed = changed or pointer_changed
    return changed


def main() -> None:
    global nodes_added_this_run, scan_candidate_count, scan_exhausted, run_stop_reason
    root_data = load_json(ROOT_FILE)
    if root_data is None:
        root_data = default_root()

    prepare_quality_context(root_data)
    changed = normalize_node(root_data)
    changed = bootstrap_root_files(root_data) or changed

    candidates: List[Dict[str, Any]] = []
    changed = collect_fetch_candidates(
        root_data,
        ROOT_FILE,
        candidates=candidates,
    ) or changed
    ordered_candidates = sort_scan_candidates(candidates)
    scan_state = load_scan_state()
    ordered_candidates = rotate_candidates(
        ordered_candidates,
        cursor_from_scan_state(scan_state),
    )
    active_sources = available_sources(scan_state)
    if MAX_REQUESTS > 0 and not active_sources:
        run_stop_reason = "all_sources_in_cooldown"
        print("所有增长来源仍在冷却期内，本轮只刷新静态数据。")
    scan_candidate_count = len(candidates)
    selected_count = 0

    if active_sources:
        iterable_candidates = ordered_candidates
    else:
        iterable_candidates = []

    for candidate in iterable_candidates:
        if request_count >= MAX_REQUESTS or run_stop_reason:
            break
        selected_count += 1
        changed = process_fetch_candidate(candidate, scan_state) or changed

    scan_exhausted = len(candidates) == selected_count and not run_stop_reason

    if changed:
        save_json(ROOT_FILE, root_data)
        print("根节点或分片数据已更新。")
    else:
        print("没有发现需要保存的数据变化。")

    total_nodes = count_tree_nodes(root_data, ROOT_FILE)
    end_nodes = collect_end_nodes(root_data, ROOT_FILE)
    save_json(
        END_NODES_FILE,
        {
            "generated_at": now_utc(),
            "fetch_strategy_version": FETCH_STRATEGY_VERSION,
            "total_items": len(end_nodes),
            "items": end_nodes,
        },
    )
    api_summary = write_static_api(root_data)
    end_node_count = len(api_summary["end_nodes"])
    record_growth_history(total_nodes, end_node_count, append_history=MAX_REQUESTS > 0)
    save_scan_state(
        last_scan_key=last_scan_key_this_run,
        last_scan_title=last_scan_title_this_run,
        candidate_count=len(candidates),
        selected_count=selected_count,
        exhausted=scan_exhausted,
    )
    print(f"本次新增节点数: {nodes_added_this_run}")
    print(f"当前总节点数: {total_nodes}")
    print(f"本次扫描候选节点数: {nodes_scanned_this_run}")
    print(f"可请求候选节点数: {scan_candidate_count}")
    print(f"未新增但成功检查数: {unchanged_requests_this_run}")
    print(f"失败请求数: {failed_requests_this_run}")
    print(f"终止节点数: {end_node_count}")
    print(f"本次来源请求数: {request_count}/{MAX_REQUESTS}")
    if source_request_counts:
        print(f"分来源请求数: {source_request_counts}")
    if run_stop_reason:
        print(f"本轮停止原因: {run_stop_reason}")


if __name__ == "__main__":
    main()
