import os
import json
from statistics import mean

# ===============================
# 配置
# ===============================
SOURCE_FILE = "万物.txt"  # 样例数据文件
OUTPUT_DIR = "output"  # 输出目录
INITIAL_THRESHOLD_MB = 2  # 初始文件大小阈值（单位：MB）

# ===============================
# 动态调整逻辑
# ===============================
def adjust_threshold(data):
    """
    动态调整分割阈值，根据节点深度和广度调整文件最大大小。
    """
    # 分析数据的广度（每级节点平均子节点数）和深度
    depth = analyze_depth(data)  # 最大深度
    breadth = analyze_breadth(data)  # 每级平均宽度

    # 动态调整：文件大小随深度和广度变化，数据可根据实际需求优化权重
    adjusted_threshold = INITIAL_THRESHOLD_MB * ((1 + depth * 0.5) / (1 + mean(breadth) * 0.5))
    return max(0.5, adjusted_threshold)  # 文件阈值不能低于 0.5MB

def analyze_depth(data, depth=0):
    """分析数据深度"""
    if isinstance(data, dict) and "children" in data:
        return max([analyze_depth(child, depth + 1) for child in data["children"]], default=depth)
    return depth

def analyze_breadth(data):
    """分析数据每级宽度"""
    levels = []

    def breadth_at_level(data, level=0):
        if len(levels) <= level:
            levels.append(0)
        levels[level] += 1
        if isinstance(data, dict) and "children" in data:
            for child in data["children"]:
                breadth_at_level(child, level + 1)

    breadth_at_level(data)
    return levels

# ===============================
# 分割数据逻辑
# ===============================
def save_split_files(data, current_path, threshold):
    """
    根据阈值递归地将数据分割为目录或文件。
    """
    os.makedirs(current_path, exist_ok=True)

    # 判断文件是否需要分割
    serialized_size = len(json.dumps(data).encode("utf-8"))
    if serialized_size / 1024 / 1024 > threshold:  # 超出阈值，分割
        if isinstance(data, dict) and "children" in data:
            for child in data["children"]:
                child_path = os.path.join(current_path, child["name"])
                save_split_files(child, child_path, threshold)
        else:
            # 保存剩余数据文件
            with open(os.path.join(current_path, "remaining.json"), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    else:
        # 保存完整文件
        with open(os.path.join(current_path, "data.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

# ===============================
# 主逻辑：加载、分析、分割
# ===============================
def main():
    # 加载数据（更新为实际文件）
    with open(SOURCE_FILE, "r", encoding="utf-8") as f:
        content = [line.strip() for line in f.readlines()]
    data = {"name": "万物", "children": [{"name": line, "children": []} for line in content]}

    # 动态调整阈值
    threshold_mb = adjust_threshold(data)
    print(f"动态调整后的文件大小阈值：{threshold_mb:.2f}MB")

    # 分割文件并存储
    save_split_files(data, OUTPUT_DIR, threshold_mb)
    print(f"输出保存至目录：{OUTPUT_DIR}")

if __name__ == "__main__":
    main()