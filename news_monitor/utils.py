# utils.py
import datetime
import akshare as ak

seen_ids = set()

def remove_duplicates(items):
    global seen_ids
    new_items = [i for i in items if i['id'] not in seen_ids]
    for i in new_items:
        seen_ids.add(i['id'])
    if len(seen_ids) > 1000:
        seen_ids = set(list(seen_ids)[-500:])
    return new_items


def get_segment(dt: datetime.datetime):
    t = dt.time()
    if t >= datetime.time(15, 0) or t < datetime.time(9, 15):
        return 'overnight'
    elif datetime.time(9, 15) <= t < datetime.time(11, 30):
        return 'morning'
    elif datetime.time(11, 30) <= t < datetime.time(13, 0):
        return 'noon'
    else:
        return 'afternoon'


def is_trading_day(date: datetime.date):
    calendar = ak.tool_trade_date_hist_sina()
    return date in list(calendar['trade_date'])


def get_trading_date(dt: datetime.datetime):
    """根据15点切换逻辑确定交易日期
    15点前归属于当天，15点后归属于下一天
    """
    # 如果时间在15点之前，归属于当天
    if dt.time() < datetime.time(15, 0):
        return dt.date()
    else:
        # 如果时间在15点及之后，归属于下一天
        return (dt + datetime.timedelta(days=1)).date()


def get_table_name(dt: datetime.datetime):
    """根据15点切换逻辑确定表名"""
    base_date = get_trading_date(dt)
    trade_flag = "trade" if is_trading_day(base_date) else "nontrade"
    return f"telegraph_{base_date.year}_{base_date.month:02d}_{base_date.day:02d}_{trade_flag}"
