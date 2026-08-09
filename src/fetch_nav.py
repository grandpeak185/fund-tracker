#!/usr/bin/env python3
"""
基金净值抓取模块
从多个数据源获取三只境外基金的最新净值
"""

import json
import re
import urllib.request
import urllib.error
import ssl
from datetime import datetime, timezone, timedelta
from pathlib import Path

# 忽略SSL证书验证（用于抓取部分数据源）
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE

# 北京时区
CST = timezone(timedelta(hours=8))

# 基金数据源配置
FUND_SOURCES = {
    "value_partners": {
        "name": "惠理高息股票基金 A2 MDis USD",
        "isin": "HK0000288784",
        # 惠理官网净值表
        "url": "https://www.valuepartners-group.com/sc/investment-solutions/institutional-funds/value-partners-high-dividend-stocks-fund-sc/",
        # 备用: 晨星
        "fallback_url": "https://www.morningstar.hk/hk/funds/snapshot/snapshot.aspx?id=F00000YIGY",
    },
    "jpm_asia_pacific": {
        "name": "JPM亚太入息基金 A(mth) USD",
        "isin": "LU0784639295",
        # 摩根大通官网
        "url": "https://am.jpmorgan.com/ch/de/asset-management/adv/products/jpm-asia-pacific-income-a-mth-usd-lu0784639295",
        "fallback_url": "https://global.morningstar.com/en-eu/investments/funds/LU0784639295/quote",
    },
    "amundi_income": {
        "name": "东方汇理收益机遇基金 A2 USD (C)",
        "isin": "LU1883839398",
        # 德国基金数据平台
        "url": "https://www.fonds-super-markt.de/fondsfinder/fondsdetails/lu1883839398-amundi-funds-pioneer-income-opportunities-a2-usd-c/",
        "fallback_url": "https://eodhd.com/financial-summary/LU1883839398.EUFUND",
    },
}

# 已知的最近净值快照（作为网络抓取失败时的回退）
KNOWN_NAV = {
    "value_partners": {"nav": 12.58, "date": "2026-08-06"},
    "jpm_asia_pacific": {"nav": 122.87, "date": "2026-08-05"},
    "amundi_income": {"nav": 83.66, "date": "2026-08-03"},
}


def fetch_url(url, timeout=15):
    """通用URL抓取函数"""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,de;q=0.7",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [警告] 抓取失败 {url}: {e}")
        return None


def parse_value_partners(html):
    """从惠理官网解析净值表"""
    # 惠理官网有一个净值表格，A2类别美元每月分派
    # 匹配模式: 日期 + A2类别美元每月分派值
    patterns = [
        # 尝试匹配表格中的数据行
        r"A2\s*类别\s*美元每月分派.*?(\d{2}\.\d{2,4})",
        r'A2.*?USD.*?MDis.*?(\d{2}\.\d{2,4})',
    ]

    # 查找日期
    date_pattern = r'(\d{2}-\d{2}-\d{4})'
    date_match = re.search(date_pattern, html)

    # 查找净值表格 - A2类别美元每月分派
    # 表格结构: 日期 | A1美元 | A1港元 | ... | A2美元每月分派 | ...
    nav_pattern = r'<tr>\s*<td>(\d{2}-\d{2}-\d{4})</td>\s*(?:<td>[\d.,]+</td>\s*)*<td>(\d{2}\.\d{2,4})</td>'
    matches = re.findall(nav_pattern, html)

    if matches:
        latest = matches[-1]
        return float(latest[1]), latest[0]

    return None, None


def parse_jpmorgan(html):
    """从摩根大通官网解析净值"""
    # 查找 NAV 和日期
    nav_patterns = [
        r'NAV\s*(?:Per|as of)?\s*(\d{2}\.\d{2}\.\d{4})?.*?USD\s*([\d.,]+)',
        r'Net Asset Value.*?USD\s*([\d.,]+)',
        r'(\d{2}\.\d{2}\.\d{4}).*?USD\s*([\d.,]+)',
    ]

    date_pattern = r'Per\s*(\d{2}\.\d{2}\.\d{4})'
    date_match = re.search(date_pattern, html)

    for pattern in nav_patterns:
        match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            # 尝试提取数字
            nav_str = match.group(2).replace('.', '').replace(',', '.')
            try:
                nav = float(nav_str)
                if 50 < nav < 200:  # 合理范围检查
                    date_str = date_match.group(1) if date_match else None
                    return nav, date_str
            except ValueError:
                continue

    return None, None


def parse_amundi(html):
    """从德国基金数据平台解析净值"""
    # 查找 "83,66 USD" 或 "vom 03.08.2026" 这样的模式
    nav_pattern = r'(\d{2},\d{2})\s*USD'
    date_pattern = r'vom\s*(\d{2}\.\d{2}\.\d{4})'

    nav_match = re.search(nav_pattern, html)
    date_match = re.search(date_pattern, html)

    if nav_match:
        nav_str = nav_match.group(1).replace(',', '.')
        try:
            nav = float(nav_str)
            date_str = date_match.group(1) if date_match else None
            return nav, date_str
        except ValueError:
            pass

    return None, None


PARSERS = {
    "value_partners": parse_value_partners,
    "jpm_asia_pacific": parse_jpmorgan,
    "amundi_income": parse_amundi,
}


def fetch_single_fund(fund_id):
    """获取单只基金的净值"""
    source = FUND_SOURCES[fund_id]
    parser = PARSERS[fund_id]

    print(f"  正在抓取 {source['name']}...")

    # 尝试主数据源
    html = fetch_url(source["url"])
    if html:
        nav, date_str = parser(html)
        if nav:
            print(f"    ✓ 主数据源: NAV={nav}, 日期={date_str}")
            return {"nav": nav, "date": date_str, "source": "primary", "isin": source["isin"]}

    # 尝试备用数据源
    html = fetch_url(source["fallback_url"])
    if html:
        nav, date_str = parser(html)
        if nav:
            print(f"    ✓ 备用数据源: NAV={nav}, 日期={date_str}")
            return {"nav": nav, "date": date_str, "source": "fallback", "isin": source["isin"]}

    # 使用已知净值作为回退
    known = KNOWN_NAV[fund_id]
    print(f"    ⚠ 网络抓取失败，使用最近已知净值: NAV={known['nav']}, 日期={known['date']}")
    return {"nav": known["nav"], "date": known["date"], "source": "known_snapshot", "isin": source["isin"]}


def fetch_all_nav():
    """获取所有基金的最新净值"""
    print("=" * 60)
    print("开始抓取基金净值")
    print(f"当前北京时间: {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = {}
    for fund_id in FUND_SOURCES:
        results[fund_id] = fetch_single_fund(fund_id)

    print("\n净值抓取完成:")
    for fund_id, data in results.items():
        name = FUND_SOURCES[fund_id]["name"]
        print(f"  {name}: ${data['nav']} ({data['date']}) [{data['source']}]")

    return results


def save_nav_history(nav_data, history_file="data/nav_history.json"):
    """保存净值到历史记录"""
    history_path = Path(history_file)
    history_path.parent.mkdir(parents=True, exist_ok=True)

    history = []
    if history_path.exists():
        with open(history_path, "r", encoding="utf-8") as f:
            try:
                history = json.load(f)
            except json.JSONDecodeError:
                history = []

    today_str = datetime.now(CST).strftime("%Y-%m-%d")
    record = {"date": today_str, "timestamp": datetime.now(CST).isoformat(), "funds": nav_data}
    history.append(record)

    # 只保留最近365天
    history = history[-365:]

    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"\n净值历史已保存到 {history_file} (共 {len(history)} 条记录)")
    return history


def load_nav_history(history_file="data/nav_history.json"):
    """加载历史净值记录"""
    history_path = Path(history_file)
    if not history_path.exists():
        return []
    with open(history_path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


if __name__ == "__main__":
    nav_data = fetch_all_nav()
    save_nav_history(nav_data)
