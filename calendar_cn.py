"""春节效应外生变量：春节假期（除夕至正月初六，共 7 天）占当月天数的比例。
原文：SARIMAX 季节项只能处理固定周期，春节公历日期每年变化，因此以“春节假期占当月天数比例”作为外生变量。"""
import calendar
from datetime import date, timedelta

# 农历正月初一公历日期
LUNAR_NEW_YEAR = {
    2008: (2, 7), 2009: (1, 26), 2010: (2, 14), 2011: (2, 3), 2012: (1, 23), 2013: (2, 10),
    2014: (1, 31), 2015: (2, 19), 2016: (2, 8), 2017: (1, 28), 2018: (2, 16), 2019: (2, 5),
    2020: (1, 25), 2021: (2, 12), 2022: (2, 1), 2023: (1, 22), 2024: (2, 10), 2025: (1, 29),
    2026: (2, 17), 2027: (2, 6), 2028: (1, 26), 2029: (2, 13), 2030: (2, 3), 2031: (1, 23),
    2032: (2, 11), 2033: (1, 31), 2034: (2, 19), 2035: (2, 8),
}


def holiday_days(year: int):
    m, d = LUNAR_NEW_YEAR[year]
    ny = date(year, m, d)
    start = ny - timedelta(days=1)  # 除夕
    return [start + timedelta(days=i) for i in range(7)]


def spring_ratio(year: int, month: int) -> float:
    """当月春节假期天数 / 当月天数。"""
    if year not in LUNAR_NEW_YEAR:
        return 0.0
    days = [d for d in holiday_days(year) if d.month == month]
    return len(days) / calendar.monthrange(year, month)[1]


def spring_series(months):
    """months: 'YYYY-MM' 列表 → 比例列表"""
    out = []
    for m in months:
        y, mm = int(m[:4]), int(m[5:7])
        out.append(spring_ratio(y, mm))
    return out
