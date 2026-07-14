# -*- coding: utf-8 -*-
"""네이버 데이터랩(검색어트렌드) — 키워드 검색량 추세 수집·분석.

데이터랩 값은 '기간 내 최고점=100'인 상대값이라, 모든 요청에 기준(anchor)
키워드를 함께 넣어 키워드 간 크기 비교가 가능하도록 정규화한다.
"""
import random
from datetime import date, timedelta
from statistics import mean

import requests

DATALAB_URL = "https://openapi.naver.com/v1/datalab/search"


def _call_datalab(cid, csec, keywords, start, end):
    """키워드(최대 5개) 묶음 하나 호출 → {키워드: [{period, ratio}, ...]}"""
    body = {
        "startDate": start, "endDate": end, "timeUnit": "month",
        "keywordGroups": [{"groupName": k, "keywords": [k]} for k in keywords],
    }
    r = requests.post(
        DATALAB_URL, json=body, timeout=10,
        headers={"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": csec})
    r.raise_for_status()
    return {res["title"]: res.get("data", []) for res in r.json().get("results", [])}


def _demo_series(keyword):
    """데모용 가짜 12개월 시계열 (여름/겨울 시즌성 흉내)."""
    rng = random.Random(hash(keyword) % 99999)
    today = date.today().replace(day=1)
    months = [(today - timedelta(days=30 * i)).replace(day=1) for i in range(11, -1, -1)]
    seasonal = "여름" in keyword or "쿨" in keyword
    out = []
    for m in months:
        base = 40 + rng.random() * 20
        if seasonal:
            base *= 1.8 if m.month in (5, 6, 7, 8) else 0.5
        out.append({"period": m.strftime("%Y-%m-%d"), "ratio": round(base, 1)})
    peak = max(x["ratio"] for x in out)
    for x in out:
        x["ratio"] = round(x["ratio"] / peak * 100, 1)
    return out


def _metrics(series):
    """시계열 → 추세 방향/배율, 피크 월."""
    ratios = [d["ratio"] for d in series]
    if len(ratios) < 4 or sum(ratios) == 0:
        return {"direction": "none", "trend_ratio": None, "peak_month": None,
                "avg": 0}
    recent = mean(ratios[-3:])
    prev = mean(ratios[-6:-3]) if len(ratios) >= 6 else mean(ratios[:-3])
    t = round(recent / prev, 2) if prev > 0 else None
    if t is None:
        direction = "none"
    elif t >= 1.2:
        direction = "up"
    elif t <= 0.8:
        direction = "down"
    else:
        direction = "flat"
    peak = max(series, key=lambda d: d["ratio"])
    return {"direction": direction, "trend_ratio": t,
            "peak_month": int(peak["period"][5:7]), "avg": mean(ratios)}


def fetch_trends(cid, csec, keywords, demo=False):
    """키워드 목록 → {키워드: {series, direction, trend_ratio, peak_month, size_index}}

    size_index: 기준(첫 키워드) 대비 상대 검색 규모. 1.0 = 기준과 비슷.
    """
    keywords = [k for i, k in enumerate(keywords) if k and k not in keywords[:i]]
    if not keywords:
        return {}

    end = date.today()
    start = end - timedelta(days=370)
    s, e = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    if demo:
        raw = {k: _demo_series(k) for k in keywords}
        anchor_avg = mean(d["ratio"] for d in raw[keywords[0]]) or 1
        out = {}
        for k, series in raw.items():
            m = _metrics(series)
            m["size_index"] = round(m.pop("avg") / anchor_avg, 2)
            out[k] = {"series": series, **m}
        return out

    anchor = keywords[0]
    out = {}
    anchor_avg_global = None
    rest = keywords[1:]
    chunks = [rest[i:i + 4] for i in range(0, len(rest), 4)] or [[]]
    for chunk in chunks:
        group = [anchor] + chunk
        data = _call_datalab(cid, csec, group, s, e)
        a_series = data.get(anchor, [])
        a_avg = mean(d["ratio"] for d in a_series) if a_series else 0
        if anchor_avg_global is None:
            anchor_avg_global = a_avg or 1
            m = _metrics(a_series)
            m["size_index"] = 1.0 if a_avg else 0
            out[anchor] = {"series": a_series, **m}
        for k in chunk:
            series = data.get(k, [])
            m = _metrics(series)
            avg = m.pop("avg")
            # 같은 호출 안의 anchor 평균으로 정규화 → 호출 간 비교 가능
            m["size_index"] = round(avg / a_avg, 2) if a_avg else None
            out[k] = {"series": series, **m}
    return out
