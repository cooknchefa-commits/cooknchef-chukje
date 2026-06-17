"""
서울·경기 요식업 구인 공고 (임베드 배포용 단일 앱)
- 서울: 서울 열린데이터광장 GetJobInfo  (http://openapi.seoul.go.kr:8088/{KEY}/json/GetJobInfo/{s}/{e}/)
- 경기: 경기데이터드림 GGJOBABARECRUSTM (https://openapi.gg.go.kr/GGJOBABARECRUSTM)
- 인증: st.secrets["SEOUL_API_KEY"], st.secrets["GYEONGGI_API_KEY"] — Streamlit Cloud Secrets에만 저장
- 라이선스: 서울 공공누리 1유형(상업 이용 가능)
- 요식업 필터: 직종(KECO)코드 531/532/8711/8722/305000 시작 + 624901/624902 (양쪽 공통)
"""

import streamlit as st
import pandas as pd
import requests
import re
from datetime import date, datetime

st.set_page_config(page_title="서울·경기 요식업 구인", layout="wide", page_icon="👔",
                   initial_sidebar_state="collapsed")

st.title("👔 서울·경기 요식업 구인 공고")
st.caption("출처: 서울시 일자리포털(서울 열린데이터광장) · 경기도일자리재단 잡아바(경기데이터드림) · 공공누리 1유형")

SEOUL_URL = "http://openapi.seoul.go.kr:8088"
GG_URL = "https://openapi.gg.go.kr/GGJOBABARECRUSTM"
PAGE = 1000

FOOD_PREFIX = ("531", "532", "8711", "8722", "305000")
FOOD_EXACT = {"624901", "624902"}

CODE_NAME = {
    "305000": "영양사", "531100": "주방장·요리연구가", "531200": "한식 조리사",
    "531300": "중식 조리사", "531400": "양식 조리사", "531500": "일식 조리사",
    "531600": "바텐더", "531700": "바리스타·음료조리", "531800": "단체급식 조리사",
    "531801": "학교급식 조리사", "531802": "유치원·어린이집 급식조리사", "531803": "병원급식 조리사",
    "531804": "구내식당 급식조리사", "531900": "기타 조리사", "531901": "분식 조리사",
    "531902": "포장마차·주점 조리사", "531903": "동남아·남미음식 조리사", "871100": "제과·제빵원",
    "532100": "패스트푸드 준비원", "532200": "식음료 서비스원", "532201": "호텔·레스토랑 웨이터",
    "532202": "일반음식점 서빙원", "532203": "주점·커피숍 서빙원", "532300": "주방 보조원",
    "532301": "주방 보조원(음식점)", "532302": "단체급식 보조원", "532900": "기타 음식서비스",
    "624901": "음식점 배달원", "624902": "패스트푸드 배달원", "872200": "김치·밑반찬 제조",
}
GROUP_BADGE = {"조리사": "🍳", "주방보조": "🥄", "홀·서빙": "🍽️", "제과·제빵": "🥐",
               "식품제조": "🥫", "영양사": "🥗", "배달": "🛵", "음식서비스": "🧑‍🍳", "기타": "📋"}


def is_food(code):
    c = str(code or "")
    return c.startswith(FOOD_PREFIX) or c in FOOD_EXACT


def job_group(code):
    c = str(code or "")
    if c.startswith("531"):
        return "조리사"
    if c.startswith("5323") or c == "532100":
        return "주방보조"
    if c.startswith("5322"):
        return "홀·서빙"
    if c.startswith("8711"):
        return "제과·제빵"
    if c.startswith("8722"):
        return "식품제조"
    if c.startswith("305000"):
        return "영양사"
    if c.startswith("6249"):
        return "배달"
    if c.startswith("532"):
        return "음식서비스"
    return "기타"


def code_label(code, fallback=""):
    c = str(code or "")
    if c in CODE_NAME:
        return CODE_NAME[c]
    return fallback or job_group(c)


def parse_date(s):
    s = str(s or "")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return datetime.strptime(m.group(0), "%Y-%m-%d").date()
        except ValueError:
            pass
    m = re.search(r"\b(\d{8})\b", s)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d").date()
        except ValueError:
            pass
    return None


# ─────────────────────────────────────────────────────────────
# 수집 (1시간 캐시)
# ─────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner="채용정보를 불러오는 중...")
def fetch_jobs(seoul_key: str, gg_key: str) -> pd.DataFrame:
    recs = []

    # --- 서울 (최대 6,000건 스캔) ---
    for page in range(6):
        s = page * PAGE + 1
        url = f"{SEOUL_URL}/{seoul_key}/json/GetJobInfo/{s}/{s + PAGE - 1}/"
        body = requests.get(url, timeout=30).json().get("GetJobInfo", {})
        if body.get("RESULT", {}).get("CODE") not in ("INFO-000", None) and page == 0:
            raise RuntimeError("서울 " + str(body.get("RESULT")))
        rows = body.get("row", [])
        if not rows:
            break
        for r in rows:
            code = r.get("RCRIT_JSSFC_CMMN_CODE_SE")
            if not is_food(code):
                continue
            addr = str(r.get("WORK_PARAR_BASS_ADRES_CN") or "")
            recs.append({
                "source": "서울", "code": str(code),
                "company": r.get("CMPNY_NM"), "title": r.get("JO_SJ") or r.get("JOBCODE_NM"),
                "jobname": r.get("JOBCODE_NM") or code_label(code),
                "salary": r.get("HOPE_WAGE"), "region": addr,
                "employ": r.get("EMPLYM_STLE_CMMN_MM"), "career": r.get("CAREER_CND_NM"),
                "academic": r.get("ACDMCR_NM"),
                "close": parse_date(r.get("RCEPT_CLOS_NM")), "close_txt": r.get("RCEPT_CLOS_NM"),
                "url": (f"https://www.work.go.kr/empInfo/empInfoSrch/detail/empDetailAuthView.do"
                        f"?callPage=detail&wantedAuthNo={r.get('JO_REGIST_NO')}"
                        if r.get("JO_REGIST_NO") else ""),
                "reg": parse_date(r.get("JO_REG_DT")),
                "detail": r.get("DTY_CN"),
                "contact": f"{r.get('MNGR_NM') or '-'} ({r.get('MNGR_INSTT_NM') or '-'}) ☎ {r.get('MNGR_PHON_NO') or '-'}",
                "rcept": r.get("RCEPT_MTH_NM"),
                "persons": r.get("RCRIT_NMPR_CO"), "apply_period": "",
            })
        if s + PAGE - 1 >= int(body.get("list_total_count", 0) or 0):
            break

    # --- 경기 (최대 5,000건 스캔) ---
    for page in range(1, 6):
        params = {"Key": gg_key, "Type": "json", "pIndex": page, "pSize": PAGE}
        svc = requests.get(GG_URL, params=params, timeout=30).json().get("GGJOBABARECRUSTM")
        if not isinstance(svc, list):
            break
        rows = svc[1].get("row", []) if len(svc) > 1 else []
        if not rows:
            break
        for r in rows:
            code = r.get("RECRUT_FIELD_CD_NM")
            if not is_food(code):
                continue
            gclose = parse_date(r.get("RCPT_END_DE"))
            recs.append({
                "source": "경기", "code": str(code),
                "company": r.get("ENTRPRS_NM"), "title": r.get("PBANC_CONT"),
                "jobname": code_label(code, r.get("RECRUT_FIELD_NM")),
                "salary": r.get("SALARY_COND"), "region": r.get("WORK_REGION_CONT"),
                "employ": r.get("PBANC_FORM_DIV"), "career": r.get("CAREER_DIV"),
                "academic": r.get("ACDMCR_DIV"),
                "close": gclose, "close_txt": (gclose.isoformat() if gclose else (r.get("RCPT_END_DE") or "-")),
                "url": r.get("URL") or "", "reg": parse_date(r.get("RCPT_BGNG_DE")),
                "detail": "", "contact": "", "rcept": "",
                "persons": r.get("EMPLMNT_PSNCNT"),
                "apply_period": f"{parse_date(r.get('RCPT_BGNG_DE')) or '?'} ~ {gclose.isoformat() if gclose else '?'}",
            })

    df = pd.DataFrame(recs)
    if not df.empty:
        df["group"] = df["code"].apply(job_group)
        df = (df.sort_values("reg", ascending=False, na_position="last")
                .drop_duplicates(subset=["company", "title"], keep="first")
                .reset_index(drop=True))
    return df


# ─────────────────────────────────────────────────────────────
# 인증키
# ─────────────────────────────────────────────────────────────
try:
    SEOUL_KEY = st.secrets["SEOUL_API_KEY"]
    GG_KEY = st.secrets["GYEONGGI_API_KEY"]
except (KeyError, FileNotFoundError):
    st.error(
        "🔑 인증키가 설정되지 않았습니다.\n\n"
        "Streamlit Cloud의 **Settings → Secrets** 에 추가하세요:\n\n"
        '```toml\nSEOUL_API_KEY = "서울_열린데이터광장_키"\nGYEONGGI_API_KEY = "경기데이터드림_키"\n```'
    )
    st.stop()

try:
    df = fetch_jobs(SEOUL_KEY, GG_KEY)
except Exception as e:
    st.error(f"API 호출 실패: {e}")
    st.stop()

if df.empty:
    st.warning("불러온 요식업 채용정보가 없습니다.")
    st.stop()

# 마감 지난 공고 제외 (마감일 없는 상시공고는 유지)
df = df[df["close"].apply(lambda d: d is None or d >= date.today())].copy()
if df.empty:
    st.warning("진행 중인 요식업 채용정보가 없습니다.")
    st.stop()

# ─────────────────────────────────────────────────────────────
# 필터
# ─────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns([2.2, 1.3, 1.6, 1.3])
with c1:
    keyword = st.text_input("🔍 검색", placeholder="회사·제목·직무·지역 (예: 한식, 카페, 수원)")
with c2:
    src_sel = st.radio("출처", ["전체", "서울", "경기"], horizontal=True)
with c3:
    grp_opts = ["전체"] + [g for g in ["조리사", "주방보조", "홀·서빙", "제과·제빵",
                                       "음식서비스", "식품제조", "영양사", "배달", "기타"]
                          if g in df["group"].unique()]
    grp_sel = st.selectbox("직종", grp_opts)
with c4:
    sort_by = st.selectbox("정렬", ["마감임박순", "최신순"])

f = df.copy()
if keyword:
    f = f[
        f["company"].astype(str).str.contains(keyword, case=False, na=False)
        | f["title"].astype(str).str.contains(keyword, case=False, na=False)
        | f["jobname"].astype(str).str.contains(keyword, case=False, na=False)
        | f["region"].astype(str).str.contains(keyword, case=False, na=False)
    ]
if src_sel != "전체":
    f = f[f["source"] == src_sel]
if grp_sel != "전체":
    f = f[f["group"] == grp_sel]

if sort_by == "마감임박순":
    f = f.sort_values(by="close", key=lambda s: s.map(lambda d: d if d else date.max), na_position="last")
else:
    f = f.sort_values(by="reg", key=lambda s: s.map(lambda d: d if d else date.min), ascending=False)

n_seoul = int((f["source"] == "서울").sum())
n_gg = int((f["source"] == "경기").sum())
st.markdown(f"**총 {len(f)}건** · 서울 {n_seoul} / 경기 {n_gg}")
st.markdown("---")

if f.empty:
    st.info("조건에 맞는 채용정보가 없습니다.")
    st.stop()

# ─────────────────────────────────────────────────────────────
# 카드 리스트
# ─────────────────────────────────────────────────────────────
SRC_TAG = {"서울": "🟦 서울", "경기": "🟩 경기"}
today = date.today()

for _, r in f.iterrows():
    with st.container(border=True):
        badge = GROUP_BADGE.get(r["group"], "📋")
        title = r["title"] or r["jobname"] or "(제목 없음)"

        close_txt = str(r["close_txt"] or "-")
        if r["close"]:
            dleft = (r["close"] - today).days
            if dleft < 0:
                close_txt += " (마감)"
            elif dleft <= 7:
                close_txt += f" (⏰ D-{dleft})"

        st.markdown(f"#### {badge} {title}")
        st.caption(f"{SRC_TAG.get(r['source'], r['source'])}  ·  {r['jobname']}  ·  `{r['group']}`")

        cc1, cc2 = st.columns(2)
        with cc1:
            st.markdown(f"**🏢 회사** {r['company'] or '-'}")
            st.markdown(f"**💰 급여** {r['salary'] or '-'}")
            st.markdown(f"**📍 근무지** {r['region'] or '-'}")
        with cc2:
            st.markdown(f"**고용형태** {r['employ'] or '-'}")
            st.markdown(f"**경력** {r['career'] or '-'}  ·  **학력** {r['academic'] or '-'}")
            st.markdown(f"**🗓️ 마감** {close_txt}")

        if r["url"]:
            st.markdown(f"➡️ [지원/상세 보기]({r['url']})")

        with st.expander("상세 보기 (모집·직무·접수·담당자)"):
            persons = r.get("persons")
            if persons not in (None, "", 0, "0"):
                try:
                    st.markdown(f"**모집인원** {int(float(persons))}명")
                except (ValueError, TypeError):
                    st.markdown(f"**모집인원** {persons}")
            if r.get("apply_period"):
                st.markdown(f"**접수기간** {r['apply_period']}")
            if r["detail"]:
                st.markdown(f"**직무내용**\n\n{r['detail']}")
            if r["rcept"]:
                st.markdown(f"**접수방법** {r['rcept']}")
            if r["contact"]:
                st.markdown(f"**담당** {r['contact']}")
            if r["source"] == "경기":
                st.caption("자세한 직무·지원 방법은 위 '지원/상세 보기' 링크에서 확인하세요.")

st.markdown("---")
st.caption("💡 서울·경기 일자리 데이터 중 조리·음식서비스 직종만 추출 · 1시간 캐시 · 지원 전 마감·조건 재확인 권장")
