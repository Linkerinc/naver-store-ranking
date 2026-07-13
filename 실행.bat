@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 네이버 스토어 순위·가격 모니터링
echo === 네이버 스토어 순위·가격 모니터링 ===

rem ---- Python 확인 ----
set PY=
py -3 --version >nul 2>nul && set PY=py -3
if not defined PY ( python --version >nul 2>nul && set "PY=python" )
if not defined PY goto NOPYTHON

rem ---- 최초 1회: 가상환경 생성 ----
if not exist .venv (
  echo [최초 실행] 환경 설정 중... 1~2분 걸립니다.
  %PY% -m venv .venv
  if errorlevel 1 goto NOPYTHON
)

rem ---- 라이브러리 설치/확인 ----
.venv\Scripts\python -m pip install --quiet --upgrade pip
.venv\Scripts\pip install --quiet requests pyyaml openpyxl flask

echo 브라우저 화면이 곧 열립니다. 이 창은 사용하는 동안 열어두세요.
.venv\Scripts\python app.py
pause
exit /b 0

:NOPYTHON
echo.
echo [안내] Python이 설치되어 있지 않습니다.
echo 지금 열리는 페이지에서 노란색 Download 버튼으로 설치해 주세요.
echo 설치 화면에서 "Add python.exe to PATH" 체크박스를 꼭 켜세요!
echo 설치가 끝나면 이 파일(실행.bat)을 다시 더블클릭하면 됩니다.
start https://www.python.org/downloads/
pause