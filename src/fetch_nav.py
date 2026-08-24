#!/usr/bin/env python3
"""
基金净值抓取模块
从多个数据源获取三只境外基金的最新净值

数据源策略：
  惠理高息股票基金   -> 惠理官网 WP API (JSON, 日度净值)
  JPM亚太入息基金    -> Morningstar API (F00000OCN6) -> JPM官网(WebFetch) -> 快照
  东方汇理收益机遇   -> fonds-super-markt.de (HTML解析)
"""

import json
import re
import urllib.request
import urllib.parse
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
        "isin": "HK0000288743",  # 修正: A2 MDis USD 的正确 ISIN
        # 惠理官网 WP API（返回 JSON 日度净值）
        "api_url": "https://www.valuepartners-group.com/wp-apis/index.php?api=get_historical_price&fundids=vphyA2MDIs",
        # 备用: 惠理官网页面
        "fallback_url": "https://www.valuepartners-group.com/sc/investment-solutions/institutional-funds/value-partners-high-dividend-stocks-fund-sc/",
    },
    "jpm_asia_pacific": {
        "name": "JPM亚太入息基金 A(mth) USD",
        "isin": "LU0784639295",
        # Morningstar API（F00000OCN6 = JPM Asia Pacific Income A mth USD）
        "morningstar_id": "F00000OCN6",
        # JPM官网（SPA，Python 无法直接解析，作为最后手段）
        "url": "https://am.jpmorgan.com/ch/de/asset-management/adv/products/jpm-asia-pacific-income-a-mth-usd-lu0784639295",
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
    "value_partners": {"nav": 12.81, "date": "2026-08-20"},
    "jpm_asia_pacific": {"nav": 122.26, "date": "2026-08-20"},
    "amundi_income": {"nav": 84.97, "date": "2026-08-20"},
}


def fetch_url(url, timeout=15, headers=None):
    """通用URL抓取函数"""
    default_headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,de;q=0.7",
    }
    if headers:
        default_headers.update(headers)
    try:
        req = urllib.request.Request(url, headers=default_headers)
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [警告] 抓取失败 {url}: {e}")
        return None


def convert_date_ddmmyyyy(date_str):
    """将 DD-MM-YYYY 转为 YYYY-MM-DD"""
    if not date_str:
        return None
    m = re.match(r'(\d{2})-(\d{2})-(\d{4})', date_str)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.match(r'(\d{2})\.(\d{2})\.(\d{4})', date_str)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return date_str


# ==================== 惠理基金 ====================

def fetch_value_partners():
    """通过惠理官网 WP API 获取最新净值（JSON格式，日度数据）"""
    source = FUND_SOURCES["value_partners"]
    api_url = source["api_url"]

    print(f"  正在抓取 {source['name']}...")

    # 调用 WP API
    html = fetch_url(api_url, headers={
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.valuepartners-group.com/sc/investment-solutions/institutional-funds/value-partners-high-dividend-stocks-fund-sc/",
        "X-Requested-With": "XMLHttpRequest",
    })
    if html:
        try:
            data = json.loads(html.strip('\ufeff'))
            rows = data.get("data", [])
            if rows:
                latest = rows[0]  # API 返回最新在前
                nav = float(latest.get("vphyA2MDIs", 0))
                date_str = convert_date_ddmmyyyy(latest.get("date", ""))
                if nav > 0:
                    print(f"    ✓ WP API: NAV={nav}, 日期={date_str}")
                    return {"nav": nav, "date": date_str, "source": "primary", "isin": source["isin"]}
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            print(f"    WP API 解析失败: {e}")

    # 备用: 尝试从官网页面解析分红表
    print(f"    主数据源失败，尝试备用...")
    html = fetch_url(source["fallback_url"])
    if html:
        nav, date_str = parse_value_partners_dividend_table(html)
        if nav:
            print(f"    ✓ 备用(分红表): NAV={nav}, 日期={date_str}")
            return {"nav": nav, "date": date_str, "source": "fallback", "isin": source["isin"]}

    # 回退到已知净值
    known = KNOWN_NAV["value_partners"]
    print(f"    ⚠ 网络抓取失败，使用最近已知净值: NAV={known['nav']}, 日期={known['date']}")
    return {"nav": known["nav"], "date": known["date"], "source": "known_snapshot", "isin": source["isin"]}


def parse_value_partners_dividend_table(html):
    """从惠理官网分红表解析最新除息日净值"""
    # 分红表: <td><span class="hide">2026-07-31</span>31-07-2026</td><td>12.53</td>
    pattern = r'<span class="hide">(\d{4}-\d{2}-\d{2})</span>(\d{2}-\d{2}-\d{4})</td>\s*<td>(\d{2}\.\d{2,4})</td>'
    matches = re.findall(pattern, html)
    if matches:
        latest = matches[0]
        return float(latest[2]), latest[1]
    return None, None


# ==================== JPM 亚太入息基金 ====================

def fetch_jpm_asia_pacific():
    """获取JPM亚太入息基金净值
    优先尝试 Morningstar API，失败则使用已知快照
    """
    source = FUND_SOURCES["jpm_asia_pacific"]
    ms_id = source.get("morningstar_id", "F00000OCN6")

    print(f"  正在抓取 {source['name']}...")

    # 方案1: Morningstar API (有时不稳定，SSL间歇性失败)
    ms_result = fetch_from_morningstar(ms_id, source["isin"])
    if ms_result:
        print(f"    ✓ Morningstar API: NAV={ms_result['nav']}, 日期={ms_result['date']}")
        return {**ms_result, "source": "primary", "isin": source["isin"]}

    # 方案2: 尝试 fonds-super-markt.de
    fsm_url = f"https://www.fonds-super-markt.de/fondsfinder/fondsdetails/lu0784639295-jpm-asia-pacific-income-a-mth-usd/"
    html = fetch_url(fsm_url)
    if html and len(html) > 30000:
        nav, date_str = parse_fonds_super_markt(html)
        if nav:
            print(f"    ✓ fonds-super-markt: NAV={nav}, 日期={date_str}")
            return {"nav": nav, "date": date_str, "source": "fallback", "isin": source["isin"]}

    # 回退到已知净值
    known = KNOWN_NAV["jpm_asia_pacific"]
    print(f"    ⚠ 网络抓取失败，使用最近已知净值: NAV={known['nav']}, 日期={known['date']}")
    return {"nav": known["nav"], "date": known["date"], "source": "known_snapshot", "isin": source["isin"]}


def fetch_from_morningstar(ms_id, isin):
    """通过 Morningstar API 获取基金净值"""
    urls_to_try = [
        f"https://www.morningstar.com/api/v2/funds/{ms_id}/quote",
        f"https://www.morningstar.com/api/v2/securities?performanceID={ms_id}",
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.morningstar.com/",
    }

    for url in urls_to_try:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15, context=SSL_CONTEXT) as resp:
                raw = resp.read().decode("utf-8", errors="replace")

            if not raw.strip():
                continue

            data = json.loads(raw)

            # 深度搜索 NAV 相关字段
            nav = find_field_recursive(data, ["nav", "lastNAV", "lastPrice", "closePrice", "lastNav", "price"])
            nav_date = find_field_recursive(data, ["navDate", "lastNavDate", "lastPriceDate", "asOfDate", "date"])

            # 如果找到 NAV，验证 ISIN
            found_isin = find_field_recursive(data, ["isin"])
            if nav and (not found_isin or found_isin == isin):
                try:
                    nav_float = float(str(nav).replace(",", "."))
                    if 50 < nav_float < 200:
                        return {"nav": nav_float, "date": str(nav_date) if nav_date else None}
                except (ValueError, TypeError):
                    pass
        except Exception:
            continue

    return None


def find_field_recursive(obj, field_names, depth=0):
    """递归搜索 JSON 中的字段"""
    if depth > 5:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in [f.lower() for f in field_names]:
                if v and not isinstance(v, (dict, list)):
                    return v
            result = find_field_recursive(v, field_names, depth + 1)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj[:3]:
            result = find_field_recursive(item, field_names, depth + 1)
            if result:
                return result
    return None


# ==================== 东方汇理基金 ====================

def fetch_amundi_income():
    """通过 fonds-super-markt.de 获取净值"""
    source = FUND_SOURCES["amundi_income"]

    print(f"  正在抓取 {source['name']}...")

    html = fetch_url(source["url"])
    if html:
        nav, date_str = parse_fonds_super_markt(html)
        if nav:
            print(f"    ✓ 主数据源: NAV={nav}, 日期={date_str}")
            return {"nav": nav, "date": date_str, "source": "primary", "isin": source["isin"]}

    # 备用数据源
    html = fetch_url(source["fallback_url"])
    if html:
        nav, date_str = parse_eodhd(html)
        if nav:
            print(f"    ✓ 备用数据源: NAV={nav}, 日期={date_str}")
            return {"nav": nav, "date": date_str, "source": "fallback", "isin": source["isin"]}

    # 回退到已知净值
    known = KNOWN_NAV["amundi_income"]
    print(f"    ⚠ 网络抓取失败，使用最近已知净值: NAV={known['nav']}, 日期={known['date']}")
    return {"nav": known["nav"], "date": known["date"], "source": "known_snapshot", "isin": source["isin"]}


def parse_fonds_super_markt(html):
    """从德国基金数据平台解析净值"""
    # 匹配 "84,97 USD" 和 "vom 20.08.2026"
    nav_pattern = r'(\d{2,3},\d{2})\s*USD'
    date_pattern = r'vom\s*(\d{2}\.\d{2}\.\d{4})'

    nav_match = re.search(nav_pattern, html)
    date_match = re.search(date_pattern, html)

    if nav_match:
        nav_str = nav_match.group(1).replace(',', '.')
        try:
            nav = float(nav_str)
            date_str = convert_date_ddmmyyyy(date_match.group(1)) if date_match else None
            return nav, date_str
        except ValueError:
            pass

    return None, None


def parse_eodhd(html):
    """从 eodhd.com 解析净值"""
    # 通用解析: 找 "NAV" 附近的数字
    nav_pattern = r'NAV.*?([\d,.]+)'
    date_pattern = r'(\d{4}-\d{2}-\d{2})'

    nav_match = re.search(nav_pattern, html, re.IGNORECASE)
    date_match = re.search(date_pattern, html)

    if nav_match:
        nav_str = nav_match.group(1).replace(',', '.')
        try:
            nav = float(nav_str)
            if 50 < nav < 150:
                return nav, date_match.group(1) if date_match else None
        except ValueError:
            pass

    return None, None


# ==================== 主入口 ====================

FETCHERS = {
    "value_partners": fetch_value_partners,
    "jpm_asia_pacific": fetch_jpm_asia_pacific,
    "amundi_income": fetch_amundi_income,
}


def fetch_all_nav():
    """获取所有基金的最新净值"""
    print("=" * 60)
    print("开始抓取基金净值")
    print(f"当前北京时间: {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = {}
    for fund_id in FUND_SOURCES:
        fetcher = FETCHERS[fund_id]
        results[fund_id] = fetcher()

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
