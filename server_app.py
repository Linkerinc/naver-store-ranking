# -*- coding: utf-8 -*-
"""네이버 스토어 순위·가격 모니터링 — 다중 대리점 웹서비스 버전.

대리점은 사이트 주소로 접속해 자기 스토어를 등록하고(고유 링크 발급),
키워드를 직접 관리하며, 수집 결과 대시보드를 열람한다.
API 키는 서버 환경변수의 운영사(링커) 키 하나만 사용 — 대리점은 키 발급 불필요.

환경변수:
  NAVER_CLIENT_ID / NAVER_CLIENT_SECRET  : 네이버 검색 API 키 (필수)
  ADMIN_KEY   : 관리자 페이지 접근 키 (필수, 아무 문자열)
  DATA_DIR    : 데이터 저장 경로 (기본 ./data — 호스팅에선 영구 디스크 경로)
  DEMO=1      : 데모 모드 (네이버 API 대신 샘플 데이터 — 로컬 테스트용)

실행(로컬 테스트): python server_app.py
실행(서버):       gunicorn -w 1 --threads 8 -b 0.0.0.0:$PORT server_app:app
"""
import io
import json
import os
import queue
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request, Response, send_file, abort

from analyzer import analyze_keyword, store_summary
from reporter_dashboard import render_dashboard_html
from reporter_excel import build_excel
from setup_wizard import detect_store_name

KST = timezone(timedelta(hours=9))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "service.db")

DEMO = os.environ.get("DEMO") == "1"
CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")

MAX_KEYWORDS = 30          # 스토어당 키워드 상한 (API 한도 보호)
RUN_COOLDOWN_SEC = 600     # 수동 수집 최소 간격 (10분)
MAX_RANK = 1000
SEARCH_CFG = {"max_rank": MAX_RANK, "compare_top": 100}
RULES = {"fair_band_pct": 10, "warn_vs_min_pct": 30, "unit_band_ratio": 2.2}

app = Flask(__name__)


# ---------------- DB ----------------

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS stores(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          token TEXT UNIQUE NOT NULL,
          name TEXT NOT NULL,
          url TEXT DEFAULT '',
          created TEXT NOT NULL,
          last_run TEXT
        );
        CREATE TABLE IF NOT EXISTS keywords(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          store_id INTEGER NOT NULL,
          keyword TEXT NOT NULL,
          product TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS runs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          store_id INTEGER NOT NULL,
          run_at TEXT NOT NULL,
          summary TEXT NOT NULL,
          results TEXT NOT NULL
        );
        """)


init_db()


def get_store(token):
    with db() as con:
        r = con.execute("SELECT * FROM stores WHERE token=?", (token,)).fetchone()
    return r


# ---------------- 수집 워커 (전역 직렬 큐) ----------------

RUN_STATUS = {}   # store_id -> {running, done, total, current, error}
JOBS = queue.Queue()


def _fetch_factory():
    if DEMO:
        from demo_data import demo_search
        return lambda kw, store_name: demo_search(kw, store_name)
    from collector import NaverShopClient
    client = NaverShopClient(CLIENT_ID, CLIENT_SECRET)
    return lambda kw, store_name: client.search(kw, max_rank=MAX_RANK)


def collect_store(store_id):
    status = RUN_STATUS.setdefault(store_id, {})
    try:
        print(f"[collect] 시작: store {store_id}", flush=True)
        with db() as con:
            st = con.execute("SELECT * FROM stores WHERE id=?", (store_id,)).fetchone()
            kws = con.execute("SELECT * FROM keywords WHERE store_id=? ORDER BY id",
                              (store_id,)).fetchall()
        if not st or not kws:
            status.update(running=False, error="키워드가 없습니다. 먼저 등록해 주세요.")
            return
        fetch = _fetch_factory()
        store_cfg = {"name": st["name"], "aliases": []}
        status.update(running=True, done=0, total=len(kws), current="", error=None)
        results = []
        for i, k in enumerate(kws):
            status.update(done=i, current=k["keyword"])
            print(f"[collect] ({i+1}/{len(kws)}) {k['keyword']}", flush=True)
            items = fetch(k["keyword"], st["name"])
            print(f"[collect]   → {len(items)}개 수집됨", flush=True)
            kw_cfg = {"keyword": k["keyword"], "product": k["product"]}
            results.append(analyze_keyword(kw_cfg, items, store_cfg, SEARCH_CFG, RULES))
        status.update(done=len(kws), current="리포트 저장 중")
        summ = store_summary(results)
        now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        with db() as con:
            con.execute("INSERT INTO runs(store_id, run_at, summary, results) VALUES(?,?,?,?)",
                        (store_id, now, json.dumps(summ, ensure_ascii=False),
                         json.dumps(results, ensure_ascii=False)))
            con.execute("UPDATE stores SET last_run=? WHERE id=?", (now, store_id))
            # 오래된 실행 기록 정리 (스토어당 최근 60개 유지)
            con.execute("""DELETE FROM runs WHERE store_id=? AND id NOT IN
                         (SELECT id FROM runs WHERE store_id=? ORDER BY id DESC LIMIT 60)""",
                        (store_id, store_id))
        print(f"[collect] 완료: store {store_id}", flush=True)
    except Exception as e:  # noqa
        status["error"] = f"수집 중 오류: {e}"
        print(f"[collect] 오류: store {store_id}: {e}", flush=True)
    finally:
        status["running"] = False


def worker():
    while True:
        store_id = JOBS.get()
        try:
            collect_store(store_id)
        except Exception as e:  # 최후 방어선 — 작업자는 절대 죽지 않는다
            RUN_STATUS.setdefault(store_id, {}).update(
                running=False, error=f"수집 실패: {e}")
            print(f"[worker] 예외: {e}", flush=True)
        finally:
            JOBS.task_done()


_worker_thread = threading.Thread(target=worker, daemon=True)
_worker_thread.start()


def _ensure_worker():
    """작업자 스레드가 죽어 있으면 되살린다."""
    global _worker_thread
    if not _worker_thread.is_alive():
        print("[worker] 재기동", flush=True)
        _worker_thread = threading.Thread(target=worker, daemon=True)
        _worker_thread.start()





# ---------------- 등록 / 대리점 API ----------------

@app.post("/api/register")
def api_register():
    d = request.get_json(force=True)
    url = (d.get("store_url") or "").strip()
    manual = (d.get("store_name") or "").strip()
    if not url and not manual:
        return jsonify({"ok": False, "msg": "스마트스토어 주소를 입력해 주세요."})
    name = manual
    if not name:
        if not re.search(r"(smartstore|brand)\.naver\.com/[\w\-.]+", url):
            return jsonify({"ok": False,
                            "msg": "스마트스토어 주소 형식이 아닙니다. 예: https://smartstore.naver.com/xxxxx"})
        name = None
        try:
            from concurrent.futures import ThreadPoolExecutor
            ex = ThreadPoolExecutor(max_workers=1)
            fut = ex.submit(detect_store_name, url)
            name = fut.result(timeout=9)
            ex.shutdown(wait=False)
        except Exception:
            name = None
        if not name:
            return jsonify({"ok": False, "need_name": True,
                            "msg": "스토어명 자동 인식에 실패했습니다. 스토어명을 직접 입력해 주세요."})
    token = secrets.token_urlsafe(8)
    with db() as con:
        con.execute("INSERT INTO stores(token, name, url, created) VALUES(?,?,?,?)",
                    (token, name, url, datetime.now(KST).strftime("%Y-%m-%d %H:%M")))
    return jsonify({"ok": True, "token": token, "store_name": name})


def _store_or_404(token):
    st = get_store(token)
    if not st:
        abort(404)
    return st


@app.get("/s/<token>/api/state")
def api_store_state(token):
    st = _store_or_404(token)
    status = RUN_STATUS.get(st["id"], {})
    with db() as con:
        kw_count = con.execute("SELECT COUNT(*) c FROM keywords WHERE store_id=?",
                               (st["id"],)).fetchone()["c"]
        runs = con.execute(
            "SELECT id, run_at, summary FROM runs WHERE store_id=? ORDER BY id DESC LIMIT 30",
            (st["id"],)).fetchall()
    return jsonify({
        "store_name": st["name"], "last_run": st["last_run"],
        "keyword_count": kw_count,
        "run": {"running": status.get("running", False),
                "done": status.get("done", 0), "total": status.get("total", 0),
                "current": status.get("current", ""), "error": status.get("error")},
        "runs": [{"id": r["id"], "run_at": r["run_at"],
                  "summary": json.loads(r["summary"])} for r in runs],
    })


@app.get("/s/<token>/api/keywords")
def api_kw_get(token):
    st = _store_or_404(token)
    with db() as con:
        rows = con.execute("SELECT keyword, product FROM keywords WHERE store_id=? ORDER BY id",
                           (st["id"],)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/s/<token>/api/keywords")
def api_kw_save(token):
    st = _store_or_404(token)
    kws = request.get_json(force=True)
    clean = []
    for k in kws[:MAX_KEYWORDS]:
        kw = (k.get("keyword") or "").strip()
        if kw:
            clean.append((st["id"], kw, (k.get("product") or "").strip()))
    with db() as con:
        con.execute("DELETE FROM keywords WHERE store_id=?", (st["id"],))
        con.executemany("INSERT INTO keywords(store_id, keyword, product) VALUES(?,?,?)", clean)
    return jsonify({"ok": True, "count": len(clean), "max": MAX_KEYWORDS})


@app.post("/s/<token>/api/run")
def api_store_run(token):
    st = _store_or_404(token)
    status = RUN_STATUS.get(st["id"], {})
    if status.get("running"):
        return jsonify({"ok": False, "msg": "이미 수집이 진행 중입니다."})
    # 쿨다운: 마지막 실행 후 10분
    if st["last_run"]:
        try:
            last = datetime.strptime(st["last_run"], "%Y-%m-%d %H:%M").replace(tzinfo=KST)
            wait = RUN_COOLDOWN_SEC - (datetime.now(KST) - last).total_seconds()
            if wait > 0:
                return jsonify({"ok": False,
                                "msg": f"잠시 후 다시 시도해 주세요 (약 {int(wait // 60) + 1}분 후 가능)."})
        except ValueError:
            pass
    _ensure_worker()
    RUN_STATUS[st["id"]] = {"running": True, "done": 0, "total": 0,
                            "current": "대기열 등록됨", "error": None}
    JOBS.put(st["id"])
    print(f"[run] 대기열 등록: store {st['id']}", flush=True)
    return jsonify({"ok": True})


def _load_run(token, run_id):
    st = _store_or_404(token)
    with db() as con:
        if run_id == "latest":
            r = con.execute("SELECT * FROM runs WHERE store_id=? ORDER BY id DESC LIMIT 1",
                            (st["id"],)).fetchone()
        else:
            r = con.execute("SELECT * FROM runs WHERE store_id=? AND id=?",
                            (st["id"], run_id)).fetchone()
    if not r:
        abort(404)
    return st, r


@app.get("/s/<token>/dashboard/<run_id>")
def store_dashboard(token, run_id):
    st, r = _load_run(token, run_id)
    html = render_dashboard_html(json.loads(r["results"]), json.loads(r["summary"]),
                                 st["name"], r["run_at"])
    return Response(html, mimetype="text/html")


@app.get("/s/<token>/excel/<run_id>")
def store_excel(token, run_id):
    st, r = _load_run(token, run_id)
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tf:
        path = tf.name
    build_excel(json.loads(r["results"]), json.loads(r["summary"]),
                st["name"], r["run_at"], path)
    with open(path, "rb") as f:
        buf = io.BytesIO(f.read())
    os.unlink(path)
    stamp = r["run_at"].replace(":", "").replace("-", "").replace(" ", "_")
    return send_file(buf, as_attachment=True,
                     download_name=f"네이버모니터링_{stamp}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# ---------------- 관리자 ----------------

@app.get("/admin/<key>/delete/<int:store_id>")
def admin_delete(key, store_id):
    if not ADMIN_KEY or key != ADMIN_KEY:
        abort(404)
    with db() as con:
        con.execute("DELETE FROM keywords WHERE store_id=?", (store_id,))
        con.execute("DELETE FROM runs WHERE store_id=?", (store_id,))
        con.execute("DELETE FROM stores WHERE id=?", (store_id,))
    return Response('<meta charset="utf-8">삭제 완료. <a href="/admin/%s">목록으로</a>' % key,
                    mimetype="text/html")


@app.get("/admin/<key>")
def admin(key):
    if not ADMIN_KEY or key != ADMIN_KEY:
        abort(404)
    with db() as con:
        stores = con.execute("""
          SELECT s.*, (SELECT COUNT(*) FROM keywords k WHERE k.store_id=s.id) kw,
                 (SELECT COUNT(*) FROM runs r WHERE r.store_id=s.id) rc
          FROM stores s ORDER BY s.id DESC""").fetchall()
    rows = "".join(
        f"<tr><td>{s['id']}</td><td><b>{s['name']}</b></td>"
        f"<td><a href='/s/{s['token']}' target='_blank'>{s['token']}</a></td>"
        f"<td>{s['kw']}</td><td>{s['rc']}</td><td>{s['last_run'] or '-'}</td>"
        f"<td>{s['created']}</td>"
        f"<td><a href='/admin/{key}/delete/{s['id']}' "
        f"onclick=\"return confirm('이 스토어를 삭제할까요?')\">삭제</a></td></tr>" for s in stores)
    return Response(f"""<!DOCTYPE html><html lang="ko"><meta charset="utf-8">
<title>관리자 — 스토어 목록</title>
<style>body{{font-family:system-ui,'Malgun Gothic',sans-serif;padding:30px;font-size:14px}}
table{{border-collapse:collapse}}td,th{{border:1px solid #ddd;padding:6px 12px;text-align:left}}
th{{background:#f5f5f2}}</style>
<h2>등록 스토어 {len(stores)}곳</h2>
<table><tr><th>ID</th><th>스토어</th><th>고유링크</th><th>키워드</th><th>실행수</th>
<th>마지막 수집</th><th>등록일</th><th></th></tr>{rows}</table>""", mimetype="text/html")


# ---------------- 화면 ----------------

@app.get("/")
def landing():
    return Response(LANDING, mimetype="text/html")


@app.get("/s/<token>")
def store_page(token):
    st = _store_or_404(token)
    return Response(CONSOLE.replace("__TOKEN__", token)
                    .replace("__STORE__", st["name"]), mimetype="text/html")


STYLE = r"""
<style>
  :root{--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
    --grid:#e1e0d9;--border:rgba(11,11,11,.10);--accent:#2a78d6;--good:#0ca30c;--crit:#d03b3b}
  @media (prefers-color-scheme:dark){:root{--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;
    --ink2:#c3c2b7;--grid:#2c2c2a;--border:rgba(255,255,255,.10);--accent:#3987e5}}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:system-ui,-apple-system,"Segoe UI","Malgun Gothic",sans-serif;
    background:var(--page);color:var(--ink);font-size:14px}
  .wrap{max-width:820px;margin:0 auto;padding:36px 22px 60px}
  h1{font-size:20px} .sub{color:var(--ink2);font-size:12px;margin-top:4px}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:12px;
    padding:20px 22px;margin-top:16px}
  .card h2{font-size:15px;margin-bottom:4px}
  .desc{font-size:12px;color:var(--muted);margin-bottom:12px}
  label{display:block;font-size:12px;color:var(--ink2);margin:12px 0 4px}
  input[type=text]{width:100%;padding:10px 12px;font-size:14px;border:1px solid var(--grid);
    border-radius:8px;background:var(--page);color:var(--ink)}
  input:focus{outline:2px solid var(--accent);border-color:transparent}
  button{font-family:inherit;font-size:14px;font-weight:600;border:none;border-radius:8px;
    padding:10px 18px;cursor:pointer}
  .btn-p{background:var(--accent);color:#fff}.btn-p:disabled{opacity:.5}
  .btn-s{background:transparent;color:var(--ink2);border:1px solid var(--grid)}
  .msg{font-size:13px;margin-top:10px}.msg.err{color:var(--crit)}.msg.ok{color:var(--good)}
  table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
  th{text-align:left;font-size:12px;color:var(--ink2);padding:6px 8px;border-bottom:1px solid var(--grid)}
  td{padding:6px 8px;border-bottom:1px solid var(--grid)} td input{padding:7px 10px!important}
  .del{color:var(--crit);cursor:pointer;font-weight:700;background:none;border:none;font-size:15px}
  .bar{height:8px;background:var(--grid);border-radius:6px;overflow:hidden;margin-top:12px}
  .bar>div{height:100%;background:var(--accent);width:0%;transition:width .4s}
  .hidden{display:none} a{color:var(--accent);text-decoration:none}
  .rep{display:flex;justify-content:space-between;align-items:center;padding:8px 4px;
    border-bottom:1px solid var(--grid);font-size:13px;gap:10px;flex-wrap:wrap}
  .pill{font-size:11px;color:var(--muted)}
  .linkbox{background:var(--page);border:1px dashed var(--grid);border-radius:8px;
    padding:12px;font-size:13px;word-break:break-all;margin-top:10px}
</style>"""

LANDING = r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>네이버 스토어 순위·가격 모니터링</title>""" + STYLE + r"""</head>
<body><div class="wrap">
  <h1>네이버 스토어 순위·가격 모니터링</h1>
  <div class="sub">스마트스토어의 네이버쇼핑 검색 순위와 가격 적정성을 자동 분석해 드립니다</div>

  <div class="card">
    <h2>내 스토어 등록</h2>
    <div class="desc">스마트스토어 주소만 입력하면 바로 시작됩니다. 별도 가입·설치 없음.</div>
    <label>스마트스토어 주소</label>
    <input type="text" id="surl" placeholder="예: https://smartstore.naver.com/xxxxx">
    <div id="nameBox" class="hidden">
      <label>스토어명 (자동 인식 실패 — 네이버쇼핑에 표시되는 판매처명을 직접 입력)</label>
      <input type="text" id="sname">
    </div>
    <div class="msg" id="msg"></div>
    <div style="margin-top:14px"><button class="btn-p" id="btnReg" onclick="reg()">등록하기</button></div>
    <div id="done" class="hidden">
      <div class="msg ok" id="doneMsg"></div>
      <div class="linkbox" id="myLink"></div>
      <div class="desc" style="margin-top:8px">⭐ 위 주소가 우리 스토어 전용 페이지입니다.
        <b>즐겨찾기에 꼭 저장</b>하세요! (이 주소만 있으면 어디서든 접속 가능)</div>
      <div style="margin-top:10px"><a id="goBtn"><button class="btn-p">내 페이지로 이동 →</button></a></div>
    </div>
  </div>

  <div class="card">
    <h2>이미 등록했다면</h2>
    <div class="desc">등록할 때 받은 전용 주소로 접속하세요. 주소를 잃어버렸으면 운영사(링커)에 문의해 주세요.</div>
  </div>
</div>
<script>
async function reg(){
  const m = document.getElementById("msg");
  const body = {store_url: document.getElementById("surl").value.trim(),
                store_name: (document.getElementById("sname")||{}).value?.trim() || ""};
  m.className="msg"; m.textContent="확인 중...";
  document.getElementById("btnReg").disabled = true;
  let r;
  try{
    const ac = new AbortController();
    const timer = setTimeout(()=>ac.abort(), 20000);
    r = await (await fetch("/api/register",{method:"POST", signal: ac.signal,
      headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})).json();
    clearTimeout(timer);
  }catch(e){
    r = {ok:false, need_name:true,
         msg:"자동 확인이 지연되고 있습니다. 아래 칸에 스토어명을 직접 입력하고 다시 등록을 눌러 주세요."};
  }
  document.getElementById("btnReg").disabled = false;
  if(!r.ok){
    m.className="msg err"; m.textContent = r.msg;
    if(r.need_name) document.getElementById("nameBox").classList.remove("hidden");
    return;
  }
  m.textContent="";
  let restored = 0;
  try{
    const bak = JSON.parse(localStorage.getItem("nsr-backup")||"null");
    if(bak && bak.name === r.store_name && bak.rows?.length){
      const kr = await (await fetch("/s/"+r.token+"/api/keywords",{method:"POST",
        headers:{"Content-Type":"application/json"},body:JSON.stringify(bak.rows)})).json();
      restored = kr.count||0;
    }
  }catch(e){}
  const url = location.origin + "/s/" + r.token;
  document.getElementById("done").classList.remove("hidden");
  document.getElementById("doneMsg").textContent = `✓ "${r.store_name}" 등록 완료!` +
    (restored? ` (이전 키워드 ${restored}개 자동 복원됨)` : "");
  document.getElementById("myLink").textContent = url;
  document.getElementById("goBtn").href = url;
  document.getElementById("btnReg").classList.add("hidden");
}
</script></body></html>"""

CONSOLE = r"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__STORE__ — 순위·가격 모니터링</title>""" + STYLE + r"""</head>
<body><div class="wrap">
  <h1>__STORE__</h1>
  <div class="sub">네이버쇼핑 순위·가격 모니터링 · 키워드를 등록하고 원할 때 수집하세요 · 이 페이지를 즐겨찾기 하세요</div>

  <div class="card">
    <h2>추적 키워드</h2>
    <div class="desc">고객이 검색할 만한 검색어를 등록하세요 (최대 30개). 제품코드가 있으면 포함하는 게 정확합니다. 예: "3M 8977K 방진마스크"</div>
    <table id="kwTable">
      <thead><tr><th style="width:55%">키워드</th><th style="width:35%">상품 라벨 (선택)</th><th></th></tr></thead>
      <tbody></tbody>
    </table>
    <div style="display:flex;gap:10px;margin-top:12px;align-items:center">
      <button class="btn-s" onclick="addRow('','')">+ 키워드 추가</button>
      <button class="btn-p" onclick="saveKeywords()">저장</button>
      <span class="msg" id="kwMsg"></span>
    </div>
  </div>

  <div class="card">
    <h2>수집 실행</h2>
    <div class="desc">키워드별로 네이버쇼핑 1,000위까지 탐색합니다. (키워드당 3~5초)</div>
    <div style="display:flex;gap:10px;align-items:center">
      <button class="btn-p" id="btnRun" onclick="runNow()">지금 수집하기</button>
      <span class="msg" id="runMsg"></span>
    </div>
    <div class="bar hidden" id="barBox"><div id="barFill"></div></div>
    <div class="msg hidden" id="runStatus"></div>
  </div>

  <div class="card">
    <h2>리포트</h2>
    <div class="desc">수집이 끝날 때마다 쌓입니다. 대시보드는 브라우저로 열리고, 엑셀은 다운로드됩니다.</div>
    <div id="repList"></div>
  </div>
</div>
<script>
const T = "__TOKEN__";
const api = p => "/s/"+T+"/api/"+p;
async function j(url, body){
  const r = await fetch(url, body?{method:"POST",
    headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{});
  return r.json();
}
function addRow(kw, product){
  const tb = document.querySelector("#kwTable tbody");
  const tr = document.createElement("tr");
  tr.innerHTML = `<td><input type="text" value="${kw}" placeholder="예: 3M 8977K 방진마스크"></td>
    <td><input type="text" value="${product}" placeholder="예: 8977K"></td>
    <td><button class="del" onclick="this.closest('tr').remove()">×</button></td>`;
  tb.appendChild(tr);
}
async function loadKeywords(){
  const kws = await j(api("keywords"));
  document.querySelector("#kwTable tbody").innerHTML = "";
  if(!kws.length) addRow("","");
  kws.forEach(k=>addRow(k.keyword||"", k.product||""));
}
async function saveKeywords(){
  const rows=[...document.querySelectorAll("#kwTable tbody tr")].map(tr=>{
    const [a,b]=tr.querySelectorAll("input");
    return {keyword:a.value.trim(), product:b.value.trim()};
  }).filter(x=>x.keyword);
  const r = await j(api("keywords"), rows);
  try{ localStorage.setItem("nsr-backup", JSON.stringify({name: document.title.split(" — ")[0], rows})); }catch(e){}
  const m = document.getElementById("kwMsg");
  m.className="msg ok"; m.textContent=`✓ ${r.count}개 저장됨`;
  setTimeout(()=>m.textContent="",2500);
}
async function runNow(){
  const r = await j(api("run"), {});
  const m = document.getElementById("runMsg");
  if(!r.ok){ m.className="msg err"; m.textContent=r.msg; setTimeout(()=>m.textContent="",6000); return; }
  m.textContent=""; poll();
}
let pt=null;
function poll(){
  clearTimeout(pt);
  pt=setTimeout(async()=>{
    const st = await j(api("state"));
    render(st);
    if(st.run.running) poll();
  }, 1200);
}
function render(st){
  const bar=document.getElementById("barBox"), fill=document.getElementById("barFill");
  const stat=document.getElementById("runStatus"), btn=document.getElementById("btnRun");
  btn.disabled = st.run.running;
  bar.classList.toggle("hidden", !st.run.running);
  stat.classList.toggle("hidden", !st.run.running && !st.run.error);
  if(st.run.running){
    const pct = st.run.total? Math.round(st.run.done/st.run.total*90)+5 : 5;
    fill.style.width=pct+"%";
    stat.className="msg"; stat.textContent=`수집 중 (${st.run.done}/${st.run.total||"?"}) — ${st.run.current}`;
  } else if(st.run.error){ stat.className="msg err"; stat.textContent=st.run.error; }
  const el=document.getElementById("repList");
  if(!st.runs.length){ el.innerHTML='<div class="pill">아직 리포트가 없습니다. 키워드 저장 후 "지금 수집하기"를 눌러보세요.</div>'; return; }
  el.innerHTML = st.runs.map(r=>{
    const s=r.summary;
    const info=`키워드 ${s.keywords_total} · 노출 ${s.exposed} · 1페이지 ${s.top10}`;
    return `<div class="rep"><span><a href="/s/${T}/dashboard/${r.id}" target="_blank">📊 ${r.run_at} 대시보드</a>
      &nbsp;<a href="/s/${T}/excel/${r.id}">📗 엑셀</a></span>
      <span class="pill">${info}</span></div>`;
  }).join("");
}
(async()=>{ loadKeywords(); const st=await j(api("state")); render(st); if(st.run.running) poll(); })();
</script></body></html>"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"서비스 시작: http://127.0.0.1:{port}  (DEMO={'ON' if DEMO else 'OFF'})")
    app.run(host="127.0.0.1", port=port, debug=False)
