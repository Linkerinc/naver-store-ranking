#!/bin/bash
# 네이버 스토어 모니터링 실행 스크립트 (macOS)
# 더블클릭하면 Terminal에서 실행됩니다.
cd "$(dirname "$0")"

echo "=== 네이버 스토어 순위·가격 모니터링 ==="

# 최초 1회: 가상환경 생성 + 라이브러리 설치
if [ ! -d ".venv" ]; then
  echo "[최초 실행] 환경 설정 중... (1~2분 소요)"
  python3 -m venv .venv || { echo "python3가 필요합니다. 안내되는 개발자 도구 설치 창에서 '설치'를 눌러주세요."; exit 1; }
  ./.venv/bin/pip install --quiet --upgrade pip
fi
# 라이브러리 확인/설치 (업데이트 후에도 자동 반영)
./.venv/bin/pip install --quiet requests pyyaml openpyxl flask

# 웹 화면 실행 → 브라우저가 자동으로 열립니다
./.venv/bin/python app.py
