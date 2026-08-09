#!/usr/bin/env python3
"""
主运行脚本
串联: 净值抓取 → 动态市值计算 → 信号生成 → HTML报告生成 → 输出

此脚本由 GitHub Actions 每天、北京时间凌晨3-7点自动调用
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from fetch_nav import fetch_all_nav, save_nav_history
from signal_engine import SignalEngine
from generate_report import generate_html

CST = timezone(timedelta(hours=8))


def calculate_market_values(config, nav_data):
    """根据最新净值动态计算各基金市值、权重和资产总额"""
    cash_value = config["cash"]["amount"]

    fund_market_values = {}
    total_fund_value = 0.0

    for fund in config["funds"]:
        fid = fund["id"]
        current_nav = nav_data[fid]["nav"]
        cost_nav = fund["cost_nav"]
        cost_investment = fund["cost_investment"]

        # 当前市值 = 初始投资额 × (当前净值 / 成本净值)
        market_value = cost_investment * (current_nav / cost_nav) if cost_nav > 0 else 0
        fund_market_values[fid] = market_value
        total_fund_value += market_value

    total_assets = total_fund_value + cash_value

    # 计算动态权重
    dynamic_weights = {}
    for fund in config["funds"]:
        fid = fund["id"]
        dynamic_weights[fid] = fund_market_values[fid] / total_assets if total_assets > 0 else 0
    dynamic_weights["cash"] = cash_value / total_assets if total_assets > 0 else 0

    return {
        "fund_market_values": fund_market_values,
        "cash_value": cash_value,
        "total_assets": total_assets,
        "dynamic_weights": dynamic_weights,
    }


def main():
    print("=" * 60)
    print("  Overseas Treasury - 每日更新")
    print(f"  运行时间: {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S CST')}")
    print("=" * 60)

    # 1. 加载配置
    config_path = Path(__file__).parent.parent / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    print("\n[1/4] 配置加载完成")
    print(f"  基金数量: {len(config['funds'])}")
    print(f"  现金金额: ${config['cash']['amount']:,.0f}")

    # 2. 抓取最新净值
    print("\n[2/4] 开始抓取净值...")
    nav_data = fetch_all_nav()

    # 保存净值历史
    history = save_nav_history(nav_data, str(config_path.parent / "data" / "nav_history.json"))

    nav_history_series = {}
    for fund in config["funds"]:
        fid = fund["id"]
        nav_history_series[fid] = []
        for record in history:
            if fid in record.get("funds", {}):
                nav_history_series[fid].append(record["funds"][fid]["nav"])

    # 3. 计算动态市值与权重
    portfolio_data = calculate_market_values(config, nav_data)
    print(f"\n  资产总额: ${portfolio_data['total_assets']:,.2f}")
    for fund in config["funds"]:
        fid = fund["id"]
        mv = portfolio_data["fund_market_values"][fid]
        w = portfolio_data["dynamic_weights"][fid]
        print(f"  {fund['name_cn']}: ${mv:,.0f} ({w*100:.1f}%)")
    print(f"  现金和存款: ${portfolio_data['cash_value']:,.0f} ({portfolio_data['dynamic_weights']['cash']*100:.1f}%)")

    # 4. 生成信号
    print("\n[3/4] 生成量化信号...")
    engine = SignalEngine(config, portfolio_data)
    signal_result = engine.generate_all_signals(nav_data, nav_history_series)

    summary = signal_result["summary"]
    print(f"  综合信号: {summary['overall_signal']}")
    print(f"  {summary['overall_detail']}")
    print(f"  卖出信号: {summary['sell_count']} (强: {summary['strong_sell_count']})")
    print(f"  买入信号: {summary['buy_count']} (强: {summary['strong_buy_count']})")
    print(f"  熔断/观望: {summary['hold_count']}")

    for sig in signal_result["signals"]:
        strength = sig.get("strength", "weak")
        action = sig["action"]
        fund = sig.get("fund_name", "组合")
        print(f"    [{sig['rule']}] [{strength}] [{action}] {fund}: {sig['name']}")
        if sig.get("suggested_action"):
            print(f"      → {sig['suggested_action']['description']}")

    # 5. 加载月度净值历史
    monthly_nav_path = config_path.parent / "data" / "monthly_nav_history.json"
    monthly_nav_history = {}
    if monthly_nav_path.exists():
        with open(monthly_nav_path, "r", encoding="utf-8") as f:
            try:
                monthly_nav_history = json.load(f)
            except json.JSONDecodeError:
                monthly_nav_history = {}
    print(f"  月度净值历史: {sum(len(v.get('monthly_nav', [])) for v in monthly_nav_history.values())} 条记录")

    # 6. 生成HTML报告
    print("\n[4/4] 生成HTML报告...")
    html_content = generate_html(config, nav_data, signal_result, monthly_nav_history, portfolio_data)

    output_path = config_path.parent / "index.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"  ✓ 报告已生成: {output_path}")

    # 保存信号记录
    signal_log_path = config_path.parent / "data" / "signal_log.json"
    signal_log = []
    if signal_log_path.exists():
        with open(signal_log_path, "r", encoding="utf-8") as f:
            try:
                signal_log = json.load(f)
            except json.JSONDecodeError:
                signal_log = []

    signal_log.append({
        "date": datetime.now(CST).strftime("%Y-%m-%d"),
        "timestamp": datetime.now(CST).isoformat(),
        "nav_data": nav_data,
        "portfolio": portfolio_data,
        "summary": summary,
        "signals": signal_result["signals"],
    })
    signal_log = signal_log[-90:]

    with open(signal_log_path, "w", encoding="utf-8") as f:
        json.dump(signal_log, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print("  ✅ 更新完成!")
    print(f"  输出文件: {output_path}")
    print(f"  信号记录: {signal_log_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
