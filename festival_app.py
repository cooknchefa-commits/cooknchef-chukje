"""
축제 정보 - 공공데이터포털 "전국문화축제표준데이터" API 표출 화면 (임베드 배포용 단일 앱)
- End Point: https://api.data.go.kr/openapi/tn_pubr_public_cltur_fstvl_api
- 인증키: st.secrets["DATA_GO_KR_KEY"] (decoding 키) — Streamlit Cloud Secrets에만 저장
"""

import streamlit as st
import pandas as pd
import requests
from datetime import date, datetime

st.set_page_config(page_title="축제 정보", layout="wide", page_icon="🎉",
                   initial_sidebar_state="collapsed")

st.title("🎉 축제 정보")
st.caption("출처: 공공데이터포털 · 전국문화축제표준데이터")

API_URL = "https://api.data.go.kr/openapi/tn_pubr_public_cltur_fstvl_api"


# ─────────────────────────────────────────────────────────────
# API 호출 (1시간 캐시 → 일일 호출한도 1000 절약)
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner="축제 정보를 불러오는 중...")
def fetch_festivals(service_key: str) -> pd.DataFrame:
    """전체 축제 데이터를 모두 받아 DataFrame으로 반환."""
    all_items = []
    page_no = 1
    num_of_rows = 100

    while True:
        params = {
            "serviceKey": service_key,
            "pageNo": page_no,
            "numOfRows": num_of_rows,
            "type": "json",
        }
        resp = requests.get(API_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        body = data.get("response", {}).get("body", {})
        items = body.get("items", [])

        # items 가 {"item": [...]} 형태로 한번 더 감싸지는 경우 대비
        if isinstance(items, dict):
            items = items.get("item", [])
        if not items:
            break

        all_items.extend(items)

        total_count = int(body.get("totalCount", 0) or 0)
        if page_no * num_of_rows >= total_count:
            break
        page_no += 1
        # 안전장치 (무한루프 방지)
        if page_no > 50:
            break

    return pd.DataFrame(all_items)


def parse_date(s):
    """'YYYY-MM-DD' 등 문자열을 date로 변환, 실패 시 None."""
    if not s or pd.isna(s):
        return None
    s = str(s).strip().replace(".", "-").replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
    return None


def extract_region(row):
    """주소(도로명 우선)에서 시/도 추출."""
    addr = row.get("rdnmadr") or row.get("lnmadr") or ""
    addr = str(addr).strip()
    if not addr:
        return "기타"
    return addr.split()[0] if addr.split() else "기타"


# ─────────────────────────────────────────────────────────────
# 인증키 로드
# ─────────────────────────────────────────────────────────────
try:
    SERVICE_KEY = st.secrets["DATA_GO_KR_KEY"]
except (KeyError, FileNotFoundError):
    st.error(
        "🔑 인증키가 설정되지 않았습니다.\n\n"
        "Streamlit Cloud의 **Settings → Secrets** 에 아래와 같이 추가하세요:\n\n"
        '```toml\nDATA_GO_KR_KEY = "발급받은_디코딩_키"\n```'
    )
    st.stop()


# ─────────────────────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────────────────────
try:
    df = fetch_festivals(SERVICE_KEY)
except Exception as e:
    st.error(f"API 호출 실패: {e}")
    st.stop()

if df.empty:
    st.warning("불러온 축제 정보가 없습니다.")
    st.stop()

# 파생 컬럼
df["_start"] = df.get("fstvlStartDate").apply(parse_date) if "fstvlStartDate" in df else None
df["_end"] = df.get("fstvlEndDate").apply(parse_date) if "fstvlEndDate" in df else None
df["_region"] = df.apply(extract_region, axis=1)

today = date.today()


def status_of(row):
    s, e = row["_start"], row["_end"]
    if s and e:
        if s <= today <= e:
            return "진행중"
        if today < s:
            return "예정"
        return "종료"
    return "미정"


df["_status"] = df.apply(status_of, axis=1)

# ─────────────────────────────────────────────────────────────
# 상단 필터
# ─────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns([2, 2, 1.5])

with col1:
    keyword = st.text_input("🔍 축제명 검색", placeholder="예: 벚꽃, 불꽃, 김치")

with col2:
    regions = ["전체"] + sorted([r for r in df["_region"].unique() if r and r != "기타"]) + ["기타"]
    region = st.selectbox("📍 지역", regions)

with col3:
    only_active = st.toggle("진행중·예정만 보기", value=True)

view_mode = st.radio("보기 방식", ["카드형", "표"], horizontal=True, label_visibility="collapsed")

# ─────────────────────────────────────────────────────────────
# 필터 적용
# ─────────────────────────────────────────────────────────────
filtered = df.copy()

if keyword:
    filtered = filtered[filtered.get("fstvlNm", "").astype(str).str.contains(keyword, case=False, na=False)]

if region != "전체":
    filtered = filtered[filtered["_region"] == region]

if only_active:
    filtered = filtered[filtered["_status"].isin(["진행중", "예정"])]

# 전화번호·홈페이지가 둘 다 없는 축제 제외
def _has(col):
    return filtered.get(col, "").astype(str).str.strip().replace("nan", "").ne("")
filtered = filtered[_has("phoneNumber") | _has("homepageUrl")]

# 정렬: 개최 시작일이 오늘과 가까운 순 (시작일 미정은 맨 뒤)
def days_from_today(d):
    if d is None:
        return float("inf")
    return abs((d - today).days)

filtered = filtered.assign(_dist=filtered["_start"].apply(days_from_today))
filtered = filtered.sort_values(by="_dist", na_position="last")

st.markdown(f"**총 {len(filtered)}건** (전체 {len(df)}건)")
st.markdown("---")

if filtered.empty:
    st.info("조건에 맞는 축제가 없습니다.")
    st.stop()


def fmt_period(row):
    s, e = row.get("fstvlStartDate", ""), row.get("fstvlEndDate", "")
    s, e = (str(s).strip() if s else ""), (str(e).strip() if e else "")
    if s and e:
        return f"{s} ~ {e}"
    return s or e or "기간 미정"


# ─────────────────────────────────────────────────────────────
# 표출
# ─────────────────────────────────────────────────────────────
if view_mode == "표":
    table = pd.DataFrame({
        "상태": filtered["_status"],
        "축제명": filtered.get("fstvlNm", ""),
        "개최기간": filtered.apply(fmt_period, axis=1),
        "개최장소": filtered.get("opar", ""),
        "전화번호": filtered.get("phoneNumber", ""),
        "홈페이지": filtered.get("homepageUrl", ""),
    })
    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "홈페이지": st.column_config.LinkColumn("홈페이지"),
        },
    )
else:
    badge = {"진행중": "🟢 진행중", "예정": "🔵 예정", "종료": "⚪ 종료", "미정": "⚫ 미정"}
    for _, row in filtered.iterrows():
        with st.container(border=True):
            name = row.get("fstvlNm", "(이름 없음)")
            st.markdown(f"### {badge.get(row['_status'], '')} · {name}")

            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**📅 개최기간**  \n{fmt_period(row)}")
                place = row.get("opar") or row.get("rdnmadr") or row.get("lnmadr") or "-"
                st.markdown(f"**📍 개최장소**  \n{place}")
            with c2:
                phone = row.get("phoneNumber") or "-"
                st.markdown(f"**☎️ 전화번호**  \n{phone}")
                home = str(row.get("homepageUrl") or "").strip()
                if home:
                    st.markdown(f"**🔗 홈페이지**  \n[{home}]({home})")
                else:
                    st.markdown("**🔗 홈페이지**  \n-")

            content = str(row.get("fstvlCo") or "").strip()
            if content:
                with st.expander("📝 축제 내용 보기"):
                    st.write(content)

st.markdown("---")
st.caption("💡 데이터는 1시간 단위로 캐시됩니다 (API 일일 호출한도 절약).")
