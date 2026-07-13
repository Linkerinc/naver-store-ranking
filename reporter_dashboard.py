# -*- coding: utf-8 -*-
"""분석 결과 → 자체 완결형 HTML 대시보드."""
import json

TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>네이버쇼핑 모니터링 — __STORE__</title>
<style>
  :root{
    --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e;
    --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7;
    --border:rgba(11,11,11,.10);
    --accent:#2a78d6; --dim:#c3c2b7;
    --pos:#e34948; --neg:#2a78d6; --mid:#f0efec;
    --good:#0ca30c; --warn:#fab219; --serious:#ec835a; --crit:#d03b3b;
    --good-text:#006300;
  }
  @media (prefers-color-scheme: dark){
    :root{
      --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7;
      --muted:#898781; --grid:#2c2c2a; --axis:#383835;
      --border:rgba(255,255,255,.10);
      --accent:#3987e5; --dim:#52514e;
      --pos:#e66767; --neg:#3987e5; --mid:#383835;
      --good-text:#0ca30c;
    }
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:system-ui,-apple-system,"Segoe UI","Malgun Gothic",sans-serif;
       background:var(--page);color:var(--ink);padding:28px 32px;font-size:14px}
  h1{font-size:20px;font-weight:700}
  .sub{color:var(--ink2);font-size:12px;margin-top:4px}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
        gap:12px;margin:20px 0}
  .tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;
        padding:14px 16px}
  .tile .lab{font-size:12px;color:var(--ink2)}
  .tile .val{font-size:28px;font-weight:700;margin-top:4px}
  .tile .note{font-size:11px;color:var(--muted);margin-top:2px}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:10px;
        padding:18px 20px;margin-bottom:16px}
  .card h2{font-size:14px;font-weight:700;margin-bottom:2px}
  .card .desc{font-size:12px;color:var(--muted);margin-bottom:12px}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{text-align:left;color:var(--ink2);font-weight:600;font-size:12px;
     border-bottom:1px solid var(--axis);padding:6px 8px}
  td{padding:7px 8px;border-bottom:1px solid var(--grid)}
  td.num{text-align:right;font-variant-numeric:tabular-nums}
  th.num{text-align:right}
  .badge{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:600}
  .badge .dot{width:8px;height:8px;border-radius:50%}
  .rank-good{color:var(--good-text);font-weight:700}
  .rank-miss{color:var(--crit)}
  .rowlab{font-weight:600}
  .rowsub{color:var(--muted);font-size:11px}
  svg text{font-family:inherit}
  .tip{position:fixed;pointer-events:none;background:var(--surface);
       border:1px solid var(--border);border-radius:8px;padding:8px 10px;
       font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.12);display:none;z-index:10;
       max-width:280px}
  .tip b{display:block;margin-bottom:2px}
  .legend{display:flex;gap:16px;font-size:12px;color:var(--ink2);margin-bottom:10px;flex-wrap:wrap}
  .legend span{display:inline-flex;align-items:center;gap:6px}
  .sw{width:10px;height:10px;border-radius:3px;display:inline-block}
</style>
</head>
<body>
<h1>네이버쇼핑 순위·가격 모니터링</h1>
<div class="sub">__STORE__ · 수집 시각 __DATE__ · 기준: 네이버쇼핑 정확도순(광고 제외), 가격 비교는 키워드별 상위권 상품</div>

<div class="kpis" id="kpis"></div>

<div class="card">
  <h2>키워드별 순위 & 가격 판정</h2>
  <div class="desc">순위는 1,000위까지 탐색. 백분위는 낮을수록 우리가 저렴한 편.</div>
  <table id="summaryTable"></table>
</div>

<div class="card">
  <h2>가격 분포 속 우리 위치</h2>
  <div class="desc">키워드별 경쟁 상품 가격 분포 — 점 하나가 판매처 하나 (마우스를 올리면 판매처·가격 표시)</div>
  <div class="legend">
    <span><span class="sw" style="background:var(--accent)"></span>우리 스토어</span>
    <span><span class="sw" style="background:var(--dim)"></span>경쟁 판매처</span>
    <span><span class="sw" style="width:2px;height:12px;border-radius:0;background:var(--ink2)"></span>시장 평균가</span>
  </div>
  <div id="strips"></div>
</div>

<div class="card">
  <h2>시장 평균가 대비 우리 가격</h2>
  <div class="desc">0% = 시장 평균과 동일 · 오른쪽(+)은 평균보다 비쌈, 왼쪽(−)은 저렴</div>
  <div id="diverging"></div>
</div>

<div class="tip" id="tip"></div>

<script>
const DATA = __DATA__;
const fmt = n => n==null ? "-" : n.toLocaleString("ko-KR");
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

/* ---------- KPI ---------- */
const S = DATA.summary;
const kpis = [
  {lab:"추적 키워드", val:S.keywords_total, note:"모니터링 대상"},
  {lab:"노출", val:S.exposed+"/"+S.keywords_total, note:"1,000위 내 검색 노출"},
  {lab:"1페이지 진입", val:S.top10, note:"10위 이내 키워드"},
  {lab:"평균 순위", val:S.avg_rank ?? "-", note:"노출 키워드 기준"},
  {lab:"시장평균 대비 가격", val:(S.avg_vs_market_pct==null?"-":(S.avg_vs_market_pct>0?"+":"")+S.avg_vs_market_pct+"%"), note:"전 키워드 평균"},
  {lab:"가격 판정", val:S.fair_priced+" 적정", note:S.over_priced+" 주의 · "+S.under_priced+" 저가"},
];
document.getElementById("kpis").innerHTML = kpis.map(k=>
  `<div class="tile"><div class="lab">${k.lab}</div><div class="val">${k.val}</div><div class="note">${k.note}</div></div>`).join("");

/* ---------- 요약 테이블 ---------- */
const VERDICT = {
  "적정":        {c:"var(--good)",    t:"✓ 적정"},
  "다소 높음":    {c:"var(--warn)",    t:"! 다소 높음"},
  "고가 주의":    {c:"var(--crit)",    t:"✕ 고가 주의"},
  "저가 (마진 점검)":{c:"var(--serious)", t:"▽ 저가"},
  "판정불가":     {c:"var(--muted)",   t:"– 판정불가"},
};
let rows = `<tr><th>키워드</th><th class="num">우리 순위</th><th class="num">우리 가격</th>
<th class="num">시장 최저</th><th class="num">시장 평균</th><th class="num">평균 대비</th>
<th class="num">백분위</th><th>판정</th></tr>`;
for(const r of DATA.results){
  const v = VERDICT[r.verdict] || VERDICT["판정불가"];
  const rank = r.our_rank
    ? `<span class="${r.our_rank<=10?'rank-good':''}">${r.our_rank}위</span>`
    : `<span class="rank-miss">1000위 밖</span>`;
  rows += `<tr>
    <td><div class="rowlab">${r.keyword}</div><div class="rowsub">${r.product||""}</div></td>
    <td class="num">${rank}</td>
    <td class="num"><b>${fmt(r.our_price)}</b></td>
    <td class="num">${fmt(r.market.min)}</td>
    <td class="num">${fmt(r.market.avg)}</td>
    <td class="num">${r.vs_avg_pct==null?"-":(r.vs_avg_pct>0?"+":"")+r.vs_avg_pct+"%"}</td>
    <td class="num">${r.percentile==null?"-":"하위 "+r.percentile+"%"}</td>
    <td><span class="badge"><span class="dot" style="background:${v.c}"></span>${v.t}</span></td>
  </tr>`;
}
document.getElementById("summaryTable").innerHTML = rows;

/* ---------- 가격 분포 스트립 ---------- */
const tip = document.getElementById("tip");
function showTip(ev, html){
  tip.innerHTML = html; tip.style.display="block";
  const x = Math.min(ev.clientX+14, innerWidth-300);
  tip.style.left = x+"px"; tip.style.top = (ev.clientY+14)+"px";
}
function hideTip(){ tip.style.display="none"; }

const stripsEl = document.getElementById("strips");
const W = Math.min(stripsEl.clientWidth || 900, 1100), ROW_H = 64, PADL = 10, PADR = 30;
for(const r of DATA.results){
  const prices = r.competitors.map(c=>c.lprice).filter(p=>p>0);
  if(!prices.length) continue;
  const lo = Math.min(...prices, r.our_price||Infinity);
  const hi = Math.max(...prices, r.our_price||0);
  const span = (hi-lo)||1;
  const X = p => PADL + (p-lo)/span*(W-PADL-PADR);
  const cy = 34;
  let svg = `<svg width="${W}" height="${ROW_H}" role="img" aria-label="${r.keyword} 가격 분포">`;
  const exNote = r.excluded ? `  ·  단위 다른 ${r.excluded}개 제외` : "";
  svg += `<text x="${PADL}" y="12" font-size="12" font-weight="600" fill="var(--ink)">${r.keyword}<tspan font-weight="400" fill="var(--muted)">${exNote}</tspan></text>`;
  svg += `<line x1="${PADL}" y1="${cy}" x2="${W-PADR}" y2="${cy}" stroke="var(--grid)" stroke-width="1"/>`;
  if(r.market.avg){
    svg += `<line x1="${X(r.market.avg)}" y1="${cy-11}" x2="${X(r.market.avg)}" y2="${cy+11}" stroke="var(--ink2)" stroke-width="2"/>`;
  }
  r.competitors.forEach((c,i)=>{
    if(c.lprice<=0) return;
    const ours = c.is_ours;
    if(ours) return; // 우리 점은 맨 위에 다시 그림
    svg += `<circle cx="${X(c.lprice)}" cy="${cy}" r="5" fill="var(--dim)" fill-opacity="0.55"
      stroke="var(--surface)" stroke-width="1"
      data-tip="<b>${c.mallName}</b>${fmt(c.lprice)}원 · ${c.rank}위"/>`;
  });
  if(r.our_price){
    svg += `<circle cx="${X(r.our_price)}" cy="${cy}" r="7" fill="var(--accent)"
      stroke="var(--surface)" stroke-width="2"
      data-tip="<b>우리 스토어</b>${fmt(r.our_price)}원 · ${r.our_rank?r.our_rank+"위":"1000위 밖"}"/>`;
    svg += `<text x="${X(r.our_price)}" y="${cy-14}" font-size="11" font-weight="700"
      text-anchor="middle" fill="var(--ink)">${fmt(r.our_price)}</text>`;
  }
  svg += `<text x="${PADL}" y="${cy+22}" font-size="10" fill="var(--muted)">${fmt(lo)}원</text>`;
  svg += `<text x="${W-PADR}" y="${cy+22}" font-size="10" text-anchor="end" fill="var(--muted)">${fmt(hi)}원</text>`;
  svg += `</svg>`;
  stripsEl.insertAdjacentHTML("beforeend", svg);
}
stripsEl.addEventListener("mousemove", ev=>{
  const t = ev.target.closest("[data-tip]");
  if(t) showTip(ev, t.getAttribute("data-tip").replace("</b>","</b>"));
  else hideTip();
});
stripsEl.addEventListener("mouseleave", hideTip);

/* ---------- 평균 대비 다이버징 바 ---------- */
const divEl = document.getElementById("diverging");
const rows2 = DATA.results.filter(r=>r.vs_avg_pct!=null);
if(rows2.length){
  const maxAbs = Math.max(10, ...rows2.map(r=>Math.abs(r.vs_avg_pct)));
  const W2 = Math.min(divEl.clientWidth || 900, 1100), RH=34, LABW=230, PR=60;
  const mid = LABW + (W2-LABW-PR)/2;
  const scale = (W2-LABW-PR)/2/maxAbs;
  let svg = `<svg width="${W2}" height="${rows2.length*RH+24}" role="img" aria-label="시장 평균가 대비 가격">`;
  svg += `<line x1="${mid}" y1="4" x2="${mid}" y2="${rows2.length*RH+4}" stroke="var(--axis)" stroke-width="1"/>`;
  rows2.forEach((r,i)=>{
    const y = 8+i*RH, h = RH-14;
    const w = Math.abs(r.vs_avg_pct)*scale;
    const pos = r.vs_avg_pct>=0;
    const x = pos ? mid : mid-w;
    svg += `<text x="${LABW-10}" y="${y+h/2+4}" font-size="12" text-anchor="end" fill="var(--ink)">${r.keyword}</text>`;
    svg += `<rect x="${x}" y="${y}" width="${Math.max(w,1)}" height="${h}"
        fill="${pos?'var(--pos)':'var(--neg)'}" rx="4"
        data-tip="<b>${r.keyword}</b>시장 평균 ${fmt(r.market.avg)}원 대비 ${(r.vs_avg_pct>0?"+":"")+r.vs_avg_pct}%"/>`;
    svg += `<text x="${pos? mid+w+6 : mid-w-6}" y="${y+h/2+4}" font-size="11" font-weight="600"
        text-anchor="${pos?'start':'end'}" fill="var(--ink2)">${(r.vs_avg_pct>0?"+":"")+r.vs_avg_pct}%</text>`;
  });
  svg += `<text x="${mid}" y="${rows2.length*RH+20}" font-size="10" text-anchor="middle" fill="var(--muted)">시장 평균 (0%)</text>`;
  svg += `</svg>`;
  divEl.innerHTML = svg;
  divEl.addEventListener("mousemove", ev=>{
    const t = ev.target.closest("[data-tip]");
    if(t) showTip(ev, t.getAttribute("data-tip")); else hideTip();
  });
  divEl.addEventListener("mouseleave", hideTip);
}
</script>
</body>
</html>
"""


def build_dashboard(results, summary, store_name, run_date, out_path):
    # 대시보드용 데이터 축약 (경쟁사 풀은 상위 60개까지만 점으로)
    slim = []
    for r in results:
        our_ranks = {o["rank"] for o in r["all_our_items"]}
        comps = [{
            "mallName": ("네이버 가격비교(카탈로그)" if c["mallName"] == "네이버"
                         else c["mallName"]),
            "lprice": c["lprice"],
            "rank": c["rank"], "is_ours": c["rank"] in our_ranks,
        } for c in r["competitors"][:60]]
        slim.append({
            "keyword": r["keyword"], "product": r["product"],
            "our_rank": r["our_rank"], "our_price": r["our_price"],
            "market": r["market"], "percentile": r["percentile"],
            "vs_min_pct": r["vs_min_pct"], "vs_avg_pct": r["vs_avg_pct"],
            "verdict": r["verdict"], "excluded": r.get("excluded", 0),
            "competitors": comps,
        })
    html = (TEMPLATE
            .replace("__STORE__", store_name)
            .replace("__DATE__", run_date)
            .replace("__DATA__", json.dumps(
                {"results": slim, "summary": summary}, ensure_ascii=False)))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path
