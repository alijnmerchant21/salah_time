import math
import datetime as dt
import os
import requests
from zoneinfo import ZoneInfo

LAT = 50.1109
LON = 8.6821
TZ = ZoneInfo("Europe/Berlin")

FAJR_ANGLE = 13.23
SUN_ALT = -1.4

WEBHOOK_URL = os.environ["TRMNL_WEBHOOK"]

RAMADAN_1_GREGORIAN = dt.date(2026, 2, 17)
RAMADAN_1_HIJRI_YEAR = 1447

HIJRI_MONTHS = [
    "Muharram","Safar","Rabi I","Rabi II",
    "Jumada I","Jumada II","Rajab","Sha'ban",
    "Ramadan","Shawwal","Dhul Qa'dah","Dhul Hijjah"
]

def deg2rad(x): return x * math.pi / 180
def day_of_year(d): return int(d.strftime("%j"))

def solar_declination(gamma):
    return (0.006918
            -0.399912*math.cos(gamma)
            +0.070257*math.sin(gamma)
            -0.006758*math.cos(2*gamma)
            +0.000907*math.sin(2*gamma)
            -0.002697*math.cos(3*gamma)
            +0.00148*math.sin(3*gamma))

def equation_of_time(gamma):
    return 229.18*(0.000075
                   +0.001868*math.cos(gamma)
                   -0.032077*math.sin(gamma)
                   -0.014615*math.cos(2*gamma)
                   -0.040849*math.sin(2*gamma))

def hour_angle(lat_rad, decl_rad, alt_deg):
    h = deg2rad(alt_deg)
    cosH = (math.sin(h)-math.sin(lat_rad)*math.sin(decl_rad)) / \
           (math.cos(lat_rad)*math.cos(decl_rad))
    cosH = max(-1,min(1,cosH))
    return math.degrees(math.acos(cosH))

def gregorian_to_hijri(date):
    delta = (date - RAMADAN_1_GREGORIAN).days
    day = 1 + delta
    month = 9
    year = RAMADAN_1_HIJRI_YEAR
    if day <= 0:
        month = 8
        day = 30 + day
    return day, month, year

def clamp_pct(x):
    return int(max(0, min(100, x)))

def compute_payload():

    now = dt.datetime.now(TZ)
    today = now.date()
    midnight = dt.datetime(today.year,today.month,today.day,0,0,tzinfo=TZ)

    doy = day_of_year(today)
    gamma = 2*math.pi/365*(doy-1)

    decl = solar_declination(gamma)
    lat_rad = deg2rad(LAT)

    noon = dt.datetime(today.year,today.month,today.day,12,tzinfo=TZ)
    tz_offset = noon.utcoffset().total_seconds()/60
    eot = equation_of_time(gamma)

    solar_noon = 720 - 4*LON - eot + tz_offset

    H0 = hour_angle(lat_rad,decl,SUN_ALT)
    sunrise_min = solar_noon - H0*4
    maghrib_min = solar_noon + H0*4

    HF = hour_angle(lat_rad,decl,-FAJR_ANGLE)
    fajr_min = solar_noon - HF*4

    def to_dt(m):
        return midnight + dt.timedelta(minutes=float(m%1440))

    sihori = to_dt(fajr_min)
    sunrise = to_dt(sunrise_min)
    zawal = to_dt(solar_noon)
    maghrib = to_dt(maghrib_min)

    maghrib_end = maghrib + dt.timedelta(minutes=15)

    # tomorrow sihori
    tomorrow = today + dt.timedelta(days=1)
    doy2 = day_of_year(tomorrow)
    gamma2 = 2*math.pi/365*(doy2-1)
    decl2 = solar_declination(gamma2)
    eot2 = equation_of_time(gamma2)
    solar_noon2 = 720 - 4*LON - eot2 + tz_offset + 1440
    HF2 = hour_angle(lat_rad,decl2,-FAJR_ANGLE)
    fajr2 = solar_noon2 - HF2*4
    sihori_next = midnight + dt.timedelta(minutes=float(fajr2%1440)) + dt.timedelta(days=1)

    # Nisf start based on half night between Maghrib and next Sihori
    night_length = sihori_next - maghrib
    nisf_start = maghrib + (night_length / 2)
    nisf_end = nisf_start + dt.timedelta(hours=2)

    # ---- Timetable windows for "Currently" ----
    windows = [
        ("Pre-Sehori", midnight, sihori),
        ("Fajr", sihori, sunrise),
        ("Midday", sunrise, zawal),
        ("Zohr", zawal, None),     # filled below
        ("Asr", None, None),       # filled below
        ("Late Afternoon", None, maghrib),
        ("Maghrib", maghrib, maghrib_end),
        ("Isha", maghrib_end, nisf_start),
        ("Late Night", nisf_end, sihori_next),
    ]

    # We do not have explicit Zohr End / Asr End math here (your reverse-engineered values used earlier).
    # To keep your timetable consistent without guessing, we will derive:
    # Zohr End = midpoint between Zawal and Maghrib (placeholder is risky)
    #
    # Better: set fixed offsets you want. For now we preserve your prior intent by:
    # Zohr End = Zawal + 2h
    # Asr End  = Maghrib (so Asr window becomes Zawal+2h -> Maghrib)
    #
    # If you want the exact Bohra Zohr End / Asr End from your app, we can plug them in.
    zohr_end = zawal + dt.timedelta(hours=2)
    asr_end = maghrib

    rebuilt = []
    for name, s, e in windows:
        if name == "Zohr":
            rebuilt.append((name, zawal, zohr_end))
        elif name == "Asr":
            rebuilt.append((name, zohr_end, asr_end))
        elif name == "Late Afternoon":
            # merge into Asr already ends at Maghrib; keep but make it a no-op small window
            # we’ll drop it to avoid overlap
            continue
        else:
            rebuilt.append((name, s, e))
    windows = rebuilt

    current_name = "Late Night"
    end_time = sihori_next

    for name, s, e in windows:
        if s <= now < e:
            current_name = name
            end_time = e
            break

    # ---- Eat / No Eat ----
    fasting = (sihori <= now < maghrib)
    eat_state = "No Eat" if fasting else "Eat"

    # ---- Option 3 progress: Roza done vs Night done ----
    if fasting:
        total = (maghrib - sihori).total_seconds()
        elapsed = (now - sihori).total_seconds()
        progress_label = "Roza done"
    else:
        total = (sihori_next - maghrib).total_seconds()
        elapsed = (now - maghrib).total_seconds()
        progress_label = "Night done"

    progress_percent = clamp_pct((elapsed / total) * 100) if total > 0 else 0

    # Hijri
    h_day, h_month, h_year = gregorian_to_hijri(today)
    hijri = f"{h_day} {HIJRI_MONTHS[h_month-1]} {h_year} AH"

    return {
        "hijri": hijri,
        "eat_state": eat_state,
        "current": current_name,
        "ends_at": end_time.strftime("%H:%M"),
        "progress_label": progress_label,
        "progress_percent": progress_percent
    }

def push(payload):
    requests.post(WEBHOOK_URL, json={"merge_variables": payload}, timeout=10)

if __name__ == "__main__":
    push(compute_payload())
