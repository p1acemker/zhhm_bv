import csv, requests, time
from concurrent.futures import ThreadPoolExecutor, as_completed

API_URL = "http://localhost:8000/edesc/search"

rows = []
with open("test.csv", "r", encoding="utf-8") as f:
    reader = csv.reader(f)
    next(reader)
    for row in reader:
        if len(row) >= 4:
            rows.append(
                {
                    "seq": row[0],
                    "customer": row[1].strip(),
                    "edesc": row[2].strip(),
                    "by1": row[3].strip(),
                }
            )

print("Total test rows: %d\n" % len(rows))


def query_one(r, top_k):
    try:
        resp = requests.post(
            API_URL,
            json={"query": r["edesc"], "top_k": top_k, "customer": r["customer"]},
            timeout=60,
        )
        data = resp.json().get("data", [])
        products = [d.get("productName", "") for d in data]
        hit = r["by1"] in products
        rank = products.index(r["by1"]) + 1 if hit else -1
        specs = []
        for d in data:
            if d.get("matched_specs"):
                specs.append(d["matched_specs"])
        return {
            "seq": r["seq"],
            "customer": r["customer"],
            "edesc": r["edesc"],
            "by1": r["by1"],
            "hit": hit,
            "rank": rank,
            "products": products,
            "specs": specs,
        }
    except Exception as e:
        return {
            "seq": r["seq"],
            "customer": r["customer"],
            "edesc": r["edesc"],
            "by1": r["by1"],
            "hit": False,
            "rank": -1,
            "products": [],
            "specs": [],
            "error": str(e)[:80],
        }


for top_k in [3, 5, 10]:
    t0 = time.time()
    results = []
    errors = 0
    with ThreadPoolExecutor(max_workers=5) as pool:
        futs = {pool.submit(query_one, r, top_k): r for r in rows}
        for fut in as_completed(futs):
            res = fut.result()
            if "error" in res:
                errors += 1
            results.append(res)
    elapsed = time.time() - t0

    hits = [r for r in results if r["hit"]]
    misses = [r for r in results if not r["hit"]]
    rate = len(hits) / len(rows) * 100
    rank1 = sum(1 for r in hits if r["rank"] == 1)

    print("=== top_%d ===" % top_k)
    print(
        "Hit: %d / %d (%.1f%%)  Rank1: %d  Errors: %d  Time: %.1fs"
        % (len(hits), len(rows), rate, rank1, errors, elapsed)
    )

    # Show hits with specs
    if hits:
        print("\nHits with matched_specs (first 20):")
        for h in hits[:20]:
            spec_str = " | ".join(str(s) for s in h["specs"]) if h["specs"] else "N/A"
            print(
                "  seq=%-6s rank=%d by1=%-12s customer=%-20s specs=%s"
                % (h["seq"], h["rank"], h["by1"], h["customer"][:20], spec_str[:80])
            )

    if misses:
        print("\nMiss (first 15):")
        for m in misses[:15]:
            err = m.get("error", "")
            if err:
                print(
                    "  seq=%-6s by1=%-12s ERROR: %s"
                    % (m["seq"], m["by1"], err)
                )
            else:
                print(
                    "  seq=%-6s by1=%-12s customer=%-20s returned=%s"
                    % (
                        m["seq"],
                        m["by1"],
                        m["customer"][:20],
                        m["products"][:5],
                    )
                )
    print()
