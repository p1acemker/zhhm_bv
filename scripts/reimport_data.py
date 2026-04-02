# -*- coding: utf-8 -*-
"""
重新导入数据脚本 - 按新策略导入向量库

新策略：
- 相同 by1 对应一个父块
- 每条货描作为独立子块存储（逐条存储）
- 检索时按 parent_id 去重
- 大批量货描分批处理，避免超时

数据预处理：
- 清洗：去除尺寸描述（如 DN100、4" 等）
- 标准化：展开缩写、统一大小写
- 去重：同一 by1 下重复的货描只保留一条
"""

import pandas as pd
import sys
import os
import time
import re

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import QDRANT_URL, EMBEDDING_DIM, PARENT_COLLECTION, CHILD_COLLECTION
from qdrant_store import QdrantVectorStore
from embedder import BGEEmbedder


class DataPreprocessor:
    """数据预处理器：清洗、标准化、去重"""

    # 尺寸模式正则表达式
    SIZE_PATTERNS = [
        r'\s*\d+\.?\d*["/]+DN\d+\s*',           # 4"/DN100
        r'\s*\d+/\d+["/]+[\d.]+MM\s*',          # 21/2"/76MM
        r'\s*/DN\d+\s*',                         # /DN150
        r'\s*/[\d.]+MM\s*',                      # /219MM
        r'\s*DN\d+\s*$',                         # DN150
        r'\s*\d+\.?\d*["]\s*$',                  # 6"
        r'^\d+\s+',                              # 开头数字
        r"\d+''\s+",                             # 6''
        r'\d+"\s+',                              # 6"
    ]

    # 缩写映射表
    ABBREVIATION_MAP = {
        'BV': 'Butterfly Valve',
        'BFV': 'Butterfly Valve',
        'GRVD': 'Grooved',
        'DI': 'Ductile Iron',
        'SS': 'Stainless Steel',
        'EPDM': 'EPDM',
        'NBR': 'NBR',
        'LUG': 'Lug',
        'WAFER': 'Wafer',
        'FLANGE': 'Flange',
        'GEAR': 'Gear',
    }

    def clean_edesc(self, text: str) -> str:
        """清洗 EDesc，去除尺寸描述"""
        if pd.isna(text) or not str(text).strip():
            return ""

        result = str(text)
        for pattern in self.SIZE_PATTERNS:
            result = re.sub(pattern, ' ', result, flags=re.IGNORECASE)

        # 清理多余空格和逗号
        result = re.sub(r'\s*,\s*', ', ', result)
        result = re.sub(r'\s+', ' ', result)
        result = result.strip(', ')

        return result

    def standardize_edesc(self, text: str) -> str:
        """标准化 EDesc：展开缩写、统一大小写"""
        if not text:
            return ""

        result = text

        # 展开缩写
        for abbr, full in sorted(self.ABBREVIATION_MAP.items(), key=lambda x: -len(x[0])):
            pattern = r'\b' + re.escape(abbr) + r'\b'
            result = re.sub(pattern, full, result, flags=re.IGNORECASE)

        # Title Case
        result = result.title()

        # 清理
        result = re.sub(r'\s+', ' ', result).strip()

        return result

    def preprocess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        预处理数据：清洗、标准化、去重

        Args:
            df: 原始 DataFrame，包含 by1 和 EDesc 列

        Returns:
            处理后的 DataFrame
        """
        print("\n  [数据预处理]")

        # 1. 过滤无效数据
        original_count = len(df)
        df = df[df['by1'].notna() & (df['by1'] != '')]
        df = df[df['EDesc'].notna() & (df['EDesc'] != '')]
        print(f"    过滤空值: {original_count} -> {len(df)} 行")

        # 2. 清洗 EDesc
        df['EDesc_Cleaned'] = df['EDesc'].apply(self.clean_edesc)
        df = df[df['EDesc_Cleaned'] != '']
        print(f"    清洗后: {len(df)} 行")

        # 3. 标准化 EDesc
        df['EDesc_Standardized'] = df['EDesc_Cleaned'].apply(self.standardize_edesc)
        df = df[df['EDesc_Standardized'] != '']
        print(f"    标准化后: {len(df)} 行")

        # 4. 按 by1 + EDesc_Standardized 去重
        before_dedup = len(df)
        df = df.drop_duplicates(subset=['by1', 'EDesc_Standardized'], keep='first')
        print(f"    去重后: {before_dedup} -> {len(df)} 行 (去除 {before_dedup - len(df)} 条重复)")

        return df


class BGEEmbedderWrapper:
    """BGE-M3 Embedder with smaller batch size and longer timeout"""

    def __init__(self):
        from embedder import BGEEmbedder as _BGEEmbedder
        # 使用更长的超时时间（5分钟）处理大量 edesc
        self._embedder = _BGEEmbedder(timeout=300)
        # 使用更小的 batch_size 避免超时
        self.batch_size = 10

    def encode(self, texts, batch_size=None):
        return self._embedder.encode(texts, batch_size=batch_size or self.batch_size)

    def get_dimension(self):
        return self._embedder.get_dimension()

    def health_check(self):
        return self._embedder.health_check()


# 每个 by1 的最大货描数，超过此值会分批处理
MAX_EDESC_PER_BATCH = 20
# 重试次数
MAX_RETRIES = 3


def rebuild_and_import(csv_file: str):
    """重建集合并导入数据"""

    print("=" * 60)
    print("按新策略重新导入向量库")
    print("=" * 60)

    # 1. 读取CSV数据
    print(f"\n[1/5] 读取CSV文件: {csv_file}")
    df = pd.read_csv(csv_file)
    print(f"  总行数: {len(df)}")
    print(f"  列名: {list(df.columns)}")

    # 2. 数据预处理：清洗、标准化、去重
    print("\n[2/5] 数据预处理...")
    preprocessor = DataPreprocessor()
    df = preprocessor.preprocess(df)

    # 3. 按 by1 分组，收集标准化后的 EDesc 列表
    print("\n[3/5] 按 by1 分组...")
    grouped = df.groupby('by1')['EDesc_Standardized'].apply(list).reset_index()
    grouped.columns = ['by1', 'edesc_list']

    total_edesc = sum(len(lst) for lst in grouped['edesc_list'])
    print(f"  分组后 by1 数量: {len(grouped)}")
    print(f"  总货描条数: {total_edesc}")

    # 4. 初始化组件
    print("\n[4/5] 初始化组件...")
    store = QdrantVectorStore()
    embedder = BGEEmbedderWrapper()  # 使用长超时、小 batch_size 的 embedder

    # 检查 embedding 服务
    print("  检查 Embedding 服务...")
    if not embedder.health_check():
        print("  [ERROR] Embedding 服务不可用!")
        return
    print(f"  [OK] Embedding 服务正常 ({embedder.get_dimension()}维)")

    # 5. 重建集合
    print("  重建集合...")
    store.delete_collections()
    store.init_collections()
    print("  [OK] 集合重建完成")

    # 6. 导入数据
    print("\n[5/5] 导入数据...")
    success_count = 0
    error_count = 0

    def add_with_retry(by1, edesc_list, metadata, retries=MAX_RETRIES):
        """带重试的添加操作"""
        last_error = None
        for attempt in range(retries):
            try:
                store.add_product_with_edesc_list(
                    product_name=by1,
                    edesc_list=edesc_list,
                    embedding_func=embedder.encode,
                    metadata=metadata
                )
                return True, None
            except Exception as e:
                last_error = e
                if attempt < retries - 1:
                    wait_time = (attempt + 1) * 5  # 递增等待时间
                    print(f"    重试 {attempt + 2}/{retries} (等待 {wait_time}s)...")
                    time.sleep(wait_time)
        return False, last_error

    for idx, row in grouped.iterrows():
        by1 = row['by1']
        edesc_list = row['edesc_list']

        try:
            # 对于大 by1，分批处理
            if len(edesc_list) > MAX_EDESC_PER_BATCH:
                print(f"  大批量处理: {by1} ({len(edesc_list)} 条货描)")
                chunks = [edesc_list[i:i + MAX_EDESC_PER_BATCH]
                          for i in range(0, len(edesc_list), MAX_EDESC_PER_BATCH)]

                all_success = True
                for chunk_idx, chunk in enumerate(chunks):
                    success, err = add_with_retry(
                        by1, chunk,
                        {"by1": by1, "edesc_count": len(edesc_list), "chunk": chunk_idx + 1}
                    )
                    if success:
                        print(f"    批次 {chunk_idx + 1}/{len(chunks)} 完成")
                        time.sleep(2)  # 批次间休息，避免服务器压力
                    else:
                        print(f"    批次 {chunk_idx + 1}/{len(chunks)} 失败: {err}")
                        all_success = False
                        break

                if all_success:
                    success_count += 1
                else:
                    error_count += 1
            else:
                success, err = add_with_retry(
                    by1, edesc_list,
                    {"by1": by1, "edesc_count": len(edesc_list)}
                )
                if success:
                    success_count += 1
                else:
                    error_count += 1
                    if error_count <= 10:
                        print(f"  [ERROR] by1={by1}: {err}")

            # 进度显示
            if (idx + 1) % 10 == 0:
                print(f"  进度: {idx + 1}/{len(grouped)} ({(idx + 1) * 100 // len(grouped)}%)")

        except Exception as e:
            error_count += 1
            if error_count <= 10:
                print(f"  [ERROR] by1={by1}: {e}")

    # 6. 统计
    print("\n" + "=" * 60)
    print("导入完成!")
    print("=" * 60)
    print(f"  成功: {success_count}/{len(grouped)} 个 by1")
    print(f"  失败: {error_count} 个")

    stats = store.get_stats()
    print(f"\n向量库统计:")
    print(f"  父块数量: {stats['parent_collection']['points_count']}")
    print(f"  子块数量: {stats['child_collection']['points_count']}")

    # 7. 验证搜索
    print("\n[验证] 测试搜索功能...")
    test_query = "Butterfly Valve"
    results = store.search(embedder.encode(test_query), top_k=3)
    print(f"  查询: '{test_query}'")
    print(f"  返回 {len(results)} 条结果:")
    for i, r in enumerate(results, 1):
        print(f"    [{i}] by1: {r['productName']}, score: {r['score']:.4f}")
        if r.get('matched_edescs'):
            print(f"        匹配货描: {r['matched_edescs'][0][:60]}...")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        csv_file = sys.argv[1]
    else:
        csv_file = "zhhm_orders/training_history_orders.csv"

    if not os.path.exists(csv_file):
        print(f"[ERROR] 文件不存在: {csv_file}")
        sys.exit(1)

    rebuild_and_import(csv_file)
