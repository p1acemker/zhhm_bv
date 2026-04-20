"""
测试 /edesc/search 接口：用 test.csv 的 EDesc+customer 查询，
统计 top3/top5/top10 中 by1 命中率
"""
import csv
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

API_URL = "http://localhost:8000/edesc/search"
CSV_FILE = "test.csv"
CONCURRENCY = 8


def test_one(query, customer, expected_by1, top_k):
    try:
        resp = requests.post(API_URL, json={
            "query": query,
            "customer": customer,
            "top_k": top_k,
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        predicted = [item.get("productName", "") for item in data]
        hit = expected_by1 in predicted
        return hit, predicted
    except Exception as e:
        return None, str(e)


def main():
    rows = []
    with open(CSV_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            edesc = row.get("EDesc", "").strip()
            customer = row.get("customer", "").strip()
            by1 = row.get("by1", "").strip()
            if edesc and by1:
                rows.append((edesc, customer, by1))

    total = len(rows)
    print(f"共 {total} 条测试数据\n")

    for top_k in [3, 5, 10]:
        t0 = time.time()
        results = [None] * total

        def do_query(idx_row):
            idx, (edesc, customer, by1) = idx_row
            return idx, test_one(edesc, customer, by1, top_k)

        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            futures = {pool.submit(do_query, (i, r)): i for i, r in enumerate(rows)}
            done_count = 0
            for f in as_completed(futures):
                idx, (hit, predicted) = f.result()
                results[idx] = (hit, predicted)
                done_count += 1
                if done_count % 200 == 0:
                    print(f"  top{top_k}: {done_count}/{total} done", flush=True)

        hits = sum(1 for r in results if r and r[0] is True)
        errors = sum(1 for r in results if r and r[0] is None)
        miss_examples = []
        for i, r in enumerate(results):
            if r and r[0] is False and len(miss_examples) < 10:
                miss_examples.append((i + 1, rows[i][2], r[1][:3]))

        elapsed = time.time() - t0
        rate = hits / total * 100 if total else 0
        print(f"\n=== Top-{top_k} 结果 ===")
        print(f"  命中: {hits}/{total}  命中率: {rate:.1f}%  错误: {errors}  耗时: {elapsed:.1f}s")
        if miss_examples:
            print(f"  未命中示例 (前10):")
            for idx, expected, preds in miss_examples:
                print(f"    #{idx} expected={expected}  got={preds}")
        print()


if __name__ == "__main__":
    main()
