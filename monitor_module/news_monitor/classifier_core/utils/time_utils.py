from datetime import datetime, timedelta

def get_current_time():
    return datetime.now()

def format_time(dt, format_string="%Y-%m-%d %H:%M:%S"):
    return dt.strftime(format_string)

def time_difference(start_time, end_time):
    return end_time - start_time

def add_days_to_date(date, days):
    return date + timedelta(days=days)

def subtract_days_from_date(date, days):
    return date - timedelta(days=days)