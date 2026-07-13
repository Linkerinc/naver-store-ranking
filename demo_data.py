# -*- coding: utf-8 -*-
"""API 키 없이 결과물 형태를 확인하기 위한 샘플 데이터 생성기.

실제 네이버쇼핑 API 응답과 동일한 구조로, 그럴듯한 분포의 가짜 데이터를 만든다.
(모든 판매처명·가격은 가상의 예시)
"""
import random

MALLS = ["세이프티월드", "산업안전마트", "공구백화점", "안전제일상사", "블루세이프",
         "다모아툴", "프로텍코리아", "세이프온", "현장맨스토어", "K세이프티",
         "대한안전물산", "원스톱안전", "세이프하우스", "툴앤세이프", "안전지대몰",
         "그린세이프티", "탑툴코리아", "세이프플러스", "한빛안전", "일등공구"]

# 키워드별 (기준가, 우리 순위, 우리 가격 배율)
SCENARIOS = {
    "3M 8977K 방진마스크": (12000, 23, 1.04),   # 평균 근처 → 적정
    "3M 귀마개 1100":      (9500,  7,  0.92),   # 1페이지 + 저렴
    "3M 보안경":           (15000, 145, 1.28),  # 순위 낮고 비쌈 → 주의
}


def demo_search(keyword: str, store_name: str):
    base, our_rank, our_mult = SCENARIOS.get(keyword, (10000, 50, 1.1))
    rng = random.Random(hash(keyword) % 10_000)
    total = rng.randint(300, 700)
    items = []
    for rank in range(1, total + 1):
        if rank == our_rank:
            mall, price = store_name, round(base * our_mult / 10) * 10
        else:
            mall = rng.choice(MALLS) + (f"{rng.randint(1,9)}호점" if rng.random() < .15 else "")
            spread = rng.gauss(1.08, 0.22)          # 평균가는 기준가보다 약간 위
            price = max(int(base * max(spread, 0.75) / 10) * 10, 1000)
        items.append({
            "rank": rank,
            "title": f"{keyword} 정품 {rng.choice(['1개', '10개입', '박스', '벌크', '낱개'])}",
            "mallName": mall,
            "lprice": price,
            "link": "https://smartstore.naver.com/example",
            "productId": str(80000000000 + rank),
            "productType": rng.choice([2, 2, 2, 3]),
            "brand": "3M", "maker": "3M",
        })
    return items
