import json
import os
import time
import random
import re
from pathlib import Path
from SPARQLWrapper import SPARQLWrapper, JSON

# --- 配置 ---
DATA_DIR = Path("data")
NODES_DIR = DATA_DIR / "nodes"
ROOT_FILE = DATA_DIR / "root.json"
THRESHOLD = 50           # 单个 JSON 文件包含的最大子节点数
MAX_REQUESTS = 20        # 每次运行最多请求几次 Wikidata

sparql = SPARQLWrapper("https://query.wikidata.org/sparql")
sparql.setReturnFormat(JSON)

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_json(path):
    if not path.exists(): return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def fetch_wikidata_children(entity_title):
    """
    为了演示，我们还是用名字搜索。
    生产环境建议在 JSON 里存储 Wikidata QID (如 Q123)，那样更准。
    """
    print(f"📡 查询: {entity_title}")
    query = f"""
    SELECT DISTINCT ?itemLabel WHERE {{
      ?parent rdfs:label "{entity_title}"@zh .
      ?item wdt:P279 ?parent .
      ?item rdfs:label ?itemLabel .
      FILTER(LANG(?itemLabel) = "zh") .
    }} LIMIT {THRESHOLD + 5}
    """
    try:
        sparql.setQuery(query)
        results = sparql.query().convert()
        children = []
        for res in results["results"]["bindings"]:
            lbl = res["itemLabel"]["value"]
            if lbl != entity_title:
                children.append({"title": lbl, "is_leaf": True}) # 默认假设是叶子
        return children
    except:
        return []

def process_node_data(data, file_path):
    """递归处理 JSON 数据"""
    global request_count
    changed = False

    # 1. 检查是否需要生长 (如果当前节点没有 children 且没被标记为 fetch_done)
    if "children" not in data:
        data["children"] = []
    
    # 简单的状态控制：如果没有获取过，且不是引用其他文件
    if not data.get("fetch_done") and "data_source" not in data:
        if request_count >= MAX_REQUESTS: return False
        
        new_children = fetch_wikidata_children(data["title"])
        request_count += 1
        time.sleep(1) # 礼貌延迟
        
        if new_children:
            # 合并去重
            existing_titles = {c["title"] for c in data["children"]}
            for nc in new_children:
                if nc["title"] not in existing_titles:
                    data["children"].append(nc)
            data["fetch_done"] = True
            changed = True
        else:
            data["fetch_done"] = True # 标记为已完成，免得下次还查
            changed = True

    # 2. 检查是否需要分裂 (Sharding)
    # 如果 children 数量超过阈值，我们将每个子节点的数据提取出去，变成独立文件
    # 注意：这里我们只把数据量大的子节点独立出去
    
    # 这里为了简化，我们采用“当层级过大时，把所有子节点都指向新文件”的策略吗？
    # 不，更好的策略是：如果 children 列表太长，我们不分裂文件，
    # 而是当我们要深入某个 child 时，才为那个 child 创建独立文件。
    
    # 我们遍历 children，随机选一个去“深化” (Deepen)
    # 只有当一个 child 也是对象结构且变得很庞大时才拆分。
    
    # 为了简化逻辑，我们只做“生长”：
    # 随机挑一个还没有 data_source 的 child，去递归处理它
    # 如果这个 child 还没有独立文件，我们就为它创建一个。
    
    for child in data["children"]:
        if request_count >= MAX_REQUESTS: break
        
        # 如果这个子节点已经是指针了，递归加载那个文件去处理
        if "data_source" in child:
            child_path = DATA_DIR / child["data_source"]
            child_data = load_json(child_path)
            if child_data:
                if process_node_data(child_data, child_path):
                    save_json(child_path, child_data)
        
        # 如果这个子节点还在父文件里，且没有被处理过
        else:
            # 决定是否要为这个子节点创建独立档案 (比如抛硬币，或者基于深度)
            # 这里我们强制：只要想获取子节点的子节点，就必须把子节点独立出去
            # 这样父文件只存目录，不存深层数据
            
            # 创建新文件路径
            safe_name = re.sub(r'[\\/*?:"<>|]', "", child["title"]).strip()
            new_rel_path = f"nodes/{safe_name}.json"
            new_full_path = DATA_DIR / new_rel_path
            
            if not new_full_path.exists():
                # 迁移数据
                new_node_data = {
                    "title": child["title"],
                    "children": [],
                    "fetch_done": False # 新节点即使创建了，初始也是未获取状态
                }
                save_json(new_full_path, new_node_data)
                
                # 修改当前父节点里的这个 child，变成指针
                child["data_source"] = new_rel_path
                # 删除多余字段，只留 metadata
                keys_to_keep = ["title", "data_source"]
                for k in list(child.keys()):
                    if k not in keys_to_keep: del child[k]
                
                changed = True
                print(f"🔨 分裂: {child['title']} -> {new_rel_path}")

    return changed

request_count = 0

def main():
    if not ROOT_FILE.exists():
        save_json(ROOT_FILE, {"title": "万物", "children": []})

    root_data = load_json(ROOT_FILE)
    if process_node_data(root_data, ROOT_FILE):
        save_json(ROOT_FILE, root_data)
        print("✅ 根节点数据已更新")

if __name__ == "__main__":
    main()
