# -*- coding: utf-8 -*-
"""
네이버 스토어 순위·가격 모니터링 — 수집 파이프라인

일반 사용은 app.py(웹 화면)를 통해 실행됩니다.
명령행에서 직접 실행할 수도 있습니다:
  python monitor.py            # settings.yaml 기반 실제 수집
  python monitor.py --demo     # 샘플 데이터로 결과물 형태 확인
"""
import argparse
import csv
import os
from datetime import datetime

import yaml

from analyzer import analyze_keyword, store_summary
from reporter_excel import build_excel
from reporter_dashboard import build_dashboard

BASE = os.path.dirname(os.path.abspath(__file__))


def load_config():
    with open(os.path.join(BASE, "config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def append_history(results, run_date):
    """실행할 때마다 키워드별 스냅샷을 누적 → 순위/가격 추이 추적용."""
    path = os.path.join(BASE, "data", "history.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["일시", "키워드", "상품", "우리순위", "우리가격",
                        "시장최저가", "시장평균가", "중앙값", "평균대비%", "백분위", "판정"])
        for r in results:
            m = r["market"]
            w.writerow([run_date, r["keyword"], r["product"],
                        r["our_rank"] or "", r["our_price"] or "",
                        m.get("min", ""), m.get("avg", ""), m.get("median", ""),
                        r["vs_avg_pct"] if r["vs_avg_pct"] is not None else "",
                        r["percentile"] if r["percentile"] is not None else "",
                        r["verdict"]])


def run_monitor(settings=None, demo=False, progress=None):
    """수집→분석→리포트 생성. progress(done, total, keyword) 콜백 지원.

    반환: {"results", "summary", "xlsx", "dash", "run_date"}
    """
    cfg = load_config()
    search_cfg = cfg.get("search", {})
    rules = cfg.get("pricing_rules", {})
    keywords = cfg.get("keywords") or []
    if not keywords:
        raise RuntimeError("추적할 키워드가 없습니다. 키워드를 먼저 등록하세요.")

    run_date = datetime.now().strftime("%Y-%m-%d %H:%M")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if demo:
        store_cfg = {"name": "우리스토어", "aliases": []}
        from demo_data import demo_search
        fetch = lambda kw: demo_search(kw, store_cfg["name"])
        store_name = store_cfg["name"] + " (데모)"
    else:
        if not settings:
            raise RuntimeError("설정(settings)이 없습니다. 화면에서 API 키와 스토어를 먼저 등록하세요.")
        store_cfg = settings["store"]
        store_name = store_cfg["name"]
        from collector import NaverShopClient
        client = NaverShopClient(settings["client_id"], settings["client_secret"])
        max_rank = int(search_cfg.get("max_rank", 1000))
        fetch = lambda kw: client.search(kw, max_rank=max_rank)

    results = []
    total = len(keywords)
    for i, kw_cfg in enumerate(keywords):
        kw = kw_cfg["keyword"]
        if progress:
            progress(i, total, kw)
        items = fetch(kw)
        results.append(analyze_keyword(kw_cfg, items, store_cfg, search_cfg, rules))
    if progress:
        progress(total, total, "리포트 생성 중")

    summary = store_summary(results)
    os.makedirs(os.path.join(BASE, "reports"), exist_ok=True)
    xlsx = build_excel(results, summary, store_name, run_date,
                       os.path.join(BASE, "reports", f"네이버모니터링_{stamp}.xlsx"))
    dash = build_dashboard(results, summary, store_name, run_date,
                           os.path.join(BASE, "reports", f"대시보드_{stamp}.html"))
    append_history(results, run_date)
    return {"results": results, "summary": summary,
            "xlsx": xlsx, "dash": dash, "run_date": run_date}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="샘플 데이터로 실행")
    args = ap.parse_args()

    settings = None
    if not args.demo:
        from setup_wizard import ensure_settings
        settings = ensure_settings(BASE, legacy_cfg=load_config())

    def prog(done, total, kw):
        print(f"[{done}/{total}] {kw}", flush=True)

    out = run_monitor(settings=settings, demo=args.demo, progress=prog)
    print("\n완료!")
    print(f"  엑셀   : {out['xlsx']}")
    print(f"  대시보드: {out['dash']}")


if __name__ == "__main__":
    main()
