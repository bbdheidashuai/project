#!/usr/bin/python
# _*_ coding: utf-8 _*_


def is_shenzhen_security(security_code: str):
    """
    判断是否为深交所上市的股票
    """
    return get_security_type(security_code) == "SZ"


def is_shanghai_security(security_code: str):
    """
    判断是否为上交所上市的股票
    """
    return get_security_type(security_code) == "SH"


def is_kechuangban(security_code: str):
    """
    判断是否为上交所上市的科创板股票
    """
    return security_code.startswith('688') or security_code.startswith('787') or security_code.startswith('789')


def get_security_type(security_code: str):
    """
    根据股票代码判断所属证券市场
    XSHG 代表 Shan(g)hai，XSHE 代表 Sh(e)nzhen

    ['50', '51', '60', '90', '110'] 为 XSHG
    ['00', '13', '18', '15', '16', '18', '20', '30', '39', '115'] 为 XSHE
    ['5', '6', '9'] 开头的为 XSHG， 其余为 XSHE
    """
    just_code = security_code.replace('.', '').replace("SH", '').replace("SZ", '')
    if len(just_code) != 6:
        raise ValueError('security code must be 6 figures')

    if security_code.endswith(("SH", "SZ")):
        return security_code[-4:]
    if security_code.startswith(
            ("50", "51", "60", "90", "110", "113", "132", "204")
    ):
        return "SH"
    if security_code.startswith(
            ("00", "13", "18", "15", "16", "18", "20", "30", "39", "115", "1318")
    ):
        return "SZ"
    if security_code.startswith(("5", "6", "9", "7")):
        return "SH"
    return "SZ"


def security_code_norm(security_code):
    """
    证券代码标准化
    """
    security_type = get_security_type(security_code)
    security_code = security_code.replace('.', '').replace("SH", '').replace("SZ", '')
    normed_security_code = f'{security_code}.{security_type}'
    return normed_security_code
