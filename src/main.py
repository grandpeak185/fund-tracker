#!/usr/bin/env python3
"""
主运行脚本
串联: 净值抓取 → 信号生成 → HTML报告生成 → 输出

此脚本由 GitHub Actions 每天北京时间12:00自动调用
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

# 添加src目录到path
sys.path.insert(0, str(Path(__file__).parent))

from fetch_nav import fetch_all_nav, save_nav_history, load_nav_history
from signal_engine import SignalEngine
from generate_report import generate_html

CST = timezone(timedelta(hours=8))


def main():
    print("=" * 60)
    print("  境外基金投资组合监控 - 每日更新")
    print(f"  运行时间: {datetime.now(CST).strftime('%Y-%m-%d %H:%M:%S CST')}")
    print("=" * 60)

    # 1. 加载配置
    config_path = Path(__file__).parent.parent / "config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    print("\n[1/4] 配置加载完成")
    print(f"  总盘子: ${config['portfolio']['total_value_usd']:,.2f} USD")
    print(f"  基金数量: {len(config['funds'])}")

    # 2. 抓取最新净值
    print("\n[2/4] 开始抓取净值...")
    nav_data = fetch_all_nav()

    # 3. 保存净值历史
    history = save_nav_history(nav_data, str(config_path.parent / "data" / "nav_history.json"))

    # 提取各基金的历史净值序列
    nav_history_series = {}
    for fund in config["funds"]:
        fid = fund["id"]
        nav_history_series[fid] = []
        for record in history:
            if fid in record.get("funds", {}):
                nav_history_series[fid].append(record["funds"][fid]["nav"])

    # 4. 生成信号
    print("\n[3/4] 生成量化信号...")
    engine = SignalEngine(config)
    signal_result = engine.generate_all_signals(nav_data, nav_history_series)

    summary = signal_result["summary"]
    print(f"  综合信号: {summary['overall_signal']}")
    print(f"  {summary['overall_detail']}")
    print(f"  卖出信号: {summary['sell_count']} (强: {summary['strong_sell_count']})")
    print(f"  买入信号: {summary['buy_count']} (强: {summary['strong_buy_count']})")
    print(f"  熔断/观望: {summary['hold_count']}")

    # 打印信号详情
    for sig in signal_result["signals"]:
        strength = sig.get("strength", "weak")
        action = sig["action"]
        fund = sig.get("fund_name", "组合")
        print(f"    [{sig['rule']}] [{strength}] [{action}] {fund}: {sig['name']}")
        if sig.get("suggested_action"):
            print(f"      → {sig['suggested_action']['description']}")

    # 5. 加载月度净值历史数据
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
    html_content = generate_html(config, nav_data, signal_result, monthly_nav_history)

    # 输出到 index.html
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
        "summary": summary,
        "signals": signal_result["signals"],
    })
    signal_log = signal_log[-90:]  # 保留90天

    with open(signal_log_path, "w", encoding="utf-8") as f:
        json.dump(signal_log, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print("  ✅ 更新完成!")
    print(f"  输出文件: {output_path}")
    print(f"  信号记录: {signal_log_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
