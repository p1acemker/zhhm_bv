# -*- coding: utf-8 -*-
"""
测试脚本 - 使用 test_orders.csv 测试检索效果
"""

import pandas as pd
from pathlib import Path
from main import ProductSearchEngine
from config import DEFAULT_TOP_K


def test_search_with_csv(
    csv_file: str, top_k: int = DEFAULT_TOP_K, max_tests: int = None
):
    """
    使用测试订单进行检索测试

    Args:
        csv_file: 测试订单 CSV 文件
        top_k: 返回结果数量
        max_tests: 最大测试数量（None 表示全部）
    """
    # 初始化引擎
    engine = ProductSearchEngine()

    # 读取测试数据
    df = pd.read_csv(csv_file)
    df = df[df["客户PO货描"].notna() & (df["客户PO货描"] != "")]

    if max_tests:
        df = df.head(max_tests)

    print(f"\n{'=' * 60}")
    print(f"开始测试: {len(df)} 条查询")
    print(f"{'=' * 60}")

    results_summary = []
    detailed_results = []

    for idx, row in df.iterrows():
        query_text = row["客户PO货描"]
        customer = row.get("客户简称（务必和IMS一致）", "Unknown")
        expected_by1 = row.get("基配品种", None)

        # 简化控制台输出
        if (idx + 1) % 10 == 0:
            print(f"进度: {idx + 1}/{len(df)}")

        try:
            # 执行检索
            results = engine.search(query_text, top_k=top_k)
            # 保存详细结果
            detailed_results.append(
                {
                    "index": idx + 1,
                    "customer": customer,
                    "query": query_text,
                    "expected": expected_by1 or "",
                    "results": results,
                }
            )

            # 汇总统计
            if results and expected_by1:
                # 前缀匹配
                found = any(r["productName"].startswith(expected_by1) for r in results)
                position = next(
                    (
                        i + 1
                        for i, r in enumerate(results)
                        if r["productName"].startswith(expected_by1)
                    ),
                    None,
                )
                results_summary.append(
                    {
                        "index": idx + 1,
                        "customer": customer,
                        "query": query_text[:100],
                        "expected": expected_by1,
                        "found": found,
                        "position": position,
                        "top_by1": results[0]["productName"],
                        "top_score": results[0]["score"],
                    }
                )

        except Exception as e:
            print(f"错误 [{idx + 1}]: {e}")

    # 输出统计
    print(f"\n{'=' * 60}")
    print("测试汇总")
    print(f"{'=' * 60}")

    if results_summary:
        summary_df = pd.DataFrame(results_summary)
        total_tests = len(summary_df)
        found_count = summary_df["found"].sum()
        accuracy = found_count / total_tests * 100 if total_tests > 0 else 0

        print(f"\n总测试数: {total_tests}")
        print(f"命中数: {found_count}")
        print(f"准确率: {accuracy:.2f}%")

        # Top-K 统计
        for k in [1, 3, 5, 10]:
            if k <= top_k:
                count = summary_df[summary_df["position"] <= k]["found"].sum()
                rate = count / total_tests * 100 if total_tests > 0 else 0
                print(f"Top-{k} 准确率: {rate:.2f}%")

        # 未命中统计
        missed = summary_df[~summary_df["found"]]
        if not missed.empty:
            print(f"\n未命中: {len(missed)}/{total_tests}")

        # 保存汇总结果
        output_summary = Path(csv_file).parent / "test_results_summary.csv"
        summary_df.to_csv(output_summary, index=False, encoding="utf-8-sig")
        print(f"\n汇总结果已保存到: {output_summary}")

    # 保存详细结果
    detailed_rows = []
    for dr in detailed_results:
        for i, r in enumerate(dr.get("results", [])):
            detailed_rows.append(
                {
                    "index": dr["index"],
                    "customer": dr["customer"],
                    "query": dr["query"][:200],
                    "expected": dr["expected"],
                    "rank": i + 1,
                    "by1": r["productName"],
                    "score": r["score"],
                    "matched_chunk": (
                        r["matched_chunks"][0][:150] if r.get("matched_chunks") else ""
                    ),
                }
            )
    if detailed_rows:
        detailed_df = pd.DataFrame(detailed_rows)
        output_detailed = Path(csv_file).parent / "test_results_detailed.csv"
        detailed_df.to_csv(output_detailed, index=False, encoding="utf-8-sig")
        print(f"详细结果已保存到: {output_detailed}")


if __name__ == "__main__":
    test_csv = r"F:\zhhm_bge_db\zhhm_orders\test_2_26.csv"

    # 运行测试（设置 max_tests=10 测试前 10 条，设为 None 测试全部）
    test_search_with_csv(
        csv_file=test_csv, top_k=10, max_tests=None  # 设为 None 测试全部
    )
