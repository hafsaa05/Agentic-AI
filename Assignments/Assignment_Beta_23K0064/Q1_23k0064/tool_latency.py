"""
Tool latency timing for SaafHawa (Assignment Beta, Question 1).

Usage:
    pip install requests
    set OPENAQ_API_KEY=your_key
    python tool_latency.py
"""

import csv
import os
import statistics
import time
from datetime import datetime

import requests

LAT, LON = 24.8607, 67.0011
CALLS_PER_API = 12
PAUSE_BETWEEN_CALLS = 2
LOCAL_REPEATS = CALLS_PER_API
LOG_FILE = "tool_latency_log.csv"

OPENAQ_KEY = os.environ.get("OPENAQ_API_KEY", "")


def find_openaq_location():
    url = "https://api.openaq.org/v3/locations"
    params = {"coordinates": f"{LAT},{LON}", "radius": 25000, "limit": 10}
    r = requests.get(url, params=params, headers={"X-API-Key": OPENAQ_KEY}, timeout=30)
    r.raise_for_status()
    results = r.json().get("results", [])
    for loc in results:
        names = [s["parameter"]["name"] for s in loc.get("sensors", [])]
        if "pm25" in names:
            return loc["id"], loc.get("name")
    if results:
        return results[0]["id"], results[0].get("name")
    raise RuntimeError("No OpenAQ station found near Karachi")


def air_quality_tool(location_id):
    url = f"https://api.openaq.org/v3/locations/{location_id}/latest"
    r = requests.get(url, headers={"X-API-Key": OPENAQ_KEY}, timeout=30)
    r.raise_for_status()
    return r.json()


def weather_tool():
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": LAT,
        "longitude": LON,
        "current": "temperature_2m,relative_humidity_2m,wind_speed_10m",
        "hourly": "temperature_2m,relative_humidity_2m",
        "forecast_days": 1,
        "timezone": "Asia/Karachi",
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def heat_index_c(temp_c, rh):
    t = temp_c * 9 / 5 + 32
    hi = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    if hi >= 80:
        hi = (-42.379 + 2.04901523 * t + 10.14333127 * rh
              - 0.22475541 * t * rh - 0.00683783 * t * t
              - 0.05481717 * rh * rh + 0.00122874 * t * t * rh
              + 0.00085282 * t * rh * rh - 0.00000199 * t * t * rh * rh)
        if rh < 13 and 80 <= t <= 112:
            hi -= ((13 - rh) / 4) * ((17 - abs(t - 95)) / 17) ** 0.5
        elif rh > 85 and 80 <= t <= 87:
            hi += ((rh - 85) / 10) * ((87 - t) / 5)
    return (hi - 32) * 5 / 9


KB = [
    ("heatwave children school", "Keep children indoors between 12pm and 4pm during a heatwave, give water often."),
    ("heatwave elderly", "Older people should avoid going out in peak heat and watch for dizziness or confusion."),
    ("heatwave outdoor labourer workers", "Outdoor workers should take shade breaks and drink water every 20 minutes."),
    ("heatstroke symptoms", "High body temperature, no sweating, confusion: move to shade and get medical help."),
    ("pm2.5 asthma", "Asthma patients should keep inhalers ready and avoid outdoor exercise when PM2.5 is high."),
    ("pm2.5 mask", "A well fitted N95 mask reduces exposure to fine particles on polluted days."),
    ("aqi unhealthy exercise jog", "When air is unhealthy, move exercise indoors or to early morning hours."),
    ("sea breeze evening", "Evening sea breeze usually lowers heat, but check air quality before a run."),
]


def kb_lookup(query):
    q = set(query.lower().split())
    scored = []
    for keys, text in KB:
        score = len(q & set(keys.split()))
        scored.append((score, text))
    scored.sort(reverse=True)
    return [t for s, t in scored[:2] if s > 0]


def log_row(writer, tool, run_label, seconds, status):
    now = datetime.now()
    writer.writerow({
        "timestamp": now.isoformat(timespec="seconds"),
        "date": now.date().isoformat(),
        "run": run_label,
        "tool": tool,
        "latency_s": f"{seconds:.6f}",
        "status": status,
    })


def main():
    run_label = datetime.now().strftime("run_%Y%m%d_%H%M")
    new_file = not os.path.exists(LOG_FILE)
    f = open(LOG_FILE, "a", newline="")
    writer = csv.DictWriter(f, fieldnames=["timestamp", "date", "run", "tool", "latency_s", "status"])
    if new_file:
        writer.writeheader()

    if OPENAQ_KEY:
        loc_id, loc_name = find_openaq_location()
        print(f"OpenAQ station: {loc_name} (id {loc_id})")
        for i in range(CALLS_PER_API):
            t0 = time.perf_counter()
            try:
                air_quality_tool(loc_id)
                status = "ok"
            except Exception as e:
                status = f"error: {e}"
            dt = time.perf_counter() - t0
            log_row(writer, "air_quality_openaq", run_label, dt, status)
            print(f"  openaq {i+1}: {dt:.3f}s {status}")
            time.sleep(PAUSE_BETWEEN_CALLS)
    else:
        print("OPENAQ_API_KEY not set, skipping OpenAQ")

    last_weather = None
    for i in range(CALLS_PER_API):
        t0 = time.perf_counter()
        try:
            last_weather = weather_tool()
            status = "ok"
        except Exception as e:
            status = f"error: {e}"
        dt = time.perf_counter() - t0
        log_row(writer, "weather_openmeteo", run_label, dt, status)
        print(f"  open-meteo {i+1}: {dt:.3f}s {status}")
        time.sleep(PAUSE_BETWEEN_CALLS)

    if last_weather:
        temp = last_weather["current"]["temperature_2m"]
        rh = last_weather["current"]["relative_humidity_2m"]
    else:
        temp, rh = 38.0, 60.0
    for _ in range(LOCAL_REPEATS):
        t0 = time.perf_counter()
        heat_index_c(temp, rh)
        log_row(writer, "heat_index_local", run_label, time.perf_counter() - t0, "ok")

    for _ in range(LOCAL_REPEATS):
        t0 = time.perf_counter()
        kb_lookup("is it safe for my asthma child to jog in the evening heatwave pm2.5")
        log_row(writer, "kb_lookup_local", run_label, time.perf_counter() - t0, "ok")

    f.close()

    rows = list(csv.DictReader(open(LOG_FILE)))
    ok = [float(r["latency_s"]) for r in rows if r["status"] == "ok"]
    days = sorted({r["date"] for r in rows})
    print(f"\nLogged {len(rows)} rows over {len(days)} day(s): {days}")
    if ok:
        print(f"Median of all successful measurements: {statistics.median(ok):.4f} s")


if __name__ == "__main__":
    main()