import os
import wikipediaapi  # pip install wikipedia-api
import json

# 输入文件和配置信息
SOURCE_FILE = "万物.txt"  # 初始分类文件
OUTPUT_DIR = "output"  # 输出目录
MAX_FILE_SIZE_MB = 2  # 文件大小阈值
MAX_DEPTH = 3  # 最大递归深度

wiki = wikipediaapi.Wikipedia("zh")  # 中文维基百科实例

def fetch_subcategories(category):
    """
    从维基百科获取子分类
    """
    page = wiki.page("Category:" + category)
    if not page.exists():
        return []
    children = []
    for c in page.categorymembers.values():
        if c.ns == wikipediaapi.Namespace.CATEGORY:  # 仅保留分类命名
            children.append(c.title.replace("Category:", ""))
    return children

def split_and_save(category, data, output_dir):
    """
    根据阈值，将数据写入文件，必要时进行分裂
    """
    # 序列化数据
    serialized_data = json.dumps(data, ensure_ascii=False, indent=2)
    size_in_mb = len(serialized_data.encode("utf-8")) / 1024 / 1024

    # 超出阈值，分裂文件
    if size_in_mb > MAX_FILE_SIZE_MB:
        os.makedirs(output_dir, exist_ok=True)
        parts = [data[i : i + 10] for i in range(0, len(data), 10)]  # 每份切10个节点
        for idx, part in enumerate(parts):
            file_path = os.path.join(output_dir, f"{category}_part{idx + 1}.txt")
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(part, ensure_ascii=False, indent=2))
    else:
        # 保存整个文件
        file_path = os.path.join(output_dir, f"{category}.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(serialized_data)

def process_category(category, depth, output_dir):
    """
    处理某个分类，递归扩展子分类
    """
    if depth > MAX_DEPTH:
        return  # 超过递归深度限制

    # 获取子分类
    subcategories = fetch_subcategories(category)

    # 保存当前分类到文件
    split_and_save(category, subcategories, output_dir)

    # 遍历处理子分类
    for subcat in subcategories:
        subcat_dir = os.path.join(output_dir, category)
        os.makedirs(subcat_dir, exist_ok=True)  # 子分类生成目录
        process_category(subcat, depth + 1, subcat_dir)

def main():
    # 递归遍历万物.txt 初始分类，并保存到目录中
    with open(SOURCE_FILE, "r", encoding="utf-8") as f:
        categories = [line.strip() for line in f if line.strip()]

    for category in categories:
        process_category(category, 1, OUTPUT_DIR)  # 开始递归处理

if __name__ == "__main__":
    main()