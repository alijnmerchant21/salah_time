import math
import datetime as dt
import os
import requests
from zoneinfo import ZoneInfo

# Frankfurt fixed
LAT = 50.1109
LON = 8.6821
TZ = ZoneInfo("Europe/Berlin")

WEBHOOK_URL = os.environ["TRMNL_WEBHOOK"]

# Reverse-engineered constants from your screenshots
SIHORI_BEFORE_SUNRISE_MIN = 75          # Sihori End = Sunrise - 75m
ASR_BEFORE_MAGHRIB_MIN = 105            # Asr End = Maghrib - 105m
MAGHRIB_WINDOW_MIN = 15                # Maghrib window lasts 15m
NISF_DURATION_MIN = 66                 # Nisf End = Nisf Start + 66m (matches ~01:46/01:47)

# Ramadan anchor only for Hijri label (not used for timetable hardcoding)
RAMADAN_1_GREGORIAN = dt.date(2026, 2, 17)
RAMADAN_1_HIJRI_YEAR = 1447
HIJRI_MONTHS = [
    "Muharram","Safar","Rabi I","Rabi II",
    "Jumada I","Jumada II","Rajab","Sha'ban",
    "Ramadan","Shawwal","Dhul Qa'dah","Dhul Hijjah"
]

# ---- Solar helper math (NOAA-ish) ----
def deg2rad(x): return x * math.pi / 180.0
def day_of_year(d: dt.date) -> int: return int(d.strftime("%j"))

def solar_declination(gamma: float) -> float:
    return (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148  * math.sin(3 * gamma)
    )

def equation_of_time(gamma: float) -> float:
    return 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma)
    )

def hour_angle(lat_rad: float, decl_rad: float, alt_deg: float) -> float:
    h = deg2rad(alt_deg)
    cosH = (math.sin(h) - math.sin(lat_rad) * math.sin(decl_rad)) / (
        math.cos(lat_rad) * math.cos(decl_rad)
    )
    cosH = max(-1.0, min(1.0, cosH))
    return math.degrees(math.acos(cosH))

def clamp_pct(x: float) -> int:
    return int(max(0, min(100, x)))

def gregorian_to_hijri_ramadan_anchor(date: dt.date):
    # simple anchor for label only
    delta = (date - RAMADAN_1_GREGORIAN).days
    day = 1 + delta
    month = 9
    year = RAMADAN_1_HIJRI_YEAR
    if day <= 0:
        month = 8
        day = 30 + day
    return day, month, year

def compute_solar_times(date: dt.date):
    """
    Returns (sunrise_dt, zawal_dt, maghrib_dt) for Frankfurt on a given date.
    Sunrise/Sunset are based on a -0.833 deg refraction-ish horizon.
    """
    midnight = dt.datetime(date.year, date.month, date.day, 0, 0, tzinfo=TZ)

    doy = day_of_year(date)
    gamma = 2 * math.pi / 365.0 * (doy - 1)
    decl = solar_declination(gamma)
    lat_rad = deg2rad(LAT)

    noon = dt.datetime(date.year, date.month, date.day, 12, tzinfo=TZ)
    tz_offset_min = noon.utcoffset().total_seconds() / 60.0
    eot = equation_of_time(gamma)

    solar_noon_min = 720.0 - 4.0 * LON - eot + tz_offset_min

    # Standard sunrise/sunset altitude
    ALT = -0.833
    H0 = hour_angle(lat_rad, decl, ALT)

    sunrise_min = solar_noon_min - H0 * 4.0
    sunset_min  = solar_noon_min + H0 * 4.0

    def to_dt(mins: float) -> dt.datetime:
        return midnight + dt.timedelta(minutes=float(mins % 1440.0))

    sunrise = to_dt(sunrise_min)
    zawal   = to_dt(solar_noon_min)
    maghrib = to_dt(sunset_min)

    return sunrise, zawal, maghrib

def compute_day_schedule(now: dt.datetime):
    today = now.date()

    sunrise, zawal, maghrib = compute_solar_times(today)
    sunrise_next, _, _ = compute_solar_times(today + dt.timedelta(days=1))

    # Reverse engineered derived times (match your app’s structure)
    sihori_end = sunrise - dt.timedelta(minutes=SIHORI_BEFORE_SUNRISE_MIN)
    asr_end = maghrib - dt.timedelta(minutes=ASR_BEFORE_MAGHRIB_MIN)
    zuhr_end = zawal + (asr_end - zawal) / 2  # midpoint

    maghrib_end = maghrib + dt.timedelta(minutes=MAGHRIB_WINDOW_MIN)

    nisf_start = maghrib + (sunrise_next - maghrib) / 2
    nisf_end = nisf_start + dt.timedelta(minutes=NISF_DURATION_MIN)

    # Next day sihori end (for late night)
    sihori_end_next = sunrise_next - dt.timedelta(minutes=SIHORI_BEFORE_SUNRISE_MIN)

    # Blocks as you specified (no blanks)
    midnight = dt.datetime(today.year, today.month, today.day, 0, 0, tzinfo=TZ)

    blocks = [
        ("Pre-Sehori", midnight, sihori_end,  f"Sihori ends at {sihori_end:%H:%M}", f"Sunrise at {sunrise:%H:%M}"),
        ("Fajr",       sihori_end, sunrise,   f"Sunrise at {sunrise:%H:%M}",        f"Zawal at {zawal:%H:%M}"),
        ("Midday",     sunrise, zawal,        f"Zawal at {zawal:%H:%M}",            f"Zuhr ends at {zuhr_end:%H:%M}"),
        ("Zohr",       zawal, zuhr_end,       f"Zuhr ends at {zuhr_end:%H:%M}",     f"Asr ends at {asr_end:%H:%M}"),
        ("Asr",        zuhr_end, asr_end,     f"Asr ends at {asr_end:%H:%M}",       f"Maghrib at {maghrib:%H:%M}"),
        ("Late Asr",   asr_end, maghrib,      f"Maghrib at {maghrib:%H:%M}",        f"Nisf starts at {nisf_start:%H:%M}"),
        ("Maghrib",    maghrib, maghrib_end,  f"Maghrib ends at {maghrib_end:%H:%M}", f"Nisf starts at {nisf_start:%H:%M}"),
        ("Isha",       maghrib_end, nisf_start, f"Nisf starts at {nisf_start:%H:%M}", f"Nisf ends at {nisf_end:%H:%M}"),
        ("Late Night", nisf_end, sihori_end_next, f"Sihori ends at {sihori_end_next:%H:%M}", f"Sunrise at {sunrise_next:%H:%M}"),
    ]

    # Determine current block
    current = blocks[-1]
    for b in blocks:
        if b[1] <= now < b[2]:
            current = b
            break

    current_name, start, end, line1, line2 = current

    # Eat/No Eat: fasting window is Sihori End -> Maghrib
    fasting = (sihori_end <= now < maghrib)
    eat_state = "No Eat" if fasting else "Eat"

    # Option 3 progress:
    # - During fasting: roza done %
    # - During night: night done % (maghrib -> next sihori_end)
    if fasting:
        total = (maghrib - sihori_end).total_seconds()
        elapsed = (now - sihori_end).total_seconds()
        progress_label = "Roza done"
    else:
        # Night is from Maghrib to next Sihori End
        # If it's before Maghrib (pre-sehori or fajr), we're still in "night done" relative to previous Maghrib.
        # For simplicity in Ramadan UX: before Sihori End, use previous maghrib from yesterday.
        if now < maghrib:
            # previous day's maghrib and next sihori_end are today's sihori_end
            _, _, maghrib_prev = compute_solar_times(today - dt.timedelta(days=1))
            sunrise_prev, _, _ = compute_solar_times(today)  # already have sunrise as "today sunrise"
            sihori_end_today = sihori_end
            total = (sihori_end_today - maghrib_prev).total_seconds()
            elapsed = (now - maghrib_prev).total_seconds()
        else:
            total = (sihori_end_next - maghrib).total_seconds()
            elapsed = (now - maghrib).total_seconds()
        progress_label = "Night done"

    progress_percent = clamp_pct((elapsed / total) * 100) if total > 0 else 0

    # Hijri label (Ramadan anchor)
    h_day, h_month, h_year = gregorian_to_hijri_ramadan_anchor(today)
    hijri = f"{h_day} {HIJRI_MONTHS[h_month-1]} {h_year} AH"

    return {
        "hijri": hijri,
        "eat_state": eat_state,
        "current": current_name,
        "ends_at": end.strftime("%H:%M"),
        "line1": line1,
        "line2": line2,
        "progress_label": progress_label,
        "progress_percent": progress_percent
    }

def push(payload):
    r = requests.post(WEBHOOK_URL, json={"merge_variables": payload}, timeout=10)
    print("status", r.status_code)
    print(payload)

if __name__ == "__main__":
    now = dt.datetime.now(TZ)
    push(compute_day_schedule(now))
