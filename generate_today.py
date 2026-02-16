import math
import datetime as dt
import os
import requests
from zoneinfo import ZoneInfo

# -------------------------------------------------
# Frankfurt Configuration
# -------------------------------------------------
LAT = 50.1109
LON = 8.6821
TZ = "Europe/Berlin"

FAJR_ANGLE = 13.23
SUN_ALT = -1.4
ASR_FACTOR_START = 0.356
ASR_FACTOR_END = 2.299
NISF_START_RATIO = 0.552
NISF_END_RATIO = 0.641333

WEBHOOK_URL = os.environ["TRMNL_WEBHOOK"]

# -------------------------------------------------
# RAMADAN ANCHOR (Adjust if needed)
# -------------------------------------------------
RAMADAN_1_GREGORIAN = dt.date(2026, 2, 17)
RAMADAN_1_HIJRI_YEAR = 1447

HIJRI_MONTHS = [
    "Muharram", "Safar", "Rabi I", "Rabi II",
    "Jumada I", "Jumada II", "Rajab", "Sha'ban",
    "Ramadan", "Shawwal", "Dhul Qa'dah", "Dhul Hijjah"
]

# -------------------------------------------------
# Astronomy Helpers
# -------------------------------------------------
def deg2rad(x): return x * math.pi / 180
def rad2deg(x): return x * 180 / math.pi
def day_of_year(date): return int(date.strftime("%j"))

def solar_declination(gamma):
    return (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma)
    )

def equation_of_time(gamma):
    return 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )

def hour_angle(lat_rad, decl_rad, alt_deg):
    h = deg2rad(alt_deg)
    cosH = (math.sin(h) - math.sin(lat_rad) * math.sin(decl_rad)) / (
        math.cos(lat_rad) * math.cos(decl_rad)
    )
    cosH = max(-1, min(1, cosH))
    return math.degrees(math.acos(cosH))

# -------------------------------------------------
# Hijri Calculation Based On Ramadan Anchor
# -------------------------------------------------
def gregorian_to_hijri(date):

    delta_days = (date - RAMADAN_1_GREGORIAN).days

    hijri_day = 1 + delta_days
    hijri_month = 9  # Ramadan
    hijri_year = RAMADAN_1_HIJRI_YEAR

    if hijri_day <= 0:
        hijri_month = 8  # Sha'ban
        hijri_day = 30 + hijri_day  # assume 30-day month

    return hijri_day, hijri_month, hijri_year

# -------------------------------------------------
# Core Calculation
# -------------------------------------------------
def compute_times():

    tz = ZoneInfo(TZ)
    now = dt.datetime.now(tz)
    today = now.date()
    midnight = dt.datetime(today.year, today.month, today.day, 0, 0, tzinfo=tz)

    doy = day_of_year(today)
    gamma = 2 * math.pi / 365 * (doy - 1)

    decl = solar_declination(gamma)
    lat_rad = deg2rad(LAT)

    noon = dt.datetime(today.year, today.month, today.day, 12, tzinfo=tz)
    tz_offset = noon.utcoffset().total_seconds() / 60
    eot = equation_of_time(gamma)

    solar_noon = 720 - 4 * LON - eot + tz_offset

    H0 = hour_angle(lat_rad, decl, SUN_ALT)
    sunrise_min = solar_noon - H0 * 4
    maghrib_min = solar_noon + H0 * 4

    HF = hour_angle(lat_rad, decl, -FAJR_ANGLE)
    fajr_min = solar_noon - HF * 4

    noon_shadow = math.tan(abs(lat_rad - decl))

    alt_asr_start = rad2deg(math.atan(1 / (ASR_FACTOR_START + noon_shadow)))
    alt_asr_end = rad2deg(math.atan(1 / (ASR_FACTOR_END + noon_shadow)))

    HA_start = hour_angle(lat_rad, decl, alt_asr_start)
    HA_end = hour_angle(lat_rad, decl, alt_asr_end)

    zuhr_end_min = solar_noon + HA_start * 4
    asr_end_min = solar_noon + HA_end * 4

    tomorrow = today + dt.timedelta(days=1)
    doy_next = day_of_year(tomorrow)
    gamma_next = 2 * math.pi / 365 * (doy_next - 1)
    decl_next = solar_declination(gamma_next)
    eot_next = equation_of_time(gamma_next)

    solar_noon_next = 720 - 4 * LON - eot_next + tz_offset + 1440
    HF_next = hour_angle(lat_rad, decl_next, -FAJR_ANGLE)
    fajr_next_min = solar_noon_next - HF_next * 4

    night_length = fajr_next_min - maghrib_min

    nisf_start_min = maghrib_min + night_length * NISF_START_RATIO
    nisf_end_min = maghrib_min + night_length * NISF_END_RATIO

    def to_dt(minutes):
        return midnight + dt.timedelta(minutes=minutes % 1440)

    events = [
        ("Sihori", to_dt(fajr_min)),
        ("Sunrise", to_dt(sunrise_min)),
        ("Zawal", to_dt(solar_noon)),
        ("Zuhr End", to_dt(zuhr_end_min)),
        ("Asr End", to_dt(asr_end_min)),
        ("Maghrib", to_dt(maghrib_min)),
        ("Nisf Start", to_dt(nisf_start_min)),
        ("Nisf End", to_dt(nisf_end_min)),
    ]

    events.sort(key=lambda x: x[1])

    current_event = None
    next_event = None

    for i in range(len(events)):
        if now < events[i][1]:
            next_event = events[i]
            current_event = events[i - 1] if i > 0 else events[-1]
            break

    if next_event is None:
        next_event = events[0]
        current_event = events[-1]

    # Countdown
    delta = next_event[1] - now
    total_seconds = max(0, int(delta.total_seconds()))
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    countdown = f"{hours:02d}:{minutes:02d}"

    # Progress bar calculation
    current_start = current_event[1]
    current_end = next_event[1]
    window = (current_end - current_start).total_seconds()
    elapsed = (now - current_start).total_seconds()
    progress = int(max(0, min(100, (elapsed / window) * 100))) if window > 0 else 0

    # Hijri
    h_day, h_month, h_year = gregorian_to_hijri(today)
    hijri_str = f"{h_day} {HIJRI_MONTHS[h_month-1]} {h_year} AH"

    return {
        "date": str(today),
        "hijri": hijri_str,
        "current_name": current_event[0],
        "next_name": next_event[0],
        "next_time": next_event[1].strftime("%H:%M"),
        "countdown": countdown,
        "progress": progress
    }

# -------------------------------------------------
# Push to TRMNL
# -------------------------------------------------
def push(data):
    requests.post(
        WEBHOOK_URL,
        json={"merge_variables": data},
        timeout=10
    )

if __name__ == "__main__":
    push(compute_times())
