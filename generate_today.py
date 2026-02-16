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
TZ = ZoneInfo("Europe/Berlin")

FAJR_ANGLE = 13.23
SUN_ALT = -1.4

WEBHOOK_URL = os.environ["TRMNL_WEBHOOK"]

# -------------------------------------------------
# RAMADAN ANCHOR
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
# Hijri Based On Ramadan Anchor
# -------------------------------------------------
def gregorian_to_hijri(date):

    delta_days = (date - RAMADAN_1_GREGORIAN).days

    hijri_day = 1 + delta_days
    hijri_month = 9
    hijri_year = RAMADAN_1_HIJRI_YEAR

    if hijri_day <= 0:
        hijri_month = 8
        hijri_day = 30 + hijri_day

    return hijri_day, hijri_month, hijri_year

# -------------------------------------------------
# Core Ramadan Logic
# -------------------------------------------------
def compute_times():

    now = dt.datetime.now(TZ)
    today = now.date()
    midnight = dt.datetime(today.year, today.month, today.day, 0, 0, tzinfo=TZ)

    doy = day_of_year(today)
    gamma = 2 * math.pi / 365 * (doy - 1)

    decl = solar_declination(gamma)
    lat_rad = deg2rad(LAT)

    noon = dt.datetime(today.year, today.month, today.day, 12, tzinfo=TZ)
    tz_offset = noon.utcoffset().total_seconds() / 60
    eot = equation_of_time(gamma)

    solar_noon = 720 - 4 * LON - eot + tz_offset

    H0 = hour_angle(lat_rad, decl, SUN_ALT)
    sunrise_min = solar_noon - H0 * 4
    maghrib_min = solar_noon + H0 * 4

    HF = hour_angle(lat_rad, decl, -FAJR_ANGLE)
    fajr_min = solar_noon - HF * 4

    def to_dt(minutes):
        return midnight + dt.timedelta(minutes=minutes % 1440)

    sihori_time = to_dt(fajr_min)
    maghrib_time = to_dt(maghrib_min)

    # Tomorrow Sihori
    tomorrow = today + dt.timedelta(days=1)
    doy_next = day_of_year(tomorrow)
    gamma_next = 2 * math.pi / 365 * (doy_next - 1)
    decl_next = solar_declination(gamma_next)
    eot_next = equation_of_time(gamma_next)

    solar_noon_next = 720 - 4 * LON - eot_next + tz_offset + 1440
    HF_next = hour_angle(lat_rad, decl_next, -FAJR_ANGLE)
    fajr_next_min = solar_noon_next - HF_next * 4
    sihori_next_time = midnight + dt.timedelta(minutes=fajr_next_min % 1440)

    # Hijri
    h_day, h_month, h_year = gregorian_to_hijri(today)
    hijri_str = f"{h_day} {HIJRI_MONTHS[h_month-1]} {h_year} AH"

    is_ramadan = (h_month == 9)

    if is_ramadan:
        fasting_duration_td = maghrib_time - sihori_time
        fasting_mins = int(fasting_duration_td.total_seconds() / 60)
        fasting_duration = f"{fasting_mins // 60}h {fasting_mins % 60}m"

        if now < maghrib_time:
            status_line = "Roza in Progress"
            next_event_name = "Maghrib"
            next_event_time = maghrib_time
            total_window = (maghrib_time - sihori_time).total_seconds()
            elapsed = (now - sihori_time).total_seconds()
            # Fun messages: hours/minutes to iftar
            delta = maghrib_time - now
            secs = max(0, int(delta.total_seconds()))
            hrs = secs // 3600
            mins = (secs % 3600) // 60
            if hrs >= 5:
                fun_message = f"Hang your belly tight – {hrs} hours to iftar! 💪"
            elif hrs >= 2:
                fun_message = f"The finish line is in sight – {hrs}h {mins}m to iftar"
            elif hrs >= 1:
                fun_message = f"Last stretch – {hrs}h {mins}m to iftar 🏁"
            elif mins >= 15:
                fun_message = f"Almost there! Iftar in {mins} min 🥤"
            elif mins >= 5:
                fun_message = "Get the dates ready! Iftar in " + str(mins) + " min"
            else:
                fun_message = "Maghrib any moment now – don’t blink! 🌙"
        else:
            status_line = "You're free to eat now"
            next_event_name = "Sihori"
            next_event_time = sihori_next_time
            total_window = (sihori_next_time - maghrib_time).total_seconds()
            elapsed = (now - maghrib_time).total_seconds()
            delta = sihori_next_time - now
            secs = max(0, int(delta.total_seconds()))
            hrs = secs // 3600
            mins = (secs % 3600) // 60
            if hrs >= 4:
                fun_message = f"Eat, sleep, repeat. Sihori in {hrs} hours 😴"
            elif hrs >= 2:
                fun_message = f"Sihori in {hrs}h {mins}m – maybe nap first?"
            elif hrs >= 1:
                fun_message = f"Next stop: Sihori in {hrs}h {mins}m"
            else:
                fun_message = f"Sihori in {mins} min – rise and shine! ☀️"

        progress = int(max(0, min(100, (elapsed / total_window) * 100)))

        delta = next_event_time - now
        total_seconds = max(0, int(delta.total_seconds()))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        countdown = f"{hours:02d}:{minutes:02d}"

        ramadan_progress = int((h_day / 30) * 100)
        ramadan_day_text = f"Day {h_day} / 30"
        qaza_in = next_event_time.strftime("%H:%M")
    else:
        status_line = ""
        next_event_name = ""
        next_event_time = now
        countdown = ""
        progress = 0
        ramadan_progress = 0
        ramadan_day_text = ""
        fasting_duration = ""
        fun_message = ""
        qaza_in = ""

    return {
        "hijri": hijri_str,
        "status_line": status_line,
        "next_name": next_event_name,
        "next_time": next_event_time.strftime("%H:%M") if is_ramadan else "",
        "qaza_in": qaza_in,
        "countdown": countdown,
        "progress": progress,
        "ramadan_progress": ramadan_progress,
        "ramadan_day_text": ramadan_day_text,
        "fasting_duration": fasting_duration,
        "fun_message": fun_message,
    }

# -------------------------------------------------
# Push To TRMNL
# -------------------------------------------------
def push(data):
    r = requests.post(
        WEBHOOK_URL,
        json={"merge_variables": data},
        timeout=10
    )
    print("Status:", r.status_code)
    print("Data:", data)

if __name__ == "__main__":
    push(compute_times())
