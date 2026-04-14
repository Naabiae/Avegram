"""
SignalBot v2 - Batch Token Scanner
Scans trending/new tokens, generates signals for each, filters by confidence > 60%

Usage:
    export AVE_API_KEY=your_key
    export API_PLAN=free
    python signal_bot.py --scan-signals --chain bsc --min-confidence 60
    python signal_bot.py --scan-signals --chain bsc --limit 50 --output json
    python signal_bot.py --scan-wallets --chain bsc --min-confidence 60
"""

import argparse
import asyncio
import json
import sys

AVENUE_SCRIPTS = "/home/workspace/ave-cloud-skill/scripts"
sys.path.insert(0, AVENUE_SCRIPTS)

from ave.config import get_api_key, get_api_plan
from ave.http import api_get, api_post
from ave.output import response_ok


def generate_signal(tok: dict) -> dict:
    price = float(tok.get("current_price_usd") or tok.get("price") or 0)
    if price == 0:
        return {"signal": None}

    price_change_1h = float(tok.get("token_price_change_1h", 0) or 0)
    price_change_4h = float(tok.get("token_price_change_4h", 0) or 0)
    price_change_24h = float(tok.get("token_price_change_24h", 0) or 0)

    volume_1h = float(tok.get("token_tx_volume_usd_1h", 0) or 0)
    volume_24h = float(tok.get("token_tx_volume_usd_24h", 0) or 0)
    liquidity = float(tok.get("main_pair_tvl") or tok.get("tvl") or 0)

    buy_count_1h = int(tok.get("token_buy_tx_count_1h", 0) or 0)
    sell_count_1h = int(tok.get("token_sell_tx_count_1h", 0) or 0)
    makers_1h = int(tok.get("token_makers_1h", 0) or 0)

    total_txs_1h = buy_count_1h + sell_count_1h
    buy_pressure = buy_count_1h / max(total_txs_1h, 1)

    conf = 0
    if liquidity > 100000:
        conf += 20
    elif liquidity > 20000:
        conf += 10
    if volume_24h > 1000000:
        conf += 20
    elif volume_24h > 100000:
        conf += 10
    if makers_1h > 500:
        conf += 15
    elif makers_1h > 100:
        conf += 8
    if buy_pressure > 0.6:
        conf += 15
    elif buy_pressure < 0.4:
        conf -= 10
    if price_change_4h > 20:
        conf += 10
    elif price_change_4h < -20:
        conf += 15
    if price_change_1h > 10:
        conf += 10
    if liquidity > 500000 and buy_pressure > 0.55:
        conf += 10
    conf = max(0, min(100, conf))

    # ATR: use 24h range from pair low/high (more stable than raw price change %)
    # Cap extreme momentum: new listings can have 100000%+ change but real ATR is much smaller
    pair_data = tok.get("pairs", [{}])[0] if tok.get("pairs") else {}
    low_24h = float(pair_data.get("low_u", 0) or 0)
    high_24h = float(pair_data.get("high_u", 0) or 0)
    
    if low_24h > 0 and high_24h > low_24h:
        atr_pct = ((high_24h - low_24h) / low_24h) * 100
    else:
        # Fallback: cap extreme price changes at 50% to avoid absurd TP/SL
        raw_change = abs(price_change_24h)
        if raw_change > 50:
            raw_change = 50  # cap at 50% even for new listings
        atr_pct = max(raw_change * 0.6, 5)  # ATR = 60% of price move, min 5%
    
    # TP/SL: standard ATR-based zones
    tp1 = round(price * (1 + atr_pct / 100), 8)
    tp2 = round(price * (1 + atr_pct * 1.5 / 100), 8)
    sl = round(price * (1 - atr_pct * 0.6 / 100), 8)

    signal = "WATCH"
    if buy_pressure > 0.58 and price_change_1h > -5:
        signal = "BUY"
    elif buy_pressure < 0.42 and price_change_1h > 5:
        signal = "SELL"
    elif price_change_4h < -30 and buy_pressure > 0.55:
        signal = "BUY"
    elif price_change_4h > 50:
        signal = "SELL"

    return {
        "signal": signal,
        "entry": round(price, 8),
        "tp1": tp1,
        "tp2": tp2,
        "sl": sl,
        "confidence": conf,
        "momentum_1h": round(price_change_1h, 2),
        "momentum_4h": round(price_change_4h, 2),
        "momentum_24h": round(price_change_24h, 2),
        "volume_24h": round(volume_24h, 2),
        "liquidity": round(liquidity, 2),
        "buy_pressure": round(buy_pressure * 100, 1),
        "makers_1h": makers_1h,
        "token_address": tok.get("token"),
        "name": tok.get("name"),
        "symbol": tok.get("symbol"),
        "chain": tok.get("chain"),
        "ave_pro_link": f"https://pro.ave.ai/token/{tok.get('token')}-{tok.get('chain')}",
    }


async def scan_tokens(chain: str, limit: int = 50, min_confidence: int = 60) -> list:
    tokens = []
    trending_resp = await api_get("/tokens/trending", {"chain": chain, "limit": limit})
    if response_ok(trending_resp.json()):
        tokens = trending_resp.json().get("data", {}).get("tokens", [])

    new_resp = await api_get("/tokens/new", {"chain": chain, "limit": 20})
    if response_ok(new_resp.json()):
        new_toks = new_resp.json().get("data", {}).get("tokens", [])
        existing = {t.get("token") for t in tokens}
        tokens.extend([t for t in new_toks if t.get("token") not in existing])

    signals = []
    for tok in tokens:
        try:
            sig = generate_signal(tok)
            if sig["signal"] and sig["confidence"] >= min_confidence:
                signals.append(sig)
        except Exception:
            continue

    signals.sort(key=lambda x: x["confidence"], reverse=True)
    return signals


async def scan_wallet_signals(chain: str, min_confidence: int = 60) -> list:
    resp = await api_get("/address/smart_wallet/list", {
        "chain": chain,
        "sort": "total_profit_rate",
        "sort_dir": "desc",
        "pageSize": 20
    })

    if not response_ok(resp.json()):
        return []

    wallets = resp.json().get("data", [])
    signals = []

    for wallet in wallets:
        wallet_addr = wallet.get("wallet_address")
        pos_resp = await api_get("/address/walletinfo/tokens", {
            "wallet_address": wallet_addr,
            "chain": chain,
            "sort": "profit_pct",
            "sort_dir": "desc",
            "pageSize": 5
        })

        if response_ok(pos_resp.json()):
            positions = pos_resp.json().get("data", [])
            for pos in positions:
                try:
                    price = float(pos.get("current_price", 0) or 0)
                    profit_pct = float(pos.get("profit_pct", 0) or 0)
                    volume_24h = float(pos.get("volume_24h", 0) or 0)
                    liquidity = float(pos.get("liquidity", 0) or 0)

                    if price == 0:
                        continue

                    conf = 0
                    if profit_pct > 100:
                        conf += 30
                    elif profit_pct > 50:
                        conf += 15
                    if volume_24h > 100000:
                        conf += 20
                    if liquidity > 50000:
                        conf += 15
                    conf = min(100, conf)

                    if conf >= min_confidence:
                        atr = max(abs(profit_pct) * 0.5, 5)
                        dp = min(8, max(2, 6)) if price < 1 else 6
                        sig = {
                            "signal": "BUY" if profit_pct > 0 else "SELL",
                            "entry": round(price, dp),
                            "tp1": round(price * (1 + atr / 100), dp),
                            "tp2": round(price * (1 + atr * 1.5 / 100), dp),
                            "sl": round(price * (1 - atr * 0.7 / 100), dp),
                            "confidence": conf,
                            "profit_pct": round(profit_pct, 2),
                            "volume_24h": round(volume_24h, 2),
                            "liquidity": round(liquidity, 2),
                            "wallet_address": wallet_addr[:10] + "...",
                            "token_address": pos.get("token_address"),
                            "symbol": pos.get("symbol"),
                            "chain": chain,
                            "ave_pro_link": f"https://pro.ave.ai/token/{pos.get('token_address')}-{chain}",
                        }
                        signals.append(sig)
                except Exception:
                    continue

    signals.sort(key=lambda x: x["confidence"], reverse=True)
    return signals


async def main():
    parser = argparse.ArgumentParser(description="SignalBot v2")
    parser.add_argument("--scan-signals", action="store_true")
    parser.add_argument("--scan-wallets", action="store_true")
    parser.add_argument("--check-token", dest="token")
    parser.add_argument("--track-wallet", dest="wallet")
    parser.add_argument("--chain", default="bsc", choices=["bsc", "eth", "base", "solana"])
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--min-confidence", type=int, default=60)
    parser.add_argument("--output", choices=["json", "text"], default="text")
    args = parser.parse_args()

    print(f"SignalBot v2 | Chain: {args.chain} | Min conf: {args.min_confidence}%", file=sys.stderr)

    if args.scan_signals:
        signals = await scan_tokens(args.chain, args.limit, args.min_confidence)
        print(f"\n=== SCAN COMPLETE: {len(signals)} signals above {args.min_confidence}% confidence ===")
        if args.output == "json":
            print(json.dumps(signals, indent=2))
        else:
            if not signals:
                print("No signals met threshold. Try lowering --min-confidence")
            for s in signals:
                emoji = "🟢" if s["signal"] == "BUY" else "🔴" if s["signal"] == "SELL" else "🟡"
                print(f"\n{emoji} [{s['confidence']}%] {s['symbol']} ({s['chain']})")
                print(f"   {s['signal']} | Entry: ${s['entry']} | TP1: ${s['tp1']} | TP2: ${s['tp2']} | SL: ${s['sl']}")
                print(f"   1h: {s['momentum_1h']:+.2f}% | 4h: {s['momentum_4h']:+.2f}% | 24h: {s['momentum_24h']:+.2f}%")
                print(f"   Vol: ${s['volume_24h']:,.0f} | Liq: ${s['liquidity']:,.0f} | Makers: {s['makers_1h']}")
                print(f"   Buy: {s['buy_pressure']}% | {s['ave_pro_link']}")

    elif args.scan_wallets:
        signals = await scan_wallet_signals(args.chain, args.min_confidence)
        print(f"\n=== WALLET SCAN: {len(signals)} signals ===")
        if args.output == "json":
            print(json.dumps(signals, indent=2))
        else:
            if not signals:
                print("No wallet signals met threshold.")
            for s in signals:
                print(f"\n🧠 [{s['confidence']}%] {s['symbol']} | {s['signal']} | Profit: {s['profit_pct']:+.1f}%")
                print(f"   Entry: ${s['entry']} | TP1: ${s['tp1']} | TP2: ${s['tp2']} | SL: ${s['sl']}")
                print(f"   Wallet: {s['wallet_address']}")
                print(f"   {s['ave_pro_link']}")

    elif args.token:
        token_id = f"{args.token}-{args.chain}"
        risk_resp = await api_get(f"/contracts/{token_id}")
        score = 100
        checks = {}
        if response_ok(risk_resp.json()):
            r = risk_resp.json().get("data", {})
            checks["is_honeypot"] = r.get("is_honeypot")
            checks["has_not_renounced"] = r.get("has_not_renounced")
            checks["has_not_audited"] = r.get("has_not_audited")
            checks["is_lp_not_locked"] = r.get("is_lp_not_locked")
            checks["has_black_method"] = r.get("has_black_method")
            if r.get("is_honeypot"):
                score -= 50
            if r.get("has_not_audited"):
                score -= 10
            if r.get("is_lp_not_locked"):
                score -= 15
            if r.get("has_black_method"):
                score -= 30

        sig_label = "🟢 SAFE" if score >= 70 else "🟡 CAUTION" if score >= 40 else "🔴 UNSAFE"
        print(f"\n=== SAFETY: {score}/100 {sig_label} ===")
        for k, v in checks.items():
            print(f"  {k}: {v}")

        new_resp = await api_get("/tokens/trending", {"chain": args.chain, "limit": 100})
        tok_data = None
        if response_ok(new_resp.json()):
            for t in new_resp.json().get("data", {}).get("tokens", []):
                if args.token.lower() in t.get("token", "").lower():
                    tok_data = t
                    break
        if not tok_data:
            t_resp = await api_get(f"/tokens/{token_id}")
            if response_ok(t_resp.json()):
                tok_data = t_resp.json().get("data", {}).get("token", {})

        if tok_data:
            sig = generate_signal(tok_data)
            print(f"\n=== SIGNAL ===")
            print(f"Signal: {sig['signal']} | Confidence: {sig['confidence']}%")
            print(f"Entry: ${sig['entry']} | TP1: ${sig['tp1']} | TP2: ${sig['tp2']} | SL: ${sig['sl']}")
            print(f"1h: {sig['momentum_1h']:+.2f}% | 4h: {sig['momentum_4h']:+.2f}% | 24h: {sig['momentum_24h']:+.2f}%")
            print(f"Vol: ${sig['volume_24h']:,.0f} | Liq: ${sig['liquidity']:,.0f}")
            print(f"Link: {sig['ave_pro_link']}")

    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())