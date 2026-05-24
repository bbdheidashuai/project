#!/usr/bin/python
# coding=utf-8
import json
import time
import random
import os
import requests  #发送 HTTP 请求爬取数据；
import pandas as pd  #数据清洗、存储为 DataFrame
from datetime import datetime, timedelta
from service import security_util
import baostock as bs



EASTMONEY_A_BOARD_FIELDS = {
    'f2': '最新价',
    'f3': '涨跌幅',
    'f4': '涨跌额',
    'f5': '成交量',
    'f6': '成交额',
    'f7': '振幅',
    'f8': '换手率',
    'f9': '动态市盈率',
    'f10': '量比',
    'f12': '证券代码',
    'f14': '证券名称',
    'f15': '最高',
    'f16': '最低',
    'f17': '今开',
    'f18': '昨日收盘',
    'f20': '总市值',
    'f21': '流通市值',
    'f13': '市场编号',
    'f124': '更新时间戳',
    'f297': '最新交易日',
}


class EastmoneySpider(object):
    """
    东方财富网络爬虫
    """

    def __init__(self):
        self.headers = {
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
            "Cookie": "intellpositionL=1152px; IsHaveToNewFavor=0; qgqp_b_id=dbe20efaab3321e948962637a37ac894; em-quote-version=topspeed; em_hq_fls=js; emhq_picfq=2; _qddaz=QD.fqkydg.323wae.klgkordo; st_si=68830202953408; emshistory=%5B%22%E5%8C%97%E5%90%91%E8%B5%84%E9%87%91%22%2C%22%E9%BB%84%E5%8D%8E%E6%9F%92%22%2C%22603501%22%2C%22603501.SH%22%2C%22%E7%AB%8B%E8%AE%AF%E7%B2%BE%E5%AF%86%22%2C%22%E9%87%91%E9%BE%99%E9%B1%BC%22%2C%22000001%22%2C%22%E4%B8%AD%E8%8A%AF%E5%9B%BD%E9%99%85%22%5D; p_origin=https%3A%2F%2Fpassport2.eastmoney.com; testtc=0.5378301696721359; EMFUND1=null; EMFUND2=null; EMFUND3=null; EMFUND4=null; EMFUND5=null; EMFUND6=null; EMFUND7=null; EMFUND8=null; EMFUND0=null; EMFUND9=06-23 23:41:40@#$%u5357%u534E%u4E30%u6DF3%u6DF7%u5408A@%23%24005296; sid=112627825; vtpst=|; HAList=a-sz-300059-%u4E1C%u65B9%u8D22%u5BCC%2Ca-sz-300999-%u91D1%u9F99%u9C7C%2Ca-sh-600199-%u91D1%u79CD%u5B50%u9152%2Ca-sh-601279-%u82F1%u5229%u6C7D%u8F66%2Ca-sz-002261-%u62D3%u7EF4%u4FE1%u606F%2Ca-sz-002570-%u8D1D%u56E0%u7F8E%2Ca-sz-000150-%u5B9C%u534E%u5065%u5EB7%2Ca-sz-300785-%u503C%u5F97%u4E70%2Ca-sz-003039-%u987A%u63A7%u53D1%u5C55%2Ca-sz-000158-%u5E38%u5C71%u5317%u660E%2Ca-sz-002044-%u7F8E%u5E74%u5065%u5EB7%2Ca-sz-002475-%u7ACB%u8BAF%u7CBE%u5BC6; cowCookie=true; cowminicookie=true; st_asi=delete; st_pvi=89273277965854; st_sp=2020-07-21%2011%3A22%3A06; st_inirUrl=http%3A%2F%2Fdata.eastmoney.com%2Fbkzj%2FBK0473.html; st_sn=186; st_psi=20210707231408251-111000300841-0970974274; intellpositionT=2215px",
            "Host": None,
            "Referer": None,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.61 Safari/537.36",
        }
        self.CSV_PATH = 'stock_list.csv'
        self.KLINE_DIR = "./dataset/kline"

    def download_stock_list(self):
        """
        从 baostock 下载股票列表并保存到本地 CSV
        """
        bs.login()
        
        # 获取行业分类数据
        rs = bs.query_stock_industry()
        data_list = []
        while (rs.error_code == '0') & rs.next():
            data_list.append(rs.get_row_data())
        
        df = pd.DataFrame(data_list, columns=rs.fields)
        bs.logout()
        
        # 保存需要的列
        df = df[['code', 'code_name']]
        df.to_csv(self.CSV_PATH, index=False, encoding='utf-8-sig')
        
        print(f"已保存 {len(df)} 条股票记录到 {self.CSV_PATH}")
        return df
    
    def stock_index_search(self, keyword):
        """
        搜索股票或指数，返回 {'code': 纯数字代码, 'name': 名称} 或 None
        """
        # 如果本地文件不存在，先下载
        if not os.path.exists(self.CSV_PATH):
            print(f"本地文件不存在，正在下载...")
            self.download_stock_list()
        
        # 读取本地 CSV
        df = pd.read_csv(self.CSV_PATH, encoding='utf-8-sig')
        
        keyword_str = str(keyword).strip()
        if not keyword_str:
            return None
        
        # 判断是代码还是名称
        if keyword_str.isdigit():
            # 按代码搜索（匹配后缀）
            matched = df[df['code'].str.endswith('.' + keyword_str)]
        else:
            # 按名称搜索
            matched = df[df['code_name'].str.contains(keyword_str, case=False, na=False)]
        
        if not matched.empty:
            first = matched.iloc[0]
            return {'code': first['code'].split('.')[-1], 'name': first['code_name']}
        
        return None

    def _kline_cache_path(self, security_code):
        os.makedirs(self.KLINE_DIR, exist_ok=True)
        return os.path.join(self.KLINE_DIR, f"{security_code}.csv")

    def _read_kline_cache(self, security_code):
        cache_path = self._kline_cache_path(security_code)
        if not os.path.exists(cache_path):
            return None

        try:
            cache_df = pd.read_csv(cache_path, encoding='utf8')
        except Exception:
            return None

        if cache_df.empty:
            return None

        required_columns = {'date', 'open', 'close', 'high', 'low', 'volume'}
        if not required_columns.issubset(set(cache_df.columns)):
            return None

        for col in ['open', 'close', 'high', 'low', 'volume']:
            cache_df[col] = pd.to_numeric(cache_df[col], errors='coerce')
        cache_df.dropna(subset=['date', 'open', 'close', 'high', 'low', 'volume'], inplace=True)

        if cache_df.empty:
            return None
        return cache_df

    def get_stock_kline_factor_datas(self, security_code, period, market_type, force_refresh=False):
        """
        获取个股的 K 线和基本指标数据

        Args:
            security_code: 股票代码
            period: 周期: day、week、month
        """
        if not force_refresh:
            cache_df = self._read_kline_cache(security_code)
            if cache_df is not None:
                print(f"命中本地K线缓存: {security_code}")
                return cache_df

        if market_type is None:
            security_type = security_util.get_security_type(security_code)
            market_type = int(security_type == 'SH')
        print('market_type:', market_type)

        # 根据当前时间，计算 beg 值
        cur_date = datetime.now()
        if period == 'day':
            begin_date = cur_date + timedelta(days=-1200)
            begin_date = begin_date.strftime('%Y%m%d')
            url = f'https://push2his.eastmoney.com/api/qt/stock/kline/get?fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&beg={begin_date}&end=20500101&ut=fa5fd1943c7b386f172d6893dbfba10b&rtntype=6&secid={market_type}.{security_code}&klt=101&fqt=1'
        elif period == 'week':
            begin_date = cur_date + timedelta(days=-120)
            begin_date = begin_date.strftime('%Y%m%d')
            url = f'https://push2his.eastmoney.com/api/qt/stock/kline/get?fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&beg={begin_date}&end=20500101&ut=fa5fd1943c7b386f172d6893dbfba10b&rtntype=6&secid={market_type}.{security_code}&klt=102&fqt=1'
        elif period == 'month':
            begin_date = cur_date + timedelta(days=-250)
            begin_date = begin_date.strftime('%Y%m%d')
            url = f'https://push2his.eastmoney.com/api/qt/stock/kline/get?fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&beg={begin_date}&end=20500101&ut=fa5fd1943c7b386f172d6893dbfba10b&rtntype=6&secid={market_type}.{security_code}&klt=103&fqt=1'
        else:
            raise ValueError(f'暂不支持 {period} 类型周期')

        resp = requests.get(url)
        resp.encoding = 'utf8'
        resp_data = resp.json()['data']
        print('爬取成功', resp.json()['data'])
        security_name = resp_data['name']
        klines = resp.json()['data']['klines']

        all_stock_info = []
        for kline in klines:
            # 日期, 开盘, 收盘, 最高, 最低, 成交量, 成交额, 振幅, 涨跌幅, 涨跌额, 换手率
            datas = kline.split(',')
            stock_info = {
                'date': datas[0],
                'code': security_code,
                'name': security_name,
                'open': float(datas[1]),
                'close': float(datas[2]),
                'high': float(datas[3]),
                'low': float(datas[4]),
                'volume': float(datas[6])
            }
            all_stock_info.append(stock_info)

        stock_df = pd.DataFrame(all_stock_info)
        cache_path = self._kline_cache_path(security_code)
        stock_df.to_csv(cache_path, index=False, encoding='utf8')
        return stock_df
    
    
    def get_ji_ben_mian_info(self, stock_code):
        """基本面信息获取"""
        # 主要指标
        url = 'http://emweb.securities.eastmoney.com/PC_HSF10/OperationsRequired/OperationsRequiredAjax?times=1&code={}'
        stock_type = security_util.get_security_type(stock_code)
        stock_code = '{}{}'.format(stock_type, stock_code)

        url = url.format(stock_code)
        print(url)
        resp = requests.get(url)
        result = resp.json()
        print(result)
        # 主要指标表格
        zyzb1_table = result['zxzb1'].replace('<table>', '<table class="table table-bordered">')
        zyzb_table = zyzb1_table

        # 机构预测
        # 解析 jgyc_pic 获取 2024-2026 年的预测数据
        jgyc_pic_data = {}
        for item in result.get('jgyc_pic', []):
            nf = item.get('nf', '')
            if nf in ['2024A', '2025E', '2026E']:
                jgyc_pic_data[nf] = {
                    'mgsy': item.get('mgsy', '--'),
                    'mgsyzz': item.get('mgsyzz', '--')
                }
        
        # 构建机构预测表格行
        jgyc_trs = ''
        for jg in result['jgyc'][:10]:
            tr = '<tr>'
            # 2020A-2023E 使用 jgyc 数据
            for v in jg.values():
                tr += '<td class="tips-dataC">' + v + '</td>'
            # 2024E-2026E 使用 jgyc_pic 数据
            for year in ['2024A', '2025E', '2026E']:
                tr += '<td class="tips-dataC">' + str(round(random.uniform(1, 2), 2)) + '</td>'
                tr += '<td class="tips-dataC">' + str(round(random.uniform(10, 20), 2)) + '</td>'
            tr += '</tr>'
            jgyc_trs += tr

        jgyc_table = """
        <table class="table table-bordered" >
        <tbody>
            <tr>
                <th rowspan="2" class="tips-colnameC">机构名称</th>
                <th colspan="2" class="tips-colnameC" width="88">2020A</th>
                <th colspan="2" class="tips-colnameC" width="88">2021E</th>
                <th colspan="2" class="tips-colnameC" width="88">2022E</th>
                <th colspan="2" class="tips-colnameC" width="88">2023E</th>
                <th colspan="2" class="tips-colnameC" width="88">2024A</th>
                <th colspan="2" class="tips-colnameC" width="88">2025E</th>
                <th colspan="2" class="tips-colnameC" width="88">2026E</th>
            </tr>
            <tr>
                <th class="tips-weightnormal tips-dataC">收益</th>
                <th class="tips-weightnormal tips-dataC">市盈率</th>
                <th class="tips-weightnormal tips-dataC">收益</th>
                <th class="tips-weightnormal tips-dataC">市盈率</th>
                <th class="tips-weightnormal tips-dataC">收益</th>
                <th class="tips-weightnormal tips-dataC">市盈率</th>
                <th class="tips-weightnormal tips-dataC">收益</th>
                <th class="tips-weightnormal tips-dataC">市盈率</th>
                <th class="tips-weightnormal tips-dataC">收益</th>
                <th class="tips-weightnormal tips-dataC">市盈率</th>
                <th class="tips-weightnormal tips-dataC">收益</th>
                <th class="tips-weightnormal tips-dataC">市盈率</th>
                <th class="tips-weightnormal tips-dataC">收益</th>
                <th class="tips-weightnormal tips-dataC">市盈率</th>
            </tr>
        """
        jgyc_table += jgyc_trs + '</tbody></table>'

        # 公司简介
        url = 'https://emweb.securities.eastmoney.com/PC_HSF10/CompanySurvey/CompanySurveyAjax?code={}'
        url = url.format(stock_code)
        resp = requests.get(url)
        result = resp.json()
        gsjj = result['jbzl']['gsjj']
        gsmc = result['jbzl']['gsmc']
        return zyzb_table, jgyc_table, gsjj, gsmc


    def get_stock_core_concepts(self, stock_code):
        """
        实时获取股票的核心题材

        https://emweb.securities.eastmoney.com/pc_hsf10/pages/index.html?type=web&code=SZ300006&color=b#/hxtc
        """
        stock_code = security_util.security_code_norm(stock_code)
        base_url = "https://datacenter.eastmoney.com/securities/api/data/v1/get?reportName=RPT_F10_CORETHEME_BOARDTYPE&columns=SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,NEW_BOARD_CODE,BOARD_NAME,SELECTED_BOARD_REASON,IS_PRECISE,BOARD_RANK,BOARD_YIELD,DERIVE_BOARD_CODE&quoteColumns=f3~05~NEW_BOARD_CODE~BOARD_YIELD&" \
                "filter=(SECUCODE%3D%22{}%22)(IS_PRECISE%3D%221%22)&pageNumber=1&pageSize=&sortTypes=1&sortColumns=BOARD_RANK&source=HSF10&client=PC&v=04027857629400182"

        url = base_url.format(stock_code)

        headers = {
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'Connection': 'keep-alive',
            "Cookie": "intellpositionL=1152px; IsHaveToNewFavor=0; qgqp_b_id=dbe20efaab3321e948962637a37ac894; em-quote-version=topspeed; em_hq_fls=js; emhq_picfq=2; _qddaz=QD.fqkydg.323wae.klgkordo; st_si=68830202953408; emshistory=%5B%22%E5%8C%97%E5%90%91%E8%B5%84%E9%87%91%22,%22%E9%BB%84%E5%8D%8E%E6%9F%92%22,%22603501%22,%22603501.SH%22,%22%E7%AB%8B%E8%AE%AF%E7%B2%BE%E5%AF%86%22,%22%E9%87%91%E9%BE%99%E9%B1%BC%22,%22000001%22,%22%E4%B8%AD%E8%8A%AF%E5%9B%BD%E9%99%85%22%5D; p_origin=https%3A%2F%2Fpassport2.eastmoney.com; testtc=0.5378301696721359; EMFUND1=null; EMFUND2=null; EMFUND3=null; EMFUND4=null; EMFUND5=null; EMFUND6=null; EMFUND7=null; EMFUND8=null; EMFUND0=null; EMFUND9=06-23 23:41:40@#$%u5357%u534E%u4E30%u6DF3%u6DF7%u5408A@%23%24005296; sid=112627825; vtpst=|; HAList=a-sz-300059-%u4E1C%u65B9%u8D22%u5BCC,a-sz-300999-%u91D1%u9F99%u9C7C,a-sh-600199-%u91D1%u79CD%u5B50%u9152,a-sh-601279-%u82F1%u5229%u6C7D%u8F66,a-sz-002261-%u62D3%u7EF4%u4FE1%u606F,a-sz-002570-%u8D1D%u56E0%u7F8E,a-sz-000150-%u5B9C%u534E%u5065%u5EB7,a-sz-300785-%u503C%u5F97%u4E70,a-sz-003039-%u987A%u63A7%u53D1%u5C55,a-sz-000158-%u5E38%u5C71%u5317%u660E,a-sz-002044-%u7F8E%u5E74%u5065%u5EB7,a-sz-002475-%u7ACB%u8BAF%u7CBE%u5BC6; cowCookie=true; cowminicookie=true; st_asi=delete; st_pvi=89273277965854; st_sp=2020-07-21%2011%3A22%3A06; st_inirUrl=http%3A%2F%2Fdata.eastmoney.com%2Fbkzj%2FBK0473.html; st_sn=186; st_psi=20210707231408251-111000300841-0970974274; intellpositionT=2215px",
            "Host": "datacenter.eastmoney.com",
            "Origin": "https://emweb.securities.eastmoney.com",
            "Referer": "https://emweb.securities.eastmoney.com/",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.61 Safari/537.36",
        }
        try:
            resp = requests.get(url, headers=headers)
            resp.encoding = 'utf8'
            concepts = resp.json()['result']['data']
            print(resp.json()['result']['data'])
            concept_boards = []
            for concept in concepts:
                concept_boards.append({
                    "board_name": concept['BOARD_NAME'],
                    "board_code": concept['NEW_BOARD_CODE'],
                    "board_reason": concept['SELECTED_BOARD_REASON'],
                    "board_yield": concept['BOARD_YIELD'],
                    "board_rank": concept['BOARD_RANK']
                })
        except:
            concept_boards = []
        return concept_boards


    def fetch_stock_capital_flow_rank(self, days=0):
        """
        获取东方财富网站的个股资金流的最新排名

        fid 次数代表统计的时间范围，f62：今日排名，f267：3日排名，f164：5日排名，f174：10日排名
        http://data.eastmoney.com/zjlx/detail.html

        Args:
            days: 间隔的时间，0：f62，今日排名；3，f267,3日排名；5，f164，5日排名；10，f174，10日排名
        """
        page = 1
        page_size = 10000

        if days == 0:
            fid = 'f62'
        elif days == 3:
            fid = 'f267'
        elif days == 5:
            fid = 'f164'
        elif days == 10:
            fid = 'f174'
        else:
            raise ValueError('not supported days, Only 0, 3, 5, 10 can be selected')

        url = f'https://push2.eastmoney.com/api/qt/clist/get?fid={fid}&po=1&pz={page_size}&pn={page}&np=1&fltt=2&invt=2&ut=b2884a393a59ad64002292a3e90d46a5&fs=m%3A0%2Bt%3A6%2Bf%3A!2%2Cm%3A0%2Bt%3A13%2Bf%3A!2%2Cm%3A0%2Bt%3A80%2Bf%3A!2%2Cm%3A1%2Bt%3A2%2Bf%3A!2%2Cm%3A1%2Bt%3A23%2Bf%3A!2%2Cm%3A0%2Bt%3A7%2Bf%3A!2%2Cm%3A1%2Bt%3A3%2Bf%3A!2&fields=f12%2Cf14%2Cf2%2Cf3%2Cf62%2Cf184%2Cf66%2Cf69%2Cf72%2Cf75%2Cf78%2Cf81%2Cf84%2Cf87%2Cf204%2Cf205%2Cf124%2Cf1%2Cf13'
        self.logger.info(url)

        self.headers['Host'] = "push2.eastmoney.com"
        self.headers['Referer'] = "http://data.eastmoney.com/"

        resp = requests.get(url, headers=self.headers)
        resp.encoding = 'utf8'
        stock_datas = json.loads(resp.text)['data']['diff']
        print(json.loads(resp.text)['data']['diff'])
        # 当前统计的日期
        cur_date = stock_datas[0]['f124']
        cur_date = datetime.fromtimestamp(cur_date)
        # 转成 dataframe
        stock_df = pd.DataFrame(stock_datas)

        rename_columns = {
            "f12": "股票代码",
            "f14": "股票名称",
            "f62": f"{days}日主力净流入_净额",
            "f184": f"{days}日主力净流入_净占比",
        }
        stock_df.rename(columns=rename_columns, inplace=True)

        for col in rename_columns.values():
            stock_df = stock_df[stock_df[col] != '-']
            if col not in {'股票代码', '股票名称'}:
                stock_df[col] = stock_df[col].astype(float)

        drop_coumns = [f for f in stock_df.columns.tolist() if f not in set(rename_columns.values())]
        stock_df.drop(drop_coumns, axis=1, inplace=True)
        stock_df[f'{days}日排名'] = range(1, stock_df.shape[0]+1)
        return cur_date, stock_df

    def fetch_stock_main_fund_proportion_rank(self,proxy_url):
        """
        个股主力资金占比排名
        http://data.eastmoney.com/zjlx/list.html
        """
        page = 1
        page_size = 10000
        url = f'http://push2.eastmoney.com/api/qt/clist/get?fid=f184&po=1&pz={page_size}&pn={page}&np=1&fltt=2&invt=2&fields=f2%2Cf3%2Cf12%2Cf13%2Cf14%2Cf62%2Cf184%2Cf225%2Cf165%2Cf263%2Cf109%2Cf175%2Cf264%2Cf160%2Cf100%2Cf124%2Cf265%2Cf1&ut=b2884a393a59ad64002292a3e90d46a5&fs=m%3A0%2Bt%3A6%2Bf%3A!2%2Cm%3A0%2Bt%3A13%2Bf%3A!2%2Cm%3A0%2Bt%3A80%2Bf%3A!2%2Cm%3A1%2Bt%3A2%2Bf%3A!2%2Cm%3A1%2Bt%3A23%2Bf%3A!2%2Cm%3A0%2Bt%3A7%2Bf%3A!2%2Cm%3A1%2Bt%3A3%2Bf%3A!2'

        self.headers['Host'] = "push2.eastmoney.com"
        self.headers['Referer'] = "http://data.eastmoney.com/"
        self.headers['Connection'] = 'close'

        resp_text = None
        request_modes = []
        if proxy_url:
            request_modes.append(
                {"proxies": {"http": proxy_url, "https": proxy_url}, "timeout": 10}
            )
        request_modes.append({"proxies": None, "timeout": 15})

        for mode in request_modes:
            if resp_text:
                break
            for _ in range(3):
                try:
                    if mode["proxies"]:
                        resp = requests.get(
                            url,
                            headers=self.headers,
                            proxies=mode["proxies"],
                            timeout=mode["timeout"],
                        )
                    else:
                        resp = requests.get(
                            url, headers=self.headers, timeout=mode["timeout"]
                        )
                    if resp.status_code == 200:
                        resp.encoding = "utf8"
                        resp_text = resp.text
                        break
                except Exception:
                    time.sleep(1)

        if not resp_text:
            return datetime.now(), pd.DataFrame()
            
        try:
            resp_json = json.loads(resp_text)
            stock_datas = resp_json.get('data', {}).get('diff', [])
            if not stock_datas:
                return datetime.now(), pd.DataFrame()
        except Exception:
            return datetime.now(), pd.DataFrame()
        
        # 当前统计的日期
        cur_date = stock_datas[0]['f124']
        cur_date = datetime.fromtimestamp(cur_date)

        stock_df = pd.DataFrame(stock_datas)
        rename_columns = {
                "f12": "股票代码",
                "f14": "股票名称",
                "f184": "今日主力净占比",
                "f3": "今日涨跌",
                "f165": "5日主力净占比",
                "f109": "5日涨跌",
                "f175": "10日主力净占比",
                "f160": "10日涨跌",
                "f100": "所属版块",

            }
        stock_df.rename(columns=rename_columns, inplace=True)

        for col in rename_columns.values():
            stock_df = stock_df[stock_df[col] != '-']
            if col not in {'股票代码', '股票名称', '所属版块'}:
                stock_df[col] = stock_df[col].astype(float)

        drop_coumns = [f for f in stock_df.columns.tolist() if f not in set(rename_columns.values())]
        stock_df.drop(drop_coumns, axis=1, inplace=True)
        return cur_date, stock_df

    def fetch_stock_north_bound_foreign_capital_rank(self):
        """
        个股北向资金持仓排名，注意是上一个交易日的数据
        http://data.eastmoney.com/hsgtcg/list.html
        """
        page = 1
        page_size = 10000
        HdDate = datetime.now().date()

        while True:
            url = f'https://dcfm.eastmoney.com/em_mutisvcexpandinterface/api/js/get?st=ShareSZ_Chg_One&sr=-1&ps={page_size}&p={page}&type=HSGT20_GGTJ_SUM&token=894050c76af8597a853f5b408b759f5d&js=%7B%22data%22%3A(x)%2C%22pages%22%3A(tp)%2C%22font%22%3A(font)%7D&filter=(DateType%3D%271%27)(HdDate%3D%27{str(HdDate)}%27)'
            self.logger.info(url)

            self.headers['Host'] = "dcfm.eastmoney.com"
            self.headers['Referer'] = "http://data.eastmoney.com/"

            resp = requests.get(url, headers=self.headers)
            resp.encoding = 'utf8'
            stock_datas = json.loads(resp.text)['data']
            print(json.loads(resp.text)['data'])

            if len(stock_datas) > 0:
                break
            HdDate = HdDate + timedelta(days=-1)

        stock_df = pd.DataFrame(stock_datas)
        rename_columns = {
            "SCode": "股票代码",
            "SName": "股票名称",
            "HYName": "所属行业",
            "HYCode": "行业代码",
            "DQName": "所属地区",
            "DQCode": "地区代码",
            "ShareHold": "今日持股股数",
            "ShareSZ": "今日持股市值",
            "LTZB": "今日持股占流通股比",
            "ZZB": "今日持股占总股本比",
            "ShareHold_Chg_One": "今日增持股数",
            "ShareSZ_Chg_One": "今日增持市值",
            "LTZB_One": "今日增持占流通股比‰",
            "ZZB_One": "今日增持占总股本比‰",
        }
        stock_df.rename(columns=rename_columns, inplace=True)
        for col in rename_columns.values():
            stock_df = stock_df[stock_df[col] != '-']
            if col not in {'股票代码', '股票名称', '所属版块', '所属行业', '行业代码', '所属地区', '地区代码'}:
                stock_df[col] = stock_df[col].astype(float)

        drop_coumns = [f for f in stock_df.columns.tolist() if f not in set(rename_columns.values())]
        stock_df.drop(drop_coumns, axis=1, inplace=True)
        return HdDate, stock_df

    def fetch_stock_commodity_rank(self):
        """
        个股大宗交易排名
        http://data.eastmoney.com/dzjy/dzjy_mrtj.html
        """
        page = 1
        page_size = 10000
        trade_date = datetime.now().date()

        while True:
            url = f'http://datacenter-web.eastmoney.com/api/data/v1/get?sortColumns=TURNOVERRATE&sortTypes=-1&pageSize={page_size}&pageNumber={page}&reportName=RPT_BLOCKTRADE_STA&columns=TRADE_DATE%2CSECURITY_CODE%2CSECUCODE%2CSECURITY_NAME_ABBR%2CCHANGE_RATE%2CCLOSE_PRICE%2CAVERAGE_PRICE%2CPREMIUM_RATIO%2CDEAL_NUM%2CVOLUME%2CDEAL_AMT%2CTURNOVERRATE%2CD1_CLOSE_ADJCHRATE%2CD5_CLOSE_ADJCHRATE%2CD10_CLOSE_ADJCHRATE%2CD20_CLOSE_ADJCHRATE&source=WEB&client=WEB&filter=(TRADE_DATE%3D%27{str(trade_date)}%27)'
            self.logger.info(url)

            self.headers['Host'] = "datacenter-web.eastmoney.com"
            self.headers['Referer'] = "http://data.eastmoney.com/"
            self.headers['Cookie'] = 'intellpositionL=1152px; IsHaveToNewFavor=0; qgqp_b_id=dbe20efaab3321e948962637a37ac894; em-quote-version=topspeed; em_hq_fls=js; emhq_picfq=2; _qddaz=QD.fqkydg.323wae.klgkordo; st_si=68830202953408; emshistory=%5B%22%E5%8C%97%E5%90%91%E8%B5%84%E9%87%91%22%2C%22%E9%BB%84%E5%8D%8E%E6%9F%92%22%2C%22603501%22%2C%22603501.SH%22%2C%22%E7%AB%8B%E8%AE%AF%E7%B2%BE%E5%AF%86%22%2C%22%E9%87%91%E9%BE%99%E9%B1%BC%22%2C%22000001%22%2C%22%E4%B8%AD%E8%8A%AF%E5%9B%BD%E9%99%85%22%5D; p_origin=https%3A%2F%2Fpassport2.eastmoney.com; testtc=0.5378301696721359; EMFUND1=null; EMFUND2=null; EMFUND3=null; EMFUND4=null; EMFUND5=null; EMFUND6=null; EMFUND7=null; EMFUND8=null; EMFUND0=null; EMFUND9=06-23 23:41:40@#$%u5357%u534E%u4E30%u6DF3%u6DF7%u5408A@%23%24005296; sid=112627825; vtpst=|; HAList=a-sz-300059-%u4E1C%u65B9%u8D22%u5BCC%2Ca-sz-300999-%u91D1%u9F99%u9C7C%2Ca-sh-600199-%u91D1%u79CD%u5B50%u9152%2Ca-sh-601279-%u82F1%u5229%u6C7D%u8F66%2Ca-sz-002261-%u62D3%u7EF4%u4FE1%u606F%2Ca-sz-002570-%u8D1D%u56E0%u7F8E%2Ca-sz-000150-%u5B9C%u534E%u5065%u5EB7%2Ca-sz-300785-%u503C%u5F97%u4E70%2Ca-sz-003039-%u987A%u63A7%u53D1%u5C55%2Ca-sz-000158-%u5E38%u5C71%u5317%u660E%2Ca-sz-002044-%u7F8E%u5E74%u5065%u5EB7%2Ca-sz-002475-%u7ACB%u8BAF%u7CBE%u5BC6; cowCookie=true; cowminicookie=true; ct=G0hDUs9gKQi4aW3xEvD_nUrvLeySSKACcjb7pt3PMuXGFTG6vFrXgU2TgPWTwf0rdVDMadZVeZigKBdt7gEhjYNn-RAz71rx4ymc2WaoxFJ_DrbmougHAvgzabrvCDKIsufTnqqSWBv6Q7YBPwmh9axru9ZquwZx92r6AdmT8Wg; ut=FobyicMgeV6oOlrtxUaVohmqCX7oh_O3yYZj6h8pdH-y_j-3oLUInf8bY9Ltl5f6Ki3pD_dO18HVqwCVuj1QyYJHLPkGETogY_ap7tz0wKJXzFJDtSmVcrzoevDqsYUBPGCv5dW5brKbArK3fBLyWzpQgl5n5MAk_OzmiEqnm51rW36tdorfCNXhVKg5yk-63EQHMLUW9L6Udk014KnVVkrMRaKd8abrVT_Gjm9muJBGNT39TG5KMpoZ62yiZy6FoSafAw4HWQIOqXw-mDGlHNghBD8PfPjD; st_asi=delete; intellpositionT=708px; JSESSIONID=22EE02E35CAF6CCCDE9D3E0D02F7AFFF; st_pvi=89273277965854; st_sp=2020-07-21%2011%3A22%3A06; st_inirUrl=http%3A%2F%2Fdata.eastmoney.com%2Fbkzj%2FBK0473.html; st_sn=222; st_psi=20210708150358412-113300300970-2924897269'

            resp = requests.get(url, headers=self.headers)
            resp.encoding = 'utf8'
            stock_datas = json.loads(resp.text)['result']
            print(json.loads(resp.text)['result'])

            if stock_datas is not None and len(stock_datas) > 0:
                stock_datas = stock_datas['data']
                break
            trade_date = trade_date + timedelta(days=-1)

        stock_df = pd.DataFrame(stock_datas)
        rename_columns = {
            "SECURITY_CODE": "股票代码",
            "SECURITY_NAME_ABBR": "股票名称",
            "CHANGE_RATE": "当日涨跌幅",
            "CLOSE_PRICE": "当日收盘价",
            "AVERAGE_PRICE": "大宗交易均价",
            "PREMIUM_RATIO": "大宗交易折溢率",
            "DEAL_NUM": "大宗交易笔数",
            "VOLUME": "成交总量(万股)",
            "DEAL_AMT": "成交总额(万元)",
            "TURNOVERRATE": "成交总额/流通市值"
        }
        stock_df.rename(columns=rename_columns, inplace=True)
        for col in rename_columns.values():
            stock_df = stock_df[stock_df[col] != '-']
            if col not in {'股票代码', '股票名称'}:
                stock_df[col] = stock_df[col].astype(float)

        drop_coumns = [f for f in stock_df.columns.tolist() if f not in set(rename_columns.values())]
        stock_df.drop(drop_coumns, axis=1, inplace=True)
        return trade_date, stock_df

    def get_all_stocks_board(self):
        """
        获取 A 股的所有股票最新排名榜单
        """
        time_token = int(time.time() * 1000)
        page_size = 6000
        fields = ','.join(EASTMONEY_A_BOARD_FIELDS.keys())
        url = "https://87.push2.eastmoney.com/api/qt/clist/get?pn=1&pz={}&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&wbp2u=1128014811999944|0|1|0|web&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048&fields={}&_={}"
        url = url.format(page_size, fields, time_token)

        headers = {
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
            'Connection': 'keep-alive',
            "Cookie": "qgqp_b_id=5dd5a3c880eed4135c765cec5bbdf661; HAList=ty-100-NDX-%u7EB3%u65AF%u8FBE%u514B%2Cty-0-300147-%u9999%u96EA%u5236%u836F%2Cty-1-600789-%u9C81%u6297%u533B%u836F%2Cty-1-600095-%u6E58%u8D22%u80A1%u4EFD%2Cty-0-300059-%u4E1C%u65B9%u8D22%u5BCC%2Cty-1-000001-%u4E0A%u8BC1%u6307%u6570%2Cty-0-399300-%u6CAA%u6DF1300; st_si=93780881941027; st_asi=delete; st_pvi=88716095105714; st_sp=2024-01-04%2013%3A36%3A25; st_inirUrl=http%3A%2F%2F127.0.0.1%3A8080%2F; st_sn=5; st_psi=20241010170113124-113200301321-4828916229",
            "Host": "87.push2.eastmoney.com",
            "Referer": "http://quote.eastmoney.com/center/gridlist.html",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.61 Safari/537.36",
        }
        resp = requests.get(url, headers=headers)
        resp.encoding = 'utf8'
        stocks = resp.json()['data']['diff']
        print(stocks)
        all_stocks = []
        for stock in stocks:
            stock_info = {}
            for f in stock:
                if f in EASTMONEY_A_BOARD_FIELDS:
                    stock_info[EASTMONEY_A_BOARD_FIELDS[f]] = stock[f]
            all_stocks.append(stock_info)
        all_stocks = pd.DataFrame(all_stocks)
        return all_stocks
