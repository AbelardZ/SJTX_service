# -*- coding: utf-8 -*-
# 六爻金融预测系统 - 排盘逻辑模块

import sxtwl
import unicodedata
import io
from datetime import datetime
from data import gua64, cangyao64

class liuyao:
    #六爻起卦与排盘主类。

    #职责：
    #- 接收时间与六爻输入，计算年/月/日/时干支与旬空。
    #- 识别动爻并生成主卦/变卦；构造固定列宽的文本排盘。

    #主要属性：
    #- ygua: 原始六爻（含 1/2/3/4，3=老阳，4=老阴），自下而上。
    #- gua: 主卦（将 3→1、4→2 后，仅含 1/2）。
    #- dgua: 动爻记录 [位置, 变后值('1' 或 '2'), ...]，位置 0~5 自下而上。
    #- guastr/bguastr: 主卦/变卦键（6 位字符串）。
    #- _paipan_time/_paipan_monthzhi/_paipan_monthgz/_paipan_day/_paipan_xunkong: 打印辅助缓存。

    def __init__(self):
        self.gua64 = gua64
        self.cangyao64 = cangyao64
        self.liushen={'甲':0,'乙':0,'丙':1,'丁':1,'戊':2,'己':3,'庚':4,'辛':4,'壬':5,'癸':5}
        self.liushencn=['青龙','朱雀','勾陈','腾蛇','白虎','玄武']
        self.tiangan={'甲':1,'乙':2,'丙':3,'丁':4,'戊':5,'己':6,'庚':7,'辛':8,'壬':9,'癸':10}
        self.dizhi={'子':1,'丑':2,'寅':3,'卯':4,'辰':5,'巳':6,'午':7,'未':8,'申':9,'酉':10,'戌':11,'亥':12}
        self.kongwangzu=['子','丑','寅','卯','辰','巳','午','未','申','酉','戌','亥']
        self.dgua = []
        self.ygua = []
        self.gua = []
        self.guastr = ''
        self.bguastr = ''
        self.ritian = ''
        self.ridi = ''
        self.subject = ''
        self._paipan_time = None
        self._paipan_monthzhi = ''
        self._paipan_monthgz = ''
        self._paipan_day = ''
        self._paipan_xunkong = ''
        self._col_widths = {
            'liushen': 8,
            'cangyao': 12,
            'zhuyao_graph': 8,
            'zhuyao_name': 10,
            'shiying': 6,
            'dong': 8,
            'bianyao_name': 10,
            'bian_graph': 10,
            'zhugua': 30,
        }

    @staticmethod
    def _disp_width(s: str) -> int:
        w = 0
        for ch in str(s):
            if unicodedata.east_asian_width(ch) in ('F', 'W'):
                w += 2
            else:
                w += 1
        return w

    def _pad(self, s: str, width: int, align: str = 'left') -> str:
        s = '' if s is None else str(s)
        cur = self._disp_width(s)
        if cur >= width:
            return s
        pad = width - cur
        if align == 'right':
            return ' ' * pad + s
        if align == 'center':
            left = pad // 2
            right = pad - left
            return ' ' * left + s + ' ' * right
        return s + ' ' * pad

    def _truncate_disp(self, s: str, width: int) -> str:
        s = '' if s is None else str(s)
        out = ''
        cur = 0
        for ch in s:
            w = 2 if unicodedata.east_asian_width(ch) in ('F', 'W') else 1
            if cur + w > width:
                break
            out += ch
            cur += w
        return out

    def date(self, year=None, month=None, day=None, hour=None, minute=None, 
             gz_year=None, gz_month=None, gz_day=None, gz_hour=None):

        #计算指定公历时间的四柱与旬空，并缓存打印字段。
        #若未提供日期则取当前日期；时柱按 0-23 小时计算。
        #若提供了干支（gz_year/gz_month/gz_day/gz_hour），则覆盖自动计算的结果。

        if year is None or month is None or day is None:
            today = datetime.now()
            year, month, day = today.year, today.month, today.day
            hour = today.hour if hour is None else hour
            minute = today.minute if minute is None else minute
        try:
            self._paipan_time = datetime(year, month, day, hour or 0, minute or 0)
        except ValueError:
            raise ValueError("无效的日期")
        day_obj = sxtwl.fromSolar(year, month, day)
        tiangan_list = ['甲','乙','丙','丁','戊','己','庚','辛','壬','癸']
        dizhi_list = ['子','丑','寅','卯','辰','巳','午','未','申','酉','戌','亥']
        year_gz = day_obj.getYearGZ(True)
        year_ganzhi = tiangan_list[year_gz.tg] + dizhi_list[year_gz.dz]
        month_gz = day_obj.getMonthGZ()
        month_ganzhi = tiangan_list[month_gz.tg] + dizhi_list[month_gz.dz]
        day_gz = day_obj.getDayGZ()
        day_ganzhi = tiangan_list[day_gz.tg] + dizhi_list[day_gz.dz]
        safe_hour = hour if hour is not None else 0
        hour_gz = day_obj.getHourGZ(safe_hour)
        hour_ganzhi = tiangan_list[hour_gz.tg] + dizhi_list[hour_gz.dz]
        
        # Override if provided
        if gz_year: year_ganzhi = gz_year
        if gz_month: month_ganzhi = gz_month
        if gz_day: day_ganzhi = gz_day
        if gz_hour: hour_ganzhi = gz_hour

        self.wanzu = [year_ganzhi, month_ganzhi, day_ganzhi, hour_ganzhi]
        ri = self.wanzu[2]
        self.ritian = ri[0]
        self.ridi = ri[1]
        self.kongwang()
        self._paipan_monthzhi = month_ganzhi[1]
        self._paipan_monthgz = month_ganzhi
        self._paipan_day = day_ganzhi

    def kongwang(self):
      
        #计算日空亡：
        #规则：日支序号 - 日干序号 = 差值（若 <0 则 +10），
        #空亡为 kongwangzu[差值-2] 与 kongwangzu[差值-1]。
        
        cha = self.dizhi[self.ridi] - self.tiangan[self.ritian]
        if cha < 0:
            cha += 10
        kw1 = self.kongwangzu[cha-2]
        kw2 = self.kongwangzu[cha-1]
        self._paipan_xunkong = f"{kw1}{kw2}"

    def paipan(self):
        #识别动爻并生成主卦键。老阳(3)→1；老阴(4)→2。
        self.gua = self.ygua.copy()
        self.dgua = []
        for i in range(6):
            if self.ygua[i] == '3':
                self.gua[i] = '1'
                self.dgua.append(i)
                self.dgua.append('1')
            elif self.ygua[i] == '4':
                self.gua[i] = '2'
                self.dgua.append(i)
                self.dgua.append('2')
        self.guastr = ''.join(map(str, self.gua))

    def get_paipan_string(self):
        #生成完整的排盘文本（与 Console 版格式一致）。
        output = io.StringIO()
        t = self._paipan_time
        output.write(f"**占卜时间：{t.year}年{t.month:02d}月{t.day:02d}日 {t.hour:02d}:{t.minute:02d}**\n\n****\n")
        output.write(f"{' ' * 17}{self._paipan_monthzhi}月{' ' * 28}{self._paipan_day}(旬空：{self._paipan_xunkong})\n\n")
        main_gua = self.gua64[self.guastr]
        main_gua_name = f"{main_gua[10].replace('宫','')}-{main_gua[11]}"
        hc = f"({main_gua[8]})" if main_gua[8] else ""
        bbgua = list(map(int, self.gua))
        for i in range(0, len(self.dgua), 2):
            idx = self.dgua[i]
            if self.dgua[i+1] == '1':
                bbgua[idx] = 2
            else:
                bbgua[idx] = 1
        self.bguastr = ''.join(map(str, bbgua))
        bian_gua = self.gua64[self.bguastr]
        bian_gua_name = f"{bian_gua[10].replace('宫','')}-{bian_gua[11]}"
        hc2 = f"({bian_gua[8]})" if bian_gua[8] else ""
        main_full = f"{main_gua_name}{hc}"
        main_fixed = self._truncate_disp(main_full, self._col_widths['zhugua'])
        main_padded = self._pad(main_fixed, self._col_widths['zhugua'])
        bian_full = f"{bian_gua_name}{hc2}"
        output.write(' ' * 16 + main_padded + ' ' + bian_full + '\n\n')
        syw = main_gua[6]
        yyw = main_gua[7]
        liushen_start = self.liushen[self.ritian]
        liushen_list = [(liushen_start + i) % 6 for i in range(6)]
        dongyao = {}
        for i in range(0, len(self.dgua), 2):
            # 与控制台一致：变后为 '1'（阳） => 原为老阴(4) 显示 〇→；
            # 变后为 '2'（阴） => 原为老阳(3) 显示 ×→。
            dongyao[self.dgua[i]] = '〇→' if self.dgua[i+1] == '1' else '×→'
        header = (
            self._pad('六神', self._col_widths['liushen']) +
            self._pad('藏爻', self._col_widths['cangyao']) +
            self._pad('主卦', self._col_widths['zhuyao_graph']) +
            self._pad('', self._col_widths['zhuyao_name']) +
            self._pad('', self._col_widths['shiying']) +
            self._pad('', self._col_widths['dong']) +
            self._pad('变卦', self._col_widths['bianyao_name']) +
            self._pad('', self._col_widths['bian_graph'])
        )
        output.write(header + '\n\n')
        cangyao_list = self.cangyao64.get(self.guastr, ['','','','','',''])
        for i in range(5, -1, -1):
            # 自上而下打印时，六神与当前行同索引 i 对齐，避免 5-i 造成错位
            liushen = self.liushencn[liushen_list[i]]
            cangyao = cangyao_list[i] if i < len(cangyao_list) else ''
            zhuyao = '▅▅▅▅▅' if self.gua[i] == '1' else '▅▅  ▅▅'
            bianyao = '▅▅▅▅▅' if str(bbgua[i]) == '1' else '▅▅  ▅▅'
            zhuyao_name = main_gua[i]
            bianyao_name = bian_gua[i]
            # 动爻索引同样直接使用 i，确保标记落在正确行
            dong = dongyao.get(i, '')
            shi_ying = ('世' if (i + 1) == syw else '') + ('应' if (i + 1) == yyw else '')
            line = (
                self._pad(liushen, self._col_widths['liushen']) +
                self._pad(cangyao, self._col_widths['cangyao']) +
                self._pad(zhuyao, self._col_widths['zhuyao_graph']) +
                self._pad(zhuyao_name, self._col_widths['zhuyao_name']) +
                self._pad(shi_ying, self._col_widths['shiying']) +
                self._pad(dong, self._col_widths['dong']) +
                self._pad(bianyao_name, self._col_widths['bianyao_name']) +
                self._pad(bianyao, self._col_widths['bian_graph'])
            )
            output.write(line + '\n\n')
        output.write("****\n")
        return output.getvalue()

    def get_paipan_data(self):
        """
        返回结构化的排盘数据，用于前端渲染
        """
        t = self._paipan_time
        
        # 1. 基础信息
        main_gua = self.gua64[self.guastr]
        main_gua_name = f"{main_gua[10].replace('宫','')}-{main_gua[11]}"
        hc = f"({main_gua[8]})" if main_gua[8] else ""
        
        bbgua = list(map(int, self.gua))
        for i in range(0, len(self.dgua), 2):
            idx = self.dgua[i]
            if self.dgua[i+1] == '1':
                bbgua[idx] = 2
            else:
                bbgua[idx] = 1
        self.bguastr = ''.join(map(str, bbgua))
        bian_gua = self.gua64[self.bguastr]
        bian_gua_name = f"{bian_gua[10].replace('宫','')}-{bian_gua[11]}"
        hc2 = f"({bian_gua[8]})" if bian_gua[8] else ""

        syw = main_gua[6]
        yyw = main_gua[7]
        liushen_start = self.liushen[self.ritian]
        liushen_list = [(liushen_start + i) % 6 for i in range(6)]
        
        dongyao = {}
        for i in range(0, len(self.dgua), 2):
            dongyao[self.dgua[i]] = 'O' if self.dgua[i+1] == '1' else 'X'

        cangyao_list = self.cangyao64.get(self.guastr, ['','','','','',''])
        
        lines = []
        # 自上而下 (5 -> 0)
        for i in range(5, -1, -1):
            line_data = {
                'index': i + 1,
                'liushen': self.liushencn[liushen_list[i]],
                'cangyao': cangyao_list[i] if i < len(cangyao_list) else '',
                'zhuyao_type': 'yang' if self.gua[i] == '1' else 'yin',
                'zhuyao_name': main_gua[i],
                'shi_ying': ('世' if (i + 1) == syw else '') + ('应' if (i + 1) == yyw else ''),
                'dong': dongyao.get(i, ''),
                'bianyao_type': 'yang' if str(bbgua[i]) == '1' else 'yin',
                'bianyao_name': bian_gua[i]
            }
            lines.append(line_data)

        return {
            'date_str': f"{t.year}年{t.month:02d}月{t.day:02d}日 {t.hour:02d}:{t.minute:02d}",
            'ganzhi_month': self._paipan_monthzhi,
            'ganzhi_day': self._paipan_day,
            'xunkong': self._paipan_xunkong,
            'main_gua_name': main_gua_name,
            'main_gua_detail': hc,
            'bian_gua_name': bian_gua_name,
            'bian_gua_detail': hc2,
            'lines': lines
        }

    def save_to_file(self, filepath):
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(self.get_paipan_string())

def create_wapp(subject, ygua, year, month, day, hour, minute, 
                gz_year=None, gz_month=None, gz_day=None, gz_hour=None):
    """
    创建并返回已初始化的 liuyao 对象（但不保存文件）。
    返回值：wapp
    """
    wapp = liuyao()
    wapp.subject = subject
    wapp.ygua = ygua
    wapp.date(year, month, day, hour, minute, gz_year, gz_month, gz_day, gz_hour)
    wapp.paipan()
    return wapp

def perform_divination(subject, ygua, year, month, day, hour, minute,
                       gz_year=None, gz_month=None, gz_day=None, gz_hour=None):
    """
    执行六爻排盘，返回 (wapp, output_string)
    """
    wapp = create_wapp(subject, ygua, year, month, day, hour, minute, gz_year, gz_month, gz_day, gz_hour)
    return wapp, wapp.get_paipan_string()

def save_to_file(wapp, filepath):
    """
    保存排盘结果到文件
    :param wapp: liuyao对象
    :param filepath: 文件路径
    """
    wapp.save_to_file(filepath)
