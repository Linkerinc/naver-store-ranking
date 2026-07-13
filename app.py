# -*- coding: utf-8 -*-
"""네이버 스토어 모니터링 — 로컬 웹 앱 (브라우저 화면에서 설정·실행·열람).

실행: python app.py  →  브라우저가 자동으로 열립니다 (http://127.0.0.1:8787)
모든 데이터는 이 컴퓨터 안에만 저장됩니다.
"""
import os
import socket
import threading
import webbrowser
from datetime import datetime

import yaml
from flask import Flask, jsonify, request, send_from_directory, Response

from monitor import BASE, load_config, run_monitor
from setup_wizard import detect_store_name, validate_api_key, load_settings, save_settings

app = Flask(__name__)
REPORTS = os.path.join(BASE, "reports")

STATE = {"running": False, "done": 0, "total": 0, "current": "",
         "error": None, "last_dash": None, "last_xlsx": None,
         "finished_at": None}
_LOCK = threading.Lock()


# ---------------- API ----------------

@app.get("/api/state")
def api_state():
    cfg = load_config()
    s = load_settings(BASE, legacy_cfg=cfg)
    return jsonify({
        "configured": bool(s),
        "store_name": s["store"]["name"] if s else None,
        "store_url": (s["store"].get("url") or "") if s else "",
        "keyword_count": len(cfg.get("keywords") or []),
        "run": {k: STATE[k] for k in
                ("running", "done", "total", "current", "error",
                 "last_dash", "last_xlsx", "finished_at")},
    })


@app.post("/api/setup/check")
def api_setup_check():
    """키 검증 + 스토어명 자동 인식 (저장 전 확인 단계)."""
    d = request.get_json(force=True)
    cid = (d.get("client_id") or "").strip()
    csec = (d.get("client_secret") or "").strip()
    url = (d.get("store_url") or "").strip()
    if not (cid and csec and url):
        return jsonify({"ok": False, "msg": "모든 항목을 입력해 주세요."})
    valid = validate_api_key(cid, csec)
    if valid is False:
        return jsonify({"ok": False,
                        "msg": "API 키 인증에 실패했습니다. Client ID/Secret을 다시 확인해 주세요."})
    name = detect_store_name(url)
    return jsonify({"ok": True, "store_name": name,
                    "key_checked": bool(valid),
                    "msg": None if name else
                    "스토어명 자동 인식에 실패했습니다. 아래 칸에 직접 입력해 주세요."})


@app.post("/api/setup/save")
def api_setup_save():
    d = request.get_json(force=True)
    name = (d.get("store_name") or "").strip()
    if not name:
        return jsonify({"ok": False, "msg": "스토어명을 입력해 주세요."})
    save_settings(BASE, {
        "client_id": d["client_id"].strip(),
        "client_secret": d["client_secret"].strip(),
        "store": {"url": (d.get("store_url") or "").strip(),
                  "name": name, "aliases": []},
    })
    return jsonify({"ok": True})


@app.post("/api/setup/reset")
def api_setup_reset():
    p = os.path.join(BASE, "settings.yaml")
    if os.path.exists(p):
        os.remove(p)
    return jsonify({"ok": True})


@app.get("/api/keywords")
def api_keywords_get():
    cfg = load_config()
    return jsonify(cfg.get("keywords") or [])


@app.post("/api/keywords")
def api_keywords_save():
    kws = request.get_json(force=True)
    clean = []
    for k in kws:
        kw = (k.get("keyword") or "").strip()
        if not kw:
            continue
        item = {"keyword": kw}
        if (k.get("product") or "").strip():
            item["product"] = k["product"].strip()
        for f in ("our_price", "price_min", "price_max"):
            if k.get(f):
                try:
                    item[f] = int(k[f])
                except (TypeError, ValueError):
                    pass
        clean.append(item)
    path = os.path.join(BASE, "config.yaml")
    cfg = load_config()
    cfg["keywords"] = clean
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    return jsonify({"ok": True, "count": len(clean)})


@app.post("/api/run")
def api_run():
    with _LOCK:
        if STATE["running"]:
            return jsonify({"ok": False, "msg": "이미 수집이 진행 중입니다."})
        s = load_settings(BASE, legacy_cfg=load_config())
        if not s:
            return jsonify({"ok": False, "msg": "먼저 설정을 완료해 주세요."})
        STATE.update(running=True, done=0, total=0, current="준비 중...",
                     error=None)

    def work():
        try:
            def prog(done, total, kw):
                STATE.update(done=done, total=total, current=kw)
            out = run_monitor(settings=s, progress=prog)
            STATE["last_dash"] = os.path.basename(out["dash"])
            STATE["last_xlsx"] = os.path.basename(out["xlsx"])
            STATE["finished_at"] = out["run_date"]
        except Exception as e:  # noqa
            STATE["error"] = str(e)
        finally:
            STATE["running"] = False

    threading.Thread(target=work, daemon=True).start()
    return jsonify({"ok": True})


@app.get("/api/reports")
def api_reports():
    items = []
    if os.path.isdir(REPORTS):
        for fn in os.listdir(REPORTS):
            p = os.path.join(REPORTS, fn)
            if os.path.isfile(p) and (fn.endswith(".html") or fn.endswith(".xlsx")):
                items.append({"name": fn,
                              "type": "dash" if fn.endswith(".html") else "xlsx",
                              "mtime": os.path.getmtime(p)})
    items.sort(key=lambda x: x["mtime"], reverse=True)
    for it in items:
        it["date"] = datetime.fromtimestamp(it.pop("mtime")).strftime("%Y-%m-%d %H:%M")
    return jsonify(items[:60])


@app.get("/reports/<path:fn>")
def serve_report(fn):
    return send_from_directory(REPORTS, fn)


@app.get("/data/history.csv")
def serve_history():
    return send_from_directory(os.path.join(BASE, "data"), "history.csv",
                               as_attachment=True)


# ---------------- 화면 ----------------

@app.get("/")
def index():
    return Response(PAGE, mimetype="text/html")


PAGE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>네이버 스토어 모니터링</title>
<style>
  :root{
    --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e;
    --muted:#898781; --grid:#e1e0d9; --border:rgba(11,11,11,.10);
    --accent:#2a78d6; --accent-ink:#ffffff; --good:#0ca30c; --crit:#d03b3b;
  }
  @media (prefers-color-scheme: dark){
    :root{
      --page:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7;
      --muted:#898781; --grid:#2c2c2a; --border:rgba(255,255,255,.10);
      --accent:#3987e5;
    }
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:system-ui,-apple-system,"Segoe UI","Malgun Gothic",sans-serif;
       background:var(--page);color:var(--ink);font-size:14px}
  .wrap{max-width:860px;margin:0 auto;padding:32px 24px 60px}
  h1{font-size:20px}
  .sub{color:var(--ink2);font-size:12px;margin-top:4px}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:12px;
        padding:20px 22px;margin-top:16px}
  .card h2{font-size:15px;margin-bottom:4px}
  .card .desc{font-size:12px;color:var(--muted);margin-bottom:14px}
  label{display:block;font-size:12px;color:var(--ink2);margin:12px 0 4px}
  input[type=text],input[type=password]{width:100%;padding:10px 12px;font-size:14px;
        border:1px solid var(--grid);border-radius:8px;background:var(--page);color:var(--ink)}
  input:focus{outline:2px solid var(--accent);border-color:transparent}
  button{font-family:inherit;font-size:14px;font-weight:600;border:none;border-radius:8px;
         padding:10px 18px;cursor:pointer}
  .btn-p{background:var(--accent);color:#fff}
  .btn-p:disabled{opacity:.5;cursor:default}
  .btn-s{background:transparent;color:var(--ink2);border:1px solid var(--grid)}
  .btn-danger{background:transparent;color:var(--crit);border:1px solid var(--grid)}
  .msg{font-size:13px;margin-top:10px}
  .msg.err{color:var(--crit)} .msg.ok{color:var(--good)}
  .row{display:flex;gap:10px;align-items:center}
  table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
  th{text-align:left;font-size:12px;color:var(--ink2);padding:6px 8px;
     border-bottom:1px solid var(--grid)}
  td{padding:6px 8px;border-bottom:1px solid var(--grid)}
  td input{padding:7px 10px !important}
  .del{color:var(--crit);cursor:pointer;font-weight:700;background:none;border:none;font-size:15px}
  .bar{height:8px;background:var(--grid);border-radius:6px;overflow:hidden;margin-top:12px}
  .bar>div{height:100%;background:var(--accent);width:0%;transition:width .4s}
  .hidden{display:none}
  a{color:var(--accent);text-decoration:none}
  .rep{display:flex;justify-content:space-between;padding:8px 4px;
       border-bottom:1px solid var(--grid);font-size:13px}
  .pill{font-size:11px;color:var(--muted)}
  .topline{display:flex;justify-content:space-between;align-items:center}
  .store-badge{font-size:13px;color:var(--ink2)}
  .store-badge b{color:var(--ink)}
</style>
</head>
<body>
<div class="wrap">
  <h1>네이버 스토어 순위·가격 모니터링</h1>
  <div class="sub">네이버쇼핑에서 우리 스토어의 검색 순위와 가격 적정성을 자동 분석합니다 · 데이터는 이 컴퓨터에만 저장됩니다</div>

  <!-- ===== 설정 화면 ===== -->
  <div id="setup" class="hidden">
    <div class="card">
      <h2>처음 설정 (한 번만)</h2>
      <div class="desc">네이버 개발자센터에서 발급받은 <b>검색 API 키</b>와 <b>스마트스토어 주소</b>를 입력하세요.
        키 발급: <a href="https://developers.naver.com/apps" target="_blank">developers.naver.com/apps</a>
        → 애플리케이션 등록 → 사용 API에서 "검색" 선택</div>
      <label>Client ID</label>
      <input type="text" id="cid" placeholder="예: 6PW0lqZuTU...">
      <label>Client Secret</label>
      <input type="password" id="csec" placeholder="예: uugUI1...">
      <label>스마트스토어 주소</label>
      <input type="text" id="surl" placeholder="예: https://smartstore.naver.com/xxxxx">
      <div id="nameBox" class="hidden">
        <label>스토어명 (자동 인식 결과 — 다르면 수정하세요)</label>
        <input type="text" id="sname">
      </div>
      <div class="msg" id="setupMsg"></div>
      <div class="row" style="margin-top:16px">
        <button class="btn-p" id="btnCheck" onclick="setupCheck()">확인</button>
        <button class="btn-p hidden" id="btnSave" onclick="setupSave()">저장하고 시작하기</button>
      </div>
    </div>
  </div>

  <!-- ===== 메인 화면 ===== -->
  <div id="main" class="hidden">
    <div class="card">
      <div class="topline">
        <div class="store-badge">스토어: <b id="storeName"></b></div>
        <button class="btn-danger" onclick="resetSetup()">키·스토어 변경</button>
      </div>
    </div>

    <div class="card">
      <h2>추적 키워드</h2>
      <div class="desc">고객이 검색할 만한 검색어를 등록하세요. 상품 라벨은 리포트 표시용(선택)입니다.</div>
      <table id="kwTable">
        <thead><tr><th style="width:55%">키워드</th><th style="width:35%">상품 라벨 (선택)</th><th></th></tr></thead>
        <tbody></tbody>
      </table>
      <div class="row" style="margin-top:12px">
        <button class="btn-s" onclick="addRow('','')">+ 키워드 추가</button>
        <button class="btn-p" onclick="saveKeywords()">키워드 저장</button>
        <span class="msg" id="kwMsg"></span>
      </div>
    </div>

    <div class="card">
      <h2>수집 실행</h2>
      <div class="desc">키워드별로 네이버쇼핑 1,000위까지 탐색해 순위·가격을 분석합니다. (키워드당 3~5초)</div>
      <div class="row">
        <button class="btn-p" id="btnRun" onclick="runNow()">지금 수집하기</button>
        <span class="msg" id="runMsg"></span>
      </div>
      <div class="bar hidden" id="barBox"><div id="barFill"></div></div>
      <div class="msg hidden" id="runStatus"></div>
      <div class="row hidden" id="doneBox" style="margin-top:12px">
        <a id="lnkDash" target="_blank"><button class="btn-p">📊 대시보드 열기</button></a>
        <a id="lnkXlsx"><button class="btn-s">엑셀 다운로드</button></a>
      </div>
    </div>

    <div class="card">
      <h2>지난 리포트</h2>
      <div class="desc">실행할 때마다 리포트가 쌓입니다 · <a href="/data/history.csv">전체 이력 CSV 내려받기</a></div>
      <div id="repList"></div>
    </div>
  </div>
</div>

<script>
let pending = {};

async function j(url, body){
  const r = await fetch(url, body ? {method:"POST",
    headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)} : {});
  return r.json();
}

async function refresh(){
  const st = await j("/api/state");
  document.getElementById("setup").classList.toggle("hidden", st.configured);
  document.getElementById("main").classList.toggle("hidden", !st.configured);
  if(st.configured){
    document.getElementById("storeName").textContent = st.store_name;
    updateRun(st.run);
  }
  return st;
}

/* ----- 설정 ----- */
async function setupCheck(){
  const m = document.getElementById("setupMsg");
  m.className = "msg"; m.textContent = "확인 중...";
  document.getElementById("btnCheck").disabled = true;
  const d = {client_id: v("cid"), client_secret: v("csec"), store_url: v("surl")};
  const r = await j("/api/setup/check", d);
  document.getElementById("btnCheck").disabled = false;
  if(!r.ok){ m.className = "msg err"; m.textContent = r.msg; return; }
  pending = d;
  document.getElementById("nameBox").classList.remove("hidden");
  document.getElementById("sname").value = r.store_name || "";
  m.className = "msg ok";
  m.textContent = (r.key_checked ? "✓ API 키 확인 완료. " : "") +
    (r.store_name ? `스토어명이 "${r.store_name}"(으)로 인식됐습니다. 맞으면 저장을 누르세요.`
                  : (r.msg || ""));
  document.getElementById("btnSave").classList.remove("hidden");
}
async function setupSave(){
  const r = await j("/api/setup/save", {...pending, store_name: v("sname")});
  const m = document.getElementById("setupMsg");
  if(!r.ok){ m.className="msg err"; m.textContent = r.msg; return; }
  await refresh(); loadKeywords(); loadReports();
}
async function resetSetup(){
  if(!confirm("API 키와 스토어 설정을 지우고 다시 입력할까요?")) return;
  await j("/api/setup/reset", {}); location.reload();
}
function v(id){ return document.getElementById(id).value.trim(); }

/* ----- 키워드 ----- */
function addRow(kw, product){
  const tb = document.querySelector("#kwTable tbody");
  const tr = document.createElement("tr");
  tr.innerHTML = `<td><input type="text" value="${kw}" placeholder="예: 3M 8977K 방진마스크"></td>
    <td><input type="text" value="${product}" placeholder="예: 8977K"></td>
    <td><button class="del" onclick="this.closest('tr').remove()">×</button></td>`;
  tb.appendChild(tr);
}
async function loadKeywords(){
  const kws = await j("/api/keywords");
  document.querySelector("#kwTable tbody").innerHTML = "";
  if(kws.length === 0) addRow("", "");
  kws.forEach(k => addRow(k.keyword || "", k.product || ""));
}
async function saveKeywords(){
  const rows = [...document.querySelectorAll("#kwTable tbody tr")].map(tr=>{
    const [a,b] = tr.querySelectorAll("input");
    return {keyword: a.value.trim(), product: b.value.trim()};
  }).filter(x=>x.keyword);
  const r = await j("/api/keywords", rows);
  const m = document.getElementById("kwMsg");
  m.className = "msg ok"; m.textContent = `✓ ${r.count}개 저장됨`;
  setTimeout(()=>m.textContent="", 2500);
}

/* ----- 실행 ----- */
async function runNow(){
  const r = await j("/api/run", {});
  const m = document.getElementById("runMsg");
  if(!r.ok){ m.className="msg err"; m.textContent = r.msg; return; }
  m.textContent = "";
  document.getElementById("doneBox").classList.add("hidden");
  poll();
}
let pollTimer = null;
function poll(){
  clearTimeout(pollTimer);
  pollTimer = setTimeout(async ()=>{
    const st = await j("/api/state");
    updateRun(st.run);
    if(st.run.running) poll(); else loadReports();
  }, 900);
}
function updateRun(run){
  const bar = document.getElementById("barBox"), fill = document.getElementById("barFill");
  const stat = document.getElementById("runStatus"), done = document.getElementById("doneBox");
  const btn = document.getElementById("btnRun");
  btn.disabled = run.running;
  bar.classList.toggle("hidden", !run.running);
  stat.classList.toggle("hidden", !run.running && !run.error);
  if(run.running){
    const pct = run.total ? Math.round(run.done/run.total*90)+5 : 5;
    fill.style.width = pct + "%";
    stat.className = "msg";
    stat.textContent = `수집 중 (${run.done}/${run.total||"?"}) — ${run.current}`;
    done.classList.add("hidden");
  } else if(run.error){
    stat.className = "msg err"; stat.textContent = "오류: " + run.error;
  } else if(run.last_dash){
    done.classList.remove("hidden");
    document.getElementById("lnkDash").href = "/reports/" + encodeURIComponent(run.last_dash);
    document.getElementById("lnkXlsx").href = "/reports/" + encodeURIComponent(run.last_xlsx);
  }
}

/* ----- 리포트 목록 ----- */
async function loadReports(){
  const reps = await j("/api/reports");
  const el = document.getElementById("repList");
  if(!reps.length){ el.innerHTML = '<div class="pill">아직 리포트가 없습니다. 위에서 수집을 실행해 보세요.</div>'; return; }
  el.innerHTML = reps.map(r=>{
    const url = "/reports/" + encodeURIComponent(r.name);
    const label = r.type === "dash" ? "📊 대시보드" : "📗 엑셀";
    const link = r.type === "dash"
      ? `<a href="${url}" target="_blank">${r.name}</a>` : `<a href="${url}">${r.name}</a>`;
    return `<div class="rep"><span>${label} &nbsp; ${link}</span><span class="pill">${r.date}</span></div>`;
  }).join("");
}

(async ()=>{
  const st = await refresh();
  if(st.configured){ loadKeywords(); loadReports(); if(st.run.running) poll(); }
})();
</script>
</body>
</html>
"""


def _free_port(start=8787):
    for p in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", p)) != 0:
                return p
    return start


if __name__ == "__main__":
    port = _free_port()
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    print(f"\n브라우저에서 http://127.0.0.1:{port} 가 열립니다.")
    print("이 창은 프로그램이 실행되는 동안 열어두세요. (종료: Ctrl+C 또는 창 닫기)\n")
    app.run(host="127.0.0.1", port=port, debug=False)
