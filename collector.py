# -*- coding: utf-8 -*-
"""네이버 쇼핑 오픈API 수집기."""
import html
import re
import time
import requests

API_URL = "https://openapi.naver.com/v1/search/shop.json"


class NaverShopClient:
    def __init__(self, client_id: str, client_secret: str, delay: float = 0.15):
        self.headers = {
            "X-Naver-Client-Id": client_id,
            "X-Naver-Client-Secret": client_secret,
        }
        self.delay = delay  # 호출 간 대기 (초당 10회 제한 대비)

    def search(self, keyword: str, max_rank: int = 1000, sort: str = "sim"):
        """키워드 검색 결과를 순위순으로 최대 max_rank개 수집."""
        items = []
        for start in range(1, min(max_rank, 1000) + 1, 100):
            resp = requests.get(
                API_URL,
                headers=self.headers,
                params={
                    "query": keyword,
                    "display": 100,
                    "start": start,
                    "sort": sort,
                },
                timeout=15,
            )
            if resp.status_code == 429:  # rate limit
                time.sleep(1.5)
                resp = requests.get(
                    API_URL, headers=self.headers,
                    params={"query": keyword, "display": 100,
                            "start": start, "sort": sort},
                    timeout=15,
                )
            resp.raise_for_status()
            batch = resp.json().get("items", [])
            if not batch:
                break
            items.extend(batch)
            if len(batch) < 100:
                break
            time.sleep(self.delay)

        # 순위 부여 + 정제
        cleaned = []
        for rank, it in enumerate(items, start=1):
            cleaned.append({
                "rank": rank,
                "title": strip_tags(it.get("title", "")),
                "mallName": it.get("mallName", ""),
                "lprice": int(it.get("lprice") or 0),
                "link": it.get("link", ""),
                "productId": it.get("productId", ""),
                "productType": int(it.get("productType") or 0),
                "brand": it.get("brand", ""),
                "maker": it.get("maker", ""),
            })
        return cleaned


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s))


# productType 참고:
# 1 일반상품(가격비교) 2 일반상품(가격비교 비매칭) 3 일반상품(가격비교 매칭)
# 4~6 중고, 7~9 단종, 10~12 판매예정
PRICE_COMPARE_CATALOG = {1}          # 가격비교 카탈로그 대표 상품
NORMAL_TYPES = {1, 2, 3}
