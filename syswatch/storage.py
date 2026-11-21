"""SQLite storage for recent local resource measurements."""

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

DATABASE_PATH = Path(__file__).resolve().parents[1] / "data" / "measurements.sqlite3"
STORAGE_SLOT_SECONDS = 0.5
RETENTION = timedelta(days=7)


class MeasurementStore:
    def __init__(self, path=DATABASE_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS measurements (
                    sample_slot INTEGER PRIMARY KEY,
                    measured_at REAL NOT NULL,
                    cpu_percent REAL,
                    memory_percent REAL NOT NULL,
                    upload_bps REAL,
                    download_bps REAL,
                    gpu_percent REAL
                )
            """)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(measurements)")}
            if "gpu_percent" not in columns:
                connection.execute("ALTER TABLE measurements ADD COLUMN gpu_percent REAL")
            connection.execute("""
                CREATE INDEX IF NOT EXISTS measurements_by_time ON measurements (measured_at)
            """)

    def save(self, sample):
        measured_at = datetime.fromisoformat(sample["timestamp"]).timestamp()
        slot_start = int(measured_at // STORAGE_SLOT_SECONDS) * STORAGE_SLOT_SECONDS
        cutoff = measured_at - RETENTION.total_seconds()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("""
                INSERT INTO measurements
                    (measured_at, cpu_percent, memory_percent, upload_bps, download_bps, gpu_percent)
                SELECT ?, ?, ?, ?, ?, ?
                WHERE NOT EXISTS (
                    SELECT 1 FROM measurements WHERE measured_at >= ? AND measured_at < ?
                )
            """, (
                measured_at,
                sample["cpu_percent"],
                sample["memory"]["percent"],
                sample["network"]["upload"],
                sample["network"]["download"],
                sample.get("gpu", {}).get("percent"),
                slot_start,
                slot_start + STORAGE_SLOT_SECONDS,
            ))
            connection.execute("DELETE FROM measurements WHERE measured_at < ?", (cutoff,))

    def read(self, since, bucket_seconds=STORAGE_SLOT_SECONDS):
        with closing(sqlite3.connect(self.path)) as connection:
            return connection.execute("""
                SELECT MIN(measured_at), AVG(cpu_percent), AVG(memory_percent),
                       AVG(upload_bps), AVG(download_bps), AVG(gpu_percent)
                FROM measurements
                WHERE measured_at >= ?
                GROUP BY CAST(measured_at / ? AS INTEGER)
                ORDER BY MIN(measured_at)
            """, (since.timestamp(), bucket_seconds)).fetchall()
