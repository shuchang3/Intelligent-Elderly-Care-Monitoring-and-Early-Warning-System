"""Generate clearly labelled synthetic records for the previous seven days.

Requires the local Java service, initialized elder_care_dev database, and
credentials from the ignored .env.local file. Generated records are retained.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env.local")

BASE = os.environ.get("JAVA_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
ADMIN_PASSWORD = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD")
AI_KEY = os.environ.get("AI_SERVICE_KEY")
if not ADMIN_PASSWORD or not AI_KEY:
    raise SystemExit(".env.local must define BOOTSTRAP_ADMIN_PASSWORD and AI_SERVICE_KEY")

http = requests.Session()
http.trust_env = False
tag = uuid.uuid4().hex[:10].upper()
elder_code = f"TEST-WEEK-E-{tag}"
worker_code = f"TEST-WEEK-W-{tag}"
camera_code = os.environ.get("AI_NODE_CODE", "NODE001")


def request(method: str, path: str, *, expected: int = 200, **kwargs):
    response = http.request(method, f"{BASE}/api/v1/{path}", timeout=20, **kwargs)
    if response.status_code != expected:
        raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {response.text[:300]}")
    body = response.json()
    if body.get("code") != 200:
        raise RuntimeError(f"{method} {path}: {body}")
    return body.get("data")


login = request("POST", "auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
http.headers["Authorization"] = f"Bearer {login['token']}"
ai_headers = {"X-AI-Key": AI_KEY}

# Validate the configured camera before creating any records.
cameras = request("GET", "cameras")
if not any(row.get("cameraCode") == camera_code and row.get("enabled") for row in cameras):
    camera_code = next((row["cameraCode"] for row in cameras if row.get("enabled")), None)
if not camera_code:
    raise SystemExit("No enabled camera is configured; initialize the local database first")

request("POST", "persons", json={
    "personCode": elder_code,
    "name": f"TEST 合成老人 {tag}",
    "personType": "ELDER",
    "note": "TEST synthetic weekly data; not a real person",
})
request("POST", "persons", json={
    "personCode": worker_code,
    "name": f"TEST 合成护理员 {tag}",
    "personType": "WORKER",
    "note": "TEST synthetic weekly data; not a real person",
})

now = datetime.now().replace(microsecond=0)
start = now - timedelta(days=7)
event_count = emotion_count = track_count = interaction_count = 0
event_types = ("FALL", "STRANGER", "EMOTION_ABNORMAL")
emotions = ("neutral", "happy", "sad", "neutral", "happy", "fear", "neutral", "sad")

for day in range(7):
    day_start = start + timedelta(days=day)
    for slot, event_type in enumerate(event_types):
        event_time = day_start.replace(hour=8 + slot * 3, minute=15 + day * 5 % 40)
        if event_time > now:
            event_time = now - timedelta(minutes=slot + 1)
        form = {
            "eventNo": str(uuid.uuid4()),
            "eventType": event_type,
            "cameraCode": camera_code,
            "personCode": elder_code,
            "trackId": f"TEST-{tag}-{day}-{slot}",
            "eventTime": event_time.isoformat(timespec="seconds"),
            "description": f"TEST 合成事件：{event_type}；仅用于页面联调，不代表真实告警。",
            "confidence": str(round(0.72 + 0.03 * slot, 2)),
            "scoreType": "TEST_SYNTHETIC",
        }
        # The endpoint is multipart/form-data even when no snapshot is attached.
        request("POST", "ai/events", headers=ai_headers, data=form,
                files={"snapshot": ("", b"", "application/octet-stream")})
        event_count += 1

    # Eight emotional observations and twelve normalized trajectory points per day.
    for sample in range(8):
        sampled_at = day_start.replace(hour=9 + sample, minute=sample * 6)
        if sampled_at > now:
            sampled_at = now - timedelta(minutes=sample + 1)
        request("POST", "ai/samples", headers=ai_headers, json={
            "kind": "emotion",
            "sampleNo": str(uuid.uuid4()),
            "cameraCode": camera_code,
            "personCode": elder_code,
            "sampleTime": sampled_at.isoformat(timespec="seconds"),
            "emotion": emotions[sample],
            "score": round(0.68 + (sample % 4) * 0.07, 2),
        })
        emotion_count += 1

    for sample in range(12):
        sampled_at = day_start.replace(hour=7 + sample, minute=sample * 4)
        if sampled_at > now:
            sampled_at = now - timedelta(minutes=sample + 1)
        request("POST", "ai/samples", headers=ai_headers, json={
            "kind": "track",
            "sampleNo": str(uuid.uuid4()),
            "cameraCode": camera_code,
            "personCode": elder_code,
            "trackId": f"TEST-{tag}-TRACK-{day}",
            "sampleTime": sampled_at.isoformat(timespec="seconds"),
            "x": round(0.2 + sample * 0.045, 3),
            "y": round(0.35 + ((sample + day) % 5) * 0.06, 3),
        })
        track_count += 1

    for slot in range(2):
        began = day_start.replace(hour=10 + slot * 5, minute=20)
        ended = min(began + timedelta(minutes=12 + slot * 7), now)
        if began > now:
            began = now - timedelta(minutes=15)
            ended = now
        request("POST", "ai/interactions", headers=ai_headers, json={
            "recordNo": str(uuid.uuid4()),
            "cameraCode": camera_code,
            "elderCode": elder_code,
            "workerCode": worker_code,
            "startTime": began.isoformat(timespec="seconds"),
            "endTime": ended.isoformat(timespec="seconds"),
        })
        interaction_count += 1

print(
    f"Created TEST tag {tag} for {start:%Y-%m-%d %H:%M} through {now:%Y-%m-%d %H:%M} "
    f"({camera_code}): persons=2, events={event_count}, emotions={emotion_count}, "
    f"tracks={track_count}, interactions={interaction_count}. Records are retained."
)
