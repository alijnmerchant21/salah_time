import math
import datetime as dt
import os
import requests
from zoneinfo import ZoneInfo

LAT = 50.1109
LON = 8.6821
TZ = "Europe/Berlin"

FAJR_ANGLE = 13.23
ISHA_ANGLE = 13.23
SUN_ALT = -1.4
ASR_FACTOR_START = 0.356
ASR_FACTOR_END = 2.299

WEBHOOK_URL = os.environ["TRMNL_WEBHOOK"]

def deg2rad(x): return x * math.pi / 180
def rad2deg(x): return x * 180 / math.pi
def day_of_year(date): return int(date.strftime("%j"))

def solar_declination(gamma):
    return (0.006918 - 0.399912 * math.cos(gamma)
            + 0.070257 * math.sin(gamma)
            - 0.006758 * math.cos(2 * gamma)
            + 0.000907 * math.sin(2 * gamma)
            - 0.002697 * math.cos(3 * gamma)
            + 0.00148 * math.sin(3 * gamma))

def equation_of_time(gamma):
    return 229.18 * (0.000075
                     + 0.001868 * math.cos(gamma)
                     - 0.032077 * math.sin(gamma)
                     - 0.014615 * math.cos(2 * gamma)
                     - 0.040849 * math.sin(2 * gamma))

def hour_angle(lat_rad, decl_rad, alt_deg):
    h = deg2rad(alt_deg)
    cosH = (math.sin(h) - math.sin(lat_rad) * math.sin(decl_rad)) / (
        math.cos(lat_rad) * math.cos(decl_rad))
    cosH = max(-1, min(1, cosH))
    return math.degrees(math.acos(cosH))

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
    sunrise = solar_noon - H0 * 4
    maghrib = solar_noon + H0 * 4

    HF = hour_angle(lat_rad, decl, -FAJR_ANGLE)
    HI = hour_angle(lat_rad, decl, -ISHA_ANGLE)

    fajr = solar_noon - HF * 4
    isha = solar_noon + HI * 4

    noon_shadow = math.tan(abs(lat_rad - decl))
    alt_asr_start = rad2deg(math.atan(1 / (ASR_FACTOR_START + noon_shadow)))
    alt_asr_end = rad2deg(math.atan(1 / (ASR_FACTOR_END + noon_shadow)))

    HA_start = hour_angle(lat_rad, decl, alt_asr_start)
    HA_end = hour_angle(lat_rad, decl, alt_asr_end)

    zuhr_end = solar_noon + HA_start * 4
    asr_end = solar_noon + HA_end * 4

    def to_dt(minutes):
        return midnight + dt.timedelta(minutes=minutes % 1440)

    prayers = [
        ("Sihori", to_dt(fajr)),
        ("Sunrise", to_dt(sunrise)),
        ("Zuhr End", to_dt(zuhr_end)),
        ("Asr End", to_dt(asr_end)),
        ("Maghrib", to_dt(maghrib)),
        ("Isha", to_dt(isha)),
    ]

    # find next 2
    upcoming = [p for p in prayers if p[1] > now]

    if len(upcoming) < 2:
        # include tomorrow's fajr if needed
        tomorrow = midnight + dt.timedelta(days=1)
        upcoming.append(("Sihori", tomorrow + dt.timedelta(minutes=fajr)))

    next_two = upcoming[:2]

    return {
        "date": str(today),
        "next1_name": next_two[0][0],
        "next1_time": next_two[0][1].strftime("%H:%M"),
        "next2_name": next_two[1][0],
        "next2_time": next_two[1][1].strftime("%H:%M"),
    }

def push(data):
    requests.post(WEBHOOK_URL, json={"merge_variables": data})

if __name__ == "__main__":
    push(compute_times())
