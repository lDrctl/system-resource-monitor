from collections import deque
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from syswatch.collector import Collector, system_info


def amount(value, suffix=""):
    if value is None:
        return "—"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{value:,.1f} {unit}{suffix}"
        value /= 1024


def percent(value):
    return "—" if value is None else f"{value:.1f}%"


st.set_page_config(page_title="SysWatch", page_icon="📈", layout="wide")
if "collector" not in st.session_state:
    st.session_state.collector = Collector()
    st.session_state.system = system_info()
    st.session_state.history = deque(maxlen=300)

system = st.session_state.system
st.title("SysWatch")
st.caption(f"{system['hostname']} · {system['os']}")
with st.expander("시스템 정보"):
    st.write(f"CPU 모델 · {system['cpu_model'] or '확인할 수 없음'}")
    st.write(f"논리 프로세서 · {system['logical_cpus'] or '확인할 수 없음'}")
    st.write(f"전체 RAM · {amount(system['ram_total'])}")
    boot_time = datetime.fromisoformat(system["boot_time"])
    st.write(f"부팅 시간 · {boot_time:%Y-%m-%d %H:%M:%S %Z}")


@st.fragment(run_every=2)
def live_dashboard():
    try:
        sample = st.session_state.collector.sample()
    except (OSError, RuntimeError) as error:
        st.error(f"로컬 측정 실패 · {error}")
        return

    memory = sample["memory"]
    network = sample["network"]
    timestamp = datetime.fromisoformat(sample["timestamp"])
    uptime = timedelta(seconds=sample["uptime_seconds"])
    st.caption(f"● 로컬 측정 중 · 최근 측정 {timestamp:%H:%M:%S} · 가동 시간 {uptime}")

    history = st.session_state.history
    history.append({
        "시간": timestamp,
        "CPU": sample["cpu_percent"],
        "RAM": memory["percent"],
        "송신": network["upload"],
        "수신": network["download"],
    })
    frame = pd.DataFrame(history).set_index("시간").astype(float)

    cpu_column, memory_column, download_column, upload_column = st.columns(4)
    cpu_column.metric("CPU 사용률", percent(sample["cpu_percent"]))
    memory_column.metric("RAM 사용률", percent(memory["percent"]))
    download_column.metric("다운로드", amount(network["download"], "/s"))
    upload_column.metric("업로드", amount(network["upload"], "/s"))

    resource_column, network_column = st.columns(2)
    with resource_column:
        st.subheader("CPU · RAM 사용률 (%)")
        st.caption(
            f"사용 {amount(memory['used'])} / 전체 {amount(memory['total'])}"
            f" · 사용 가능 {amount(memory['available'])}"
        )
        st.line_chart(frame[["CPU", "RAM"]])
    with network_column:
        st.subheader("네트워크 속도 (B/s)")
        st.caption(f"누적 송신 {amount(network['sent'])} · 수신 {amount(network['received'])}")
        st.line_chart(frame[["송신", "수신"]])

    st.subheader("디스크")
    if sample["disks"]:
        st.dataframe([{
            "드라이브 / 마운트": disk["mount"],
            "전체": amount(disk["total"]),
            "사용": amount(disk["used"]),
            "남은 공간": amount(disk["free"]),
            "사용률": percent(disk["percent"]),
        } for disk in sample["disks"]], hide_index=True)
    else:
        st.info("용량을 확인할 수 있는 디스크가 없습니다.")


live_dashboard()
