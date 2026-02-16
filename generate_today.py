import math
import datetime as dt
import os
import requests
from zoneinfo import ZoneInfo

# Frankfurt fixed
LAT = 50.1109
LON = 8.6821
TZ = "Europe/Berlin"

FAJR_ANGLE = 13.23
ISHA_ANGLE = 13.23
SUN_ALT = -1.4
ASR_FACTOR_START = 0.356
ASR_FACTOR_END = 2.299
NISF_START_RATIO = 0.552
NISF_END_RATIO = 0.641333

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

def compute_today():

    tz = ZoneInfo(TZ)
    today = dt.datetime.now(tz).date()
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

    def fmt(minutes):
        minutes %= 1440
        return (midnight + dt.timedelta(minutes=minutes)).strftime("%H:%M")

    return {
        "date": str(today),
        "fajr": fmt(fajr),
        "sunrise": fmt(sunrise),
        "zawal": fmt(solar_noon),
        "zuhr_end": fmt(zuhr_end),
        "asr_end": fmt(asr_end),
        "maghrib": fmt(maghrib),
        "isha": fmt(isha),
    }

def push_to_trmnl(data):
    requests.post(WEBHOOK_URL, json={"merge_variables": data})

if __name__ == "__main__":
    data = compute_today()
    push_to_trmnl(data)
