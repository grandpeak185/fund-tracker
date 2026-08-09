#!/usr/bin/env python3
"""
HTML报告生成器 - Overseas Treasury
浅色金融风格，6大板块布局，动态市值与权重，净值趋势tooltip
"""

import json
import re
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


def normalize_date(date_str):
    """将各种日期格式统一为 YYYY-MM-DD"""
    if not date_str or date_str == "-":
        return "-"
    # DD.MM.YYYY -> YYYY-MM-DD
    m = re.match(r'(\d{2})\.(\d{2})\.(\d{4})', date_str)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    # YYYY-MM-DD (already correct)
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', date_str)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return date_str


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

    # 现金和存款行
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

    # ---- 信号区块 ----
    sell_section = _build_signal_section(signal_result["sell_signals"], "sell")
    buy_section = _build_signal_section(signal_result["buy_signals"], "buy")

    # ---- 月度趋势图数据 ----
    trend_months = []
    fund_trend_data = {}
    fund_colors = {
        "value_partners": "#1a56db",
        "jpm_asia_pacific": "#059669",
        "amundi_income": "#d97706",
    }
    fund_labels = {
        "value_partners": "惠理高息股票",
        "jpm_asia_pacific": "JPM亚太入息",
        "amundi_income": "东方汇理收益机遇",
    }

    for fid in ["value_partners", "jpm_asia_pacific", "amundi_income"]:
        if fid in monthly_nav_history:
            monthly = monthly_nav_history[fid].get("monthly_nav", [])
            fund_trend_data[fid] = {
                "label": fund_labels.get(fid, fid),
                "color": fund_colors.get(fid, "#6366f1"),
                "data": [{"month": m["month"], "nav": m["nav"]} for m in monthly],
            }
            if not trend_months:
                trend_months = [m["month"] for m in monthly]

    trend_json = json.dumps(fund_trend_data, ensure_ascii=False)
    months_json = json.dumps(trend_months, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes">
  <title>Overseas Treasury</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
      background: linear-gradient(180deg, #f0f4f8 0%, #e6ecf2 100%);
      color: #1e293b;
      line-height: 1.6;
      min-height: 100vh;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}

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

    /* 板块编号 */
    .section-num {{
      display: inline-block;
      width: 28px; height: 28px;
      line-height: 28px;
      text-align: center;
      background: #1a365d;
      color: #fff;
      border-radius: 50%;
      font-size: 14px;
      font-weight: 700;
      margin-right: 10px;
      vertical-align: middle;
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
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
    }}
    .breakdown-item {{
      flex: 1;
      min-width: 140px;
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

    /* 信号区块 */
    .signal-card.sell {{ border-top: 3px solid #dc2626; }}
    .signal-card.buy {{ border-top: 3px solid #059669; }}
    .signal-card.sell h2 {{ color: #dc2626; }}
    .signal-card.buy h2 {{ color: #059669; }}
    .signal-card h2 .icon {{ margin-right: 8px; }}

    .signal-item {{
      padding: 14px 16px;
      border-radius: 8px;
      margin-bottom: 10px;
      border-left: 3px solid #cbd5e0;
      background: #f7fafc;
    }}
    .signal-item.sell {{ border-left-color: #dc2626; background: #fef2f2; }}
    .signal-item.buy {{ border-left-color: #059669; background: #f0fdf4; }}
    .signal-tag {{
      display: inline-block; padding: 2px 10px; border-radius: 6px;
      font-size: 11px; font-weight: 700; margin-right: 8px;
    }}
    .signal-tag.sell {{ background: #fee2e2; color: #991b1b; }}
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

    /* 趋势图 */
    .trend-container {{
      position: relative;
      width: 100%;
    }}
    #trendChart {{
      width: 100%;
      height: 400px;
      display: block;
    }}
    #chartTooltip {{
      position: absolute;
      display: none;
      background: rgba(30,41,59,0.95);
      color: #f1f5f9;
      padding: 8px 12px;
      border-radius: 8px;
      font-size: 13px;
      pointer-events: none;
      white-space: nowrap;
      box-shadow: 0 4px 12px rgba(0,0,0,0.2);
      z-index: 10;
    }}
    #chartTooltip .tt-date {{
      font-weight: 700;
      margin-bottom: 2px;
    }}
    #chartTooltip .tt-line {{
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    #chartTooltip .tt-dot {{
      width: 8px; height: 8px; border-radius: 50%;
    }}

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

      /* 头部 */
      .header {{
        padding: 20px 18px;
        border-radius: 12px;
        margin-bottom: 16px;
      }}
      .header h1 {{
        font-size: 22px;
        letter-spacing: 0.5px;
      }}
      .header .update-time {{
        font-size: 12px;
        margin-top: 8px;
      }}

      /* 卡片 */
      .card {{
        padding: 16px 14px;
        margin-bottom: 16px;
        border-radius: 10px;
      }}
      .card h2 {{
        font-size: 16px;
        margin-bottom: 12px;
        padding-bottom: 8px;
      }}

      /* 资产总额 */
      .total-assets-box .label {{
        font-size: 14px;
      }}
      .total-assets-box .value {{
        font-size: 32px;
      }}
      .total-assets-box .currency {{
        font-size: 15px;
      }}
      .total-breakdown {{
        margin-top: 14px;
        gap: 10px;
      }}
      .breakdown-item {{
        min-width: 0;
        flex: 1 1 calc(50% - 5px);
        padding: 10px 12px;
      }}
      .breakdown-item .b-value {{
        font-size: 17px;
      }}

      /* 投资明细表 */
      .table-wrapper {{
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        margin: 0 -14px;
      }}
      .table-wrapper table {{
        min-width: 580px;
      }}
      table {{ font-size: 13px; }}
      thead th {{
        padding: 10px 8px;
        font-size: 11px;
        letter-spacing: 0.3px;
      }}
      tbody td {{
        padding: 10px 8px;
      }}
      .sub {{ font-size: 11px; }}

      /* 趋势图 */
      #trendChart {{
        height: 280px;
      }}

      /* Tooltip */
      #chartTooltip {{
        font-size: 12px;
        padding: 6px 10px;
      }}

      /* 信号 */
      .signal-item {{
        padding: 12px 12px;
      }}
      .signal-name {{ font-size: 14px; }}
      .signal-detail {{ font-size: 12px; }}
      .suggested-action {{
        padding: 8px 10px;
        font-size: 12px;
      }}

      /* 规则说明 */
      .rules-section h3 {{ font-size: 14px; }}
      .rules-section li {{
        font-size: 13px;
        line-height: 1.8;
      }}
      .rules-section code {{
        font-size: 11px;
        min-width: 36px;
        padding: 2px 6px;
      }}

      /* 免责条款 */
      .disclaimer {{
        padding: 12px 8px;
        font-size: 11px;
      }}
    }}

    /* 超小屏 (<=380px) */
    @media (max-width: 380px) {{
      .header h1 {{ font-size: 18px; }}
      .total-assets-box .value {{ font-size: 26px; }}
      .breakdown-item {{
        flex: 1 1 100%;
      }}
      #trendChart {{ height: 240px; }}
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

    <!-- 第三板块：净值趋势 -->
    <div class="card">
      <h2>净值趋势 (2025年1月至今 · 月末净值)</h2>
      <div class="trend-container">
        <canvas id="trendChart"></canvas>
        <div id="chartTooltip"></div>
      </div>
    </div>

    <!-- 第四板块：规则说明 -->
    <div class="card rules-section">
      <h2>量化信号规则说明</h2>
      <h3>卖出规则</h3>
      <ul>
        <li><code>S-01</code>止盈止损: 累计收益 ≥+15%触发止盈, ≥+25%强止盈; ≤-8%止损预警, ≤-12%强止损</li>
        <li><code>S-02</code>趋势反转: MA5下穿MA20（死叉）</li>
        <li><code>S-04</code>仓位偏离: 当前权重超出目标权重+3%，触发再平衡减仓</li>
        <li><code>S-05</code>急跌熔断: 5日跌幅>15%，暂停自动操作，转人工复核</li>
      </ul>
      <h3>买入规则</h3>
      <ul>
        <li><code>B-02</code>趋势确立: MA5上穿MA20（金叉）</li>
        <li><code>B-03</code>回撤企稳: 从高点回撤15%-25%且近3日波动&lt;1%</li>
        <li><code>B-04</code>现金过多: 现金仓位&gt;30%，建议配置</li>
        <li><code>B-05</code>仓位不足: 当前权重低于目标权重-3%，触发再平衡加仓</li>
      </ul>
      <h3>信号强度</h3>
      <ul>
        <li><code>强</code>≥3条核心规则同时触发，或触及强止盈/止损线 — 立即执行</li>
        <li><code>中</code>2条规则触发 — 分批操作</li>
        <li><code>弱</code>1条规则触发 — 观望预警</li>
      </ul>
    </div>

    <!-- 第五板块：赎回/卖出信号 -->
    <div class="card signal-card sell">
      <h2><span class="icon">🔴</span>赎回/卖出信号</h2>
      {sell_section if sell_section else '<div class="no-signal">暂无卖出信号触发</div>'}
    </div>

    <!-- 第六板块：申购/买入信号 -->
    <div class="card signal-card buy">
      <h2><span class="icon">🟢</span>申购/买入信号</h2>
      {buy_section if buy_section else '<div class="no-signal">暂无买入信号触发</div>'}
    </div>

    <!-- 免责条款 -->
    <div class="disclaimer">
      <p>本页面由量化规则自动生成，所有信号和数据仅供参考，不构成任何投资建议。</p>
      <p>投资有风险，过往业绩不代表未来表现，请根据自身风险承受能力独立决策。</p>
    </div>

  </div>

  <script>
    // ---- 月度净值趋势折线图 (带tooltip) ----
    const trendData = {trend_json};
    const monthLabels = {months_json};

    const canvas = document.getElementById('trendChart');
    const ctx = canvas.getContext('2d');
    const tooltip = document.getElementById('chartTooltip');

    // 存储绘制坐标用于tooltip
    let pointCoords = []; // {{ x, y, month, nav, fid, label, color }}

    function drawChart() {{
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = 400 * dpr;
      ctx.scale(dpr, dpr);

      const W = rect.width;
      const H = 400;
      const padL = 70, padR = 30, padT = 50, padB = 50;
      const chartW = W - padL - padR;
      const chartH = H - padT - padB;

      let allVals = [];
      Object.values(trendData).forEach(f => {{
        f.data.forEach(d => allVals.push(d.nav));
      }});
      if (allVals.length === 0) return;

      const minVal = Math.min(...allVals);
      const maxVal = Math.max(...allVals);
      const valRange = maxVal - minVal;
      const yMin = minVal - valRange * 0.08;
      const yMax = maxVal + valRange * 0.08;
      const yRange = yMax - yMin;

      const n = monthLabels.length;
      const xStep = n > 1 ? chartW / (n - 1) : 0;

      pointCoords = [];

      ctx.clearRect(0, 0, W, H);

      // 网格线
      ctx.strokeStyle = '#e2e8f0';
      ctx.lineWidth = 1;
      ctx.font = '11px -apple-system, sans-serif';
      ctx.fillStyle = '#94a3b8';
      ctx.textAlign = 'right';
      for (let i = 0; i <= 5; i++) {{
        const y = padT + chartH * i / 5;
        const val = yMax - (yRange * i / 5);
        ctx.beginPath();
        ctx.moveTo(padL, y);
        ctx.lineTo(W - padR, y);
        ctx.stroke();
        ctx.fillText(val.toFixed(2), padL - 8, y + 4);
      }}

      // X轴标签
      ctx.textAlign = 'center';
      const labelStep = Math.ceil(n / 12);
      for (let i = 0; i < n; i += labelStep) {{
        const x = padL + xStep * i;
        ctx.fillText(monthLabels[i].substring(5), x, H - padB + 18);
      }}

      // Y轴标题
      ctx.save();
      ctx.translate(16, padT + chartH / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.textAlign = 'center';
      ctx.fillStyle = '#64748b';
      ctx.font = '12px -apple-system, sans-serif';
      ctx.fillText('NAV (USD)', 0, 0);
      ctx.restore();

      // 绘制每条线
      Object.entries(trendData).forEach(([fid, f]) => {{
        const vals = f.data.map(d => d.nav);
        if (vals.length < 1) return;

        ctx.strokeStyle = f.color;
        ctx.lineWidth = 2.5;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';
        ctx.beginPath();
        vals.forEach((v, i) => {{
          const x = padL + xStep * i;
          const y = padT + chartH * (1 - (v - yMin) / yRange);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }});
        ctx.stroke();

        // 数据点 + 存储坐标
        vals.forEach((v, i) => {{
          const x = padL + xStep * i;
          const y = padT + chartH * (1 - (v - yMin) / yRange);
          ctx.fillStyle = f.color;
          ctx.beginPath();
          ctx.arc(x, y, 4, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = '#fff';
          ctx.beginPath();
          ctx.arc(x, y, 2, 0, Math.PI * 2);
          ctx.fill();

          pointCoords.push({{
            x: x, y: y,
            month: f.data[i].month,
            nav: v,
            fid: fid,
            label: f.label,
            color: f.color
          }});
        }});

        // 最后一个点不再标注金额
      }});

      // 图例
      let legendX = padL;
      const legendY = 20;
      Object.entries(trendData).forEach(([fid, f]) => {{
        ctx.fillStyle = f.color;
        ctx.fillRect(legendX, legendY, 14, 3);
        ctx.fillStyle = '#1e293b';
        ctx.font = '13px -apple-system, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(f.label, legendX + 20, legendY + 6);
        legendX += ctx.measureText(f.label).width + 50;
      }});
    }}

    // Tooltip 交互
    canvas.addEventListener('mousemove', function(e) {{
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;

      // 找最近的点
      let closest = null;
      let minDist = 20;
      pointCoords.forEach(p => {{
        const dist = Math.sqrt((p.x - mx) ** 2 + (p.y - my) ** 2);
        if (dist < minDist) {{
          minDist = dist;
          closest = p;
        }}
      }});

      if (closest) {{
        // 只显示鼠标所在折线的单只基金净值
        let html = '<div class="tt-date">' + closest.month + '</div>';
        html += '<div class="tt-line"><span class="tt-dot" style="background:' + closest.color + '"></span>' +
                closest.label + ': $' + closest.nav.toFixed(2) + '</div>';
        tooltip.innerHTML = html;
        tooltip.style.display = 'block';
        tooltip.style.left = (closest.x + 15) + 'px';
        tooltip.style.top = (closest.y - 10) + 'px';
      }} else {{
        tooltip.style.display = 'none';
      }}
    }});

    canvas.addEventListener('mouseleave', function() {{
      tooltip.style.display = 'none';
    }});

    drawChart();
    window.addEventListener('resize', drawChart);
  </script>
</body>
</html>"""

    return html


def _build_signal_section(signals, signal_type):
    """构建信号区块HTML"""
    if not signals:
        return ""

    html = ""
    for sig in signals:
        strength_badge = {
            "strong": '<span style="color:#dc2626;font-weight:700;">[强]</span>',
            "medium": '<span style="color:#b45309;font-weight:700;">[中]</span>',
            "weak": '<span style="color:#64748b;">[弱]</span>',
            "suspended": '<span style="color:#dc2626;">[已暂停]</span>',
        }.get(sig.get("strength", "weak"), "")

        fund_name = sig.get("fund_name", "组合整体")
        html += f"""
        <div class="signal-item {signal_type}">
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
