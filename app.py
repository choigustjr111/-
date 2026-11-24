import streamlit as st
from datetime import datetime
import requests
import calendar
import re
import json
import urllib3
import gspread
from google.oauth2.service_account import Credentials

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
st.set_page_config(page_title="교사 통합 대시보드", page_icon="📊", layout="centered")

# ----------------------------------------------------
# 1. 구글 스프레드시트 연결 설정
# ----------------------------------------------------
@st.cache_resource
def init_gsheet():
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_url(st.secrets["sheet_url"]).worksheet("일정")
        return sheet
    except Exception as e:
        return None

sheet = init_gsheet()

# ----------------------------------------------------
# 2. 초기 상태값 세팅 (환경설정 탭에서 수정 가능)
# ----------------------------------------------------
if "api_key" not in st.session_state:
    st.session_state.api_key = "7f4019dca7cd42a6899c6e1fb0b78c87"
if "office_code" not in st.session_state:
    st.session_state.office_code = "R10"
if "school_code" not in st.session_state:
    st.session_state.school_code = "8750127"

if "timetable_teacher" not in st.session_state:
    st.session_state.timetable_teacher = {
        "월": ["공통수학1(1-5)", "", "대수(2-5)", "대수(2-3)", "", "", "대수(2-4)"],
        "화": ["", "", "공통수학1(1-3)", "대수(2-4)", "", "", "대수(2-3)"],
        "수": ["", "", "대수(2-5)", "대수(2-4)", "동아리", "동아리", "공통수학1(1-2)"],
        "목": ["공통수학1(1-4)", "", "대수(2-4)", "", "대수(2-5)", "", "대수(2-3)"],
        "금": ["자율", "진로", "", "공통수학1(1-1)", "대수(2-3)", "대수(2-5)", ""],
    }

if "timetable_student" not in st.session_state:
    st.session_state.timetable_student = {
        "월": ["탐구B", "탐구A", "영어", "문학", "국영선택", "스포츠", "대수"],
        "화": ["독서", "국영선택", "탐구C", "대수", "수학선택", "탐구B", "영어"],
        "수": ["수학선택", "탐구B", "영어", "대수", "동아리", "동아리", "탐구A"],
        "목": ["탐구A", "국영선택", "대수", "탐구C", "문학", "수학선택", "영어"],
        "금": ["자율", "진로", "국영선택", "탐구C", "문학", "문학", "수학선택"],
    }

if "overtime_list" not in st.session_state:
    st.session_state.overtime_list = []

# ----------------------------------------------------
# 3. 나이스 API 함수
# ----------------------------------------------------
@st.cache_data(ttl=1800)
def get_day_meal(date_str, api_key, office, school):
    try:
        url = f"https://open.neis.go.kr/hub/mealServiceDietInfo?KEY={api_key}&Type=json&pIndex=1&pSize=5&ATPT_OFCDC_SC_CODE={office}&SD_SCHUL_CODE={school}&MLSV_YMD={date_str}"
        res = requests.get(url, timeout=3, verify=False).json()
        if "mealServiceDietInfo" in res:
            output = []
            for row in res["mealServiceDietInfo"][1]["row"]:
                m_type = row.get("MMEAL_SC_NM", "급식")
                m_full = row.get("DDISH_NM", "")
                clean_m = re.sub(r'\([^)]*\)', '', m_full).replace('*', '').strip()
                lines = [m.strip() for m in re.split(r'<br\s*/?>', clean_m) if m.strip()]
                output.append(f"**[{m_type}]**\n" + "\n".join(f"- {line}" for line in lines))
            return "\n\n".join(output)
        return "등록된 급식 정보가 없습니다. 🍩"
    except Exception:
        return "급식 서버 연결 실패 ❌ (환경설정에서 학교/교육청 코드를 확인하세요)"

@st.cache_data(ttl=1800)
def get_month_events(year, month, api_key, office, school):
    events = {}
    try:
        last_day = calendar.monthrange(year, month)[1]
        from_ymd = f"{year}{month:02d}01"
        to_ymd = f"{year}{month:02d}{last_day:02d}"
        school_year = year if month >= 3 else year - 1
        url = (
            f"https://open.neis.go.kr/hub/SchoolSchedule?KEY={api_key}&Type=json"
            f"&pIndex=1&pSize=100&ATPT_OFCDC_SC_CODE={office}&SD_SCHUL_CODE={school}"
            f"&AY={school_year}&AA_FROM_YMD={from_ymd}&AA_TO_YMD={to_ymd}"
        )
        res = requests.get(url, timeout=3, verify=False).json()
        if "SchoolSchedule" in res:
            for row in res["SchoolSchedule"][1]["row"]:
                ymd_str = str(row["AA_YMD"])
                day_int = int(ymd_str[6:8])
                ev_name = str(row.get("EVENT_NM", "")).strip()
                if ev_name and "휴업일" not in ev_name:
                    events.setdefault(day_int, []).append(ev_name)
    except Exception:
        pass
    return events

# ----------------------------------------------------
# 4. 메인 화면 UI
# ----------------------------------------------------
st.title("📊 교사 통합 대시보드")

col_l1, col_l2 = st.columns(2)
col_l1.link_button("🟢 리로스쿨 열기", "https://jchsl.riroschool.kr/", use_container_width=True)
col_l2.link_button("🔵 나이스(NEIS) 열기", "https://gbe.eduptl.kr/", use_container_width=True)

tab1, tab2, tab3, tab4, tab5 = st.tabs(["🗓️ 통합 캘린더", "🍱 급식", "📅 시간표", "⏰ 초과근무", "⚙️ 환경설정"])

# [탭 1] 통합 캘린더 (나이스 학사일정 + 구글 시트 개인일정 동기화)
with tab1:
    now = datetime.now()
    c_y, c_m = st.columns(2)
    sel_y = c_y.number_input("연도", value=now.year, step=1)
    sel_m = c_m.number_input("월", min_value=1, max_value=12, value=now.month, step=1)
    
    # 나이스 학사일정 불러오기
    neis_evs = get_month_events(sel_y, sel_m, st.session_state.api_key, st.session_state.office_code, st.session_state.school_code)
    
    # 구글 시트 개인일정 불러오기
    personal_evs = {}
    if sheet:
        records = sheet.get_all_records()
        for idx, r in enumerate(records, start=2):
            d_str = str(r.get("날짜", ""))
            if d_str.startswith(f"{sel_y}-{sel_m:02d}"):
                day_num = int(d_str.split("-")[2])
                personal_evs.setdefault(day_num, []).append({
                    "row": idx,
                    "text": str(r.get("내용", "")),
                    "done": str(r.get("완료", "")).upper() == "TRUE"
                })
    else:
        st.warning("⚠️ 구글 스프레드시트가 아직 연결되지 않아 개인 일정은 표시되지 않습니다.")

    # 새 개인 일정 추가 폼
    with st.expander("➕ 새 개인 일정 추가하기", expanded=False):
        add_date = st.date_input("일정 날짜", datetime(sel_y, sel_m, now.day if now.month == sel_m else 1))
        add_text = st.text_input("일정 내용", placeholder="예: 2학년 수학 수행평가 채점 마감")
        if st.button("구글 시트에 일정 저장", type="primary"):
            if sheet and add_text.strip():
                sheet.append_row([add_date.strftime("%Y-%m-%d"), add_text.strip(), "FALSE"])
                st.success("일정이 저장되었습니다!")
                st.rerun()

    st.divider()
    all_days = sorted(set(list(neis_evs.keys()) + list(personal_evs.keys())))
    if not all_days:
        st.info("이번 달에 등록된 학사일정 및 개인 일정이 없습니다.")
    else:
        for d in all_days:
            st.markdown(f"#### 📌 {sel_m}월 {d}일")
            if d in neis_evs:
                for ev in neis_evs[d]:
                    st.markdown(f"- 🏫 **[학사]** {ev}")
            if d in personal_evs:
                for p_ev in personal_evs[d]:
                    c_chk, c_del = st.columns([5, 1])
                    checked = c_chk.checkbox(p_ev["text"], value=p_ev["done"], key=f"chk_{p_ev['row']}")
                    if checked != p_ev["done"] and sheet:
                        sheet.update_cell(p_ev["row"], 3, "TRUE" if checked else "FALSE")
                        st.rerun()
                    if c_del.button("삭제", key=f"pdel_{p_ev['row']}") and sheet:
                        sheet.delete_rows(p_ev["row"])
                        st.rerun()

# [탭 2] 오늘의 급식
with tab2:
    sel_date = st.date_input("급식 날짜 선택", datetime.now())
    st.info(get_day_meal(sel_date.strftime("%Y%m%d"), st.session_state.api_key, st.session_state.office_code, st.session_state.school_code))

# [탭 3] 주간 시간표
with tab3:
    mode = st.radio("시간표 보기", ["교사용 (내 수업)", "학생용 (우리 반)"], horizontal=True)
    target_data = st.session_state.timetable_teacher if "교사용" in mode else st.session_state.timetable_student
    rows = []
    for p in range(7):
        row = {"교시": f"{p+1}교시"}
        for d in ["월", "화", "수", "목", "금"]:
            row[d] = target_data[d][p]
        rows.append(row)
    st.table(rows)

# [탭 4] 초과근무 계산기
with tab4:
    c1, c2, c3 = st.columns([2, 1, 1])
    memo_in = c1.text_input("메모", placeholder="예: 야근")
    h_in = c2.number_input("시간", min_value=0, max_value=24, value=1)
    m_in = c3.number_input("분", min_value=0, max_value=59, value=0)
    b1, b2 = st.columns(2)
    if b1.button("➕ 추가", use_container_width=True, type="primary"):
        if h_in > 0 or m_in > 0:
            st.session_state.overtime_list.append({"메모": memo_in or "초과근무", "시간": h_in, "분": m_in})
            st.rerun()
    if b2.button("🔄 초기화", use_container_width=True):
        st.session_state.overtime_list = []
        st.rerun()
    total_mins = sum(i["시간"] * 60 + i["분"] for i in st.session_state.overtime_list)
    rate = st.number_input("시간당 단가 (원)", min_value=0, value=14000, step=500)
    st.success(f"**총 시간:** {total_mins // 60}시간 {total_mins % 60}분 | **NEIS 정산액:** {(total_mins // 60) * rate:,}원")
    for idx, item in enumerate(st.session_state.overtime_list):
        ci, cd = st.columns([4, 1])
        ci.write(f"• {item['메모']} : **{item['시간']}시간 {item['분']}분**")
        if cd.button("삭제", key=f"odel_{idx}"):
            st.session_state.overtime_list.pop(idx)
            st.rerun()

# [탭 5] 환경설정 (나이스 API, 학교코드, 시간표 수정, 기존 JSON 일괄 업로드)
with tab5:
    st.subheader("🏛️ 나이스(NEIS) API 및 학교 설정")
    new_key = st.text_input("인증 API KEY", value=st.session_state.api_key)
    new_office = st.text_input("시도교육청 코드 (예: 경북 R10)", value=st.session_state.office_code)
    new_school = st.text_input("표준 학교 코드 (7자리)", value=st.session_state.school_code)
    
    if st.button("나이스 설정 적용 및 새로고침", type="primary"):
        st.session_state.api_key = new_key.strip()
        st.session_state.office_code = new_office.strip()
        st.session_state.school_code = new_school.strip()
        st.cache_data.clear()
        st.success("나이스 설정이 적용되었습니다!")
        st.rerun()

    st.divider()
    st.subheader("📤 기존 PC 일정(dashboard_data.json) 일괄 옮기기")
    uploaded_json = st.file_uploader("컴퓨터에 있던 dashboard_data.json 파일을 선택하세요", type=["json"])
    if uploaded_json is not None and st.button("구글 스프레드시트로 기존 일정 전체 전송"):
        if sheet:
            raw_data = json.load(uploaded_json)
            events_dict = raw_data.get("custom_user_events", {})
            rows_to_add = []
            for d_key, ev_list in events_dict.items():
                for ev in ev_list:
                    rows_to_add.append([d_key, ev.get("text", ""), "TRUE" if ev.get("done") else "FALSE"])
            if rows_to_add:
                sheet.append_rows(rows_to_add)
                st.success(f"총 {len(rows_to_add)}개의 기존 일정이 구글 스프레드시트로 전송되었습니다!")
            else:
                st.info("파일 안에 옮길 개인 일정이 없습니다.")
        else:
            st.error("먼저 Streamlit Secrets에 구글 스프레드시트 연동을 완료해 주세요.")

    st.divider()
    st.subheader("📅 교사용 시간표 빠른 수정")
    edit_day = st.selectbox("수정할 요일 선택", ["월", "화", "수", "목", "금"])
    new_subjects = []
    for p in range(7):
        val = st.text_input(f"{edit_day}요일 {p+1}교시", value=st.session_state.timetable_teacher[edit_day][p], key=f"t_{edit_day}_{p}")
        new_subjects.append(val)
    if st.button(f"{edit_day}요일 시간표 저장"):
        st.session_state.timetable_teacher[edit_day] = new_subjects
        st.success(f"{edit_day}요일 시간표가 반영되었습니다!")
