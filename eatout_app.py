"""
외식 물가 - 행정안전부 하모니 "개인서비스(외식비) 시도별 평균가격" (임베드 배포용 단일 앱)
- 비공식 내부 엔드포인트: POST /portal/lcpr/getIndvSrcvEatoutCstList.do (인증 불필요)
- 월 1회 갱신. 조회월을 코드로 계산 → 매달 자동으로 최신월 반영(수동 작업/크론 불필요)
- 8개 품목, 정사각형 카드 4×2 그리드, 전국 평균(또는 시도) 집계
"""

import streamlit as st
import pandas as pd
import requests
import json
import html
from datetime import date
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

st.set_page_config(page_title="외식 물가", layout="wide", page_icon="🍽️",
                   initial_sidebar_state="collapsed")

st.title("🍽️ 외식 물가")
st.caption("출처: 행정안전부 하모니 · 국가데이터처 (개인서비스 외식비, 시·도별 평균) · 월 1회 갱신")

API_URL = "https://hamoni.mois.go.kr/portal/lcpr/getIndvSrcvEatoutCstList.do"

# 8개 품목 (BD 삼겹살 환산 전 제외, BE 환산 후 포함)
ITEM_CODES = ["BA", "BB", "BC", "BE", "BF", "BG", "BH", "BI"]
ITEM_ORDER = ["냉면", "비빔밥", "김치찌개 백반", "삼겹살 환산 후", "짜장면", "삼계탕", "칼국수", "김밥"]
DISPLAY = {
    "냉면": "냉면", "비빔밥": "비빔밥", "김치찌개 백반": "김치찌개",
    "삼겹살 환산 후": "삼겹살", "짜장면": "짜장면", "삼계탕": "삼계탕",
    "칼국수": "칼국수", "김밥": "김밥",
}
UNIT = {
    "냉면": "1인분", "비빔밥": "1인분", "김치찌개 백반": "1인분",
    "삼겹살 환산 후": "200g", "짜장면": "1인분", "삼계탕": "1인분",
    "칼국수": "1인분", "김밥": "1줄",
}
PALETTE = ["#e8f5e9", "#fff8e1", "#fce4ec", "#fff3e0",
           "#e3f2fd", "#f3e5f5", "#e0f7fa", "#f1f8e9"]


# 일부 정부 서버 구형 TLS 대비
class _LegacyTLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context(ciphers="DEFAULT@SECLEVEL=1")
        ctx.options |= 0x4
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def _session():
    s = requests.Session()
    a = _LegacyTLSAdapter()
    s.mount("https://", a)
    s.mount("http://", a)
    return s


def _ym_shift(y, m, delta):
    idx = y * 12 + (m - 1) + delta
    return idx // 12, idx % 12 + 1


def _ym(t):
    return f"{t[0]}{t[1]:02d}"


def to_num(x):
    if x is None:
        return None
    s = str(x).replace(",", "").strip()
    if s in ("", "-", "null"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fmt_won(x):
    return f"{x:,.0f}원" if x is not None and pd.notna(x) else "-"


HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://hamoni.mois.go.kr/portal/lcpr/indvSrcvEatoutCstList.do",
}


def _call(session, bgng_ym, end_ym):
    payload = {
        "menuYn": "",
        "searchItemNo": ",".join(ITEM_CODES),
        "searchBgngYm": bgng_ym,
        "searchEndYm": end_ym,
        "searchCtpv": "",
    }
    resp = session.post(API_URL, data=payload, headers=HEADERS, timeout=25)
    obj = json.loads(resp.text)
    months = json.loads(obj["colNmList"])
    rows = json.loads(obj["indvSrcvEatoutCstList"])
    records = []
    for r in rows:
        item, region = r.get("itemNm"), r.get("ctpvNm")
        for i, mlabel in enumerate(months):
            records.append({"item": item, "region": region,
                            "month": mlabel, "value": to_num(r.get(f"col{i}"))})
    return records, months


# ─────────────────────────────────────────────────────────────
# API 호출 (하루 캐시 — 월 1회 갱신이라 충분, 매달 자동 최신월 반영)
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=86400, show_spinner="외식 물가를 불러오는 중...")
def fetch_eatout():
    s = _session()
    today = date.today()

    # 1) 최신 12개월: [현재월-12 .. 현재월-1]
    bg1 = _ym_shift(today.year, today.month, -12)
    recs, _ = _call(s, _ym(bg1), _ym((today.year, today.month)))
    df = pd.DataFrame(recs)

    # 최신 가용월 탐색 (코드가 자동 판별 → 매달 자동 갱신)
    latest = None
    for m in sorted(df["month"].unique(), reverse=True):
        if df.loc[df["month"] == m, "value"].notna().any():
            latest = m
            break

    # 2) 전년동월 보강: [최신-12 .. 최신-1]
    if latest:
        ly, lm = map(int, latest.split("."))
        recs2, _ = _call(s, _ym(_ym_shift(ly, lm, -12)), _ym(_ym_shift(ly, lm, -1)))
        df = pd.concat([df, pd.DataFrame(recs2)]).drop_duplicates(
            subset=["item", "region", "month"])

    months_all = sorted(df["month"].unique())
    return df, months_all, latest


# ─────────────────────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────────────────────
try:
    df, months, latest_month = fetch_eatout()
except Exception as e:
    st.error(f"데이터 호출 실패: {e}")
    st.stop()

if df.empty or not months:
    st.warning("불러온 외식 물가 정보가 없습니다.")
    st.stop()

regions = sorted(df["region"].dropna().unique())

# ─────────────────────────────────────────────────────────────
# 상단 컨트롤
# ─────────────────────────────────────────────────────────────
col1, col2 = st.columns([1.5, 3])
with col1:
    region_sel = st.selectbox("📍 지역", ["전국 평균"] + regions)

if region_sel == "전국 평균":
    g = df.groupby(["item", "month"], as_index=False)["value"].mean()
else:
    g = df[df["region"] == region_sel][["item", "month", "value"]]

pivot = g.pivot_table(index="item", columns="month", values="value")

ARROW = {"up": "▲", "down": "▼", "flat": "―"}
COLOR = {"up": "#d32f2f", "down": "#1976d2", "flat": "#888"}


def series_for(item):
    if item not in pivot.index:
        return []
    return [(m, pivot.loc[item, m] if m in pivot.columns else None) for m in months]


cap = f"**개인서비스(외식비) · {region_sel}**"
if latest_month:
    cap += f" · 기준월 {latest_month}"
st.markdown(cap)
st.markdown("---")

# ─────────────────────────────────────────────────────────────
# 정사각형 카드 4×2 그리드
# ─────────────────────────────────────────────────────────────
cards = []
for idx, item in enumerate(ITEM_ORDER):
    seq = series_for(item)
    last_i = None
    for i in range(len(seq) - 1, -1, -1):
        v = seq[i][1]
        if v is not None and pd.notna(v):
            last_i = i
            break

    if last_i is None:
        cur = prev = yr = None
        cur_month = "-"
    else:
        cur_month, cur = seq[last_i]
        prev = seq[last_i - 1][1] if last_i - 1 >= 0 else None
        try:
            y, m = cur_month.split(".")
            yr_label = f"{int(y) - 1}.{m}"
        except ValueError:
            yr_label = None
        yr = None
        if yr_label:
            for mm, vv in seq:
                if mm == yr_label:
                    yr = vv
                    break

    if cur is not None and prev is not None and pd.notna(cur) and pd.notna(prev) and prev != 0:
        diff = cur - prev
        d = "up" if diff > 0 else ("down" if diff < 0 else "flat")
        rate = f"{diff / prev * 100:+.1f}%"
    else:
        d, rate = "flat", "―"

    color = COLOR[d]
    arrow = ARROW[d]
    bg = PALETTE[idx % len(PALETTE)]
    name = html.escape(DISPLAY.get(item, item))
    unit = html.escape(UNIT.get(item, ""))

    cards.append(f"""
    <div class="eat-card" style="background:{bg}">
      <div class="e-top">
        <div class="e-name">{name}</div>
        <div class="e-unit">{unit}</div>
      </div>
      <div class="e-price" style="color:{color}">{fmt_won(cur)}</div>
      <div class="e-rate" style="color:{color}">{arrow} {rate}</div>
      <div class="e-cmp">
        전월 {fmt_won(prev)}<br>
        전년 {fmt_won(yr)}
      </div>
    </div>""")

grid_html = f"""
<style>
  .eat-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
  }}
  .eat-card {{
    aspect-ratio: 1 / 1;
    border: 1px solid #e3e3e3;
    border-radius: 12px;
    padding: 18px 20px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    overflow: hidden;
  }}
  @media (max-width: 820px) {{
    .eat-grid {{ grid-template-columns: repeat(2, 1fr); }}
    .eat-card {{ aspect-ratio: auto; min-height: 150px; }}
  }}
  @media (max-width: 480px) {{
    .eat-grid {{ grid-template-columns: 1fr; }}
  }}
  .e-name {{ font-size: 1.5rem; font-weight: 700; line-height: 1.25; }}
  .e-unit {{ font-size: 1.0rem; color: #888; margin-top: 3px; }}
  .e-price {{ font-size: 2.2rem; font-weight: 800; }}
  .e-rate {{ font-size: 1.25rem; font-weight: 600; margin-top: -6px; }}
  .e-cmp {{ font-size: 1.05rem; color: #777; line-height: 1.55; }}
</style>
<div class="eat-grid">{''.join(cards)}</div>
"""
st.markdown(grid_html, unsafe_allow_html=True)

st.markdown("---")
st.caption(
    "💡 ▲ 상승(빨강) · ▼ 하락(파랑) · ― 보합 (전월 대비) · 하루 단위 캐시  \n"
    "※ '전국 평균'은 시·도 단순평균 / 세종은 충남에 포함 / 삼겹살은 200g 환산 기준"
)
