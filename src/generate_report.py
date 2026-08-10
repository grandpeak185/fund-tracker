#!/usr/bin/env python3
"""
HTML报告生成器 - Overseas Treasury
5大板块布局：资产总额、投资明细、持有基金分析、潜力基金分析、量化规则说明
滚动5年净值趋势，价格分位数，操作建议
"""

import json
import re
import calendar
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


def normalize_date(date_str):
    """将各种日期格式统一为 YYYY-MM-DD"""
    if not date_str or date_str == "-":
        return "-"
    m = re.match(r'(\d{2})\.(\d{2})\.(\d{4})', date_str)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', date_str)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return date_str


def is_month_end(date_str):
    """检查日期是否为月末"""
    if not date_str or "-" not in date_str:
        return False
    parts = date_str.split("-")
    if len(parts) != 3:
        return False
    y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    last_day = calendar.monthrange(y, m)[1]
    return d == last_day


def calculate_rolling_window(monthly_nav_history):
    """计算滚动5年窗口
    返回: (start_str, end_str, start_display, end_display)
    例如: ("2021-08", "2026-07", "2021年8月", "2026年7月")
    """
    latest_month_end = None
    for fid, fdata in monthly_nav_history.items():
        for m in fdata.get("monthly_nav", []):
            date_str = m["date"]
            if is_month_end(date_str):
                if not latest_month_end or date_str > latest_month_end:
                    latest_month_end = date_str

    if not latest_month_end:
        return None, None, None, None

    end_year = int(latest_month_end[:4])
    end_month = int(latest_month_end[5:7])

    start_year = end_year - 5
    start_month = end_month + 1
    if start_month > 12:
        start_year += 1
        start_month -= 12

    start_str = f"{start_year:04d}-{start_month:02d}"
    end_str = f"{end_year:04d}-{end_month:02d}"
    start_display = f"{start_year}年{start_month}月"
    end_display = f"{end_year}年{end_month}月"

    return start_str, end_str, start_display, end_display


def filter_monthly_to_window(monthly_data, start_str, end_str):
    """筛选月度数据，只保留滚动窗口内的月末数据"""
    filtered = []
    for m in monthly_data.get("monthly_nav", []):
        date_str = m["date"]
        month_key = date_str[:7]
        if is_month_end(date_str) and start_str <= month_key <= end_str:
            filtered.append(m)
    return filtered


def generate_html(config, nav_data, signal_result, monthly_nav_history, portfolio_data):
    """生成完整的HTML页面"""

    funds = config["funds"]
    cash = config["cash"]
    all_signals = signal_result["signals"]
    now_str = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S CST")

    total_assets = portfolio_data["total_assets"]
    fund_market_values = portfolio_data["fund_market_values"]
    dynamic_weights = portfolio_data["dynamic_weights"]
    cash_value = portfolio_data["cash_value"]

    # ---- 计算相较期初数的增减百分比 ----
    base_value = 263000
    change_amount = total_assets - base_value
    change_pct = (change_amount / base_value) * 100
    change_arrow = "↑" if change_amount >= 0 else "↓"
    change_class = "up" if change_amount >= 0 else "down"

    # ---- 滚动窗口计算 ----
    win_start, win_end, win_start_display, win_end_display = calculate_rolling_window(monthly_nav_history)
    if not win_start:
        win_start, win_end = "2021-08", "2026-07"
        win_start_display, win_end_display = "2021年8月", "2026年7月"
    period_str = f"{win_start_display} 至 {win_end_display}"

    # ---- 投资明细表行 ----
    fund_rows = []
    for fund in funds:
        fid = fund["id"]
        nav_info = nav_data[fid]
        current_nav = nav_info["nav"]
        cost_nav = fund["cost_nav"]
        returns = ((current_nav - cost_nav) / cost_nav) * 100 if cost_nav > 0 else 0
        market_value = fund_market_values[fid]
        weight = dynamic_weights[fid]

        returns_class = "pos" if returns >= 0 else "neg"
        nav_date = normalize_date(nav_info['date'])

        fund_rows.append(f"""
        <tr>
          <td><strong>{fund['name_cn']}</strong><br><span class="sub">{fund['share_class']} | ISIN: {fund['isin']}</span></td>
          <td class="mono">{nav_date}</td>
          <td class="mono">${current_nav:,.2f}</td>
          <td class="mono">${market_value:,.0f}</td>
          <td class="mono {returns_class}">{returns:+.2f}%</td>
          <td><span class="badge">{weight*100:.1f}%</span></td>
        </tr>""")

    cash_weight = dynamic_weights["cash"]
    fund_rows.append(f"""
        <tr class="cash-row">
          <td><strong>现金和存款</strong></td>
          <td>-</td>
          <td>-</td>
          <td class="mono">${cash_value:,.0f}</td>
          <td>-</td>
          <td><span class="badge">{cash_weight*100:.1f}%</span></td>
        </tr>""")

    # ---- 按基金分组信号 ----
    fund_signals_map = {}
    for sig in all_signals:
        fid = sig.get("fund_id")
        if fid:
            if fid not in fund_signals_map:
                fund_signals_map[fid] = {"sell": [], "buy": []}
            if sig["action"] == "sell":
                fund_signals_map[fid]["sell"].append(sig)
            elif sig["action"] == "buy":
                fund_signals_map[fid]["buy"].append(sig)

    # ---- 持有基金分析 ----
    fund_colors = {
        "value_partners": "#1a56db",
        "jpm_asia_pacific": "#059669",
        "amundi_income": "#d97706",
    }

    percentile_details = signal_result.get("percentile_details", {})
    fund_analysis_blocks = []
    chart_configs = {}

    for fund in funds:
        fid = fund["id"]
        fund_name = fund["name_cn"]

        # 筛选滚动窗口内的月末数据
        if fid in monthly_nav_history:
            filtered_monthly = filter_monthly_to_window(monthly_nav_history[fid], win_start, win_end)
        else:
            filtered_monthly = []

        # 图表数据
        chart_configs[fid] = {
            "label": fund_name,
            "color": fund_colors.get(fid, "#6366f1"),
            "canvasId": f"chart_{fid}",
            "tooltipId": f"tooltip_{fid}",
            "data": [{"month": m["date"], "nav": m["nav"]} for m in filtered_monthly],
        }

        # 价格分位数
        detail = percentile_details.get(fid, {})
        pct = detail.get("percentile", 50.0)
        hist_high = detail.get("hist_high", 0)
        hist_low = detail.get("hist_low", 0)
        current = detail.get("current_nav", 0)

        if pct >= 95:
            bar_color = "#dc2626"
            status = "极端高位"
        elif pct >= 85:
            bar_color = "#f97316"
            status = "高位预警"
        elif pct <= 10:
            bar_color = "#16a34a"
            status = "极端低位"
        elif pct <= 20:
            bar_color = "#22c55e"
            status = "低位机会"
        else:
            bar_color = "#3b82f6"
            status = "正常区间"

        bar_width = min(max(pct, 2), 100)
        pct_html = f"""
        <div class="pct-item">
          <div class="pct-header">
            <span class="pct-status" style="color:{bar_color}">{status}</span>
            <span class="pct-value" style="color:{bar_color};font-weight:bold">{pct:.1f}%</span>
          </div>
          <div class="pct-bar-container">
            <div class="pct-bar" style="width:{bar_width:.1f}%;background:{bar_color}"></div>
            <div class="pct-threshold" style="left:10%"></div>
            <div class="pct-threshold" style="left:20%"></div>
            <div class="pct-threshold" style="left:85%"></div>
            <div class="pct-threshold" style="left:95%"></div>
          </div>
          <div class="pct-labels">
            <span>0%</span>
            <span>100%</span>
          </div>
          <div class="pct-detail">区间高: {hist_high:.2f} | 区间低: {hist_low:.2f} | 当前: {current:.2f}</div>
        </div>"""

        # 操作建议
        sigs = fund_signals_map.get(fid, {"sell": [], "buy": []})
        if sigs["sell"]:
            rec_html = '<div class="recommendation redeem">'
            for sig in sigs["sell"]:
                strength_badge = {
                    "strong": '<span class="strength-tag strong">强</span>',
                    "medium": '<span class="strength-tag medium">中</span>',
                    "weak": '<span class="strength-tag weak">弱</span>',
                    "suspended": '<span class="strength-tag suspended">暂停</span>',
                }.get(sig.get("strength", "weak"), "")
                rec_html += f"""
              <div class="rec-item">
                {strength_badge}
                <span class="signal-tag sell">{sig['rule']}</span>
                <span class="rec-name">{sig['name']}</span>
                <p class="rec-detail">{sig['detail']}</p>
                {_build_suggested_action_html(sig.get('suggested_action'))}
              </div>"""
            rec_html += '</div>'
        elif sigs["buy"]:
            rec_html = '<div class="recommendation buy">'
            for sig in sigs["buy"]:
                strength_badge = {
                    "strong": '<span class="strength-tag strong">强</span>',
                    "medium": '<span class="strength-tag medium">中</span>',
                    "weak": '<span class="strength-tag weak">弱</span>',
                }.get(sig.get("strength", "weak"), "")
                rec_html += f"""
              <div class="rec-item">
                {strength_badge}
                <span class="signal-tag buy">{sig['rule']}</span>
                <span class="rec-name">{sig['name']}</span>
                <p class="rec-detail">{sig['detail']}</p>
                {_build_suggested_action_html(sig.get('suggested_action'))}
              </div>"""
            rec_html += '</div>'
        else:
            rec_html = '<div class="recommendation hold"><div class="rec-item"><span class="rec-name hold-text">继续持有</span></div></div>'

        fund_analysis_blocks.append(f"""
      <div class="fund-block">
        <div class="fund-block-header">
          <h3>{fund_name}</h3>
          <span class="fund-meta">{fund['share_class']} | ISIN: {fund['isin']}</span>
        </div>
        <div class="fund-subsection">
          <div class="subsection-header">
            <span class="subsection-label">净值趋势</span>
            <span class="subsection-period">{period_str}</span>
          </div>
          <div class="mini-chart-container">
            <canvas id="chart_{fid}" class="mini-chart"></canvas>
            <div id="tooltip_{fid}" class="chart-tooltip"></div>
          </div>
        </div>
        <div class="fund-subsection">
          <div class="subsection-header">
            <span class="subsection-label">价格分位数</span>
            <span class="subsection-period">{period_str}</span>
          </div>
          {pct_html}
        </div>
        <div class="fund-subsection">
          <div class="subsection-header">
            <span class="subsection-label">操作建议</span>
          </div>
          {rec_html}
        </div>
      </div>""")

    fund_analysis_html = '\n'.join(fund_analysis_blocks)

    # ---- 潜力基金分析 ----
    fund_buy_signals = [s for s in signal_result["buy_signals"] if s.get("fund_id")]
    if fund_buy_signals:
        potential_items = []
        for sig in fund_buy_signals:
            strength_badge = {
                "strong": '<span class="strength-tag strong">强</span>',
                "medium": '<span class="strength-tag medium">中</span>',
                "weak": '<span class="strength-tag weak">弱</span>',
            }.get(sig.get("strength", "weak"), "")
            potential_items.append(f"""
        <div class="signal-item buy">
          {strength_badge}
          <span class="signal-tag buy">{sig['rule']}</span>
          <span class="signal-name">{sig['fund_name']} - {sig['name']}</span>
          <p class="signal-detail">{sig['detail']}</p>
          {_build_suggested_action_html(sig.get('suggested_action'))}
        </div>""")
        potential_html = '\n'.join(potential_items)
    else:
        potential_html = '<div class="no-signal">暂无推荐基金</div>'

    # ---- 图表配置 JSON ----
    chart_configs_json = json.dumps(chart_configs, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes, viewport-fit=cover">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="Overseas Treasury">
  <meta name="theme-color" content="#1a365d">
  <link rel="manifest" href="manifest.json">
  <title>Overseas Treasury</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
      background: linear-gradient(180deg, #f0f4f8 0%, #e6ecf2 100%);
      color: #1e293b;
      line-height: 1.6;
      min-height: 100vh;
      padding-top: env(safe-area-inset-top);
      padding-bottom: env(safe-area-inset-bottom);
    }}
    .container {{ max-width: 1200px; margin: 0 auto; padding: 24px; padding-left: max(24px, env(safe-area-inset-left)); padding-right: max(24px, env(safe-area-inset-right)); }}

    /* 头部 */
    .header {{
      background: linear-gradient(135deg, #1a365d 0%, #2c5282 100%);
      border-radius: 14px;
      padding: 28px 32px;
      margin-bottom: 24px;
      box-shadow: 0 2px 12px rgba(26,54,93,0.15);
    }}
    .header h1 {{
      font-size: 30px;
      color: #fff;
      font-weight: 700;
      letter-spacing: 1px;
    }}
    .header .update-time {{
      color: #a0aec0;
      font-size: 13px;
      margin-top: 10px;
    }}

    /* 卡片通用 */
    .card {{
      background: #fff;
      border-radius: 12px;
      padding: 24px;
      margin-bottom: 24px;
      box-shadow: 0 1px 6px rgba(0,0,0,0.06);
      border: 1px solid #e2e8f0;
    }}
    .card h2 {{
      font-size: 18px;
      color: #1a365d;
      margin-bottom: 16px;
      padding-bottom: 10px;
      border-bottom: 2px solid #e2e8f0;
      font-weight: 700;
    }}

    /* 资产总额 */
    .total-assets-box {{
      display: flex;
      align-items: baseline;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .total-assets-box .label {{
      font-size: 16px;
      color: #475569;
      font-weight: 600;
    }}
    .total-assets-box .value {{
      font-size: 42px;
      font-weight: 800;
      color: #1a365d;
      font-variant-numeric: tabular-nums;
    }}
    .total-assets-box .currency {{
      font-size: 18px;
      color: #64748b;
      font-weight: 600;
    }}
    .total-breakdown {{
      margin-top: 20px;
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 16px;
    }}
    .breakdown-item {{
      padding: 12px 16px;
      background: #f8fafc;
      border-radius: 8px;
      border: 1px solid #e2e8f0;
    }}
    .breakdown-item .b-label {{
      font-size: 12px;
      color: #94a3b8;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .breakdown-item .b-value {{
      font-size: 20px;
      font-weight: 700;
      color: #1e293b;
      font-variant-numeric: tabular-nums;
      margin-top: 4px;
    }}
    .breakdown-item .b-value.up {{ color: #dc2626; }}
    .breakdown-item .b-value.down {{ color: #059669; }}

    /* 投资明细表 */
    .table-wrapper {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 15px; }}
    thead th {{
      text-align: left; padding: 14px 12px;
      color: #64748b; font-weight: 600; font-size: 13px;
      text-transform: uppercase; letter-spacing: 0.5px;
      border-bottom: 2px solid #cbd5e0;
      background: #f8fafc;
    }}
    tbody td {{
      padding: 14px 12px;
      border-bottom: 1px solid #e2e8f0;
      vertical-align: middle;
    }}
    .cash-row {{ background: #f8fafc; border-top: 2px solid #cbd5e0; }}
    .mono {{
      font-variant-numeric: tabular-nums;
      font-family: "SF Mono", "Fira Code", "Cascadia Code", monospace;
    }}
    .sub {{ font-size: 12px; color: #94a3b8; }}
    .pos {{ color: #059669; font-weight: 600; }}
    .neg {{ color: #dc2626; font-weight: 600; }}
    .badge {{
      display: inline-block; padding: 3px 12px; border-radius: 20px;
      background: #e0e7ff; color: #3730a3; font-size: 13px; font-weight: 600;
    }}
    .cash-row .badge {{ background: #f1f5f9; color: #64748b; }}

    /* 持有基金分析 */
    .fund-block {{
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      padding: 20px;
      margin-bottom: 20px;
    }}
    .fund-block:last-child {{ margin-bottom: 0; }}
    .fund-block-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      padding-bottom: 12px;
      border-bottom: 1px solid #e2e8f0;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .fund-block-header h3 {{
      font-size: 16px;
      color: #1a365d;
      font-weight: 700;
    }}
    .fund-meta {{
      font-size: 12px;
      color: #94a3b8;
    }}
    .fund-subsection {{
      margin-bottom: 16px;
    }}
    .fund-subsection:last-child {{ margin-bottom: 0; }}
    .subsection-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 8px;
    }}
    .subsection-label {{
      font-size: 14px;
      font-weight: 600;
      color: #475569;
    }}
    .subsection-period {{
      font-size: 12px;
      color: #94a3b8;
    }}

    /* 迷你图表 */
    .mini-chart-container {{
      position: relative;
      width: 100%;
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
      padding-bottom: 8px;
    }}
    .mini-chart {{
      width: 100%;
      min-width: 500px;
      height: 200px;
      display: block;
    }}
    .chart-tooltip {{
      position: absolute;
      display: none;
      background: rgba(30,41,59,0.95);
      color: #f1f5f9;
      padding: 6px 10px;
      border-radius: 6px;
      font-size: 12px;
      pointer-events: none;
      white-space: nowrap;
      box-shadow: 0 4px 12px rgba(0,0,0,0.2);
      z-index: 10;
    }}
    .chart-tooltip .tt-date {{ font-weight: 700; margin-bottom: 2px; }}
    .chart-tooltip .tt-line {{ display: flex; align-items: center; gap: 6px; }}
    .chart-tooltip .tt-dot {{ width: 8px; height: 8px; border-radius: 50%; }}

    /* 价格分位数 */
    .pct-item {{ margin-bottom: 4px; }}
    .pct-header {{
      display: flex; justify-content: space-between; align-items: center;
      margin-bottom: 6px;
    }}
    .pct-status {{ font-size: 13px; font-weight: 600; }}
    .pct-value {{ font-size: 14px; }}
    .pct-bar-container {{
      position: relative; width: 100%; height: 24px;
      background: #f1f5f9; border-radius: 12px; overflow: visible;
    }}
    .pct-bar {{
      height: 100%; border-radius: 12px;
      transition: width 0.6s ease;
      min-width: 4px;
    }}
    .pct-threshold {{
      position: absolute; top: 0; bottom: 0;
      width: 2px; background: #cbd5e1; opacity: 0.7;
    }}
    .pct-labels {{
      display: flex; justify-content: space-between; align-items: center;
      margin-top: 4px; font-size: 12px; color: #94a3b8;
    }}
    .pct-detail {{
      font-size: 12px; color: #64748b; margin-top: 4px;
    }}

    /* 操作建议 */
    .recommendation {{
      padding: 12px;
      border-radius: 8px;
    }}
    .recommendation.redeem {{
      background: #fef2f2;
      border-left: 3px solid #dc2626;
    }}
    .recommendation.buy {{
      background: #f0fdf4;
      border-left: 3px solid #059669;
    }}
    .recommendation.hold {{
      background: #f8fafc;
      border-left: 3px solid #94a3b8;
    }}
    .rec-item {{
      margin-bottom: 10px;
    }}
    .rec-item:last-child {{ margin-bottom: 0; }}
    .rec-name {{
      font-weight: 600;
      color: #1e293b;
      font-size: 14px;
    }}
    .rec-name.hold-text {{
      color: #64748b;
      font-size: 15px;
    }}
    .rec-detail {{
      font-size: 13px;
      color: #475569;
      margin-top: 4px;
    }}
    .strength-tag {{
      display: inline-block; padding: 2px 8px; border-radius: 4px;
      font-size: 11px; font-weight: 700; margin-right: 6px;
    }}
    .strength-tag.strong {{ background: #fee2e2; color: #991b1b; }}
    .strength-tag.medium {{ background: #fef3c7; color: #92400e; }}
    .strength-tag.weak {{ background: #e2e8f0; color: #475569; }}
    .strength-tag.suspended {{ background: #fee2e2; color: #991b1b; }}

    /* 信号区块（潜力基金分析） */
    .signal-item {{
      padding: 14px 16px;
      border-radius: 8px;
      margin-bottom: 10px;
      border-left: 3px solid #cbd5e0;
      background: #f7fafc;
    }}
    .signal-item.buy {{ border-left-color: #059669; background: #f0fdf4; }}
    .signal-tag {{
      display: inline-block; padding: 2px 10px; border-radius: 6px;
      font-size: 11px; font-weight: 700; margin-right: 8px;
    }}
    .signal-tag.buy {{ background: #dcfce7; color: #166534; }}
    .signal-name {{ font-weight: 600; color: #1e293b; font-size: 15px; }}
    .signal-detail {{ font-size: 13px; color: #475569; margin-top: 4px; }}
    .suggested-action {{
      margin-top: 8px; padding: 10px 14px; border-radius: 8px;
      background: #fff; border: 1px dashed #cbd5e0; font-size: 13px;
    }}
    .suggested-action .action-label {{
      font-weight: 700; color: #b45309; font-size: 12px; display: block; margin-bottom: 4px;
    }}
    .suggested-action .action-desc {{ color: #1e293b; }}
    .no-signal {{ text-align: center; padding: 24px; color: #94a3b8; font-size: 14px; }}

    /* 规则说明 */
    .rules-section h3 {{
      font-size: 15px; margin: 16px 0 8px; color: #2c5282;
    }}
    .rules-section ul {{ list-style: none; padding-left: 0; }}
    .rules-section li {{
      padding: 6px 0; font-size: 14px; color: #475569;
      display: flex; align-items: flex-start; gap: 8px;
    }}
    .rules-section li::before {{
      content: "\\25AA"; color: #2c5282; font-weight: bold;
    }}
    .rules-section code {{
      background: #e0e7ff; padding: 2px 8px; border-radius: 4px;
      font-size: 12px; color: #3730a3; font-weight: 600;
      min-width: 44px; display: inline-block; text-align: center;
      margin-right: 4px;
    }}

    /* 免责条款 */
    .disclaimer {{
      text-align: center;
      padding: 16px 24px;
      color: #94a3b8;
      font-size: 12px;
      line-height: 1.8;
    }}
    .disclaimer p {{ margin: 4px 0; }}

    /* ===== 移动端适配 ===== */
    @media (max-width: 640px) {{
      .container {{ padding: 12px; }}
      .header {{ padding: 20px 18px; border-radius: 12px; margin-bottom: 16px; }}
      .header h1 {{ font-size: 22px; letter-spacing: 0.5px; }}
      .header .update-time {{ font-size: 12px; margin-top: 8px; }}
      .card {{ padding: 16px 14px; margin-bottom: 16px; border-radius: 10px; }}
      .card h2 {{ font-size: 16px; margin-bottom: 12px; padding-bottom: 8px; }}
      .total-assets-box .label {{ font-size: 14px; }}
      .total-assets-box .value {{ font-size: 32px; }}
      .total-assets-box .currency {{ font-size: 15px; }}
      .total-breakdown {{ margin-top: 14px; gap: 10px; }}
      .breakdown-item {{ padding: 10px 12px; }}
      .breakdown-item .b-value {{ font-size: 17px; }}
      .table-wrapper {{ overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 0 -14px; }}
      .table-wrapper table {{ min-width: 580px; }}
      table {{ font-size: 13px; }}
      thead th {{ padding: 10px 8px; font-size: 11px; letter-spacing: 0.3px; }}
      tbody td {{ padding: 10px 8px; }}
      .sub {{ font-size: 11px; }}

      /* 持有基金分析 */
      .fund-block {{ padding: 14px 12px; }}
      .fund-block-header h3 {{ font-size: 15px; }}
      .fund-meta {{ font-size: 11px; }}
      .subsection-label {{ font-size: 13px; }}
      .subsection-period {{ font-size: 11px; }}
      .mini-chart {{ min-width: 400px; height: 180px; }}
      .chart-tooltip {{ font-size: 11px; padding: 4px 8px; }}

      /* 价格分位数 */
      .pct-status {{ font-size: 12px; }}
      .pct-detail {{ font-size: 11px; }}
      .pct-bar-container {{ height: 20px; }}

      /* 操作建议 */
      .rec-name {{ font-size: 13px; }}
      .rec-detail {{ font-size: 12px; }}
      .suggested-action {{ padding: 8px 10px; font-size: 12px; }}

      /* 信号 */
      .signal-item {{ padding: 12px 12px; }}
      .signal-name {{ font-size: 14px; }}
      .signal-detail {{ font-size: 12px; }}

      /* 规则说明 */
      .rules-section h3 {{ font-size: 14px; }}
      .rules-section li {{ font-size: 13px; line-height: 1.8; }}
      .rules-section code {{ font-size: 11px; min-width: 36px; padding: 2px 6px; }}

      /* 免责条款 */
      .disclaimer {{ padding: 12px 8px; font-size: 11px; }}
    }}

    @media (max-width: 380px) {{
      .header h1 {{ font-size: 18px; }}
      .total-assets-box .value {{ font-size: 26px; }}
      .mini-chart {{ height: 160px; min-width: 320px; }}
    }}
  </style>
</head>
<body>
  <div class="container">

    <!-- 头部 -->
    <div class="header">
      <h1>Overseas Treasury</h1>
      <div class="update-time">最后更新: {now_str}</div>
    </div>

    <!-- 第一板块：资产总额 -->
    <div class="card">
      <h2>资产总额</h2>
      <div class="total-assets-box">
        <span class="label">资产总额</span>
        <span class="value">${total_assets:,.0f}</span>
        <span class="currency">USD</span>
      </div>
      <div class="total-breakdown">
        <div class="breakdown-item">
          <div class="b-label">基金市值合计</div>
          <div class="b-value">${total_assets - cash_value:,.0f}</div>
        </div>
        <div class="breakdown-item">
          <div class="b-label">现金和存款</div>
          <div class="b-value">${cash_value:,.0f}</div>
        </div>
        <div class="breakdown-item">
          <div class="b-label">基金数量</div>
          <div class="b-value">{len(funds)}</div>
        </div>
        <div class="breakdown-item">
          <div class="b-label">相较期初数</div>
          <div class="b-value {change_class}">{change_arrow} {change_pct:+.2f}%</div>
        </div>
      </div>
    </div>

    <!-- 第二板块：投资明细 -->
    <div class="card">
      <h2>投资明细</h2>
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>资产名称</th>
              <th>日期</th>
              <th>净值</th>
              <th>市值</th>
              <th>累计收益</th>
              <th>权重</th>
            </tr>
          </thead>
          <tbody>
            {''.join(fund_rows)}
          </tbody>
        </table>
      </div>
    </div>

    <!-- 第三板块：持有基金分析 -->
    <div class="card">
      <h2>持有基金分析</h2>
      {fund_analysis_html}
    </div>

    <!-- 第四板块：潜力基金分析 -->
    <div class="card">
      <h2>潜力基金分析</h2>
      {potential_html}
    </div>

    <!-- 第五板块：量化规则说明 -->
    <div class="card rules-section">
      <h2>量化规则说明</h2>
      <h3>卖出规则</h3>
      <ul>
        <li><code>S-01</code>止盈止损: 累计收益 ≥+15%触发止盈, ≥+25%强止盈; ≤-8%止损预警, ≤-12%强止损（价格分位数调制）</li>
        <li><code>S-02</code>趋势反转: MA5下穿MA20（死叉）</li>
        <li><code>S-04</code>仓位偏离: 当前权重超出目标权重+3%，触发再平衡减仓</li>
        <li><code>S-05</code>急跌熔断: 5日跌幅>15%，暂停自动操作，转人工复核</li>
        <li><code>S-06</code>历史高位: 价格分位数 &gt;85% 高位预警，&gt;95% 极端高位强信号</li>
      </ul>
      <h3>买入规则</h3>
      <ul>
        <li><code>B-02</code>趋势确立: MA5上穿MA20（金叉）</li>
        <li><code>B-03</code>回撤企稳: 从高点回撤15%-25%且近3日波动&lt;1%</li>
        <li><code>B-04</code>现金过多: 现金仓位&gt;30%，建议配置</li>
        <li><code>B-05</code>仓位不足: 当前权重低于目标权重-3%，触发再平衡加仓</li>
        <li><code>B-06</code>历史低位: 价格分位数 &lt;20% 低位机会，&lt;10% 极端低位强信号</li>
      </ul>
      <h3>价格分位数</h3>
      <ul>
        <li>分位数 = (当前净值 − 区间最低) / (区间最高 − 区间最低) × 100%</li>
        <li>数据来源: Morningstar月度净值 API，覆盖{win_start_display}至{win_end_display}的月末数据</li>
        <li>分位数越高，当前价格越接近区间高点，回调风险越大；反之则处于区间低位</li>
      </ul>
      <h3>信号强度</h3>
      <ul>
        <li><code>强</code>≥3条核心规则同时触发，或触及强止盈/止损线 — 立即执行</li>
        <li><code>中</code>2条规则触发 — 分批操作</li>
        <li><code>弱</code>1条规则触发 — 观望预警</li>
      </ul>
    </div>

    <!-- 免责条款 -->
    <div class="disclaimer">
      <p>本页面由量化规则自动生成，所有信号和数据仅供参考，不构成任何投资建议。</p>
      <p>投资有风险，过往业绩不代表未来表现，请根据自身风险承受能力独立决策。</p>
    </div>

  </div>

  <script>
    const chartConfigs = {chart_configs_json};
    const chartState = {{}};

    function drawMiniChart(config) {{
      const canvas = document.getElementById(config.canvasId);
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      const data = config.data;
      if (data.length === 0) return;

      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      ctx.scale(dpr, dpr);

      const W = rect.width;
      const H = rect.height;
      const padL = 60, padR = 20, padT = 20, padB = 40;
      const chartW = W - padL - padR;
      const chartH = H - padT - padB;

      const vals = data.map(d => d.nav);
      const minVal = Math.min(...vals);
      const maxVal = Math.max(...vals);
      const valRange = maxVal - minVal || 1;
      const yMin = minVal - valRange * 0.08;
      const yMax = maxVal + valRange * 0.08;
      const yRange = yMax - yMin || 1;

      const n = data.length;
      const xStep = n > 1 ? chartW / (n - 1) : 0;

      const pointCoords = [];
      ctx.clearRect(0, 0, W, H);

      // 网格线
      ctx.strokeStyle = '#e2e8f0';
      ctx.lineWidth = 1;
      ctx.font = '10px -apple-system, sans-serif';
      ctx.fillStyle = '#94a3b8';
      ctx.textAlign = 'right';
      for (let i = 0; i <= 4; i++) {{
        const y = padT + chartH * i / 4;
        const val = yMax - (yRange * i / 4);
        ctx.beginPath();
        ctx.moveTo(padL, y);
        ctx.lineTo(W - padR, y);
        ctx.stroke();
        ctx.fillText(val.toFixed(2), padL - 6, y + 3);
      }}

      // X轴标签
      ctx.textAlign = 'center';
      const labelStep = Math.max(1, Math.ceil(n / 8));
      for (let i = 0; i < n; i += labelStep) {{
        const x = padL + xStep * i;
        ctx.fillText(data[i].month.substring(0, 7), x, H - padB + 16);
      }}

      // 折线
      ctx.strokeStyle = config.color;
      ctx.lineWidth = 2;
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      ctx.beginPath();
      data.forEach((d, i) => {{
        const x = padL + xStep * i;
        const y = padT + chartH * (1 - (d.nav - yMin) / yRange);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }});
      ctx.stroke();

      // 数据点
      data.forEach((d, i) => {{
        const x = padL + xStep * i;
        const y = padT + chartH * (1 - (d.nav - yMin) / yRange);
        ctx.fillStyle = config.color;
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#fff';
        ctx.beginPath();
        ctx.arc(x, y, 1.5, 0, Math.PI * 2);
        ctx.fill();
        pointCoords.push({{ x, y, month: d.month, nav: d.nav, label: config.label, color: config.color }});
      }});

      chartState[config.canvasId] = pointCoords;
    }}

    function setupTooltip(canvasId, tooltipId) {{
      const canvas = document.getElementById(canvasId);
      const tooltip = document.getElementById(tooltipId);
      if (!canvas || !tooltip) return;

      canvas.addEventListener('mousemove', function(e) {{
        const rect = canvas.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const coords = chartState[canvasId] || [];

        let closest = null;
        let minDist = 15;
        coords.forEach(p => {{
          const dist = Math.sqrt((p.x - mx) ** 2 + (p.y - my) ** 2);
          if (dist < minDist) {{
            minDist = dist;
            closest = p;
          }}
        }});

        if (closest) {{
          tooltip.innerHTML = '<div class="tt-date">' + closest.month + '</div>' +
            '<div class="tt-line"><span class="tt-dot" style="background:' + closest.color + '"></span>$' + closest.nav.toFixed(2) + '</div>';
          tooltip.style.display = 'block';
          tooltip.style.left = (closest.x + 10) + 'px';
          tooltip.style.top = Math.max(0, closest.y - 10) + 'px';
        }} else {{
          tooltip.style.display = 'none';
        }}
      }});

      canvas.addEventListener('mouseleave', function() {{
        tooltip.style.display = 'none';
      }});
    }}

    // 初始化所有图表
    Object.values(chartConfigs).forEach(config => {{
      drawMiniChart(config);
      setupTooltip(config.canvasId, config.tooltipId);
    }});

    // 窗口resize时重绘
    let resizeTimer;
    window.addEventListener('resize', function() {{
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(function() {{
        Object.values(chartConfigs).forEach(config => drawMiniChart(config));
      }}, 200);
    }});
  </script>
</body>
</html>"""

    return html


def _build_suggested_action_html(action):
    """构建建议操作HTML"""
    if not action:
        return ""
    desc = action.get("description", "")
    return f"""
      <div class="suggested-action">
        <span class="action-label">⚡ 建议操作</span>
        <span class="action-desc">{desc}</span>
      </div>"""
