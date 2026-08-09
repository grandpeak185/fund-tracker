#!/usr/bin/env python3
"""
HTML报告生成器
生成投资组合监控网页，包含持仓明细、净值变动、买卖信号
"""

import json
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


def generate_html(config, nav_data, signal_result, nav_history):
    """生成完整的HTML页面"""

    total_value = config["portfolio"]["total_value_usd"]
    funds = config["funds"]
    cash = config["cash"]
    summary = signal_result["summary"]
    all_signals = signal_result["signals"]
    now_str = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S CST")

    # 计算每只基金的详情
    fund_rows = []
    fund_cards = []
    for fund in funds:
        fid = fund["id"]
        nav_info = nav_data[fid]
        current_nav = nav_info["nav"]
        cost_nav = fund["cost_nav"]
        returns = ((current_nav - cost_nav) / cost_nav) * 100 if cost_nav > 0 else 0
        market_value = total_value * fund["current_weight"]
        target_value = total_value * fund["target_weight"]
        weight_diff = (fund["current_weight"] - fund["target_weight"]) * 100

        returns_class = "positive" if returns >= 0 else "negative"
        weight_diff_class = "positive" if weight_diff > 0 else "negative"

        fund_rows.append(f"""
        <tr>
          <td><strong>{fund['name_cn']}</strong><br><span class="sub-text">{fund['share_class']} | ISIN: {fund['isin']}</span></td>
          <td class="mono">${current_nav:,.2f}</td>
          <td class="sub-text">{nav_info['date']}</td>
          <td class="mono ${returns_class}">{returns:+.2f}%</td>
          <td class="mono">${market_value:,.0f}</td>
          <td><span class="weight-badge">{fund['current_weight']*100:.1f}%</span></td>
          <td class="sub-text">{fund['target_weight']*100:.0f}% <span class="${weight_diff_class}">({weight_diff:+.1f}%)</span></td>
        </tr>""")

        # 信号卡片
        fund_sigs = [s for s in all_signals if s.get("fund_id") == fid]
        sig_html = ""
        if fund_sigs:
            for sig in fund_sigs:
                strength_class = sig.get("strength", "weak")
                action_class = sig["action"]
                sig_html += f"""
                <div class="signal-item {action_class} {strength_class}">
                  <span class="signal-tag {action_class}">{sig['rule']}</span>
                  <span class="signal-name">{sig['name']}</span>
                  <p class="signal-detail">{sig['detail']}</p>
                  {_build_suggested_action_html(sig.get('suggested_action'))}
                </div>"""
        else:
            sig_html = '<div class="signal-item none"><span class="signal-name">无信号触发</span><p class="signal-detail">该基金当前无买卖信号</p></div>'

        fund_cards.append(f"""
        <div class="fund-card">
          <div class="fund-card-header">
            <h3>{fund['name_cn']}</h3>
            <span class="fund-type-badge">{fund['share_class']}</span>
          </div>
          <div class="fund-card-body">
            <div class="fund-metric">
              <span class="metric-label">最新净值</span>
              <span class="metric-value">${current_nav:,.2f} <small>USD</small></span>
              <span class="metric-date">{nav_info['date']}</span>
            </div>
            <div class="fund-metric">
              <span class="metric-label">累计收益</span>
              <span class="metric-value {returns_class}">{returns:+.2f}%</span>
              <span class="metric-sub">成本 ${cost_nav:.2f}</span>
            </div>
            <div class="fund-metric">
              <span class="metric-label">持仓市值</span>
              <span class="metric-value">${market_value:,.0f}</span>
              <span class="metric-sub">权重 {fund['current_weight']*100:.1f}% (目标 {fund['target_weight']*100:.0f}%)</span>
            </div>
          </div>
          <div class="fund-signals">
            <h4>信号</h4>
            {sig_html}
          </div>
        </div>""")

    # 总盘子变动计算
    current_total = sum(total_value * f["current_weight"] * (1 + ((nav_data[f["id"]]["nav"] - f["cost_nav"]) / f["cost_nav"] if f["cost_nav"] > 0 else 0)) * 0.1 for f in funds)  # 近似
    # 更准确的计算: 基金市值 + 现金
    fund_total = sum(total_value * f["current_weight"] for f in funds)
    cash_total = total_value * cash["current_weight"]
    current_portfolio_total = fund_total + cash_total  # 基于配置的市值
    total_change = current_portfolio_total - total_value
    total_change_pct = (total_change / total_value * 100) if total_value > 0 else 0

    # 信号横幅
    overall = summary["overall_signal"]
    banner_class = {
        "SELL": "banner-sell",
        "BUY": "banner-buy",
        "REBALANCE": "banner-rebalance",
        "CAUTION": "banner-caution",
        "OPPORTUNITY": "banner-opportunity",
        "HOLD": "banner-hold",
        "HOLD (熔断保护)": "banner-hold",
    }.get(overall, "banner-hold")

    banner_icon = {
        "SELL": "🔴",
        "BUY": "🟢",
        "REBALANCE": "🟡",
        "CAUTION": "🟠",
        "OPPORTUNITY": "🔵",
        "HOLD": "⚪",
        "HOLD (熔断保护)": "⛔",
    }.get(overall, "⚪")

    # 卖出信号区
    sell_section = _build_signal_section(signal_result["sell_signals"], "sell", "赎回/卖出信号")
    buy_section = _build_signal_section(signal_result["buy_signals"], "buy", "申购/买入信号")

    # 资产配置环形图数据
    chart_data = []
    colors = ["#6366f1", "#10b981", "#f59e0b", "#94a3b8"]
    for i, fund in enumerate(funds):
        chart_data.append({
            "label": fund["name_cn"],
            "value": round(fund["current_weight"] * 100, 1),
            "color": colors[i],
        })
    chart_data.append({
        "label": "现金",
        "value": round(cash["current_weight"] * 100, 1),
        "color": colors[3],
    })

    chart_js_data = json.dumps(chart_data, ensure_ascii=False)

    # 净值历史趋势图数据
    trend_data = _build_trend_data(nav_data, nav_history)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>境外基金投资组合监控</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      line-height: 1.6;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}

    /* 头部 */
    .header {{
      text-align: center;
      padding: 30px 20px;
      background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
      border-radius: 16px;
      margin-bottom: 24px;
      border: 1px solid #334155;
    }}
    .header h1 {{ font-size: 28px; color: #f8fafc; margin-bottom: 8px; }}
    .header .update-time {{ color: #94a3b8; font-size: 14px; }}
    .header .total-value {{
      font-size: 42px; font-weight: 700; color: #38bdf8;
      margin: 16px 0 8px;
      font-variant-numeric: tabular-nums;
    }}
    .header .total-change {{ font-size: 16px; }}
    .header .total-change .positive {{ color: #4ade80; }}
    .header .total-change .negative {{ color: #f87171; }}

    /* 信号横幅 */
    .signal-banner {{
      border-radius: 12px;
      padding: 20px 24px;
      margin-bottom: 24px;
      display: flex;
      align-items: center;
      gap: 16px;
      font-size: 18px;
      font-weight: 600;
    }}
    .banner-sell {{ background: #7f1d1d; border: 1px solid #ef4444; }}
    .banner-buy {{ background: #14532d; border: 1px solid #22c55e; }}
    .banner-rebalance {{ background: #713f12; border: 1px solid #eab308; }}
    .banner-caution {{ background: #78350f; border: 1px solid #f97316; }}
    .banner-opportunity {{ background: #1e3a5f; border: 1px solid #3b82f6; }}
    .banner-hold {{ background: #1e293b; border: 1px solid #475569; }}
    .signal-banner .icon {{ font-size: 32px; }}
    .signal-banner .detail {{ font-size: 14px; font-weight: 400; color: #cbd5e1; margin-top: 4px; }}

    /* 信号计数 */
    .signal-counts {{
      display: flex; gap: 12px; margin-bottom: 24px; flex-wrap: wrap;
    }}
    .count-card {{
      flex: 1; min-width: 140px; padding: 16px; border-radius: 10px;
      text-align: center; border: 1px solid #334155; background: #1e293b;
    }}
    .count-card .num {{ font-size: 32px; font-weight: 700; font-variant-numeric: tabular-nums; }}
    .count-card .label {{ font-size: 13px; color: #94a3b8; margin-top: 4px; }}
    .count-card.sell .num {{ color: #f87171; }}
    .count-card.buy .num {{ color: #4ade80; }}
    .count-card.hold .num {{ color: #94a3b8; }}
    .count-card.strong .num {{ color: #fbbf24; }}

    /* 卡片网格 */
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }}
    @media (max-width: 768px) {{ .grid {{ grid-template-columns: 1fr; }} }}

    .card {{
      background: #1e293b; border-radius: 12px; padding: 20px;
      border: 1px solid #334155;
    }}
    .card h2 {{ font-size: 18px; color: #f1f5f9; margin-bottom: 16px; }}

    /* 持仓表格 */
    .table-wrapper {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th {{ text-align: left; padding: 12px 8px; color: #94a3b8; font-weight: 600; border-bottom: 2px solid #334155; }}
    td {{ padding: 12px 8px; border-bottom: 1px solid #1e293b; vertical-align: top; }}
    .mono {{ font-variant-numeric: tabular-nums; font-family: "SF Mono", "Fira Code", monospace; }}
    .sub-text {{ font-size: 12px; color: #94a3b8; }}
    .positive {{ color: #4ade80; }}
    .negative {{ color: #f87171; }}
    .weight-badge {{
      display: inline-block; padding: 2px 10px; border-radius: 12px;
      background: #334155; font-size: 13px; font-weight: 600;
    }}

    /* 基金卡片 */
    .fund-card {{
      background: #1e293b; border-radius: 12px; margin-bottom: 16px;
      border: 1px solid #334155; overflow: hidden;
    }}
    .fund-card-header {{
      padding: 16px 20px; border-bottom: 1px solid #334155;
      display: flex; justify-content: space-between; align-items: center;
    }}
    .fund-card-header h3 {{ font-size: 16px; color: #f1f5f9; }}
    .fund-type-badge {{
      padding: 2px 10px; border-radius: 8px; background: #334155;
      font-size: 12px; color: #94a3b8;
    }}
    .fund-card-body {{
      padding: 16px 20px; display: flex; gap: 24px; flex-wrap: wrap;
    }}
    .fund-metric {{ flex: 1; min-width: 120px; }}
    .fund-metric .metric-label {{ font-size: 12px; color: #94a3b8; display: block; }}
    .fund-metric .metric-value {{ font-size: 20px; font-weight: 700; color: #f1f5f9; display: block; font-variant-numeric: tabular-nums; }}
    .fund-metric .metric-value small {{ font-size: 12px; color: #94a3b8; }}
    .fund-metric .metric-date {{ font-size: 12px; color: #64748b; }}
    .fund-metric .metric-sub {{ font-size: 12px; color: #94a3b8; }}

    /* 信号项 */
    .fund-signals {{ padding: 12px 20px 20px; }}
    .fund-signals h4 {{ font-size: 13px; color: #94a3b8; margin-bottom: 8px; text-transform: uppercase; }}
    .signal-item {{
      padding: 10px 14px; border-radius: 8px; margin-bottom: 8px;
      border-left: 3px solid #475569; background: #0f172a;
    }}
    .signal-item.sell {{ border-left-color: #ef4444; }}
    .signal-item.buy {{ border-left-color: #22c55e; }}
    .signal-item.hold {{ border-left-color: #eab308; }}
    .signal-item.none {{ border-left-color: #475569; opacity: 0.6; }}
    .signal-item.strong {{ background: #1a0000; }}
    .signal-item.sell.strong {{ background: #2a0a0a; }}
    .signal-item.buy.strong {{ background: #0a2a0a; }}
    .signal-item.suspended {{ opacity: 0.5; }}

    .signal-tag {{
      display: inline-block; padding: 1px 8px; border-radius: 6px;
      font-size: 11px; font-weight: 700; margin-right: 8px;
    }}
    .signal-tag.sell {{ background: #7f1d1d; color: #fca5a5; }}
    .signal-tag.buy {{ background: #14532d; color: #86efac; }}
    .signal-tag.hold {{ background: #713f12; color: #fde047; }}
    .signal-name {{ font-weight: 600; color: #e2e8f0; font-size: 14px; }}
    .signal-detail {{ font-size: 13px; color: #cbd5e1; margin-top: 4px; }}

    .suggested-action {{
      margin-top: 8px; padding: 10px 14px; border-radius: 8px;
      background: #1e293b; border: 1px dashed #475569; font-size: 13px;
    }}
    .suggested-action .action-label {{
      font-weight: 700; color: #fbbf24; font-size: 12px;
      text-transform: uppercase; display: block; margin-bottom: 4px;
    }}
    .suggested-action .action-desc {{ color: #e2e8f0; }}

    /* 信号区块 */
    .signal-section {{
      background: #1e293b; border-radius: 12px; padding: 20px;
      border: 1px solid #334155; margin-bottom: 24px;
    }}
    .signal-section h2 {{
      font-size: 18px; margin-bottom: 16px; display: flex; align-items: center; gap: 8px;
    }}
    .signal-section.sell-section h2 {{ color: #f87171; }}
    .signal-section.buy-section h2 {{ color: #4ade80; }}
    .signal-section .no-signal {{
      text-align: center; padding: 20px; color: #64748b; font-size: 14px;
    }}

    /* 图表区 */
    .chart-container {{
      position: relative; width: 100%; max-width: 300px; margin: 0 auto;
    }}
    .chart-legend {{
      margin-top: 16px;
    }}
    .legend-item {{
      display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 14px;
    }}
    .legend-color {{
      width: 12px; height: 12px; border-radius: 3px;
    }}

    /* NCB基金池 */
    .ncb-list {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .ncb-tag {{
      padding: 6px 14px; border-radius: 8px; background: #0f172a;
      border: 1px solid #334155; font-size: 13px; color: #cbd5e1;
    }}
    .ncb-tag .type {{ font-size: 11px; color: #64748b; margin-left: 4px; }}

    /* 规则说明 */
    .rules-section {{
      background: #1e293b; border-radius: 12px; padding: 20px;
      border: 1px solid #334155; margin-bottom: 24px;
    }}
    .rules-section h2 {{ font-size: 18px; margin-bottom: 12px; }}
    .rules-section h3 {{ font-size: 15px; margin: 12px 0 8px; color: #94a3b8; }}
    .rules-section ul {{ list-style: none; padding-left: 0; }}
    .rules-section li {{ padding: 4px 0; font-size: 13px; color: #cbd5e1; }}
    .rules-section li code {{
      background: #0f172a; padding: 1px 6px; border-radius: 4px;
      font-size: 12px; color: #38bdf8;
    }}

    /* 页脚 */
    .footer {{
      text-align: center; padding: 20px; color: #64748b; font-size: 13px;
    }}
    .footer a {{ color: #38bdf8; text-decoration: none; }}

    /* 趋势图 */
    .trend-chart {{ width: 100%; height: 200px; }}
  </style>
</head>
<body>
  <div class="container">

    <!-- 头部 -->
    <div class="header">
      <h1>境外基金投资组合监控</h1>
      <div class="update-time">最后更新: {now_str} | 每日北京时间12:00自动刷新</div>
      <div class="total-value">${total_value:,.2f} <small style="font-size:18px;color:#94a3b8;">USD</small></div>
      <div class="total-change">
        组合总市值 |
        <span class="{'positive' if total_change >= 0 else 'negative'}">
          {total_change:+,.2f} USD ({total_change_pct:+.2f}%)
        </span>
      </div>
    </div>

    <!-- 信号横幅 -->
    <div class="signal-banner {banner_class}">
      <span class="icon">{banner_icon}</span>
      <div>
        <div>综合信号: {overall}</div>
        <div class="detail">{summary['overall_detail']}</div>
      </div>
    </div>

    <!-- 信号计数 -->
    <div class="signal-counts">
      <div class="count-card sell">
        <div class="num">{summary['sell_count']}</div>
        <div class="label">卖出信号</div>
      </div>
      <div class="count-card buy">
        <div class="num">{summary['buy_count']}</div>
        <div class="label">买入信号</div>
      </div>
      <div class="count-card hold">
        <div class="num">{summary['hold_count']}</div>
        <div class="label">熔断/观望</div>
      </div>
      <div class="count-card strong">
        <div class="num">{summary['strong_sell_count']}</div>
        <div class="label">强卖出</div>
      </div>
      <div class="count-card strong">
        <div class="num">{summary['strong_buy_count']}</div>
        <div class="label">强买入</div>
      </div>
    </div>

    <!-- 持仓明细表格 + 资产配置图 -->
    <div class="grid">
      <div class="card">
        <h2>投资明细</h2>
        <div class="table-wrapper">
          <table>
            <thead>
              <tr>
                <th>基金名称</th>
                <th>净值</th>
                <th>日期</th>
                <th>累计收益</th>
                <th>市值</th>
                <th>权重</th>
                <th>目标</th>
              </tr>
            </thead>
            <tbody>
              {''.join(fund_rows)}
              <tr style="border-top: 2px solid #334155;">
                <td><strong>现金</strong></td>
                <td>-</td>
                <td>-</td>
                <td>-</td>
                <td class="mono">${total_value * cash['current_weight']:,.0f}</td>
                <td><span class="weight-badge">{cash['current_weight']*100:.1f}%</span></td>
                <td class="sub-text">{cash['target_weight']*100:.0f}%</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="card">
        <h2>资产配置</h2>
        <div class="chart-container">
          <canvas id="pieChart" width="280" height="280"></canvas>
        </div>
        <div class="chart-legend" id="pieLegend"></div>
      </div>
    </div>

    <!-- 净值趋势 -->
    <div class="card" style="margin-bottom: 24px;">
      <h2>净值趋势</h2>
      <canvas id="trendChart" class="trend-chart"></canvas>
    </div>

    <!-- 卖出信号 -->
    <div class="signal-section sell-section">
      <h2>🔴 赎回/卖出信号</h2>
      {sell_section if sell_section else '<div class="no-signal">暂无卖出信号触发</div>'}
    </div>

    <!-- 买入信号 -->
    <div class="signal-section buy-section">
      <h2>🟢 申购/买入信号</h2>
      {buy_section if buy_section else '<div class="no-signal">暂无买入信号触发</div>'}
    </div>

    <!-- 各基金详情卡片 -->
    <div class="card" style="margin-bottom: 24px;">
      <h2>基金详情与信号</h2>
      {''.join(fund_cards)}
    </div>

    <!-- NCB可购买基金池 -->
    <div class="card" style="margin-bottom: 24px;">
      <h2>南洋商业银行(NCB)可购基金池</h2>
      <p class="sub-text" style="margin-bottom: 12px;">以下为NCB代销的可选基金，买入信号将在该范围内推荐</p>
      <div class="ncb-list">
        {''.join(f'<span class="ncb-tag">{f["name_cn"]}<span class="type">[{f["type"]}]</span></span>' for f in config['ncb_fund_pool'])}
      </div>
    </div>

    <!-- 量化规则说明 -->
    <div class="rules-section">
      <h2>量化信号规则说明</h2>

      <h3>卖出规则</h3>
      <ul>
        <li><code>S-01</code> 止盈止损: 累计收益 ≥+15%触发止盈, ≥+25%强止盈; ≤-8%止损预警, ≤-12%强止损</li>
        <li><code>S-02</code> 趋势反转: MA5下穿MA20（死叉）</li>
        <li><code>S-04</code> 仓位偏离: 当前权重超出目标权重+3%，触发再平衡减仓</li>
        <li><code>S-05</code> 急跌熔断: 5日跌幅>15%，暂停自动操作，转人工复核</li>
      </ul>

      <h3>买入规则</h3>
      <ul>
        <li><code>B-02</code> 趋势确立: MA5上穿MA20（金叉）</li>
        <li><code>B-03</code> 回撤企稳: 从高点回撤15%-25%且近3日波动<1%</li>
        <li><code>B-04</code> 现金过多: 现金仓位>30%，建议配置</li>
        <li><code>B-05</code> 仓位不足: 当前权重低于目标权重-3%，触发再平衡加仓</li>
      </ul>

      <h3>信号强度</h3>
      <ul>
        <li><strong>强信号</strong>(立即执行): ≥3条核心规则同时触发，或触及强止盈/止损线</li>
        <li><strong>中信号</strong>(分批操作): 2条规则触发</li>
        <li><strong>弱信号</strong>(观望预警): 1条规则触发</li>
      </ul>
    </div>

    <!-- 页脚 -->
    <div class="footer">
      <p>数据来源: 惠理基金官网 / JPMorgan AM / Fonds-Super-Markt / Morningstar</p>
      <p>本页面由GitHub Actions每日北京时间12:00自动更新 | <a href="#">查看仓库</a></p>
      <p style="margin-top:8px;">⚠ 投资有风险，信号仅供参考，不构成投资建议</p>
    </div>

  </div>

  <script>
    // 环形图绘制
    const pieData = {chart_js_data};
    const ctx = document.getElementById('pieChart').getContext('2d');
    const cx = 140, cy = 140, r = 100, rInner = 60;
    let startAngle = -Math.PI / 2;

    pieData.forEach(item => {{
      const angle = (item.value / 100) * Math.PI * 2;
      ctx.beginPath();
      ctx.arc(cx, cy, r, startAngle, startAngle + angle);
      ctx.arc(cx, cy, rInner, startAngle + angle, startAngle, true);
      ctx.closePath();
      ctx.fillStyle = item.color;
      ctx.fill();
      startAngle += angle;
    }});

    // 中心文字
    ctx.fillStyle = '#94a3b8';
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('资产配置', cx, cy - 5);
    ctx.fillStyle = '#f1f5f9';
    ctx.font = 'bold 18px sans-serif';
    ctx.fillText('100%', cx, cy + 18);

    // 图例
    const legend = document.getElementById('pieLegend');
    pieData.forEach(item => {{
      legend.innerHTML += `<div class="legend-item"><span class="legend-color" style="background:${{item.color}}"></span>${{item.label}}: ${{item.value}}%</div>`;
    }});

    // 净值趋势图
    {trend_data}
  </script>
</body>
</html>"""

    return html


def _build_signal_section(signals, signal_type, title):
    """构建信号区块HTML"""
    if not signals:
        return ""

    html = ""
    for sig in signals:
        strength_badge = {
            "strong": '<span style="color:#fbbf24;font-weight:700;">[强]</span>',
            "medium": '<span style="color:#94a3b8;">[中]</span>',
            "weak": '<span style="color:#64748b;">[弱]</span>',
            "suspended": '<span style="color:#ef4444;">[已暂停]</span>',
        }.get(sig.get("strength", "weak"), "")

        fund_name = sig.get("fund_name", "组合整体")
        html += f"""
        <div class="signal-item {signal_type} {sig.get('strength', 'weak')}">
          <span class="signal-tag {signal_type}">{sig['rule']}</span>
          {strength_badge}
          <span class="signal-name">{fund_name} - {sig['name']}</span>
          <p class="signal-detail">{sig['detail']}</p>
          {_build_suggested_action_html(sig.get('suggested_action'))}
        </div>"""

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


def _build_trend_data(nav_data, nav_history):
    """构建趋势图JS代码"""
    # 简单的趋势图 - 使用历史净值数据
    funds_data = {}
    for fid in ["value_partners", "jpm_asia_pacific", "amundi_income"]:
        navs = []
        if fid in nav_history and nav_history[fid]:
            navs = nav_history[fid][-30:]  # 最近30个数据点
        if not navs:
            navs = [nav_data[fid]["nav"]]
        funds_data[fid] = navs

    return f"""
    const trendData = {json.dumps(funds_data)};
    const trendCtx = document.getElementById('trendChart').getContext('2d');
    const colors = {{'value_partners': '#6366f1', 'jpm_asia_pacific': '#10b981', 'amundi_income': '#f59e0b'}};
    const labels = {{'value_partners': '惠理高息', 'jpm_asia_pacific': 'JPM亚太入息', 'amundi_income': '东方汇理'}};

    const w = trendCtx.canvas.width;
    const h = trendCtx.canvas.height;
    const pad = 40;

    // 绘制网格
    trendCtx.strokeStyle = '#334155';
    trendCtx.lineWidth = 0.5;
    for (let i = 0; i <= 4; i++) {{
      const y = pad + (h - 2*pad) * i / 4;
      trendCtx.beginPath();
      trendCtx.moveTo(pad, y);
      trendCtx.lineTo(w - pad, y);
      trendCtx.stroke();
    }}

    // 找到全局最大最小值
    let allVals = [];
    Object.values(trendData).forEach(vals => allVals = allVals.concat(vals));
    const minVal = Math.min(...allVals) * 0.98;
    const maxVal = Math.max(...allVals) * 1.02;

    // 绘制每条线
    Object.entries(trendData).forEach(([fid, vals]) => {{
      if (vals.length < 2) return;
      const color = colors[fid];
      trendCtx.strokeStyle = color;
      trendCtx.lineWidth = 2;
      trendCtx.beginPath();
      vals.forEach((v, i) => {{
        const x = pad + (w - 2*pad) * i / (vals.length - 1);
        const y = h - pad - (h - 2*pad) * (v - minVal) / (maxVal - minVal);
        if (i === 0) trendCtx.moveTo(x, y);
        else trendCtx.lineTo(x, y);
      }});
      trendCtx.stroke();

      // 最后一个点
      const lastX = pad + (w - 2*pad);
      const lastY = h - pad - (h - 2*pad) * (vals[vals.length-1] - minVal) / (maxVal - minVal);
      trendCtx.fillStyle = color;
      trendCtx.beginPath();
      trendCtx.arc(lastX, lastY, 4, 0, Math.PI * 2);
      trendCtx.fill();
    }});

    // 图例
    let legendX = pad;
    Object.entries(labels).forEach(([fid, label]) => {{
      trendCtx.fillStyle = colors[fid];
      trendCtx.fillRect(legendX, 8, 12, 12);
      trendCtx.fillStyle = '#94a3b8';
      trendCtx.font = '12px sans-serif';
      trendCtx.textAlign = 'left';
      trendCtx.fillText(label, legendX + 16, 18);
      legendX += 120;
    }});
    """
