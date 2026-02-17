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

def chaotic_message(fasting, percent):
    if fasting:
        if percent < 30:
            return "Belly is calm. Discipline level: monk."
        elif percent < 60:
            return "Hydration memories loading..."
        elif percent < 85:
            return "Fridge is staring at you."
        else:
            return "Final stretch. Kitchen raid denied."
    else:
        if percent < 30:
            return "You may eat. Don't embarrass yourself."
        elif percent < 60:
            return "Strategic snack window active."
        else:
            return "Night slipping away. Sehori approaching."

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
        return midnight + dt.timedelta(minutes=m%1440)

    sihori = to_dt(fajr_min)
    sunrise = to_dt(sunrise_min)
    zawal = to_dt(solar_noon)
    maghrib = to_dt(maghrib_min)

    tomorrow = today + dt.timedelta(days=1)
    doy2 = day_of_year(tomorrow)
    gamma2 = 2*math.pi/365*(doy2-1)
    decl2 = solar_declination(gamma2)
    eot2 = equation_of_time(gamma2)
    solar_noon2 = 720 - 4*LON - eot2 + tz_offset + 1440
    HF2 = hour_angle(lat_rad,decl2,-FAJR_ANGLE)
    fajr2 = solar_noon2 - HF2*4
    sihori_next = midnight + dt.timedelta(minutes=fajr2%1440) + dt.timedelta(days=1)

    # Hijri
    h_day,h_month,h_year = gregorian_to_hijri(today)
    hijri = f"{h_day} {HIJRI_MONTHS[h_month-1]} {h_year} AH"

    fasting = sihori <= now < maghrib

    if fasting:
        percent = int(((now-sihori).total_seconds() /
                      (maghrib-sihori).total_seconds())*100)
        percent = max(0,min(100,percent))
        eat_state = "No Eat"
        current = "Roza"
        time1 = f"Sihori ended at {sihori.strftime('%H:%M')}"
        time2 = f"Maghrib at {maghrib.strftime('%H:%M')}"
    else:
        percent = int(((now-maghrib).total_seconds() /
                      (sihori_next-maghrib).total_seconds())*100)
        percent = max(0,min(100,percent))
        eat_state = "Eat"
        current = "Night"
        time1 = f"Maghrib at {maghrib.strftime('%H:%M')}"
        time2 = f"Sihori ends at {sihori_next.strftime('%H:%M')}"

    message = chaotic_message(fasting,percent)

    return {
        "hijri": hijri,
        "eat_state": eat_state,
        "current": current,
        "time1": time1,
        "time2": time2,
        "percent": percent,
        "message": message
    }

def push(payload):
    requests.post(WEBHOOK_URL,json={"merge_variables":payload})

if __name__ == "__main__":
    push(compute_payload())
