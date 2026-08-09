#!/usr/bin/env python3
"""
量化信号引擎
基于多维度量化规则生成基金买卖信号，使用动态市值与权重

信号规则体系：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【卖出/赎回信号】
  S-01 止盈止损: 累计收益率触及止盈线(+15%~+25%)或止损线(-8%~-12%)
                 ※ 价格分位数调制：高位时降低止盈门槛，低位时提高止损容忍
  S-02 趋势反转: MA5下穿MA20（死叉），或MA20下穿MA60
  S-03 估值过高: PE分位数 > 80%（危险区）
  S-04 仓位偏离: 持仓权重超出目标权重 +3%以上，触发再平衡减仓
  S-05 急跌熔断: 5个交易日内跌幅超15%，触发人工复核（不自动卖出）
  S-06 历史高位: 价格分位数 > 85%（高位预警）或 > 95%（极端高位，强信号）

【买入/申购信号】
  B-02 趋势确立: MA5上穿MA20（金叉），且成交量放大
  B-03 回撤修复: 净值从高点回撤15%-25%后企稳
  B-04 现金过多: 现金仓位超过30%，建议配置
  B-05 仓位不足: 持仓权重低于目标权重 -3%以上，触发再平衡加仓
  B-06 历史低位: 价格分位数 < 20%（低位机会）或 < 10%（极端低位，强信号）

【价格分位数 Price Percentile Rank】
  分位数 = (当前净值 - 历史最低) / (历史最高 - 历史最低) × 100
  综合日度净值历史和月度净值历史，取最长可用区间计算
  分位数越高，当前价格越接近历史高点，回调风险越大

【信号强度分级】
  强信号(立即执行): ≥3条核心规则同时触发
  中信号(分批操作): 2条规则触发
  弱信号(观望预警): 1条规则触发
"""

import json
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))


class SignalEngine:
    """量化信号引擎 - 使用动态市值与权重"""

    def __init__(self, config, portfolio_data):
        self.config = config
        self.rules = config["signal_rules"]
        self.funds = config["funds"]
        self.cash = config["cash"]
        self.portfolio_data = portfolio_data
        self.total_value = portfolio_data["total_assets"]
        self.fund_market_values = portfolio_data["fund_market_values"]
        self.dynamic_weights = portfolio_data["dynamic_weights"]
        self.cash_value = portfolio_data["cash_value"]

    def calculate_returns(self, current_nav, cost_nav):
        if cost_nav <= 0:
            return 0.0
        return (current_nav - cost_nav) / cost_nav

    def calculate_drawdown(self, nav_history):
        if not nav_history or len(nav_history) < 2:
            return 0.0
        peak = max(nav_history)
        current = nav_history[-1]
        if peak <= 0:
            return 0.0
        return (peak - current) / peak

    def calculate_price_percentile(self, daily_history, monthly_history=None):
        """计算价格分位数 (0-100)
        优先使用月度净值历史（5年回溯，数据源一致），
        月度数据不足时回退到日度历史。
        分位数 = (当前 - 最低) / (最高 - 最低) × 100
        """
        # 优先使用月度历史：数据源一致，覆盖5年区间
        if monthly_history:
            monthly_navs = [m["nav"] for m in monthly_history.get("monthly_nav", [])]
            if len(monthly_navs) >= 5:
                hist_max = max(monthly_navs)
                hist_min = min(monthly_navs)
                current = monthly_navs[-1]
                if hist_max == hist_min:
                    return 50.0
                return (current - hist_min) / (hist_max - hist_min) * 100

        # 回退：使用日度历史
        all_navs = list(daily_history) if daily_history else []
        if len(all_navs) < 5:
            return 50.0
        hist_max = max(all_navs)
        hist_min = min(all_navs)
        current = all_navs[-1]
        if hist_max == hist_min:
            return 50.0
        return (current - hist_min) / (hist_max - hist_min) * 100

    def get_percentile_detail(self, daily_history, monthly_history=None):
        """获取价格分位数的详细信息（用于报告展示）"""
        if monthly_history:
            monthly_navs = [m["nav"] for m in monthly_history.get("monthly_nav", [])]
            if len(monthly_navs) >= 5:
                hist_max = max(monthly_navs)
                hist_min = min(monthly_navs)
                current = monthly_navs[-1]
                source = f"月度历史（{monthly_history.get('start_date', 'N/A')}起，{len(monthly_navs)}个数据点）"
                if hist_max == hist_min:
                    return {"percentile": 50.0, "high": hist_max, "low": hist_min, "current": current, "source": source}
                pct = (current - hist_min) / (hist_max - hist_min) * 100
                return {"percentile": pct, "high": hist_max, "low": hist_min, "current": current, "source": source}

        all_navs = list(daily_history) if daily_history else []
        if len(all_navs) < 5:
            return {"percentile": 50.0, "high": 0, "low": 0, "current": 0, "source": "数据不足"}
        hist_max = max(all_navs)
        hist_min = min(all_navs)
        current = all_navs[-1]
        source = f"日度历史（{len(all_navs)}个数据点）"
        if hist_max == hist_min:
            return {"percentile": 50.0, "high": hist_max, "low": hist_min, "current": current, "source": source}
        pct = (current - hist_min) / (hist_max - hist_min) * 100
        return {"percentile": pct, "high": hist_max, "low": hist_min, "current": current, "source": source}

    def check_price_position(self, fund_id, daily_history, monthly_history=None):
        """S-06 / B-06: 基于历史价格位置生成信号"""
        signals = []
        percentile = self.calculate_price_percentile(daily_history, monthly_history)
        if percentile == 50.0 and len(daily_history) < 5 and not monthly_history:
            return signals

        fund = next((f for f in self.funds if f["id"] == fund_id), None)
        if not fund:
            return signals

        pct_high = self.rules["price_percentile_high"]
        pct_extreme = self.rules["price_percentile_extreme"]
        pct_low = self.rules["price_percentile_low"]
        pct_extreme_low = self.rules["price_percentile_extreme_low"]

        if percentile >= pct_extreme:
            signals.append({
                "rule": "S-06", "name": "历史极端高位（强）",
                "detail": f"{fund['name_cn']} 当前价格分位数 {percentile:.1f}%（高于{pct_extreme}%极端线），处于历史极高位置，回调风险极大，建议立即减仓",
                "action": "sell", "strength": "strong", "score": 35,
                "suggested_action": self._build_redeem_suggestion(fund_id, "strong"),
            })
        elif percentile >= pct_high:
            signals.append({
                "rule": "S-06", "name": "历史高位预警",
                "detail": f"{fund['name_cn']} 当前价格分位数 {percentile:.1f}%（高于{pct_high}%警戒线），接近历史高位，需警惕回调风险",
                "action": "sell", "strength": "medium", "score": 20,
                "suggested_action": self._build_redeem_suggestion(fund_id, "medium"),
            })

        if percentile <= pct_extreme_low:
            signals.append({
                "rule": "B-06", "name": "历史极端低位（强）",
                "detail": f"{fund['name_cn']} 当前价格分位数 {percentile:.1f}%（低于{pct_extreme_low}%极端线），处于历史极低位置，中长期布局良机",
                "action": "buy", "strength": "strong", "score": 35,
                "suggested_action": self._build_buy_suggestion(fund_id),
            })
        elif percentile <= pct_low:
            signals.append({
                "rule": "B-06", "name": "历史低位机会",
                "detail": f"{fund['name_cn']} 当前价格分位数 {percentile:.1f}%（低于{pct_low}%机会线），处于历史低位区间，可考虑逢低布局",
                "action": "buy", "strength": "medium", "score": 20,
            })
        return signals

    def _build_buy_suggestion(self, fund_id):
        """构建买入建议"""
        fund = next((f for f in self.funds if f["id"] == fund_id), None)
        if not fund:
            return None
        current_value = self.fund_market_values.get(fund_id, 0)
        target_value = self.total_value * fund["target_weight"]
        buy_amount = target_value - current_value
        if buy_amount <= 0:
            buy_amount = self.cash_value * 0.1
        return {
            "type": "buy", "fund": fund["name_cn"],
            "amount": round(buy_amount, 2),
            "description": f"建议申购 {fund['name_cn']} 约 ${buy_amount:,.0f}，把握历史低位布局机会",
        }

    def calculate_moving_averages(self, nav_history):
        ma_short = self.rules["ma_short"]
        ma_mid = self.rules["ma_mid"]
        ma_long = self.rules["ma_long"]
        result = {"ma5": None, "ma20": None, "ma60": None}
        if len(nav_history) >= ma_short:
            result["ma5"] = sum(nav_history[-ma_short:]) / ma_short
        if len(nav_history) >= ma_mid:
            result["ma20"] = sum(nav_history[-ma_mid:]) / ma_mid
        if len(nav_history) >= ma_long:
            result["ma60"] = sum(nav_history[-ma_long:]) / ma_long
        return result

    def detect_cross(self, nav_history):
        signals = []
        if len(nav_history) < self.rules["ma_mid"] + 1:
            return signals
        ma_s = self.rules["ma_short"]
        ma_m = self.rules["ma_mid"]
        current_ma5 = sum(nav_history[-ma_s:]) / ma_s
        current_ma20 = sum(nav_history[-ma_m:]) / ma_m
        prev_ma5 = sum(nav_history[-ma_s - 1:-1]) / ma_s
        prev_ma20 = sum(nav_history[-ma_m - 1:-1]) / ma_m
        if prev_ma5 <= prev_ma20 and current_ma5 > current_ma20:
            signals.append({
                "rule": "B-02", "name": "趋势确立（金叉）",
                "detail": f"MA5({current_ma5:.4f})上穿MA20({current_ma20:.4f})，趋势向上确立",
                "action": "buy", "strength": "medium", "score": 25,
            })
        if prev_ma5 >= prev_ma20 and current_ma5 < current_ma20:
            signals.append({
                "rule": "S-02", "name": "趋势反转（死叉）",
                "detail": f"MA5({current_ma5:.4f})下穿MA20({current_ma20:.4f})，趋势向下反转",
                "action": "sell", "strength": "medium", "score": 25,
            })
        return signals

    def check_stop_profit_loss(self, fund_id, current_nav, cost_nav, percentile=None):
        signals = []
        returns = self.calculate_returns(current_nav, cost_nav)
        sp_low = self.rules["stop_profit_low"]
        sp_high = self.rules["stop_profit_high"]
        sl_low = self.rules["stop_loss_low"]
        sl_high = self.rules["stop_loss_high"]

        # 价格位置调制：高位时降低止盈门槛，低位时放宽止损容忍
        pct_ctx = ""
        adj_sp_low = sp_low
        adj_sl_high = sl_high
        if percentile is not None:
            pct_high = self.rules["price_percentile_high"]
            pct_low = self.rules["price_percentile_low"]
            adj_amount = self.rules["stop_profit_adj_high_pos"]
            adj_loss = self.rules["stop_loss_adj_low_pos"]
            if percentile >= pct_high:
                adj_sp_low = sp_low - adj_amount
                pct_ctx = f" [价格分位数{percentile:.0f}%≥{pct_high}%，止盈门槛下调至{adj_sp_low*100:.0f}%]"
            elif percentile <= pct_low:
                adj_sl_high = sl_high - adj_loss
                pct_ctx = f" [价格分位数{percentile:.0f}%≤{pct_low}%，止损容忍度放宽至{adj_sl_high*100:.0f}%]"

        if returns >= sp_high:
            signals.append({
                "rule": "S-01", "name": "止盈信号（强）",
                "detail": f"累计收益率 {returns*100:.1f}% 已超过强止盈线 {sp_high*100:.0f}%，建议赎回至目标仓位{pct_ctx}",
                "action": "sell", "strength": "strong", "score": 40,
                "suggested_action": self._build_redeem_suggestion(fund_id, "strong"),
            })
        elif returns >= adj_sp_low:
            strength = "medium"
            score = 30
            if percentile is not None and percentile >= pct_high:
                strength = "strong"
                score = 38
            signals.append({
                "rule": "S-01", "name": f"止盈信号（{'强·高位调制' if strength == 'strong' else '中'}）",
                "detail": f"累计收益率 {returns*100:.1f}% 触及止盈区间 [{adj_sp_low*100:.0f}%, {sp_high*100:.0f}%]，可考虑分批减仓{pct_ctx}",
                "action": "sell", "strength": strength, "score": score,
                "suggested_action": self._build_redeem_suggestion(fund_id, "medium"),
            })

        if returns <= adj_sl_high:
            signals.append({
                "rule": "S-01", "name": "止损信号（强）",
                "detail": f"累计收益率 {returns*100:.1f}% 已跌破止损线 {adj_sl_high*100:.0f}%，建议立即止损赎回{pct_ctx}",
                "action": "sell", "strength": "strong", "score": 40,
                "suggested_action": self._build_redeem_suggestion(fund_id, "strong_stoploss"),
            })
        elif returns <= sl_low:
            signals.append({
                "rule": "S-01", "name": "止损预警",
                "detail": f"累计收益率 {returns*100:.1f}% 接近止损线 [{sl_low*100:.0f}%, {sl_high*100:.0f}%]，密切关注{pct_ctx}",
                "action": "sell", "strength": "weak", "score": 15,
            })
        return signals

    def _build_redeem_suggestion(self, fund_id, strength):
        fund = next((f for f in self.funds if f["id"] == fund_id), None)
        if not fund:
            return None
        current_value = self.fund_market_values.get(fund_id, 0)
        target_value = self.total_value * fund["target_weight"]
        current_weight = self.dynamic_weights.get(fund_id, 0)

        if strength == "strong":
            redeem_amount = current_value - target_value
            return {
                "type": "redeem", "fund": fund["name_cn"],
                "current_value": round(current_value, 2),
                "target_value": round(target_value, 2),
                "redeem_amount": round(redeem_amount, 2),
                "description": f"建议赎回 {fund['name_cn']} 约 ${redeem_amount:,.0f}，将仓位从 {current_weight*100:.1f}% 减至 {fund['target_weight']*100:.0f}%",
            }
        elif strength == "medium":
            excess = current_value - target_value
            redeem_amount = excess * 0.5
            return {
                "type": "redeem", "fund": fund["name_cn"],
                "current_value": round(current_value, 2),
                "redeem_amount": round(redeem_amount, 2),
                "description": f"建议分批赎回 {fund['name_cn']} 约 ${redeem_amount:,.0f}，逐步向目标仓位 {fund['target_weight']*100:.0f}% 靠拢",
            }
        elif strength == "strong_stoploss":
            bottom_value = self.total_value * 0.05
            redeem_amount = current_value - bottom_value
            return {
                "type": "redeem", "fund": fund["name_cn"],
                "current_value": round(current_value, 2),
                "redeem_amount": round(redeem_amount, 2),
                "description": f"止损赎回 {fund['name_cn']} 约 ${redeem_amount:,.0f}，仅保留5%底仓观察",
            }
        return None

    def check_weight_deviation(self, fund_id):
        signals = []
        fund = next((f for f in self.funds if f["id"] == fund_id), None)
        if not fund:
            return signals
        current_weight = self.dynamic_weights.get(fund_id, 0)
        deviation = current_weight - fund["target_weight"]
        threshold = self.rules["weight_deviation_threshold"]

        if deviation > threshold:
            current_value = self.fund_market_values.get(fund_id, 0)
            target_value = self.total_value * fund["target_weight"]
            excess = current_value - target_value
            signals.append({
                "rule": "S-04", "name": "仓位超配",
                "detail": f"{fund['name_cn']} 当前权重 {current_weight*100:.1f}% 超出目标 {fund['target_weight']*100:.0f}% 达 {deviation*100:.1f}%，建议再平衡减仓约 ${excess:,.0f}",
                "action": "sell", "strength": "medium", "score": 20,
                "suggested_action": {
                    "type": "rebalance_sell", "fund": fund["name_cn"],
                    "amount": round(excess, 2),
                    "description": f"再平衡: 赎回 {fund['name_cn']} 约 ${excess:,.0f}，使权重回归 {fund['target_weight']*100:.0f}%",
                },
            })
        elif deviation < -threshold:
            current_value = self.fund_market_values.get(fund_id, 0)
            target_value = self.total_value * fund["target_weight"]
            shortfall = target_value - current_value
            signals.append({
                "rule": "B-05", "name": "仓位低配",
                "detail": f"{fund['name_cn']} 当前权重 {current_weight*100:.1f}% 低于目标 {fund['target_weight']*100:.0f}% 达 {abs(deviation)*100:.1f}%，建议再平衡加仓约 ${shortfall:,.0f}",
                "action": "buy", "strength": "medium", "score": 20,
                "suggested_action": {
                    "type": "rebalance_buy", "fund": fund["name_cn"],
                    "amount": round(shortfall, 2),
                    "description": f"再平衡: 申购 {fund['name_cn']} 约 ${shortfall:,.0f}，使权重回归 {fund['target_weight']*100:.0f}%",
                },
            })
        return signals

    def check_cash_position(self):
        signals = []
        cash_weight = self.dynamic_weights.get("cash", 0)
        high_threshold = self.rules["cash_high_threshold"]
        low_threshold = self.rules["cash_low_threshold"]

        if cash_weight > high_threshold:
            excess_cash = self.cash_value - self.total_value * self.cash["target_weight"]
            signals.append({
                "rule": "B-04", "name": "现金仓位过高",
                "detail": f"现金和存款占比 {cash_weight*100:.1f}% 超过阈值 {high_threshold*100:.0f}%，持有闲置现金约 ${self.cash_value:,.0f}，建议配置至低配基金或优质固收产品",
                "action": "buy", "strength": "medium", "score": 20,
                "suggested_action": {
                    "type": "deploy_cash", "amount": round(excess_cash, 2),
                    "description": f"建议将约 ${excess_cash:,.0f} 现金配置至低配基金或美元货币基金（年化约4%）",
                },
            })
        elif cash_weight < low_threshold:
            signals.append({
                "rule": "S-05", "name": "现金仓位过低",
                "detail": f"现金和存款占比 {cash_weight*100:.1f}% 低于阈值 {low_threshold*100:.0f}%，防御厚度不足，建议适当减仓补充现金",
                "action": "sell", "strength": "weak", "score": 10,
            })
        return signals

    def check_drawdown(self, fund_id, nav_history):
        signals = []
        if len(nav_history) < 5:
            return signals
        drawdown = self.calculate_drawdown(nav_history)
        buy_low = self.rules["drawdown_buy_low"]
        buy_high = self.rules["drawdown_buy_high"]

        if buy_low <= drawdown <= buy_high:
            if len(nav_history) >= 3:
                recent = nav_history[-3:]
                volatility = (max(recent) - min(recent)) / max(recent) if max(recent) > 0 else 0
                if volatility < 0.01:
                    fund = next((f for f in self.funds if f["id"] == fund_id), None)
                    if fund:
                        signals.append({
                            "rule": "B-03", "name": "回撤企稳买入",
                            "detail": f"{fund['name_cn']} 从高点回撤 {drawdown*100:.1f}%，近3日波动仅 {volatility*100:.2f}%，已企稳可考虑逢低布局",
                            "action": "buy", "strength": "medium", "score": 25,
                        })

        if len(nav_history) >= 6:
            recent_drop = (nav_history[-6] - nav_history[-1]) / nav_history[-6] if nav_history[-6] > 0 else 0
            if recent_drop > self.rules["circuit_breaker_drop"]:
                fund = next((f for f in self.funds if f["id"] == fund_id), None)
                if fund:
                    signals.append({
                        "rule": "S-05", "name": "急跌熔断（暂停自动操作）",
                        "detail": f"{fund['name_cn']} 近5日跌幅 {recent_drop*100:.1f}% 超过熔断线 {self.rules['circuit_breaker_drop']*100:.0f}%，暂停自动卖出，转为人工复核",
                        "action": "hold", "strength": "strong", "score": 0,
                    })
        return signals

    def generate_all_signals(self, nav_data, nav_history_data, monthly_nav_history=None):
        all_signals = []
        percentile_details = {}

        for fund in self.funds:
            fund_id = fund["id"]
            fund_name = fund["name_cn"]
            current_nav = nav_data[fund_id]["nav"]
            cost_nav = fund["cost_nav"]

            fund_nav_history = []
            if fund_id in nav_history_data:
                fund_nav_history = nav_history_data[fund_id]
            if not fund_nav_history or fund_nav_history[-1] != current_nav:
                fund_nav_history = fund_nav_history + [current_nav]

            # 计算价格分位数（优先使用月度5年历史）
            monthly_data = monthly_nav_history.get(fund_id) if monthly_nav_history else None
            percentile = self.calculate_price_percentile(fund_nav_history, monthly_data)
            pct_detail = self.get_percentile_detail(fund_nav_history, monthly_data)
            percentile_details[fund_id] = {
                "fund_name": fund_name,
                "percentile": pct_detail["percentile"],
                "hist_high": pct_detail["high"],
                "hist_low": pct_detail["low"],
                "current_nav": pct_detail["current"],
                "source": pct_detail["source"],
            }

            fund_signals = []
            fund_signals.extend(self.check_stop_profit_loss(fund_id, current_nav, cost_nav, percentile))
            fund_signals.extend(self.detect_cross(fund_nav_history))
            fund_signals.extend(self.check_weight_deviation(fund_id))
            fund_signals.extend(self.check_drawdown(fund_id, fund_nav_history))
            fund_signals.extend(self.check_price_position(fund_id, fund_nav_history, monthly_data))

            for sig in fund_signals:
                sig["fund_id"] = fund_id
                sig["fund_name"] = fund_name
                all_signals.append(sig)

        all_signals.extend(self.check_cash_position())

        sell_signals = [s for s in all_signals if s["action"] == "sell"]
        buy_signals = [s for s in all_signals if s["action"] == "buy"]
        hold_signals = [s for s in all_signals if s["action"] == "hold"]

        if hold_signals:
            for s in sell_signals:
                s["strength"] = "suspended"
                s["detail"] = "[熔断保护] " + s["detail"]

        summary = self._build_signal_summary(sell_signals, buy_signals, hold_signals)

        return {
            "signals": all_signals,
            "sell_signals": sell_signals,
            "buy_signals": buy_signals,
            "hold_signals": hold_signals,
            "summary": summary,
            "percentile_details": percentile_details,
            "generated_at": datetime.now(CST).isoformat(),
        }

    def _build_signal_summary(self, sell_signals, buy_signals, hold_signals):
        sell_count = len(sell_signals)
        buy_count = len(buy_signals)
        hold_count = len(hold_signals)
        strong_sells = [s for s in sell_signals if s.get("strength") == "strong"]
        strong_buys = [s for s in buy_signals if s.get("strength") == "strong"]

        if hold_count > 0:
            overall = "HOLD (熔断保护)"
            overall_detail = "市场出现急跌，自动交易已暂停，建议人工复核后决策"
        elif strong_sells:
            overall = "SELL"
            overall_detail = f"检测到 {len(strong_sells)} 个强卖出信号，建议立即执行赎回操作"
        elif strong_buys:
            overall = "BUY"
            overall_detail = f"检测到 {len(strong_buys)} 个强买入信号，建议把握申购机会"
        elif sell_count > 0 and buy_count > 0:
            overall = "REBALANCE"
            overall_detail = f"同时检测到 {sell_count} 个卖出信号和 {buy_count} 个买入信号，建议进行组合再平衡"
        elif sell_count > 0:
            overall = "CAUTION"
            overall_detail = f"检测到 {sell_count} 个卖出信号（无强信号），建议关注但暂不急操作"
        elif buy_count > 0:
            overall = "OPPORTUNITY"
            overall_detail = f"检测到 {buy_count} 个买入信号（无强信号），可考虑小仓位布局"
        else:
            overall = "HOLD"
            overall_detail = "无买卖信号触发，维持当前持仓"

        return {
            "overall_signal": overall,
            "overall_detail": overall_detail,
            "sell_count": sell_count,
            "buy_count": buy_count,
            "hold_count": hold_count,
            "strong_sell_count": len(strong_sells),
            "strong_buy_count": len(strong_buys),
        }
