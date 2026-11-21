from collections import deque
from datetime import datetime, timedelta
import sqlite3
import time

import pandas as pd
import streamlit as st

from syswatch.collector import Collector, system_info
from syswatch.storage import STORAGE_SLOT_SECONDS, MeasurementStore

REFRESH_OPTIONS = {
    "high": ("높음 · 0.5초", 0.5),
    "normal": ("보통 · 1초", 1),
    "low": ("낮음 · 4초", 4),
    "paused": ("일시 중지", None),
}
LIVE_HISTORY_WINDOW = timedelta(minutes=10)
HIGH_USAGE_THRESHOLD = 90
RESOURCE_CHART_COLORS = {"CPU": "#83c9ff", "RAM": "#29b09d", "GPU": "#0068c9"}

HISTORY_RANGES = {
    "15분": (timedelta(minutes=15), STORAGE_SLOT_SECONDS),
    "1시간": (timedelta(hours=1), 10),
    "24시간": (timedelta(days=1), 60),
}


def amount(value, suffix=""):
    if value is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1000 or unit == "TB":
            return f"{value:,.1f} {unit}{suffix}"
        value /= 1000


def percent(value):
    return "—" if value is None else f"{value:.1f}%"


def usage_metric(column, label, value, key):
    if value is not None and value > HIGH_USAGE_THRESHOLD:
        column.container(key=f"{key}-high-usage").metric(label, percent(value))
    else:
        column.metric(label, percent(value))



def resource_chart(frame, key, resources=None, height=300):
    resources = resources or list(RESOURCE_CHART_COLORS)
    selected = st.pills(
        "표시할 자원",
        resources,
        selection_mode="multi",
        default=resources,
        key=key,
    )
    if not selected:
        st.info("CPU·RAM·GPU 버튼을 눌러 표시할 그래프를 선택하세요.")
        return
    st.line_chart(
        frame[selected],
        color=[RESOURCE_CHART_COLORS[resource] for resource in selected],
        height=height,
        y_label="사용률 (%)",
    )


def network_chart(frame, caption=None, height=300):
    network = frame[["송신", "수신"]]
    peak = network.max().max()
    divisor, unit = 1, "B"
    for candidate in ("KB", "MB", "GB", "TB"):
        if not peak >= divisor * 1000:
            break
        divisor *= 1000
        unit = candidate
    st.subheader(f"네트워크 속도 ({unit}/s)")
    if caption:
        st.caption(caption)
    st.line_chart(network / divisor, y_label=f"{unit}/s", height=height)


st.set_page_config(
    page_title="PC Condition", page_icon="📈", layout="wide", initial_sidebar_state="expanded",
)
st.html("""
    <style>
    .stMainBlockContainer { padding-top: 2rem; }
    [data-testid="stMetric"] {
        padding: 1rem;
        border: 1px solid #2b3545;
        border-radius: 10px;
        background: #171e29;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] label {
        border-radius: 8px;
        padding: 0.45rem 0.7rem;
    }
    [data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) {
        background: #24334a;
    }
    :is(.st-key-cpu-high-usage, .st-key-ram-high-usage) [data-testid="stMetricValue"] {
        color: #ff4b4b;
    }
    </style>
""")
if "collector" not in st.session_state:
    st.session_state.collector = Collector()
    st.session_state.system = system_info()
    st.session_state.history = deque()

system = st.session_state.system
st.title("PC Condition")
st.caption(f"{system['hostname']} · {system['os']}")

mode = st.query_params.get("refresh", "normal")
if mode not in REFRESH_OPTIONS:
    mode = "normal"
with st.sidebar:
    st.subheader("성능")
    selected_view = st.radio(
        "자원 선택", ["전체 보기", "CPU", "RAM", "GPU", "네트워크", "디스크"],
        label_visibility="collapsed", key="resource_view",
    )
    st.divider()
    selected_mode = st.radio(
        "갱신 주기",
        list(REFRESH_OPTIONS),
        index=list(REFRESH_OPTIONS).index(mode),
        format_func=lambda option: REFRESH_OPTIONS[option][0],
        key="refresh_mode",
    )
    with st.expander("시스템 정보"):
        st.write(f"CPU 모델 · {system['cpu_model'] or '확인할 수 없음'}")
        st.write(f"논리 프로세서 · {system['logical_cpus'] or '확인할 수 없음'}")
        st.write(f"전체 RAM · {amount(system['ram_total'])}")
        boot_time = datetime.fromisoformat(system["boot_time"])
        st.write(f"부팅 시간 · {boot_time:%Y-%m-%d %H:%M:%S %Z}")

if selected_mode != mode:
    st.query_params["refresh"] = selected_mode
refresh_interval = REFRESH_OPTIONS[selected_mode][1]
paused = refresh_interval is None


@st.cache_resource
def measurement_store():
    return MeasurementStore()


def disk_view(disks):
    st.subheader("디스크 저장 공간")
    if not disks:
        st.info("용량을 확인할 수 있는 디스크가 없습니다.")
        return
    for disk in disks:
        with st.container(border=True):
            label, capacity = st.columns([1, 2])
            label.write(f"**{disk['mount']}**")
            capacity.caption(
                f"사용 {amount(disk['used'])} / 전체 {amount(disk['total'])}"
                f" · 남은 공간 {amount(disk['free'])}"
            )
            st.progress(min(1.0, max(0.0, disk["percent"] / 100)))
            st.caption(f"공간 사용률 {percent(disk['percent'])}")


def render_live_view(sample, frame):
    memory = sample["memory"]
    network = sample["network"]
    if selected_view == "전체 보기":
        cpu, ram, gpu, download, upload = st.columns(5)
        usage_metric(cpu, "CPU 사용률", sample["cpu_percent"], "cpu")
        usage_metric(ram, "RAM 사용률", memory["percent"], "ram")
        gpu.metric("GPU 사용률", percent(sample["gpu"]["percent"]))
        download.metric("다운로드", amount(network["download"], "/s"))
        upload.metric("업로드", amount(network["upload"], "/s"))
        if sample["gpu"]["message"]:
            st.caption(sample["gpu"]["message"])
        resources, traffic = st.columns(2)
        with resources, st.container(border=True):
            st.subheader("CPU · RAM · GPU")
            resource_chart(frame, "live_resources")
        with traffic, st.container(border=True):
            network_chart(frame)
        disk_view(sample["disks"])
        return

    if selected_view == "CPU":
        st.subheader("CPU")
        st.caption(system["cpu_model"] or "CPU 모델을 확인할 수 없습니다.")
        usage, processors, uptime = st.columns(3)
        usage_metric(usage, "사용률", sample["cpu_percent"], "cpu")
        processors.metric("논리 프로세서", system["logical_cpus"] or "—")
        uptime.metric("가동 시간", str(timedelta(seconds=sample["uptime_seconds"])))
    elif selected_view == "RAM":
        st.subheader("메모리")
        usage, used, available, total = st.columns(4)
        usage_metric(usage, "사용률", memory["percent"], "ram")
        used.metric("사용 중", amount(memory["used"]))
        available.metric("사용 가능", amount(memory["available"]))
        total.metric("전체", amount(memory["total"]))
    elif selected_view == "GPU":
        st.subheader("GPU")
        st.metric("사용률", percent(sample["gpu"]["percent"]))
        st.caption(sample["gpu"]["message"] or "GPU 엔진 중 가장 높은 사용률")
    elif selected_view == "네트워크":
        st.subheader("네트워크")
        download, upload, received, sent = st.columns(4)
        download.metric("다운로드", amount(network["download"], "/s"))
        upload.metric("업로드", amount(network["upload"], "/s"))
        received.metric("누적 수신", amount(network["received"]))
        sent.metric("누적 송신", amount(network["sent"]))
        with st.container(border=True):
            network_chart(frame, height=380)
        return
    else:
        disk_view(sample["disks"])
        return

    with st.container(border=True):
        resource_chart(frame, f"live_{selected_view}", [selected_view], height=380)


@st.fragment(run_every=refresh_interval)
def live_dashboard():
    sample = st.session_state.get("last_sample")
    history = st.session_state.history
    if not paused or sample is None:
        try:
            if paused:
                # A fresh browser session needs a baseline interval for CPU and network.
                time.sleep(STORAGE_SLOT_SECONDS)
            sample = st.session_state.collector.sample()
        except (OSError, RuntimeError) as error:
            st.error(f"로컬 측정 실패 · {error}")
            return

        st.session_state.last_sample = sample
        timestamp = datetime.fromisoformat(sample["timestamp"])
        history.append({
            "시간": timestamp,
            "CPU": sample["cpu_percent"],
            "RAM": sample["memory"]["percent"],
            "GPU": sample["gpu"]["percent"],
            "송신": sample["network"]["upload"],
            "수신": sample["network"]["download"],
        })
        while history and history[0]["시간"] < timestamp - LIVE_HISTORY_WINDOW:
            history.popleft()
        try:
            measurement_store().save(sample)
        except (OSError, sqlite3.Error):
            st.warning("측정값을 저장할 수 없습니다. 실시간 모니터링은 계속됩니다.")

    timestamp = datetime.fromisoformat(sample["timestamp"])
    uptime = timedelta(seconds=sample["uptime_seconds"])
    status = "일시 중지 · F5로 한 번 갱신" if paused else "로컬 측정 중"
    measured_time = timestamp.strftime("%H:%M:%S.%f")[:-5]
    st.caption(f"● {status} · 최근 측정 {measured_time} · 가동 시간 {uptime}")
    frame = pd.DataFrame(history).set_index("시간").astype(float)

    render_live_view(sample, frame)


@st.fragment(run_every=None if paused else 10)
def history_dashboard():
    selected = st.selectbox("조회 범위", HISTORY_RANGES)
    duration, bucket_seconds = HISTORY_RANGES[selected]
    if bucket_seconds > STORAGE_SLOT_SECONDS:
        st.caption(f"{bucket_seconds}초 구간별 평균")

    try:
        rows = measurement_store().read(datetime.now().astimezone() - duration, bucket_seconds)
    except (OSError, sqlite3.Error):
        st.error("저장된 측정값을 읽을 수 없습니다.")
        return

    if not rows:
        st.info("선택한 기간에 저장된 측정값이 없습니다.")
        return

    frame = pd.DataFrame(rows, columns=["시간", "CPU", "RAM", "송신", "수신", "GPU"])
    frame["시간"] = pd.to_datetime(frame["시간"], unit="s", utc=True)
    frame = frame.set_index("시간").astype(float)
    if selected_view == "전체 보기":
        resource_column, network_column = st.columns(2)
        with resource_column, st.container(border=True):
            st.subheader("CPU · RAM · GPU")
            resource_chart(frame, "history_resources")
        with network_column, st.container(border=True):
            network_chart(frame)
    elif selected_view in RESOURCE_CHART_COLORS:
        st.subheader(f"{selected_view} 기록")
        resource_chart(frame, f"history_{selected_view}", [selected_view], height=380)
    elif selected_view == "네트워크":
        network_chart(frame, height=380)
    else:
        st.info("디스크 용량은 실시간 탭에서 확인할 수 있습니다.")


live_tab, history_tab = st.tabs(["실시간", "기록"])
with live_tab:
    live_dashboard()
with history_tab:
    history_dashboard()
