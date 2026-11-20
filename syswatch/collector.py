"""Local system metrics shared by the dashboard and command line."""

import platform
import time
from datetime import datetime

import psutil


def cpu_model():
    if platform.system() == "Linux":
        try:
            with open("/proc/cpuinfo", encoding="utf-8") as source:
                for line in source:
                    key, _, value = line.partition(":")
                    if key.strip() == "model name" and value.strip():
                        return value.strip()
        except OSError:
            pass
    if platform.system() == "Windows":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
                return value.strip()
        except OSError:
            pass
    return platform.processor() or platform.machine() or None


def system_info():
    boot_time = psutil.boot_time()
    return {
        "os": platform.platform(),
        "hostname": platform.node(),
        "cpu_model": cpu_model(),
        "logical_cpus": psutil.cpu_count(logical=True),
        "ram_total": psutil.virtual_memory().total,
        "boot_time": datetime.fromtimestamp(boot_time).astimezone().isoformat(),
    }


def disks():
    partitions = psutil.disk_partitions()
    mounts = sorted({item.mountpoint for item in partitions} or {"/"})
    result = []
    for mount in mounts:
        try:
            usage = psutil.disk_usage(mount)
        except OSError:
            continue
        result.append({"mount": mount, **usage._asdict()})
    return result


def cpu_times():
    counters = psutil.cpu_times()
    times = counters._asdict()
    total = sum(times.values()) - times.get("guest", 0) - times.get("guest_nice", 0)
    idle = times["idle"] + times.get("iowait", 0)
    return total, idle


class Collector:
    def __init__(self):
        self.previous_cpu = cpu_times()
        self.previous_network = self.network_snapshot()

    @staticmethod
    def network_snapshot():
        counters = psutil.net_io_counters()
        return time.monotonic(), counters

    def sample(self):
        current_cpu = cpu_times()
        total = current_cpu[0] - self.previous_cpu[0]
        idle = current_cpu[1] - self.previous_cpu[1]
        self.previous_cpu = current_cpu
        cpu_percent = min(100.0, max(0.0, 100 * (total - idle) / total)) if total > 0 else None

        now, network = self.network_snapshot()
        previous_time, previous_network = self.previous_network
        self.previous_network = now, network
        upload = download = None
        if network is not None and previous_network is not None and now > previous_time:
            elapsed = now - previous_time
            sent = network.bytes_sent - previous_network.bytes_sent
            received = network.bytes_recv - previous_network.bytes_recv
            upload = sent / elapsed if sent >= 0 else None
            download = received / elapsed if received >= 0 else None

        memory = psutil.virtual_memory()
        return {
            "timestamp": datetime.now().astimezone().isoformat(),
            "uptime_seconds": max(0, int(time.time() - psutil.boot_time())),
            "cpu_percent": cpu_percent,
            "memory": {
                "total": memory.total,
                "used": memory.total - memory.available,
                "available": memory.available,
                "percent": memory.percent,
            },
            "disks": disks(),
            "network": {
                "upload": upload,
                "download": download,
                "sent": network.bytes_sent if network is not None else None,
                "received": network.bytes_recv if network is not None else None,
            },
        }
