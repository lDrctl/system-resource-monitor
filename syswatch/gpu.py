"""Windows GPU utilization from the PDH GPU Engine performance counters."""

import ctypes
import math
import platform
import re
from collections import defaultdict

DWORD = ctypes.c_uint32
PDH_MORE_DATA = 0x800007D2
PDH_FMT_DOUBLE = 0x00000200
PDH_FMT_NOCAP100 = 0x00008000
ENGINE_PATTERN = re.compile(r"luid_(.+?)_phys_(\d+)_eng_(\d+)_")


class CounterNumber(ctypes.Union):
    _fields_ = [
        ("long_value", ctypes.c_int32),
        ("double_value", ctypes.c_double),
        ("large_value", ctypes.c_int64),
        ("string_value", ctypes.c_void_p),
    ]


class CounterValue(ctypes.Structure):
    _fields_ = [("status", DWORD), ("number", CounterNumber)]


class CounterItem(ctypes.Structure):
    _fields_ = [("name", ctypes.c_wchar_p), ("value", CounterValue)]


def busiest_engine(values):
    """Sum process contributions to each physical engine, then take the maximum."""
    engines = defaultdict(float)
    for name, value in values:
        match = ENGINE_PATTERN.search(name)
        if match and math.isfinite(value) and value >= 0:
            engines[match.groups()] += value
    if not engines:
        return None
    return min(100.0, max(engines.values()))


class GPUCollector:
    def __init__(self):
        self._query = ctypes.c_void_p()
        self._counter = ctypes.c_void_p()
        self._pdh = None
        self._message = "GPU 측정은 Windows의 GPU Engine 카운터를 지원하는 드라이버에서 사용할 수 있습니다."
        if platform.system() != "Windows":
            return

        try:
            self._pdh = ctypes.WinDLL("pdh.dll")
        except OSError:
            return

        signatures = {
            "PdhOpenQueryW": ([ctypes.c_wchar_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)], DWORD),
            "PdhAddEnglishCounterW": (
                [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_void_p)], DWORD,
            ),
            "PdhCollectQueryData": ([ctypes.c_void_p], DWORD),
            "PdhGetFormattedCounterArrayW": (
                [ctypes.c_void_p, DWORD, ctypes.POINTER(DWORD), ctypes.POINTER(DWORD), ctypes.c_void_p], DWORD,
            ),
            "PdhCloseQuery": ([ctypes.c_void_p], DWORD),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self._pdh, name)
            function.argtypes = arguments
            function.restype = result

        if self._pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query)) != 0:
            return
        status = self._pdh.PdhAddEnglishCounterW(
            self._query, r"\GPU Engine(*)\Utilization Percentage", 0, ctypes.byref(self._counter),
        )
        if status != 0:
            self._counter = ctypes.c_void_p()
            return
        self._pdh.PdhCollectQueryData(self._query)

    def sample(self):
        if not self._counter.value:
            return {"percent": None, "message": self._message}
        if self._pdh.PdhCollectQueryData(self._query) != 0:
            return {"percent": None, "message": "GPU 측정값을 읽을 수 없습니다. 다음 갱신 때 다시 시도합니다."}

        size, count = DWORD(), DWORD()
        flags = PDH_FMT_DOUBLE | PDH_FMT_NOCAP100
        status = self._pdh.PdhGetFormattedCounterArrayW(
            self._counter, flags, ctypes.byref(size), ctypes.byref(count), None,
        )
        # Process instances may change between asking for the size and reading the array.
        for _ in range(3):
            if status != PDH_MORE_DATA or not size.value:
                break
            buffer = ctypes.create_string_buffer(size.value)
            status = self._pdh.PdhGetFormattedCounterArrayW(
                self._counter, flags, ctypes.byref(size), ctypes.byref(count), buffer,
            )
            if status == 0:
                items = ctypes.cast(buffer, ctypes.POINTER(CounterItem))
                values = [
                    (items[index].name or "", items[index].value.number.double_value)
                    for index in range(count.value)
                    if items[index].value.status in (0, 1)
                ]
                percent = busiest_engine(values)
                if percent is not None:
                    return {"percent": percent, "message": ""}
                break
        return {
            "percent": None,
            "message": "GPU 측정 준비 중이거나 드라이버가 GPU 엔진 정보를 제공하지 않습니다.",
        }

    def __del__(self):
        if self._pdh is not None and self._query.value:
            self._pdh.PdhCloseQuery(self._query)
