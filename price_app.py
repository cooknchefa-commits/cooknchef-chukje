"""
식자재 물가 - KAMIS "최근일자 도·소매가격정보(dailySalesList)" API 표출 (임베드 배포용 단일 앱)
- 요청 URL: http://www.kamis.or.kr/service/price/xml.do?action=dailySalesList
- 인증: st.secrets["KAMIS_CERT_KEY"], st.secrets["KAMIS_CERT_ID"] — Streamlit Cloud Secrets에만 저장
- 정사각형 카드 가로 4개 그리드
"""

import streamlit as st
import pandas as pd
import requests
import html
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

st.set_page_config(page_title="식자재 물가", layout="wide", page_icon="🥬",
                   initial_sidebar_state="collapsed")

st.title("🥬 식자재 물가")
st.caption("출처: KAMIS 농산물유통정보 (한국농수산식품유통공사) · 최근 조사일 기준")

API_URL = "http://www.kamis.or.kr/service/price/xml.do"


# KAMIS 서버는 구형 TLS(약한 cipher)만 지원 → 최신 OpenSSL(클라우드)에서 핸드셰이크 실패.
# 보안레벨을 낮춘 SSL 컨텍스트로 호출한다.
class _LegacyTLSAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context(ciphers="DEFAULT@SECLEVEL=1")
        ctx.options |= 0x4  # OP_LEGACY_SERVER_CONNECT (구형 재협상 허용)
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def _kamis_session():
    s = requests.Session()
    adapter = _LegacyTLSAdapter()
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


# ─────────────────────────────────────────────────────────────
# API 호출 (1시간 캐시)
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner="가격 정보를 불러오는 중...")
def fetch_prices(cert_key: str, cert_id: str):
    params = {
        "action": "dailySalesList",
        "p_cert_key": cert_key,
        "p_cert_id": cert_id,
        "p_returntype": "json",
    }
    resp = _kamis_session().get(API_URL, params=params, timeout=25)
    resp.raise_for_status()
    data = resp.json()

    error_code = str(data.get("error_code", ""))
    items = data.get("price", [])
    if isinstance(items, dict):
        items = items.get("item", []) or [items]
    rows = [it for it in items if isinstance(it, dict) and it.get("item_name")]

    survey_day = ""
    cond = data.get("condition")
    try:
        survey_day = cond[0][0]
    except (TypeError, IndexError, KeyError):
        if rows:
            survey_day = rows[0].get("lastest_day", "")

    return pd.DataFrame(rows), error_code, survey_day


def to_num(x):
    if x is None:
        return None
    s = str(x).replace(",", "").strip()
    if s in ("", "-", "null", "[]"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def fmt_price(x):
    n = to_num(x)
    return f"{n:,.0f}원" if n is not None else "-"


# ─────────────────────────────────────────────────────────────
# 인증 정보 로드
# ─────────────────────────────────────────────────────────────
try:
    CERT_KEY = st.secrets["KAMIS_CERT_KEY"]
    CERT_ID = st.secrets["KAMIS_CERT_ID"]
except (KeyError, FileNotFoundError):
    st.error(
        "🔑 인증 정보가 설정되지 않았습니다.\n\n"
        "Streamlit Cloud의 **Settings → Secrets** 에 아래와 같이 추가하세요:\n\n"
        '```toml\nKAMIS_CERT_KEY = "발급받은_API_KEY"\nKAMIS_CERT_ID = "요청자ID"\n```'
    )
    st.stop()


# ─────────────────────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────────────────────
try:
    df, error_code, survey_day = fetch_prices(CERT_KEY, CERT_ID)
except Exception as e:
    st.error(f"API 호출 실패: {e}")
    st.stop()

if error_code and error_code != "000":
    msg = {"200": "잘못된 파라미터", "900": "인증 실패 (키/ID 확인)"}.get(error_code, "")
    st.error(f"KAMIS 오류 코드 {error_code} {('- ' + msg) if msg else ''}")
    st.stop()

if df.empty:
    st.warning("불러온 가격 정보가 없습니다. (인증키/ID를 확인해 주세요)")
    st.stop()

if survey_day and len(str(survey_day)) == 8 and str(survey_day).isdigit():
    s = str(survey_day)
    survey_day_fmt = f"{s[:4]}-{s[4:6]}-{s[6:]}"
else:
    survey_day_fmt = str(survey_day)

# 대표 16개 품목 (4×4 그리드용, 소매 기준) — 사용자 지정 배치 순서
REPRESENTATIVE = [
    "쌀/20kg",                          # 1행
    "배추/봄",
    "양파/양파",
    "파/대파",
    "깐마늘(국산)/깐마늘(국산)",        # 2행
    "호박/애호박",
    "시금치/시금치",
    "새송이버섯/새송이버섯",
    "돼지/삼겹살",                      # 3행
    "소/등심(1등급)",
    "닭/육계(kg)",
    "계란/특란30구(일반란)",
    "고등어/국산(신선 냉장)(中)",        # 4행
    "바지락/냉장",
    "참외/참외",
    "수박/수박",
]

# ─────────────────────────────────────────────────────────────
# 상단 컨트롤
# ─────────────────────────────────────────────────────────────
top1, top2 = st.columns([1.4, 3])
with top1:
    rep_only = st.toggle("⭐ 대표 16개만 보기", value=True)
with top2:
    keyword = st.text_input("🔍 품목 검색", placeholder="예: 배추, 사과, 돼지고기",
                            label_visibility="collapsed")

if not rep_only:
    col2, col3, col4 = st.columns([1.6, 1.6, 1.4])
    with col2:
        cls_opts = ["전체"] + sorted([c for c in df.get("product_cls_name", pd.Series()).dropna().unique() if c])
        cls_default = cls_opts.index("소매") if "소매" in cls_opts else 0
        cls = st.selectbox("구분", cls_opts, index=cls_default)
    with col3:
        cat_opts = ["전체"] + sorted([c for c in df.get("category_name", pd.Series()).dropna().unique() if c])
        cat = st.selectbox("부류", cat_opts)
    with col4:
        only_changed = st.toggle("등락 있는 품목만", value=False)
else:
    cls, cat, only_changed = "전체", "전체", False

view_mode = st.radio("보기", ["카드형", "표"], horizontal=True, label_visibility="collapsed")

# ─────────────────────────────────────────────────────────────
# 필터 적용
# ─────────────────────────────────────────────────────────────
if rep_only:
    filtered = df[(df.get("product_cls_name", "") == "소매") &
                  (df.get("item_name", "").isin(REPRESENTATIVE))].copy()
    filtered = filtered.drop_duplicates(subset="item_name")
    order = {name: i for i, name in enumerate(REPRESENTATIVE)}
    filtered["_o"] = filtered["item_name"].map(order)
    filtered = filtered.sort_values("_o")
else:
    filtered = df.copy()
    if cls != "전체":
        filtered = filtered[filtered.get("product_cls_name", "") == cls]
    if cat != "전체":
        filtered = filtered[filtered.get("category_name", "") == cat]
    if only_changed:
        filtered = filtered[filtered.get("direction", "2").astype(str).isin(["0", "1"])]

if keyword:
    filtered = filtered[filtered.get("item_name", "").astype(str).str.contains(keyword, case=False, na=False)]

cap = f"**총 {len(filtered)}개 품목** (전체 {len(df)}개)"
if survey_day_fmt:
    cap += f" · 조사일 {survey_day_fmt}"
st.markdown(cap)
st.markdown("---")

if filtered.empty:
    st.info("조건에 맞는 품목이 없습니다.")
    st.stop()

# 등락 표기: 0 하락(파랑), 1 상승(빨강), 2 보합(회색)
ARROW = {"0": "▼", "1": "▲", "2": "―"}
COLOR = {"0": "#1976d2", "1": "#d32f2f", "2": "#888"}

# 부류별 연한 배경색
CAT_BG = {
    "식량작물": "#fff8e1",
    "채소류": "#e8f5e9",
    "과일류": "#fce4ec",
    "축산물": "#fff3e0",
    "수산물": "#e3f2fd",
    "특용작물": "#f3e5f5",
}


# ─────────────────────────────────────────────────────────────
# 표출
# ─────────────────────────────────────────────────────────────
if view_mode == "표":
    table = pd.DataFrame({
        "구분": filtered.get("product_cls_name", ""),
        "부류": filtered.get("category_name", ""),
        "품목": filtered.get("item_name", ""),
        "단위": filtered.get("unit", ""),
        "현재가": filtered.get("dpr1", "").apply(fmt_price),
        "1일전": filtered.get("dpr2", "").apply(fmt_price),
        "1개월전": filtered.get("dpr3", "").apply(fmt_price),
        "1년전": filtered.get("dpr4", "").apply(fmt_price),
        "등락": filtered.apply(
            lambda r: f"{ARROW.get(str(r.get('direction','2')),'―')} {r.get('value','')}%", axis=1
        ),
    })
    st.dataframe(table, use_container_width=True, hide_index=True)
else:
    cards = []
    for _, row in filtered.iterrows():
        d = str(row.get("direction", "2"))
        color = COLOR.get(d, "#888")
        arrow = ARROW.get(d, "―")
        name = html.escape(str(row.get("item_name", "-")))
        unit = html.escape(str(row.get("unit", "")))
        cls_name = html.escape(str(row.get("product_cls_name", "")))
        rate = html.escape(str(row.get("value", "")))
        bg = CAT_BG.get(str(row.get("category_name", "")), "#ffffff")
        cards.append(f"""
        <div class="kamis-card" style="background:{bg}">
          <div class="k-top">
            <div class="k-name">{name}</div>
            <div class="k-unit">{unit} · {cls_name}</div>
          </div>
          <div class="k-price" style="color:{color}">{fmt_price(row.get('dpr1'))}</div>
          <div class="k-rate" style="color:{color}">{arrow} {rate}%</div>
          <div class="k-cmp">
            전일 {fmt_price(row.get('dpr2'))}<br>
            전월 {fmt_price(row.get('dpr3'))}<br>
            전년 {fmt_price(row.get('dpr4'))}
          </div>
        </div>""")

    grid_html = f"""
    <style>
      .kamis-grid {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 12px;
      }}
      .kamis-card {{
        aspect-ratio: 1 / 1;
        border: 1px solid #e3e3e3;
        border-radius: 12px;
        padding: 18px 20px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        background: #fff;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        overflow: hidden;
      }}
      @media (max-width: 820px) {{
        .kamis-grid {{ grid-template-columns: repeat(2, 1fr); }}
        .kamis-card {{ aspect-ratio: auto; min-height: 150px; }}
      }}
      @media (max-width: 480px) {{
        .kamis-grid {{ grid-template-columns: 1fr; }}
      }}
      .k-name {{ font-size: 1.4rem; font-weight: 700; line-height: 1.25; }}
      .k-unit {{ font-size: 1.0rem; color: #888; margin-top: 3px; }}
      .k-price {{ font-size: 2.1rem; font-weight: 800; }}
      .k-rate {{ font-size: 1.25rem; font-weight: 600; margin-top: -6px; }}
      .k-cmp {{ font-size: 1.0rem; color: #777; line-height: 1.55; }}
    </style>
    <div class="kamis-grid">{''.join(cards)}</div>
    """
    st.markdown(grid_html, unsafe_allow_html=True)

st.markdown("---")
st.caption("💡 ▲ 상승(빨강) · ▼ 하락(파랑) · ― 보합 (전일 대비) · 데이터는 1시간 단위 캐시")
