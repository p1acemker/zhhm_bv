# -*- coding: utf-8 -*-
"""
混合预测: 召回 → 精排 两阶段

Stage 1 (Recall):  向量库 Top-20 + 规则引擎 Top-10 → 合并候选池
Stage 2 (Rerank):  By1Reranker 逐维度特征匹配精排 → Top-10

使用:
    python hybrid_predict.py           → 默认 alpha=0.3 评估
    python hybrid_predict.py 0.4       → 指定向量融合权重
    python hybrid_predict.py sweep     → alpha 扫描
"""

import re
import csv
import sys
import os
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.by1_rule_engine import predict_top10
from scripts.reranker import By1Reranker


# ============================================================
# 向量召回客户端 (延迟初始化)
# ============================================================

_embedder = None
_store = None
_vec_available = None


def _init_clients():
    global _embedder, _store
    if _embedder is None:
        from embedder.bge_embedder import BGEEmbedder
        _embedder = BGEEmbedder()
    if _store is None:
        from qdrant_store import QdrantVectorStore
        _store = QdrantVectorStore()


def _check_vec_available():
    global _vec_available
    if _vec_available is not None:
        return _vec_available
    try:
        _init_clients()
        test_vec = _embedder.encode("test")
        if len(test_vec) != 1024:
            raise ValueError(f"embedding dim={len(test_vec)}")
        _store.search(test_vec, top_k=1)
        _vec_available = True
        print("[INFO] 向量服务可用, 启用混合预测")
    except Exception as e:
        _vec_available = False
        print(f"[WARN] 向量服务不可用 ({type(e).__name__}: {e}), 降级为纯规则引擎")
    return _vec_available


# ============================================================
# 混合预测: 召回 → 精排
# ============================================================

_reranker = None


def _get_reranker():
    global _reranker
    if _reranker is None:
        _reranker = By1Reranker()
    return _reranker


def predict_hybrid(edesc: str, top_k: int = 10, alpha: float = 0.3) -> dict:
    """混合预测: 召回 → 精排。

    Stage 1 (Recall):
        1a. 向量库召回 Top-20 (语义相似)
        1b. 规则引擎召回 Top-10 (特征匹配变体)
        → 合并去重

    Stage 2 (Rerank):
        By1Reranker 逐维度特征匹配评分
        → 融合向量分 → 排序取 Top-K

    Args:
        edesc: 英文描述
        top_k: 返回候选数量 (默认 10)
        alpha: 向量分融合权重 (默认 0.3)

    Returns:
        精排结果字典
    """
    # ========== Stage 1: 召回 (Recall) ==========
    vec_results = []
    vec_scores = {}

    # 1a. 向量召回 Top-20
    if _check_vec_available():
        try:
            query_vec = _embedder.encode(edesc)
            vec_results = _store.search(query_vec, top_k=20)
            vec_scores = {r['productName']: r['score'] for r in vec_results}
        except Exception:
            vec_results = []

    # 1b. 规则引擎召回 Top-10 (补充召回)
    rule_result = predict_top10(edesc)
    rule_candidates = rule_result['candidates']

    # 1c. 合并去重
    all_candidates = list(set(vec_scores.keys()) | set(rule_candidates))

    # ========== Stage 2: 精排 (Rerank) ==========
    reranker = _get_reranker()
    ranked = reranker.rerank(edesc, all_candidates, top_k=top_k,
                             vec_scores=vec_scores, alpha=alpha)

    return {
        'original': edesc,
        'top': ranked[0]['by1'] if ranked else '',
        'candidates': [r['by1'] for r in ranked],
        'scores': [r['score'] for r in ranked],
        'sources': ['both' if r['vec_score'] > 0 and r.get('rule_score', 0) > 0
                    else 'vector' if r['vec_score'] > 0 else 'rule'
                    for r in ranked],
        'details': ranked,
        'recall_size': len(all_candidates),
    }


# ============================================================
# 评估
# ============================================================

def run_evaluation(csv_path: str = None, alpha: float = 0.3):
    """在训练数据上评估"""
    if csv_path is None:
        csv_path = 'F:/zhhm_bge_db/zhhm_orders/edesc_by1_filtered.csv'

    with open(csv_path, 'r', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    total = len(rows)
    top1 = top3 = top5 = top10_count = 0
    misses = []

    print(f"评估混合预测: 召回 → 精排 (alpha={alpha})")
    print(f"{'序号':<5} {'实际by1':<18} {'Top-1':<18} {'来源':<6} {'命中':<6} {'位置'}")
    print("-" * 100)

    for i, row in enumerate(rows):
        edesc = row['EDesc']
        actual = row['by1']

        result = predict_hybrid(edesc, alpha=alpha)
        cands = result['candidates']
        top = cands[0] if cands else ''
        source = result['sources'][0] if result['sources'] else ''

        if top == actual:
            top1 += 1; top3 += 1; top5 += 1; top10_count += 1
            hit = '#1'
        elif actual in cands[:3]:
            top3 += 1; top5 += 1; top10_count += 1
            hit = '#3'
        elif actual in cands[:5]:
            top5 += 1; top10_count += 1
            hit = '#5'
        elif actual in cands:
            top10_count += 1
            hit = '#10'
        else:
            misses.append({'idx': i+1, 'actual': actual, 'top': top,
                           'cands': cands, 'edesc': edesc[:80]})
            hit = 'MISS'

        if hit != '#1' and i < 50:
            pos = f"#{cands.index(actual)+1}" if actual in cands else "未命中"
            print(f"{i+1:<5} {actual:<18} {top:<18} {source:<6} {hit:<6} {pos}")

        if (i + 1) % 200 == 0:
            print(f"  ... 已处理 {i+1}/{total}")

    print("\n" + "=" * 80)
    print(f"混合预测准确率报告 (alpha={alpha})")
    print("=" * 80)
    print(f"总样本数:     {total}")
    print(f"Top-1 命中:   {top1}/{total} ({top1/total*100:.1f}%)")
    print(f"Top-3 命中:   {top3}/{total} ({top3/total*100:.1f}%)")
    print(f"Top-5 命中:   {top5}/{total} ({top5/total*100:.1f}%)")
    print(f"Top-10 命中:  {top10_count}/{total} ({top10_count/total*100:.1f}%)")
    print(f"完全未命中:   {len(misses)}/{total} ({len(misses)/total*100:.1f}%)")

    if misses:
        print(f"\n未命中案例 ({len(misses)} 条):")
        patterns = defaultdict(int)
        for m in misses:
            patterns[f"{m['actual']} <- {m['top']}"] += 1
        for pat, cnt in sorted(patterns.items(), key=lambda x: -x[1])[:20]:
            print(f"  {pat} (n={cnt})")

    return {'total': total, 'top1': top1, 'top3': top3,
            'top5': top5, 'top10': top10_count, 'misses': len(misses)}


def sweep_alpha(csv_path: str = None):
    """遍历 alpha 值找最优融合权重"""
    if csv_path is None:
        csv_path = 'F:/zhhm_bge_db/zhhm_orders/edesc_by1_filtered.csv'

    print("Alpha 扫描: 向量权重 vs 准确率")
    print(f"{'alpha':<8} {'Top-1':<10} {'Top-3':<10} {'Top-5':<10} {'Top-10':<10} {'Miss':<10}")
    print("-" * 58)

    best_alpha = 0
    best_top10 = 0
    for a_int in range(0, 11):
        alpha = a_int / 10.0
        result = run_evaluation(csv_path, alpha=alpha)
        print(f"{alpha:<8.1f} "
              f"{result['top1']/result['total']*100:<10.1f} "
              f"{result['top3']/result['total']*100:<10.1f} "
              f"{result['top5']/result['total']*100:<10.1f} "
              f"{result['top10']/result['total']*100:<10.1f} "
              f"{result['misses']:<10}")
        if result['top10'] > best_top10:
            best_top10 = result['top10']
            best_alpha = alpha

    print(f"\n最优 alpha = {best_alpha} (Top-10 = {best_top10})")


def run_test_csv(csv_path: str = None, alpha: float = 0.3):
    """在 test.csv 上评估混合预测"""
    import re

    if csv_path is None:
        csv_path = 'F:/zhhm_bge_db/test.csv'

    # 读取 CSV (处理 BOM)
    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        raw_rows = list(csv.DictReader(f))

    # 统一列名 (处理 BOM 和乱码)
    rows = []
    for row in raw_rows:
        clean_row = {}
        for k, v in row.items():
            # 去除 BOM 和不可见字符
            clean_key = k.strip().replace('\ufeff', '')
            if '题目' in clean_key or 'EDesc' in clean_key:
                clean_row['edesc'] = v.strip()
            elif '答案' in clean_key or 'by1' in clean_key:
                clean_row['answer'] = v.strip()
        if clean_row:
            rows.append(clean_row)

    def extract_by1_from_answer(ans: str) -> str:
        """从答案中提取 by1 编码
        QXD381X D76 → XD381X
        LD71X4 D100 → D71X4
        RXD371XL D100 → XD371XL
        """
        ans = ans.strip()
        parts = ans.split()
        code_part = parts[0] if parts else ans
        # 去掉首字母品牌码 (Q/R/L)
        if code_part and code_part[0] in 'QRL':
            code_part = code_part[1:]
        return code_part

    total = len(rows)
    top1 = top3 = top5 = top10_count = 0

    print(f"评估 test.csv: 召回 → 精排 (alpha={alpha})")
    print(f"{'序号':<4} {'EDesc':<55} {'实际by1':<15} {'Top-1':<15} {'命中':<6} {'位置'}")
    print("-" * 115)

    for i, row in enumerate(rows):
        edesc = row.get('edesc', '')
        answer = row.get('answer', '')
        actual_by1 = extract_by1_from_answer(answer)

        if not edesc or not actual_by1:
            print(f"{i+1:<4} [跳过] edesc或by1为空")
            continue

        result = predict_hybrid(edesc, alpha=alpha)
        cands = result['candidates']
        top = cands[0] if cands else ''

        if top == actual_by1:
            top1 += 1; top3 += 1; top5 += 1; top10_count += 1
            hit = '#1'
        elif actual_by1 in cands[:3]:
            top3 += 1; top5 += 1; top10_count += 1
            hit = '#3'
        elif actual_by1 in cands[:5]:
            top5 += 1; top10_count += 1
            hit = '#5'
        elif actual_by1 in cands:
            top10_count += 1
            hit = '#10'
        else:
            hit = 'MISS'

        pos = f"#{cands.index(actual_by1)+1}" if actual_by1 in cands else "未命中"
        print(f"{i+1:<4} {edesc[:55]:<55} {actual_by1:<15} {top:<15} {hit:<6} {pos}")

    valid = len([r for r in rows if r.get('edesc') and r.get('answer')])
    print("\n" + "=" * 80)
    print(f"test.csv 评估报告 (alpha={alpha})")
    print("=" * 80)
    print(f"总题目数:     {valid}")
    if valid > 0:
        print(f"Top-1 命中:   {top1}/{valid} ({top1/valid*100:.1f}%)")
        print(f"Top-3 命中:   {top3}/{valid} ({top3/valid*100:.1f}%)")
        print(f"Top-5 命中:   {top5}/{valid} ({top5/valid*100:.1f}%)")
        print(f"Top-10 命中:  {top10_count}/{valid} ({top10_count/valid*100:.1f}%)")

    return {'total': valid, 'top1': top1, 'top3': top3,
            'top5': top5, 'top10': top10_count}


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'sweep':
        sweep_alpha()
    elif len(sys.argv) > 1 and sys.argv[1] == 'test':
        alpha = float(sys.argv[2]) if len(sys.argv) > 2 else 0.3
        run_test_csv(alpha=alpha)
    else:
        alpha = float(sys.argv[1]) if len(sys.argv) > 1 else 0.3
        run_evaluation(alpha=alpha)
