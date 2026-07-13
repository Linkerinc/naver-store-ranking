# -*- coding: utf-8 -*-
"""최초 실행 설정 마법사 — API 키 직접 입력 + 스마트스토어 URL로 스토어 자동 인식.

입력된 값은 settings.yaml에 저장되며, 이후 실행부터는 묻지 않는다.
(다른 대리점에 프로그램을 배포할 때는 settings.yaml만 빼고 주면 됨)
"""
import os
import re
import requests
import yaml

UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/126.0.0.0 Safari/537.36")}
API_TEST = "https://openapi.naver.com/v1/search/shop.json"


def detect_store_name(url: str):
    """스마트스토어 주소에서 스토어명(판매처명) 자동 감지."""
    if not url.startswith("http"):
        url = "https://" + url
    try:
        r = requests.get(url, headers=UA, timeout=(4, 6))
        html = r.text
        # 1) 스마트스토어 내부 데이터의 채널명 (가장 정확)
        m = re.search(r'"channelName"\s*:\s*"([^"]+)"', html)
        if m:
            return m.group(1).strip()
        # 2) og:title 메타태그
        m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
        if m:
            name = re.sub(r"\s*(입니다|스토어입니다)\s*$", "", m.group(1)).strip()
            if name:
                return name
        # 3) <title>
        m = re.search(r"<title>([^<]+)</title>", html)
        if m:
            return m.group(1).split(":")[0].split("|")[0].strip()
    except Exception:
        pass
    return None


def validate_api_key(cid: str, csec: str):
    """키가 유효한지 테스트 호출 1회. (True/False/None=네트워크불가)"""
    try:
        r = requests.get(API_TEST,
                         headers={"X-Naver-Client-Id": cid,
                                  "X-Naver-Client-Secret": csec},
                         params={"query": "테스트", "display": 1}, timeout=10)
        return r.status_code == 200
    except Exception:
        return None


def _ask(prompt: str) -> str:
    while True:
        v = input(prompt).strip()
        if v:
            return v
        print("  (값을 입력해 주세요)")


def run_wizard(base: str) -> dict:
    print()
    print("=" * 46)
    print(" 최초 설정 — 한 번만 입력하면 저장됩니다")
    print("=" * 46)
    print("네이버 개발자센터(https://developers.naver.com/apps)에서")
    print("발급받은 '검색' API 키를 입력해 주세요.\n")

    while True:
        cid = _ask("① Client ID: ")
        csec = _ask("② Client Secret: ")
        ok = validate_api_key(cid, csec)
        if ok is False:
            print("  [!] 키 인증에 실패했습니다. 다시 확인해서 입력해 주세요.\n")
            continue
        if ok is None:
            print("  (인터넷 연결을 확인할 수 없어 키 검증은 건너뜁니다)")
        else:
            print("  ✓ 키 확인 완료")
        break

    print("\n③ 스마트스토어 주소를 입력해 주세요.")
    print("   예: https://smartstore.naver.com/xxxxx")
    store_name = None
    url = ""
    while not store_name:
        url = _ask("   스토어 URL: ")
        print("   스토어명 확인 중...")
        store_name = detect_store_name(url)
        if store_name:
            ans = input(f'   → "{store_name}" 이 맞나요? (Enter=예 / 아니면 스토어명 직접 입력): ').strip()
            if ans:
                store_name = ans
        else:
            print("   [!] 자동 인식에 실패했습니다.")
            store_name = _ask("   네이버쇼핑 검색 결과에 표시되는 판매처명을 직접 입력해 주세요: ")

    settings = {
        "client_id": cid,
        "client_secret": csec,
        "store": {"url": url, "name": store_name, "aliases": []},
    }
    path = os.path.join(base, "settings.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(settings, f, allow_unicode=True, sort_keys=False)
    try:
        os.chmod(path, 0o600)   # 본인만 읽을 수 있게
    except OSError:
        pass
    print(f'\n✓ 설정 저장 완료 → settings.yaml  (스토어: {store_name})')
    print("  키나 스토어를 바꾸려면 settings.yaml을 지우고 다시 실행하세요.\n")
    return settings


def load_settings(base: str, legacy_cfg: dict = None):
    """settings.yaml 로드 (비대화형). 없으면 구버전 config 이관 시도, 실패 시 None."""
    path = os.path.join(base, "settings.yaml")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            s = yaml.safe_load(f) or {}
        if s.get("client_id") and s.get("client_secret") and \
           s.get("store", {}).get("name"):
            return s
    if legacy_cfg:
        api = legacy_cfg.get("naver_api") or {}
        st = legacy_cfg.get("store") or {}
        cid, csec = api.get("client_id", ""), api.get("client_secret", "")
        if cid and csec and "YOUR_" not in cid and st.get("name"):
            s = {"client_id": cid, "client_secret": csec,
                 "store": {"url": st.get("url", ""), "name": st["name"],
                           "aliases": st.get("aliases", [])}}
            save_settings(base, s)
            return s
    return None


def save_settings(base: str, settings: dict):
    path = os.path.join(base, "settings.yaml")
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(settings, f, allow_unicode=True, sort_keys=False)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def ensure_settings(base: str, legacy_cfg: dict = None) -> dict:
    """settings.yaml 로드. 없으면 (1) 구버전 config 값 이관 (2) 설정 마법사."""
    path = os.path.join(base, "settings.yaml")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            s = yaml.safe_load(f) or {}
        if s.get("client_id") and s.get("client_secret") and \
           s.get("store", {}).get("name"):
            return s

    # 구버전 config.yaml에 키가 들어있으면 자동 이관 (질문 없이)
    if legacy_cfg:
        api = legacy_cfg.get("naver_api") or {}
        st = legacy_cfg.get("store") or {}
        cid, csec = api.get("client_id", ""), api.get("client_secret", "")
        if cid and csec and "YOUR_" not in cid and st.get("name"):
            settings = {"client_id": cid, "client_secret": csec,
                        "store": {"url": st.get("url", ""),
                                  "name": st["name"],
                                  "aliases": st.get("aliases", [])}}
            with open(path, "w", encoding="utf-8") as f:
                yaml.safe_dump(settings, f, allow_unicode=True, sort_keys=False)
            return settings

    return run_wizard(base)
