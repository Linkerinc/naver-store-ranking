# -*- coding: utf-8 -*-
"""수집 결과 → 순위/가격 분석."""
from statistics import mean, median


def normalize(s: str) -> str:
    return "".join((s or "").lower().split())


def is_our_store(mall_name: str, store_name: str, aliases) -> bool:
    m = normalize(mall_name)
    if not m:
        return False
    targets = [normalize(store_name)] + [normalize(a) for a in (aliases or [])]
    return any(t and (t == m or t in m) for t in targets)


def analyze_keyword(kw_cfg: dict, items: list, store_cfg: dict,
                    search_cfg: dict, rules: dict) -> dict:
    """키워드 하나에 대한 순위·가격 분석."""
    store_name = store_cfg.get("name", "")
    aliases = store_cfg.get("aliases", [])
    compare_top = int(search_cfg.get("compare_top", 100))
    pmin = kw_cfg.get("price_min")
    pmax = kw_cfg.get("price_max")

    # 우리 스토어 상품 찾기 (전체 수집 범위에서)
    ours = [it for it in items
            if is_our_store(it["mallName"], store_name, aliases)]
    best = ours[0] if ours else None

    our_price = best["lprice"] if best else kw_cfg.get("our_price")
    our_rank = best["rank"] if best else None

    # 가격 비교 대상: 상위 compare_top개 중 유효 가격
    pool0 = [it for it in items[:compare_top] if it["lprice"] > 0]

    # 단위 필터: 낱개/박스/대용량이 뒤섞여 평균이 왜곡되는 것 방지
    #  1) price_min/price_max가 명시되면 그대로 사용
    #  2) 없으면 우리 가격 기준 ±(unit_band_ratio)배 범위만 비교
    #     (기본 2.2배 → 우리가 3만원이면 약 1.4만~6.6만원 상품만 같은 단위로 간주)
    band = None
    if pmin or pmax:
        band = (pmin or 0, pmax or float("inf"))
    elif our_price:
        ratio = float(rules.get("unit_band_ratio", 2.2))
        if ratio > 1:
            band = (our_price / ratio, our_price * ratio)

    if band:
        pool = [it for it in pool0 if band[0] <= it["lprice"] <= band[1]]
    else:
        pool = pool0
    excluded = len(pool0) - len(pool)
    prices = sorted(it["lprice"] for it in pool)

    stats = {}
    if prices:
        stats = {
            "count": len(prices),
            "min": prices[0],
            "max": prices[-1],
            "avg": round(mean(prices)),
            "median": round(median(prices)),
        }

    # 가격 포지션 (백분위: 낮을수록 저렴한 편)
    percentile = None
    vs_min = vs_avg = None
    verdict = "판정불가"
    if our_price and prices:
        below = sum(1 for p in prices if p < our_price)
        percentile = round(below / len(prices) * 100)
        vs_min = round((our_price / stats["min"] - 1) * 100, 1)
        vs_avg = round((our_price / stats["avg"] - 1) * 100, 1)
        fair_band = float(rules.get("fair_band_pct", 10))
        warn_min = float(rules.get("warn_vs_min_pct", 30))
        if abs(vs_avg) <= fair_band:
            verdict = "적정"
        elif vs_avg < -fair_band:
            verdict = "저가 (마진 점검)"
        elif vs_min > warn_min:
            verdict = "고가 주의"
        else:
            verdict = "다소 높음"

    return {
        "keyword": kw_cfg["keyword"],
        "product": kw_cfg.get("product", ""),
        "our_rank": our_rank,                 # None = 1000위 밖
        "our_price": our_price,
        "our_title": best["title"] if best else "",
        "our_link": best["link"] if best else "",
        "our_items_count": len(ours),         # 이 키워드에 노출된 우리 상품 수
        "market": stats,
        "percentile": percentile,             # 우리 가격이 하위 N% 지점
        "vs_min_pct": vs_min,
        "vs_avg_pct": vs_avg,
        "verdict": verdict,
        "competitors": pool,                  # 가격 비교 풀 (단위 필터 적용)
        "excluded": excluded,                 # 단위가 달라 제외된 상품 수
        "pool_total": len(pool0),
        "band": band,
        "all_our_items": ours,
        "total_collected": len(items),
    }


def store_summary(results: list) -> dict:
    """스토어 종합 스코어카드."""
    ranked = [r for r in results if r["our_rank"]]
    vs_avgs = [r["vs_avg_pct"] for r in results if r["vs_avg_pct"] is not None]
    return {
        "keywords_total": len(results),
        "exposed": len(ranked),                                   # 1000위 내 노출
        "top10": sum(1 for r in ranked if r["our_rank"] <= 10),
        "top40": sum(1 for r in ranked if r["our_rank"] <= 40),
        "top100": sum(1 for r in ranked if r["our_rank"] <= 100),
        "avg_rank": round(mean(r["our_rank"] for r in ranked)) if ranked else None,
        "avg_vs_market_pct": round(mean(vs_avgs), 1) if vs_avgs else None,
        "over_priced": sum(1 for r in results if r["verdict"] in ("고가 주의", "다소 높음")),
        "fair_priced": sum(1 for r in results if r["verdict"] == "적정"),
        "under_priced": sum(1 for r in results if r["verdict"].startswith("저가")),
    }
