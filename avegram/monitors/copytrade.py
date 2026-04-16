import asyncio
import hashlib

from ave.http import api_get

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..db import load_copy_trades, load_users, save_copy_trades, db_log_error, db_heartbeat_ok, db_heartbeat_error, db_upsert_token_meta, db_save_pending_retry
from ..proxy import proxy_get, send_swap_order
from ..utils import get_bsc_address

async def monitor_copy_trades(app):
    usdt_addr = "0x55d398326f99059fF775485246999027B3197955"
    while True:
        try:
            copy_trades = load_copy_trades()
            users = load_users()
            changed = False

            for uid, targets in list(copy_trades.items()):
                if uid not in users or not users[uid].get("assets_id"):
                    continue
                aid = users[uid]["assets_id"]
                bsc_addr = get_bsc_address(users[uid])

                for target_addr, cfg in list(targets.items()):
                    if cfg.get("status") != "active":
                        continue

                    chain = cfg.get("chain", "bsc")
                    r = await api_get("/address/tx", {"wallet_address": target_addr, "chain": chain, "pageSize": 5, "pageNO": 0})
                    if r.status_code != 200:
                        continue
                    data = r.json()
                    txs_data = data.get("data", {})
                    if isinstance(txs_data, dict):
                        txs = txs_data.get("result", [])
                    elif isinstance(txs_data, list):
                        txs = txs_data
                    else:
                        continue
                    if not txs:
                        continue

                    latest_tx = txs[0]
                    tx_hash = latest_tx.get("transaction", "")
                    tx_time = int(latest_tx.get("time") or latest_tx.get("timestamp") or 0)
                    tx_block = int(latest_tx.get("block") or latest_tx.get("block_number") or 0)

                    if not cfg.get("last_tx_hash"):
                        cfg["last_tx_hash"] = tx_hash
                        cfg["last_tx_time"] = tx_time
                        cfg["last_tx_block"] = tx_block
                        changed = True
                        continue

                    if tx_hash and tx_hash == cfg.get("last_tx_hash"):
                        continue
                    if (not tx_hash) and tx_time and tx_time <= int(cfg.get("last_tx_time") or 0) and tx_block and tx_block <= int(cfg.get("last_tx_block") or 0):
                        continue

                    cfg["last_tx_hash"] = tx_hash
                    cfg["last_tx_time"] = tx_time
                    cfg["last_tx_block"] = tx_block
                    changed = True

                    # Determine swap direction from the Ave transaction structure.
                    # Ave returns: from_symbol/from_address (token spent) → to_symbol/to_address (token received).
                    # A BUY means the wallet spent a stablecoin/BNB and received a non-stable token.
                    # A SELL means the wallet spent a non-stable token and received a stablecoin/BNB.
                    STABLE_ADDRS = {
                        usdt_addr.lower(),
                        "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",  # WBNB
                        "0xe9e7cea3dedca5984780bafc599bd69add087d56",  # BUSD
                        "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d",  # USDC
                    }
                    from_addr_field = (latest_tx.get("from_address") or "").lower()
                    to_addr_field = (latest_tx.get("to_address") or "").lower()
                    to_sym = latest_tx.get("to_symbol", "")
                    from_sym = latest_tx.get("from_symbol", "")

                    # is_buy: wallet spent a stable and received a non-stable
                    is_buy = from_addr_field in STABLE_ADDRS and to_addr_field not in STABLE_ADDRS
                    is_sell = to_addr_field in STABLE_ADDRS and from_addr_field not in STABLE_ADDRS
                    if not is_buy and not is_sell:
                        # Can't determine direction – skip
                        continue

                    tx_type = "buy" if is_buy else "sell"
                    token_sym = to_sym if is_buy else from_sym
                    tx_token_addr = to_addr_field if is_buy else from_addr_field

                    if not tx_token_addr or tx_token_addr in STABLE_ADDRS:
                        continue

                    try:
                        trade_amount = cfg["max_usdt_per_trade"]

                        if tx_type == "buy":
                            in_amount_wei = str(int(trade_amount * 1e18))
                            qr = send_swap_order(uid, chain, aid, usdt_addr, tx_token_addr, in_amount_wei, "buy", slippage="1500", context={"source": "copy_trade", "target": target_addr})

                            if qr.get("status") in (200, 0):
                                msg = f"👥 **Copied Buy**\nTarget: `{target_addr[:10]}...`\nBought: ~${trade_amount} of {token_sym}\nOrder: `{qr.get('data', {}).get('id', '')}`"
                                await app.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
                            else:
                                err_msg = qr.get('msg', 'Unknown Error')
                                rkey = hashlib.md5(f"{uid}{chain}{usdt_addr}{tx_token_addr}{in_amount_wei}buy".encode()).hexdigest()[:10]
                                db_save_pending_retry(rkey, uid, chain, aid, usdt_addr, tx_token_addr, in_amount_wei, "buy")
                                kb = [[
                                    InlineKeyboardButton("🔄 Retry Buy", callback_data=f"retry_{rkey}"),
                                    InlineKeyboardButton("❌ Dismiss", callback_data="cb_dismiss")
                                ]]
                                await app.bot.send_message(chat_id=uid, text=f"❌ **Copy Trade Failed (Buy {token_sym})**\nReason: {err_msg}", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

                        else:
                            bal = 0.0
                            decimals = 18
                            try:
                                if bsc_addr:
                                    bal_r = proxy_get("/address/walletinfo/tokens", {"wallet_address": bsc_addr, "chain": chain, "pageSize": 50})
                                else:
                                    bal_r = {}
                                for tok in bal_r.get("data", []):
                                    tok_addr = (tok.get("token") or "").split("-")[0].lower()
                                    if tok_addr == tx_token_addr.lower():
                                        bal = float(tok.get("balance_amount", 0) or 0)
                                        decimals = int(tok.get("decimals") or tok.get("token_decimals") or 18)
                                        db_upsert_token_meta(chain, tx_token_addr, symbol=token_sym, decimals=decimals)
                                        break
                            except Exception:
                                pass

                            if bal > 0.0001:
                                in_amount_smallest = str(int(bal * (10 ** decimals)))
                                qr = send_swap_order(uid, chain, aid, tx_token_addr, usdt_addr, in_amount_smallest, "sell", slippage="1500", context={"source": "copy_trade", "target": target_addr})

                                if qr.get("status") in (200, 0):
                                    msg = f"👥 **Copied Sell**\nTarget: `{target_addr[:10]}...`\nSold: {round(bal, 4)} {token_sym}"
                                    await app.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
                                else:
                                    err_msg = qr.get('msg', 'Unknown Error')
                                    rkey = hashlib.md5(f"{uid}{chain}{tx_token_addr}{usdt_addr}{in_amount_smallest}sell".encode()).hexdigest()[:10]
                                    db_save_pending_retry(rkey, uid, chain, aid, tx_token_addr, usdt_addr, in_amount_smallest, "sell")
                                    kb = [[
                                        InlineKeyboardButton("🔄 Retry Sell", callback_data=f"retry_{rkey}"),
                                        InlineKeyboardButton("❌ Dismiss", callback_data="cb_dismiss")
                                    ]]
                                    await app.bot.send_message(chat_id=uid, text=f"❌ **Copy Trade Failed (Sell {token_sym})**\nReason: {err_msg}", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

                    except Exception as inner_e:
                        db_log_error("copy_trade_inner_error", inner_e, telegram_id=uid, context={"target": target_addr, "chain": chain})

            if changed:
                save_copy_trades(copy_trades)
            db_heartbeat_ok("monitor_copy_trades")

        except Exception as e:
            db_log_error("copy_trade_monitor_error", e)
            try:
                db_heartbeat_error("monitor_copy_trades", e)
            except Exception:
                pass

        await asyncio.sleep(60)
