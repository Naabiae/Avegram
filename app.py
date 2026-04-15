"""SignalBot v2 - Ave proxy wallet integration"""
import os, json, asyncio, sys, urllib.request, urllib.parse, base64, datetime, hmac, hashlib
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv

AVENUE_SCRIPTS = "/home/workspace/ave-cloud-skill/scripts"
# Try using relative path for the workspace if absolute path doesn't exist
if not os.path.exists(AVENUE_SCRIPTS):
    AVENUE_SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ave-cloud-skill", "scripts")
sys.path.insert(0, AVENUE_SCRIPTS)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
AVE_API_KEY = os.environ.get("AVE_API_KEY", "")
AVE_SECRET_KEY = os.environ.get("AVE_SECRET_KEY", "")
API_PLAN = os.environ.get("API_PLAN", "pro")
USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")
TRADES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades.json")
COPY_TRADES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "copy_trades.json")
ALERT_CHANNEL = "@AvegramAlerts"

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE) as f: return json.load(f)
    return {}

def save_users(u):
    with open(USERS_FILE, "w") as f: json.dump(u, f, indent=2)

def load_trades():
    if os.path.exists(TRADES_FILE):
        with open(TRADES_FILE) as f: return json.load(f)
    return {}

def save_trades(t):
    with open(TRADES_FILE, "w") as f: json.dump(t, f, indent=2)

def load_copy_trades():
    if os.path.exists(COPY_TRADES_FILE):
        with open(COPY_TRADES_FILE) as f: return json.load(f)
    return {}

def save_copy_trades(t):
    with open(COPY_TRADES_FILE, "w") as f: json.dump(t, f, indent=2)

SIGNAL_HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "signal_history.json")

def load_signal_history():
    if os.path.exists(SIGNAL_HISTORY_FILE):
        with open(SIGNAL_HISTORY_FILE) as f: return json.load(f)
    return []

def save_signal_history(h):
    with open(SIGNAL_HISTORY_FILE, "w") as f: json.dump(h, f, indent=2)

def proxy_headers(method, path, body=None):
    import base64, datetime, hashlib, hmac
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    msg = ts + method.upper() + path
    if body: msg += json.dumps(body, sort_keys=True, separators=(",", ":"))
    sig = base64.b64encode(hmac.new(AVE_SECRET_KEY.encode(), msg.encode(), hashlib.sha256).digest()).decode()
    return {"AVE-ACCESS-KEY": AVE_API_KEY, "AVE-ACCESS-TIMESTAMP": ts, "AVE-ACCESS-SIGN": sig, "Content-Type": "application/json"}

def proxy_get(path, params=None):
    import urllib.request, urllib.parse
    url = "https://bot-api.ave.ai" + path
    if params: url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=proxy_headers("GET", path))
    with urllib.request.urlopen(req, timeout=15) as r: return json.loads(r.read())

def proxy_post(path, body):
    import urllib.request
    data = json.dumps(body).encode()
    req = urllib.request.Request("https://bot-api.ave.ai" + path, data=data, headers=proxy_headers("POST", path, body))
    with urllib.request.urlopen(req, timeout=15) as r: return json.loads(r.read())

def auto_link_wallet(uid_str, username):
    users = load_users()
    # Only link from local users.json - never query API for a shared wallet
    return uid_str in users and bool(users[uid_str].get("assets_id"))

async def show_main_menu(message, uid, edit=False, username=""):
    auto_link_wallet(str(uid), username)
    users = load_users()
    uid_str = str(uid)
    text = "🚀 *Avegram Dashboard*\n\nPowered by Ave Cloud API"
    
    if uid_str not in users or not users[uid_str].get("assets_id"):
        keyboard = [[InlineKeyboardButton("💳 Create Wallet", callback_data="cb_register")]]
    else:
        keyboard = [
            [InlineKeyboardButton("📊 My Portfolio", callback_data="cb_balance")],
            [InlineKeyboardButton("💱 Trade", callback_data="cb_trade"), InlineKeyboardButton("📡 Scan Signals", callback_data="cb_signal")],
            [InlineKeyboardButton("⬇️ Deposit", callback_data="cb_deposit"), InlineKeyboardButton("⬆️ Withdraw", callback_data="cb_withdraw")],
            [InlineKeyboardButton("🐋 Smart Money Wallets", callback_data="cb_topwallets")],
            [InlineKeyboardButton("❓ Help", callback_data="cb_help")]
        ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    if edit:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    else:
        await message.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_callback(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = u.callback_query
    await query.answer()
    data = query.data
    uid = u.effective_user.id

    if data == "cb_menu":
        users = load_users()
        if str(uid) in users and "state" in users[str(uid)]:
            users[str(uid)]["state"] = None
            save_users(users)
        await show_main_menu(query.message, uid, edit=True, username=u.effective_user.username)
    elif data.startswith("sell_"):
        parts = data.split("_")
        if len(parts) >= 3:
            ta = parts[1]
            sym = "_".join(parts[2:])  # symbol may have underscores
            users = load_users()
            uid_str = str(u.effective_user.id)
            if uid_str in users and users[uid_str].get("assets_id"):
                # Get current balance from on-chain data
                bsc_addr = next((a["address"] for a in users[uid_str].get("address_list", []) if a["chain"] == "bsc"), "")
                if bsc_addr:
                    try:
                        r2 = await api_get("/address/walletinfo/tokens", {
                            "wallet_address": bsc_addr, "chain": "bsc",
                            "sort": "balance_usd", "sort_dir": "desc", "pageSize": 50
                        })
                        bal = 0.0
                        if r2.status_code == 200:
                            for t in r2.json().get("data", []):
                                if t.get("token", "").lower() == ta.lower():
                                    bal = float(t.get("balance_amount", 0) or 0)
                                    break
                    except Exception as e:
                        print(f"Balance lookup error: {e}")
                users[uid_str]["state"] = "awaiting_sell_amount"
                users[uid_str]["sell_token"] = {"addr": ta, "symbol": sym, "balance": bal}
                save_users(users)
                kb = [[InlineKeyboardButton("🔙 Cancel", callback_data="cb_menu")]]
                rm = InlineKeyboardMarkup(kb)
                await query.message.edit_text(f"💸 *Sell {sym}*\n\nBalance: {bal}\nEnter amount of {sym} to sell:", reply_markup=rm, parse_mode="Markdown")
            else:
                await query.answer("Use /register first", show_alert=True)
        return

    elif data == "cb_register":
        await cmd_register(u, ctx, is_callback=True)
    elif data == "cb_balance":
        await cmd_balance(u, ctx, is_callback=True)
    elif data == "cb_signal":
        await cmd_signal(u, ctx, is_callback=True)
    elif data == "cb_topwallets":
        await cmd_topwallets(u, ctx, is_callback=True)
    elif data == "cb_help":
        await cmd_help(u, ctx, is_callback=True)
    elif data == "cb_deposit":
        await cmd_deposit(u, ctx, is_callback=True)
    elif data == "cb_withdraw":
        auto_link_wallet(str(uid), u.effective_user.username)
        users = load_users()
        uid_str = str(uid)
        users[uid_str]["state"] = "awaiting_withdraw_address"
        save_users(users)
        keyboard = [[InlineKeyboardButton("🔙 Cancel", callback_data="cb_menu")]]
        await query.message.edit_text("💸 *Withdraw Funds*\n\nPlease paste the destination BSC address:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data == "cb_trade":
        auto_link_wallet(str(uid), u.effective_user.username)
        users = load_users()
        uid_str = str(uid)
        users[uid_str]["state"] = "awaiting_trade_input"
        save_users(users)
        keyboard = [[InlineKeyboardButton("🔙 Cancel", callback_data="cb_menu")]]
        await query.message.edit_text("💱 *Trade Token*\n\nPlease enter the SYMBOL and AMOUNT separated by space.\nExample: `PEPE 10` (to buy $10 worth of PEPE)", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data == "cb_dismiss":
        await query.message.delete()
    elif data.startswith("retry_"):
        parts = data.split("_")
        if len(parts) >= 7:
            _, chain, aid, in_token, out_token, in_amount, swap_type = parts
            await query.message.edit_text("🔄 Retrying trade...", reply_markup=None)
            qr = proxy_post("/v1/thirdParty/tx/sendSwapOrder", {
                "chain": chain, "assetsId": aid, "inTokenAddress": in_token, "outTokenAddress": out_token, 
                "inAmount": in_amount, "swapType": swap_type, "slippage": "1500"
            })
            if qr.get("status") in (200, 0):
                oid = qr.get('data', {}).get('id', '')
                await query.message.edit_text(f"✅ **Retry Successful!**\nOrder ID: `{oid}`", parse_mode="Markdown")
            else:
                err_msg = qr.get('msg', 'Unknown Error')
                kb = [[InlineKeyboardButton("🔄 Retry Again", callback_data=data), InlineKeyboardButton("❌ Dismiss", callback_data="cb_dismiss")]]
                await query.message.edit_text(f"❌ **Retry Failed**\nReason: {err_msg}", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
    elif data.startswith("copy_"):
        parts = data.split("_")
        if len(parts) >= 3:
            chain = parts[1]
            addr = parts[2]
            users = load_users()
            uid_str = str(uid)
            users[uid_str]["state"] = "awaiting_copy_pct"
            users[uid_str]["copy_trade"] = {"chain": chain, "addr": addr}
            save_users(users)
            keyboard = [[InlineKeyboardButton("🔙 Cancel", callback_data="cb_menu")]]
            await query.message.edit_text(f"👥 *Copy Trade Setup*\nTarget: `{addr}`\n\nEnter the **percentage** of your USDT balance to use per trade (e.g., 10 for 10%):", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    elif data.startswith("auto_"):
        parts = data.split("_")
        if len(parts) >= 5:
            chain = parts[1]
            addr_short = parts[2]
            sym = parts[3]
            price = parts[4]
            users = load_users()
            uid_str = str(uid)
            users[uid_str]["state"] = "awaiting_auto_trade_amount"
            users[uid_str]["auto_trade"] = {"chain": chain, "sym": sym, "price": price, "addr_short": addr_short}
            save_users(users)
            keyboard = [[InlineKeyboardButton("🔙 Cancel", callback_data="cb_menu")]]
            await query.message.edit_text(f"⚡ *Auto-Trade {sym}*\n\nEnter amount of USDT to invest:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def handle_text(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = str(u.effective_user.id)
    usdt_addr = "0x55d398326f99059fF775485246999027B3197955"
    users = load_users()
    if uid not in users or "state" not in users[uid]:
        return
        
    state = users[uid]["state"]
    text = u.message.text.strip()
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)
    
    if state == "awaiting_withdraw_address":
        users[uid]["withdraw_address"] = text
        users[uid]["state"] = "awaiting_withdraw_amount"
        save_users(users)
        await u.message.reply_text(f"Address `{text}` saved.\n\nNow enter the amount of USDT to withdraw:", reply_markup=rm, parse_mode="Markdown")
        
    elif state == "awaiting_withdraw_amount":
        users[uid]["state"] = None
        save_users(users)
        try:
            amount = float(text)
            # Placeholder for actual withdraw logic
            await u.message.reply_text(f"✅ Withdrawal of {amount} USDT to `{users[uid]['withdraw_address']}` initiated! (Mock)", reply_markup=rm, parse_mode="Markdown")
        except ValueError:
            await u.message.reply_text("Invalid amount. Please try again from the menu.", reply_markup=rm)
            
    elif state == "awaiting_trade_input":
        users[uid]["state"] = None
        save_users(users)
        parts = text.split()
        if len(parts) != 2:
            await u.message.reply_text("Invalid format. Use SYMBOL AMOUNT (e.g. PEPE 10). Try again from the menu.", reply_markup=rm)
            return
        
        # We can simulate the context args to call cmd_trade
        class MockCtx:
            def __init__(self, args):
                self.args = args
        await cmd_trade(u, MockCtx(parts), is_callback=False)

    elif state == "awaiting_sell_amount":
        try:
            sell_cfg = users[uid]["sell_token"]
            ta = sell_cfg["addr"]
            sym = sell_cfg["symbol"]
            bal = sell_cfg["balance"]
            amount = min(float(text), bal)
            users[uid]["state"] = None
            save_users(users)

            in_amount_wei = str(int(amount * 1e18))
            qr = proxy_post("/v1/thirdParty/tx/sendSwapOrder", {
                "chain": "bsc", "assetsId": users[uid]["assets_id"],
                "inTokenAddress": ta, "outTokenAddress": usdt_addr,
                "inAmount": in_amount_wei, "swapType": "sell", "slippage": "1500"
            })

            kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
            rm = InlineKeyboardMarkup(kb)

            if qr.get("status") in (200, 0):
                oid = qr.get("data", {}).get("id", "") if isinstance(qr.get("data", {}), dict) else ""
                await u.message.reply_text(f"✅ *Sell submitted!*\nSold {round(amount, 4)} {sym}\nOrder ID: `{oid}`", reply_markup=rm, parse_mode="Markdown")
            else:
                err = qr.get("msg", "Unknown error")
                kb2 = [[InlineKeyboardButton("🔄 Retry", callback_data=f"retry_bsc_{users[uid]['assets_id']}_{ta}_{usdt_addr}_{in_amount_wei}_sell"), InlineKeyboardButton("❌ Dismiss", callback_data="cb_dismiss")]]
                await u.message.reply_text(f"❌ *Sell failed!*\nReason: {err}", reply_markup=InlineKeyboardMarkup(kb2), parse_mode="Markdown")
        except ValueError:
            await u.message.reply_text("Invalid amount.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="cb_menu")]]))
        return

    elif state == "awaiting_auto_trade_amount":
        try:
            amount = float(text)
            users[uid]["auto_trade"]["amount"] = amount
            users[uid]["state"] = "awaiting_auto_trade_tp"
            save_users(users)
            # Ensure auto_trade context exists
            if "auto_trade" not in users[uid]:
                await u.message.reply_text("Auto-trade session expired. Please try again from the menu.", reply_markup=rm)
                return
            sym = users[uid]["auto_trade"]["sym"]
            await u.message.reply_text(f"Amount: ${amount}\n\nEnter Take-Profit % for {sym} (e.g. 50):", reply_markup=rm)
        except ValueError:
            await u.message.reply_text("Invalid amount. Please try again.", reply_markup=rm)

    elif state == "awaiting_auto_trade_tp":
        try:
            tp = float(text)
            users[uid]["auto_trade"]["tp_pct"] = tp
            users[uid]["state"] = "awaiting_auto_trade_sl"
            save_users(users)
            # Ensure auto_trade context exists
            if "auto_trade" not in users[uid]:
                await u.message.reply_text("Auto-trade session expired. Please try again from the menu.", reply_markup=rm)
                return
            sym = users[uid]["auto_trade"]["sym"]
            await u.message.reply_text(f"Take-Profit: +{tp}%\n\nEnter Stop-Loss % for {sym} (e.g. -20):", reply_markup=rm)
        except ValueError:
            await u.message.reply_text("Invalid percentage. Please try again.", reply_markup=rm)

    elif state == "awaiting_auto_trade_sl":
        try:
            sl = float(text)
            users[uid]["auto_trade"]["sl_pct"] = sl
            users[uid]["state"] = None
            save_users(users)
            
            # Ensure auto_trade context exists
            if "auto_trade" not in users[uid]:
                await u.message.reply_text("Auto-trade session expired. Please try again from the menu.", reply_markup=rm)
                return
                
            auto_cfg = users[uid]["auto_trade"]
            sym = auto_cfg["sym"]
            amount = auto_cfg["amount"]
            chain = auto_cfg["chain"]
            
            await u.message.reply_text(f"⏳ Setting up TP/SL for {sym}...\nExecuting initial buy of ${amount}...", reply_markup=rm)
            
            # Execute BUY order
            from ave.http import api_get
            sr = await api_get("/tokens", {"keyword": sym, "limit": 5, "chain": chain})
            tok_data = sr.json().get("data", [])
            if not tok_data:
                await u.message.reply_text(f"Token {sym} not found. Auto-trade cancelled.", reply_markup=rm)
                return
                
            ta = tok_data[0].get("token", "").split("-")[0]
            aid = users[uid]["assets_id"]
            usdt = "0x55d398326f99059fF775485246999027B3197955"
            
            qr = proxy_post("/v1/thirdParty/tx/sendSwapOrder", {"chain": chain, "assetsId": aid, "inTokenAddress": usdt, "outTokenAddress": ta, "inAmount": str(int(amount * 1e18)), "swapType": "buy", "slippage": "1000"})
            
            if qr.get("status") not in (200, 0):
                err_msg = qr.get('msg', 'Unknown Error')
                kb = [[InlineKeyboardButton("🔄 Retry Buy", callback_data=f"retry_{chain}_{aid}_{usdt}_{ta}_{int(amount * 1e18)}_buy"), InlineKeyboardButton("❌ Dismiss", callback_data="cb_dismiss")]]
                await u.message.reply_text(f"❌ **Buy Failed**\nReason: {err_msg}\nTP/SL setup cancelled.", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
                return
                
            oid = ""
            d = qr.get("data", {})
            if isinstance(d, dict): oid = d.get("id", "")
            elif isinstance(d, list) and d: oid = d[0].get("id", "") if isinstance(d[0], dict) else str(d[0])
            
            # Save to trades.json
            trades = load_trades()
            if uid not in trades:
                trades[uid] = {}
                
            # Get actual current price for entry
            pr = await api_get(f"/tokens/{ta}-{chain}")
            entry_price = float(auto_cfg["price"])
            if pr.status_code == 200 and pr.json().get("data"):
                entry_price = float(pr.json()["data"].get("token", {}).get("current_price_usd", entry_price))
                
            trades[uid][ta] = {
                "chain": chain,
                "symbol": sym,
                "entry_price": entry_price,
                "invested_usdt": amount,
                "tp_pct": auto_cfg["tp_pct"],
                "sl_pct": auto_cfg["sl_pct"],
                "status": "active"
            }
            save_trades(trades)
            
            await u.message.reply_text(
                f"✅ **Buy submitted!** Order ID: `{oid}`\n\n"
                f"🛡️ **TP/SL Configured for {sym}:**\n"
                f"Entry: ${entry_price:.6f}\n"
                f"Take-Profit: +{auto_cfg['tp_pct']}%\n"
                f"Stop-Loss: {auto_cfg['sl_pct']}%\n\n"
                f"The bot will automatically sell if limits are hit.", 
                reply_markup=rm, parse_mode="Markdown"
            )
            
        except ValueError:
            await u.message.reply_text("Invalid percentage. Please try again.", reply_markup=rm)

    elif state == "awaiting_copy_pct":
        try:
            pct = float(text)
            if pct <= 0 or pct > 100: raise ValueError
            users[uid]["copy_trade"]["pct"] = pct
            users[uid]["state"] = "awaiting_copy_max"
            save_users(users)
            await u.message.reply_text(f"Allocation: {pct}%\n\nEnter the **maximum USDT** to spend per copied trade (e.g., 50):", reply_markup=rm, parse_mode="Markdown")
        except ValueError:
            await u.message.reply_text("Invalid percentage. Enter a number between 1 and 100.", reply_markup=rm)

    elif state == "awaiting_copy_max":
        try:
            max_usdt = float(text)
            if max_usdt <= 0: raise ValueError
            users[uid]["copy_trade"]["max_usdt"] = max_usdt
            users[uid]["state"] = None
            save_users(users)
            
            cfg = users[uid]["copy_trade"]
            chain = cfg["chain"]
            target_addr = cfg["addr"]
            
            copy_trades = load_copy_trades()
            if uid not in copy_trades: copy_trades[uid] = {}
            
            copy_trades[uid][target_addr] = {
                "chain": chain,
                "pct_allocation": cfg["pct"],
                "max_usdt_per_trade": max_usdt,
                "last_tx_hash": "", # Will be set on first poll
                "status": "active"
            }
            save_copy_trades(copy_trades)
            
            await u.message.reply_text(
                f"✅ **Copy Trade Active!**\n\n"
                f"Target: `{target_addr[:15]}...`\n"
                f"Allocation: {cfg['pct']}%\n"
                f"Max Per Trade: ${max_usdt}\n\n"
                f"The bot will automatically mirror new swaps.",
                reply_markup=rm, parse_mode="Markdown"
            )
        except ValueError:
            await u.message.reply_text("Invalid amount. Enter a positive number.", reply_markup=rm)

async def monitor_tp_sl(app: Application):
    """Background WSS task — real-time TP/SL monitoring via WebSocket price stream."""
    import websockets, json
    from ave.http import api_get

    usdt_addr = "0x55d398326f99059fF775485246999027B3197955"
    WSS_BASE = "wss://wss.ave-api.xyz"

    async def get_ws_headers():
        return {"X-API-KEY": AVE_API_KEY}

    def load_active_trades():
        all_trades = load_trades()
        result = {}  # key: (token_address, chain) -> {uid, sym, entry, tp_pct, sl_pct, aid}
        for uid, user_trades in all_trades.items():
            for ta, t in user_trades.items():
                if t.get("status") != "active":
                    continue
                chain = t.get("chain", "bsc")
                key = (ta.lower(), chain)
                if key not in result:
                    result[key] = {
                        "uid": uid, "sym": t.get("symbol", "?"),
                        "entry": t.get("entry_price", 0),
                        "tp_pct": t.get("tp_pct", 50),
                        "sl_pct": t.get("sl_pct", -20),
                        "aid": users.get(uid, {}).get("assets_id") if uid in users else None
                    }
        return result

    while True:
        try:
            users = load_users()
            trades = load_trades()
            active = load_active_trades()

            if not active:
                await asyncio.sleep(15)
                continue

            # Build token list for WSS subscription
            topics = [f"{ta}-{chain}" for (ta, chain) in active.keys()]
            if not topics:
                await asyncio.sleep(15)
                continue

            # Connect to WSS once, stream prices, handle hits
            async def run_ws_session():
                nonlocal active
                headers = await get_ws_headers()
                async with websockets.connect(WSS_BASE, additional_headers=headers) as ws:
                    # Subscribe to all active tokens
                    await ws.send(json.dumps({
                        "method": "subscribe",
                        "params": ["price", topics],
                        "id": 1
                    }))

                    session_deadline = asyncio.get_event_loop().time() + 55  # refresh every 55s

                    while asyncio.get_event_loop().time() < session_deadline:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=10)
                            data = json.loads(msg)
                            prices = (
                                data.get("result", {}).get("prices", []) or
                                data.get("params", {}).get("data", {}).get("prices", []) or
                                []
                            )
                            for p in prices:
                                target_token = p.get("target_token", "").lower()
                                chain = p.get("chain", "bsc")
                                curr_price = float(p.get("uprice") or 0)
                                if curr_price == 0:
                                    continue
                                key = (target_token, chain)
                                if key not in active:
                                    continue
                                t = active[key]
                                entry = t["entry"]
                                if entry == 0:
                                    continue

                                tp_target = entry * (1 + (t["tp_pct"] / 100))
                                sl_target = entry * (1 + (t["sl_pct"] / 100))

                                hit_type = None
                                if curr_price >= tp_target:
                                    hit_type = "Take-Profit"
                                elif curr_price <= sl_target:
                                    hit_type = "Stop-Loss"

                                if not hit_type:
                                    continue

                                uid = t["uid"]
                                sym = t["sym"]
                                aid = t["aid"]

                                # Fetch balance
                                bal = 0.0
                                if aid:
                                    try:
                                        r = proxy_get("/v1/thirdParty/tx/getSwapOrder", {
                                            "chain": chain, "assetsId": aid, "pageSize": "50", "pageNO": "0"
                                        })
                                        if r.get("status") in (200, 0) and r.get("data"):
                                            for o in r["data"]:
                                                if o.get("status") != "confirmed":
                                                    continue
                                                if o.get("outTokenAddress", "").lower() == target_token:
                                                    bal += float(o.get("outAmount", "0")) / 1e18
                                                elif o.get("inTokenAddress", "").lower() == target_token:
                                                    bal -= float(o.get("inAmount", "0")) / 1e18
                                    except Exception:
                                        pass

                                if bal <= 0.0001:
                                    # Manually sold — clear trade
                                    trades = load_trades()
                                    if uid in trades and target_token in trades[uid]:
                                        del trades[uid][target_token]
                                        save_trades(trades)
                                    active.pop(key, None)
                                    continue

                                # Execute SELL
                                if aid:
                                    try:
                                        qr = proxy_post("/v1/thirdParty/tx/sendSwapOrder", {
                                            "chain": chain, "assetsId": aid,
                                            "inTokenAddress": target_token,
                                            "outTokenAddress": usdt_addr,
                                            "inAmount": str(int(bal * 1e18)),
                                            "swapType": "sell", "slippage": "1500"
                                        })
                                        if qr.get("status") in (200, 0):
                                            pnl_pct = ((curr_price - entry) / entry) * 100
                                            usd_out = bal * curr_price
                                            msg_txt = (
                                                f"🚨 **{hit_type} Hit!**\n\n"
                                                f"Sold {round(bal, 4)} {sym} for ~${usd_out:.2f}\n"
                                                f"PNL: {pnl_pct:+.2f}%\n"
                                                f"Price: ${curr_price:.6f}"
                                            )
                                            await app.bot.send_message(chat_id=int(uid), text=msg_txt, parse_mode="Markdown")
                                            # Clear trade
                                            trades = load_trades()
                                            if uid in trades and target_token in trades[uid]:
                                                del trades[uid][target_token]
                                                save_trades(trades)
                                            active.pop(key, None)
                                        else:
                                            print(f"SELL failed for {uid} {sym}: {qr.get('msg')}")
                                    except Exception as e:
                                        print(f"SELL error: {e}")

                                # Remove processed token from active
                                active.pop(key, None)

                        except TimeoutError:
                            # No message — just loop to check deadline
                            continue
                        except Exception as e:
                            print(f"WSS session error: {e}")
                            break

                    await ws.send(json.dumps({"method": "unsubscribe", "params": ["price", topics], "id": 2}))

            await run_ws_session()

        except Exception as e:
            print(f"TP/SL Monitor error: {e}")

        await asyncio.sleep(5)  # Restart WSS connection loop


async def monitor_copy_trades(app: Application):
    """Background task to mirror smart money wallets."""
    from ave.http import api_get
    usdt_addr = "0x55d398326f99059fF775485246999027B3197955"
    
    while True:
        try:
            copy_trades = load_copy_trades()
            users = load_users()
            changed = False
            
            for uid, targets in list(copy_trades.items()):
                if uid not in users or not users[uid].get("assets_id"): continue
                aid = users[uid]["assets_id"]
                
                for target_addr, cfg in list(targets.items()):
                    if cfg.get("status") != "active": continue
                    
                    chain = cfg.get("chain", "bsc")
                    # Fetch latest txs for target wallet
                    r = await api_get("/address/walletinfo/transactions", {"wallet_address": target_addr, "chain": chain, "pageSize": 5, "pageNO": 0})
                    if r.status_code != 200: continue
                    data = r.json()
                    if data.get("status") != 1 or not data.get("data"): continue
                    
                    txs = data["data"]
                    if not txs: continue
                    
                    latest_tx = txs[0]
                    tx_hash = latest_tx.get("transaction_hash", "")
                    
                    # If this is the first poll, just set the hash and continue
                    if not cfg.get("last_tx_hash"):
                        cfg["last_tx_hash"] = tx_hash
                        changed = True
                        continue
                        
                    # If we have seen this hash, nothing new
                    if tx_hash == cfg["last_tx_hash"]: continue
                    
                    # New transaction found! Parse it
                    cfg["last_tx_hash"] = tx_hash
                    changed = True
                    
                    tx_type = latest_tx.get("trade_type", "")
                    token_addr = latest_tx.get("token_address", "")
                    token_sym = latest_tx.get("symbol", "?")
                    
                    # Ensure it's a swap we can mirror
                    if tx_type not in ("buy", "sell") or not token_addr: continue
                    
                    try:
                        # Find User's USDT balance
                        user_bal_resp = proxy_get("/v1/thirdParty/tx/getSwapOrder", {"chain": chain, "assetsId": aid, "pageSize": 50, "pageNO": 0})
                        
                        if tx_type == "buy":
                            # Calculate user's USDT balance to determine trade size
                            # We'll use a mock total since we don't have a direct wallet balance endpoint in the provided snippets.
                            # Usually, we would query the proxy wallet balance directly. 
                            # For safety in this mockup, we'll just try to use the max_usdt config limit if they have it.
                            trade_amount = cfg["max_usdt_per_trade"]
                            
                            # Execute Buy
                            in_amount_wei = str(int(trade_amount * 1e18))
                            qr = proxy_post("/v1/thirdParty/tx/sendSwapOrder", {
                                "chain": chain, "assetsId": aid, "inTokenAddress": usdt_addr, "outTokenAddress": token_addr, 
                                "inAmount": in_amount_wei, "swapType": "buy", "slippage": "1500"
                            })
                            
                            if qr.get("status") in (200, 0):
                                msg = f"👥 **Copied Buy**\nTarget: `{target_addr[:10]}...`\nBought: ~${trade_amount} of {token_sym}\nOrder: `{qr.get('data', {}).get('id', '')}`"
                                await app.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
                            else:
                                err_msg = qr.get('msg', 'Unknown Error')
                                kb = [[InlineKeyboardButton("🔄 Retry Buy", callback_data=f"retry_{chain}_{aid}_{usdt_addr}_{token_addr}_{in_amount_wei}_buy"), InlineKeyboardButton("❌ Dismiss", callback_data="cb_dismiss")]]
                                await app.bot.send_message(chat_id=uid, text=f"❌ **Copy Trade Failed (Buy {token_sym})**\nReason: {err_msg}", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
                                
                        elif tx_type == "sell":
                            # For sell, we would look up the user's holding of `token_addr` and sell 100%
                            # In a full impl, we'd calculate the proportional sell amount. Here we do 100% for safety.
                            
                            # Calculate user's token balance
                            bal = 0.0
                            if user_bal_resp.get("status") in (200, 0) and user_bal_resp.get("data"):
                                for o in user_bal_resp["data"]:
                                    if o.get("status") != "confirmed": continue
                                    if o.get("outTokenAddress") == token_addr: bal += float(o.get("outAmount", "0")) / 1e18
                                    elif o.get("inTokenAddress") == token_addr: bal -= float(o.get("inAmount", "0")) / 1e18
                                    
                            if bal > 0.0001:
                                in_amount_wei = str(int(bal * 1e18))
                                qr = proxy_post("/v1/thirdParty/tx/sendSwapOrder", {
                                    "chain": chain, "assetsId": aid, "inTokenAddress": token_addr, "outTokenAddress": usdt_addr, 
                                    "inAmount": in_amount_wei, "swapType": "sell", "slippage": "1500"
                                })
                                
                                if qr.get("status") in (200, 0):
                                    msg = f"👥 **Copied Sell**\nTarget: `{target_addr[:10]}...`\nSold: {round(bal, 4)} {token_sym}"
                                    await app.bot.send_message(chat_id=uid, text=msg, parse_mode="Markdown")
                                else:
                                    err_msg = qr.get('msg', 'Unknown Error')
                                    kb = [[InlineKeyboardButton("🔄 Retry Sell", callback_data=f"retry_{chain}_{aid}_{token_addr}_{usdt_addr}_{in_amount_wei}_sell"), InlineKeyboardButton("❌ Dismiss", callback_data="cb_dismiss")]]
                                    await app.bot.send_message(chat_id=uid, text=f"❌ **Copy Trade Failed (Sell {token_sym})**\nReason: {err_msg}", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
                                    
                    except Exception as inner_e:
                        print(f"Inner copy trade error for {uid}: {inner_e}")
                        
            if changed:
                save_copy_trades(copy_trades)
                
        except Exception as e:
            print(f"Copy Trade Monitor error: {e}")
            
        await asyncio.sleep(60)

async def cmd_start(u, ctx):
    await show_main_menu(u.message, u.effective_user.id, username=u.effective_user.username)

async def cmd_register(u, ctx, is_callback=False):
    users = load_users()
    uid = str(u.effective_user.id)
    username = u.effective_user.username
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)
    
    # Check if they already have a wallet (this handles existing proxy wallets)
    if auto_link_wallet(uid, username):
        users = load_users()
        w = users[uid]
        bsc_addr = next((a["address"] for a in w.get("address_list", []) if a["chain"] == "bsc"), "N/A")
        text = f"✅ Proxy wallet linked and ready!\n\nBSC: `{bsc_addr}`\n\nThis wallet holds your funded USDT. Check Portfolio to see your holdings."
        if is_callback: await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
        else: await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")
        return

    if not is_callback: await msg.reply_text("No existing wallet found. Creating new one...")
    
    # New user - create proxy wallet
    r = proxy_post("/v1/thirdParty/user/generateWallet", {"assetsName": "user_" + uid[-8:], "returnMnemonic": False})
    if r.get("status") not in (200, 0) or not r.get("data"):
        text = "Registration failed: " + str(r.get("msg", ""))
        if is_callback: await msg.edit_text(text, reply_markup=rm)
        else: await msg.reply_text(text, reply_markup=rm)
        return
    d = r["data"]
    users[uid] = {"assets_id": d["assetsId"], "address_list": d.get("addressList", []), "username": username, "chain": "bsc"}
    save_users(users)
    bsc_addr = next((a["address"] for a in d.get("addressList", []) if a["chain"] == "bsc"), "N/A")
    text = f"Proxy wallet created!\n\nBSC: `{bsc_addr}`\n\nDeposit USDT BEP20 to this address, then check Portfolio."
    if is_callback: await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
    else: await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")

async def cmd_deposit(u, ctx, is_callback=False):
    uid = str(u.effective_user.id)
    username = u.effective_user.username
    auto_link_wallet(uid, username)
    users = load_users()
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)
    
    if uid not in users or not users[uid].get("assets_id"):
        text = "Use /register first"
        if is_callback: await msg.edit_text(text, reply_markup=rm)
        else: await msg.reply_text(text, reply_markup=rm)
        return
    addr = next((a["address"] for a in users[uid].get("address_list", []) if a["chain"] == "bsc"), "N/A")
    text = "Deposit Address (BSC BEP20)\n\n`" + addr + "`\n\nDeposit USDT to this address"
    if is_callback: await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
    else: await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")

async def cmd_balance(u, ctx, is_callback=False):
    uid = str(u.effective_user.id)
    username = u.effective_user.username
    auto_link_wallet(uid, username)
    users = load_users()
    msg = u.callback_query.message if is_callback else u.message
    kb = [
        [InlineKeyboardButton("🔄 Refresh", callback_data="cb_balance")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]
    ]
    rm = InlineKeyboardMarkup(kb)
    
    if uid not in users or not users[uid].get("assets_id"):
        text = "Use /register first"
        if is_callback: await msg.edit_text(text, reply_markup=rm)
        else: await msg.reply_text(text, reply_markup=rm)
        return

    aid = users[uid]["assets_id"]
    bsc_addr = next((a["address"] for a in users[uid].get("address_list", []) if a["chain"] == "bsc"), None)
    trades = load_trades()
    user_trades = trades.get(uid, {})

    text_loading = "Fetching on-chain portfolio..."
    if is_callback: await msg.edit_text(text_loading)
    else: msg = await msg.reply_text(text_loading)

    # --- Attempt 1: On-chain holdings via Ave public API (no swap history needed) ---
    from ave.http import api_get
    onchain_positions = {}
    usdt_balance = 0.0

    if bsc_addr:
        try:
            r = await api_get("/address/walletinfo/tokens", {
                "wallet_address": bsc_addr, "chain": "bsc",
                "sort": "balance_usd", "sort_dir": "desc", "pageSize": 50
            })
            if r.status_code == 200:
                d = r.json()
                for t in d.get("data", []):
                    bal = float(t.get("balance_amount") or 0)
                    if bal <= 0: continue
                    sym = t.get("symbol", "?")
                    ta = t.get("token", "")
                    onchain_positions[sym] = {
                        "addr": ta, "bal": bal,
                        "balance_usd": float(t.get("balance_usd") or 0)
                    }
                    if sym.upper() == "USDT":
                        usdt_balance = bal
        except Exception as e:
            print(f"On-chain balance fetch error: {e}")

    # --- Attempt 2: Swap history for P&L if no on-chain positions ---
    positions = {}
    if not onchain_positions:
        r = proxy_get("/v1/thirdParty/tx/getSwapOrder", {"chain": "bsc", "assetsId": aid, "pageSize": "50", "pageNO": "0"})
        if r.get("status") in (200, 0) and r.get("data"):
            for o in r["data"]:
                if o.get("status") != "confirmed": continue
                swap_type = o.get("swapType", "buy")
                if swap_type == "buy":
                    sym = o.get("outTokenSymbol", "?")
                    ta = o.get("outTokenAddress")
                    bal_chg = float(o.get("outAmount", "0")) / 1e18
                    usd_spent = float(o.get("txPriceUsd", "0")) * bal_chg
                    if sym not in positions: positions[sym] = {"addr": ta, "bal": 0.0, "invested": 0.0}
                    positions[sym]["bal"] += bal_chg
                    positions[sym]["invested"] += usd_spent
                else:
                    sym = o.get("inTokenSymbol", "?")
                    ta = o.get("inTokenAddress")
                    bal_chg = float(o.get("inAmount", "0")) / 1e18
                    usd_received = float(o.get("txPriceUsd", "0")) * bal_chg
                    if sym in positions:
                        positions[sym]["bal"] -= bal_chg
                        positions[sym]["invested"] -= usd_received
                        if positions[sym]["invested"] < 0: positions[sym]["invested"] = 0

    lines = ["📊 *Portfolio - BSC*\\n"]
    total_invested = 0.0
    total_current = 0.0

    # Build display list from whichever source has data
    display_positions = {}
    if onchain_positions:
        display_positions = onchain_positions
    elif positions:
        display_positions = positions

    if not display_positions:
        # No holdings anywhere — show USDT balance at minimum + prompt to deposit
        if usdt_balance > 0:
            lines = ["📊 *Portfolio - BSC*\\n"]
            lines.append(f"💵 *USDT*: {usdt_balance:,.2f}")
            lines.append(f"\\n💰 *Total Value*: ${usdt_balance:,.2f}")
            lines.append("\\n_Other tokens will appear here after your first swap._")
        else:
            await msg.edit_text(
                "📊 *Portfolio - BSC*\\n\\nNo holdings yet.\\n"
                "Deposit USDT to your BSC wallet address to start trading.",
                reply_markup=rm, parse_mode="Markdown"
            )
            return

    for sym, p in display_positions.items():
        bal = p.get("bal", 0)
        if isinstance(bal, float) and bal < 0.0001: continue

        if onchain_positions:
            # On-chain mode: we have balance_usd directly
            curr_value = p.get("balance_usd", 0)
            lines.append(f"*{sym}*: {bal:,.4f}")
            lines.append(f"  Val: ${curr_value:,.2f}")
            total_current += curr_value
            # No invested/P&L data in on-chain mode
            # Show TP/SL if active
            ta = p.get("addr", "")
            if ta in user_trades and user_trades[ta].get("status") == "active":
                t = user_trades[ta]
                lines.append(f"  ⚡ TP: +{t['tp_pct']}% | SL: {t['sl_pct']}%")
            sell_cb = f"sell_{ta}_{sym}"
            sell_button = InlineKeyboardButton(f"⚡ Sell {sym}", callback_data=sell_cb)
            kb_sell = [[sell_button]]
            lines.append(f"  ⚡ Sell {sym} → tap button below")
            # Store button for this position
            sell_buttons.append(sell_button)
            lines.append("")
        else:
            # Swap history mode: calculate P&L
            if bal < 0.0001: continue
            invested = p.get("invested", 0)
            total_invested += invested
            pr = await api_get(f"/tokens/{p['addr']}-bsc")
            curr_price = 0.0
            if pr.status_code == 200 and pr.json().get("data"):
                curr_price = float(pr.json()["data"].get("token", {}).get("current_price_usd", 0))
            curr_value = bal * curr_price
            total_current += curr_value
            pnl_usd = curr_value - invested
            pnl_pct = (pnl_usd / invested * 100) if invested > 0 else 0
            sign = "🟢 +" if pnl_usd >= 0 else "🔴 "
            lines.append(f"*{sym}*: {round(bal, 4)}")
            lines.append(f"  Val: ${curr_value:.2f} | Inv: ${invested:.2f}")
            lines.append(f"  PNL: {sign}${abs(pnl_usd):.2f} ({pnl_pct:+.2f}%)")
            ta = p.get("addr", "")
            if ta in user_trades and user_trades[ta].get("status") == "active":
                t = user_trades[ta]
                lines.append(f"  ⚡ TP: +{t['tp_pct']}% | SL: {t['sl_pct']}%")
            sell_cb = f"sell_{ta}_{sym}"
            sell_button = InlineKeyboardButton(f"⚡ Sell {sym}", callback_data=sell_cb)
            kb_sell = [[sell_button]]
            lines.append(f"  ⚡ Sell {sym} → tap button below")
            # Store button for this position
            sell_buttons.append(sell_button)
            lines.append("")

    if onchain_positions and total_current == 0 and usdt_balance > 0:
        total_current = usdt_balance

    if total_current == 0 and not onchain_positions:
        await msg.edit_text("No active positions.", reply_markup=rm)
        return

    if onchain_positions:
        lines.append(f"💰 *Total Value*: ${total_current:,.2f}")
    else:
        tot_pnl_usd = total_current - total_invested
        tot_pnl_pct = (tot_pnl_usd / total_invested * 100) if total_invested > 0 else 0
        tot_sign = "🟢 +" if tot_pnl_usd >= 0 else "🔴 "
        lines.append(f"💰 *Total Value*: ${total_current:.2f}")
        lines.append(f"📈 *Total PNL*: {tot_sign}${abs(tot_pnl_usd):.2f} ({tot_pnl_pct:+.2f}%)")

    await msg.edit_text("\\n".join(lines), reply_markup=rm, parse_mode="Markdown")

async def cmd_signal(u, ctx, is_callback=False):
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)
    
    text_loading = "Scanning for signals (60%+ confidence)..."
    if is_callback: await msg.edit_text(text_loading)
    else: msg = await msg.reply_text(text_loading)
    
    tokens = []
    seen = set()
    # 1. Public signals (Ave-filtered, multi-chain)
    try:
        from ave.http import api_get
        for chain in ["bsc", "solana"]:
            url = f"https://data.ave-api.xyz/v2/signals/public/list?chain={chain}&pageSize=20&pageNO=1"
            req = urllib.request.Request(url, headers={"X-API-KEY": AVE_API_KEY})
            r = await asyncio.get_event_loop().run_in_executor(None, lambda u=url: urllib.request.urlopen(req, timeout=10))
            d = json.loads(r.read())
            for s in d.get("data", []):
                ta = s.get("token", ""); chain_tok = s.get("chain", chain)
                a = ta.split("-")[0] if "-" in ta else ta
                if a and a not in seen:
                    seen.add(a); tokens.append({"addr": a, "chain": chain_tok, "sym": s.get("symbol", "?"), "name": s.get("name", "")})
    except: pass
    # 2. Trending BSC tokens by keyword
    for kw in ["PEPE", "SHIB", "DOGE", "BNB", "CAKE", "WBNB", "BTCB", "ETH", "SOL", "XRP"]:
        try:
            url = f"https://data.ave-api.xyz/v2/tokens?keyword={kw}&limit=3&chain=bsc"
            req = urllib.request.Request(url, headers={"X-API-KEY": AVE_API_KEY})
            r = await asyncio.get_event_loop().run_in_executor(None, lambda u=url: urllib.request.urlopen(req, timeout=10))
            d = json.loads(r.read())
            for t in d.get("data", []):
                a = (t.get("token") or "").split("-")[0]
                if a and a not in seen: seen.add(a); tokens.append({"addr": a, "chain": "bsc", "sym": t.get("symbol", "?"), "name": t.get("name", "")})
        except: pass
    if not tokens:
        await msg.edit_text("No tokens found to scan.", reply_markup=rm)
        return
    signals = []
    for tok in tokens[:25]:
        try:
            ta = tok["addr"]; chain_tok = tok["chain"]; tid = f"{ta}-{chain_tok}"
            url1 = f"https://data.ave-api.xyz/v2/tokens/{tid}"
            url2 = f"https://data.ave-api.xyz/v2/contracts/{tid}"
            r1 = await asyncio.get_event_loop().run_in_executor(None, lambda u=url1: urllib.request.urlopen(urllib.request.Request(u, headers={"X-API-KEY": AVE_API_KEY}), timeout=10))
            d1 = json.loads(r1.read())
            r2 = await asyncio.get_event_loop().run_in_executor(None, lambda u=url2: urllib.request.urlopen(urllib.request.Request(u, headers={"X-API-KEY": AVE_API_KEY}), timeout=10))
            d2 = json.loads(r2.read())
            pd = d1.get("data", {}).get("token", {}); rd = d2.get("data", {})
            price = float(pd.get("current_price_usd") or 0)
            liq = float(pd.get("liquidity") or pd.get("tvl") or 0)
            vol = float(pd.get("tx_volume_u_24h") or 0)
            chg = float(pd.get("price_change_24h") or 0)
            if rd.get("is_honeypot") == 1 or price == 0: continue
            conf = 0
            if liq > 50000: conf += 30
            if vol > 10000: conf += 30
            if abs(chg) > 5: conf += 20
            if rd.get("risk_score", 50) < 30: conf += 20
            conf = min(100, conf)
            if conf >= 60:
                signals.append({"conf": conf, "sym": tok["sym"], "price": price, "chg": chg, "liq": liq, "vol": vol, "addr": ta, "chain": chain_tok})
        except: continue
    signals.sort(key=lambda x: x["conf"], reverse=True)
    if not signals:
        await msg.edit_text("No signals above 60% confidence right now. Try again later.", reply_markup=rm)
        return
    lines = [f"🔔 {len(signals)} Signals Found (≥60% confidence)\n"]
    buttons = []
    for s in signals[:8]:
        d = "🟢 BUY" if s["chg"] < -3 else "🔴 SELL" if s["chg"] > 5 else "🟡 WATCH"
        lines.append(f"{d} [{s['conf']}%] {s['sym']} | ${round(s['price'], 8)} | 24h:{round(s['chg'],1)}% | Liq:${s['liq']:,.0f}")
        # Note: callback_data max len is 64 bytes. 
        # auto_trade_<chain>_<addr>_<sym>_<price>
        cb_data = f"auto_{s['chain']}_{s['addr'][:10]}_{s['sym']}_{round(s['price'],8)}"
        buttons.append([InlineKeyboardButton(f"⚡ Auto-Trade {s['sym']} (TP/SL)", callback_data=cb_data)])
        
    lines.append("\n`/trade <sym> <amt>` to execute manually")
    
    # Add back to menu button at the end
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")])
    new_rm = InlineKeyboardMarkup(buttons)
    
    await msg.edit_text("\n".join(lines), reply_markup=new_rm, parse_mode="Markdown")

async def cmd_trade(u, ctx, is_callback=False):
    uid = str(u.effective_user.id)
    username = u.effective_user.username
    auto_link_wallet(uid, username)
    users = load_users()
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)
    
    if uid not in users or not users[uid].get("assets_id"):
        text = "Use /register first"
        if is_callback: await msg.edit_text(text, reply_markup=rm)
        else: await msg.reply_text(text, reply_markup=rm)
        return
        
    if not ctx.args or len(ctx.args) < 2:
        text = "Usage: `/trade SYMBOL AMOUNT`\n\nExample: `/trade ASTER 10`\n(Interactive trade UI coming soon)"
        if is_callback: await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
        else: await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")
        return
        
    sym = ctx.args[0].upper()
    amount = float(ctx.args[1])
    from ave.http import api_get
    
    if is_callback: await msg.edit_text(f"Looking up {sym}...")
    else: msg = await msg.reply_text(f"Looking up {sym}...")
    
    sr = await api_get("/tokens", {"keyword": sym, "limit": 3, "chain": "bsc"})
    tok_data = sr.json().get("data", [])
    if not tok_data:
        await msg.edit_text("Token " + sym + " not found", reply_markup=rm)
        return
        
    ta = tok_data[0].get("token", "").split("-")[0]
    aid = users[uid]["assets_id"]
    usdt = "0x55d398326f99059fF775485246999027B3197955"
    await msg.edit_text("Getting quote for " + str(amount) + " USDT to " + sym + "...")
    
    qr = proxy_post("/v1/thirdParty/tx/sendSwapOrder", {"chain": "bsc", "assetsId": aid, "inTokenAddress": usdt, "outTokenAddress": ta, "inAmount": str(int(amount * 1e18)), "swapType": "buy", "slippage": "500"})
    if qr.get("status") not in (200, 0):
        err_msg = qr.get('msg', 'Unknown Error')
        kb = [[InlineKeyboardButton("🔄 Retry Trade", callback_data=f"retry_bsc_{aid}_{usdt}_{ta}_{int(amount * 1e18)}_buy"), InlineKeyboardButton("❌ Dismiss", callback_data="cb_dismiss")]]
        await msg.edit_text(f"❌ **Swap Failed**\nReason: {err_msg}", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return
        
    oid = ""
    d = qr.get("data", {})
    if isinstance(d, dict): oid = d.get("id", "")
    elif isinstance(d, list) and d: oid = d[0].get("id", "") if isinstance(d[0], dict) else str(d[0])
    
    await msg.edit_text("✅ Swap submitted!\nOrder ID: `" + oid + "`\n\nCheck Portfolio after 30s for confirmation.", reply_markup=rm, parse_mode="Markdown")

async def cmd_topwallets(u, ctx, is_callback=False):
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)
    from ave.http import api_get
    chain = "bsc"
    if ctx.args and ctx.args[0].lower() in ("bsc", "eth", "base", "solana"): chain = ctx.args[0].lower()
    
    text_loading = "Loading top wallets on " + chain.upper() + "..."
    if is_callback: await msg.edit_text(text_loading)
    else: msg = await msg.reply_text(text_loading)
    
    r = await api_get("/address/smart_wallet/list", {"chain": chain, "sort": "profit_above_900_percent_num", "sort_dir": "desc", "profit_900_percent_num_min": 1, "profit_300_900_percent_num_min": 3})
    d = r.json()
    if d.get("status") != 1 or not d.get("data"):
        await msg.edit_text("No wallets found on " + chain.upper(), reply_markup=rm)
        return
    lines = ["Top Smart Money Wallets - " + chain.upper() + "\n"]
    for i, w in enumerate(d["data"][:8], 1):
        addr = w.get("wallet_address", "")
        addr_short = addr[:10] + "..."
        lines.append(str(i) + ". " + addr_short + " | 900%+: " + str(w.get("profit_above_900_percent_num", 0)) + " | 300-900%: " + str(w.get("profit_300_900_percent_num", 0)))
        lines.append("   `/track " + addr + "`")
    
    await msg.edit_text("\n".join(lines), reply_markup=rm, parse_mode="Markdown")

async def cmd_track(u, ctx, is_callback=False):
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)
    from ave.http import api_get
    if not ctx.args:
        text = "Usage: `/track ADDRESS [chain]`"
        if is_callback: await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
        else: await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")
        return
        
    addr = ctx.args[0]; chain = "bsc"
    if len(ctx.args) > 1 and ctx.args[1].lower() in ("bsc", "eth", "solana"): chain = ctx.args[1].lower()
    
    text_loading = "Tracking " + addr[:10] + "... on " + chain.upper()
    if is_callback: await msg.edit_text(text_loading)
    else: msg = await msg.reply_text(text_loading)
    
    r = await api_get("/address/walletinfo/tokens", {"wallet_address": addr, "chain": chain, "sort": "balance_usd", "sort_dir": "desc", "pageSize": 8})
    d = r.json()
    lines = ["Wallet: `" + addr[:20] + "...` | " + chain.upper() + "\n"]
    if d.get("status") == 1 and d.get("data"):
        for t in d["data"][:6]:
            bal = float(t.get("balance_amount", 0) or 0)
            if bal <= 0: continue
            lines.append(t.get("symbol", "?") + ": " + str(round(bal, 4)) + " | P/L: " + str(round(float(t.get("profit_pct", 0)), 1)) + "%")
    else: lines.append("No holdings found")
    
    # Add Copy Trade button
    # copy_chain_address
    cb_data = f"copy_{chain}_{addr}"
    kb = [
        [InlineKeyboardButton(f"👥 Copy Trade {addr[:6]}...", callback_data=cb_data)],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]
    ]
    rm = InlineKeyboardMarkup(kb)
    
    await msg.edit_text("\n".join(lines), reply_markup=rm, parse_mode="Markdown")

async def cmd_help(u, ctx, is_callback=False):
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)
    text = (
        "/register /deposit /balance /quote SYM [AMT] /signal /trade SYM AMT /topwallets [chain] /track ADDRESS /help\n\n"
        "ENV Status:\n"
        f"TELEGRAM_BOT_TOKEN: {'✅ set' if BOT_TOKEN else '❌ missing'}\n"
        f"AVE_API_KEY: {'✅ set' if AVE_API_KEY else '❌ missing'}\n"
        f"AVE_SECRET_KEY: {'✅ set' if AVE_SECRET_KEY else '❌ missing'}\n"
        f"API_PLAN: {API_PLAN or 'pro'}\n\n"
        "Powered by Ave Cloud API"
    )
    if is_callback: await msg.edit_text(text, reply_markup=rm, parse_mode="Markdown")
    else: await msg.reply_text(text, reply_markup=rm, parse_mode="Markdown")

async def cmd_analyse(u, ctx, is_callback=False):
    """Analyse a held token — gives buy/hold/sell recommendation based on on-chain data."""
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)

    if not ctx.args:
        await u.message.reply_text(
            "Usage: `/analyse SYMBOL`\n\nExample: `/analyse PEPE`\n\n Analyses a token you hold and gives a buy/hold/sell rating.",
            reply_markup=rm, parse_mode="Markdown"
        )
        return

    sym = ctx.args[0].upper()
    loading_msg = await u.message.reply_text(f"🔍 Analysing {sym}...")

    try:
        from ave.http import api_get

        # Step 1: Find token address
        sr = await api_get("/tokens", {"keyword": sym, "limit": 5, "chain": "bsc"})
        tok_data = sr.json().get("data", [])
        if not tok_data:
            sr2 = await api_get("/tokens", {"keyword": sym, "limit": 5, "chain": "eth"})
            tok_data = sr2.json().get("data", [])

        if not tok_data:
            await loading_msg.edit_text(f"Token '{sym}' not found.", reply_markup=rm)
            return

        # Use exact symbol match
        ta = None
        tok_chain = "bsc"
        for t in tok_data:
            if t.get("symbol", "").upper() == sym.upper():
                ta = t.get("token", "").split("-")[0]
                tok_chain = t.get("chain", "bsc")
                break
        if not ta:
            ta = tok_data[0].get("token", "").split("-")[0]
            tok_chain = tok_data[0].get("chain", "bsc")

        # Step 2: Fetch token price data and contract risk data concurrently
        pr, cr = await asyncio.gather(
            api_get(f"/tokens/{ta}-{tok_chain}"),
            api_get(f"/contracts/{ta}-{tok_chain}"),
        )

        pd = pr.json().get("data", {}) if pr.status_code == 200 else {}
        cd = cr.json().get("data", {}) if cr.status_code == 200 else {}

        token_info = pd.get("token", {})
        current_price = float(token_info.get("current_price_usd", 0))
        liquidity = float(token_info.get("tvl") or token_info.get("main_pair_tvl") or 0)
        volume_24h = float(token_info.get("tx_volume_u_24h") or 0)
        mc = float(token_info.get("market_cap") or 0)
        price_change_24h = float(token_info.get("price_change_24h") or 0)
        price_change_1d = float(token_info.get("price_change_1d") or 0)
        holders = int(token_info.get("holders") or 0)

        ai_report = cd.get("ai_report", {})
        risks = ai_report.get("risk", [])
        honeypot_flag = cd.get("is_honeypot") == 1

        # Step 3: Compute scores
        scores = []
        explanations = []

        # Liquidity score (0-100)
        if liquidity > 1_000_000:
            liq_score, liq_label = 90, "Excellent"
        elif liquidity > 200_000:
            liq_score, liq_label = 70, "Good"
        elif liquidity > 50_000:
            liq_score, liq_label = 50, "Moderate"
        elif liquidity > 10_000:
            liq_score, liq_label = 30, "Low"
        else:
            liq_score, liq_label = 10, "Very Low"
        scores.append(("Liquidity", liq_score, liq_label))
        explanations.append(f"  Liquidity: ${liquidity:,.0f} — {liq_label}")

        # Volume momentum (0-100)
        if volume_24h > 100_000:
            vol_score, vol_label = 90, "Very Active"
        elif volume_24h > 20_000:
            vol_score, vol_label = 70, "Active"
        elif volume_24h > 5_000:
            vol_score, vol_label = 50, "Moderate"
        else:
            vol_score, vol_label = 20, "Thin"
        scores.append(("Volume 24h", vol_score, vol_label))
        explanations.append(f"  Volume: ${volume_24h:,.0f}/24h — {vol_label}")

        # Price momentum (0-100)
        if price_change_24h > 10:
            mom_score, mom_label = 85, "Strong Uptick"
        elif price_change_24h > 3:
            mom_score, mom_label = 70, "Bullish"
        elif price_change_24h > -3:
            mom_score, mom_label = 55, "Neutral"
        elif price_change_24h > -10:
            mom_score, mom_label = 35, "Bearish"
        else:
            mom_score, mom_label = 15, "Heavy Selloff"
        scores.append(("Price Momentum", mom_score, mom_label))
        explanations.append(f"  Momentum: {price_change_24h:+.1f}%/24h — {mom_label}")

        # Honeypot / contract risk (0-100, inverted to score)
        if honeypot_flag:
            risk_score, risk_label = 0, "HONEYPOT ⚠️"
        elif risks:
            critical = sum(1 for r in risks if r.get("risk_level", 0) < 0 and not r.get("risk_removed"))
            if critical >= 3:
                risk_score, risk_label = 15, "Very High Risk"
            elif critical >= 1:
                risk_score, risk_label = 35, "High Risk"
            else:
                risk_score, risk_label = 65, "Moderate Risk"
        else:
            risk_score, risk_label = 80, "Clean"
        scores.append(("Contract Safety", risk_score, risk_label))
        explanations.append(f"  Contract: {risk_label}")

        # Holder count (0-100)
        if holders > 10000:
            hold_score, hold_label = 90, "Widely Held"
        elif holders > 1000:
            hold_score, hold_label = 70, "Good Distribution"
        elif holders > 100:
            hold_score, hold_label = 50, "Moderate"
        else:
            hold_score, hold_label = 20, "Low Holders"
        scores.append(("Holders", hold_score, hold_label))
        explanations.append(f"  Holders: {holders:,} — {hold_label}")

        # Weighted total score (out of 100)
        total = (
            scores[0][1] * 0.25 +   # Liquidity
            scores[1][1] * 0.20 +   # Volume
            scores[2][1] * 0.25 +   # Momentum
            scores[3][1] * 0.20 +   # Safety
            scores[4][1] * 0.10     # Holders
        )

        if total >= 80:
            verdict, emoji = "BUY 🟢", "🟢"
        elif total >= 60:
            verdict, emoji = "HOLD 🟡", "🟡"
        elif total >= 40:
            verdict, emoji = "HOLD / SELL ⚠️", "🟡"
        else:
            verdict, emoji = "SELL 🔴", "🔴"

        # Cap for honeypot
        if honeypot_flag:
            verdict, emoji = "SELL 🔴", "🔴"
            total = min(total, 25)

        # Build response
        lines = [
            f"📊 *Token Analysis — {sym}*",
            f"",
            f"💰 Price: `${current_price:.8f}`",
            f"   MC: ${mc:,.0f} | Liq: ${liquidity:,.0f}",
            f"",
            f"*Scores:*"
        ]

        for name, score, label in scores:
            bar = "▓" * round(score / 10) + "░" * (10 - round(score / 10))
            lines.append(f"  {name}: {bar} {score}/100 ({label})")

        lines.extend([
            "",
            f"*Overall Score: {total:.0f}/100*",
            f"{verdict}",
            "",
            f"🔗 https://pro.ave.ai/token/{ta}-{tok_chain}"
        ])

        if honeypot_flag:
            lines.insert(2, "⚠️ *HONEYPOT DETECTED — DO NOT BUY*")

        await loading_msg.edit_text("\n".join(lines), reply_markup=rm, parse_mode="Markdown")

    except Exception as e:
        await loading_msg.edit_text(f"Analysis failed: {e}\n\nTry again or use `/analyse PEPE` etc.", reply_markup=rm)



def _store_signal(sym, chain, signal_type, conf, entry_price, duration_hrs=4):
    """Store a new signal in history."""
    import time
    now = time.time()
    history = load_signal_history()
    sid = f"{sym}_{int(now * 1000)}"
    history.append({
        "signal_id": sid,
        "symbol": sym.upper(),
        "chain": chain,
        "signal_type": signal_type,  # "buy" or "sell"
        "confidence": conf,
        "entry_price": entry_price,
        "duration_hrs": duration_hrs,
        "created_at": now,
        "expiry_time": now + (duration_hrs * 3600),
        "status": "active",
        "close_price": None,
        "pnl_pct": None
    })
    save_signal_history(history)
    return sid


async def cmd_analytics(u, ctx, is_callback=False):
    """Show signal performance analytics."""
    from ave.http import api_get
    msg = u.callback_query.message if is_callback else u.message
    kb = [[InlineKeyboardButton("🔄 Refresh", callback_data="cb_analytics")],
          [InlineKeyboardButton("🔙 Back to Menu", callback_data="cb_menu")]]
    rm = InlineKeyboardMarkup(kb)

    history = load_signal_history()
    active = [s for s in history if s["status"] == "active"]
    closed = [s for s in history if s["status"] in ("won", "lost")]
    won = [s for s in closed if s["status"] == "won"]
    lost = [s for s in closed if s["status"] == "lost"]

    win_rate = len(won) / len(closed) * 100 if closed else 0
    avg_pnl = sum(s["pnl_pct"] or 0 for s in won) / len(won) if won else 0
    avg_loss = sum(s["pnl_pct"] or 0 for s in lost) / len(lost) if lost else 0

    total_return = sum(s["pnl_pct"] or 0 for s in closed)

    lines = [
        "📊 *Signal Analytics*\n",
        f"_All time (since first signal)_\n",
        "",
        f"*Overview*",
        f"  Total Signals: {len(history)}",
        f"  Active: {len(active)} | Closed: {len(closed)}",
        "",
        f"*Win Rate*",
        f"  🟢 Won: {len(won)} | 🔴 Lost: {len(lost)}",
        f"  Win Rate: {win_rate:.1f}%",
        "",
        f"*Avg Performance*",
        f"  Avg Win: +{avg_pnl:.2f}%",
        f"  Avg Loss: {avg_loss:.2f}%",
        f"  Total Return: {total_return:+.2f}%",
    ]

    if closed:
        best = max(closed, key=lambda s: s["pnl_pct"] or 0)
        worst = min(closed, key=lambda s: s["pnl_pct"] or 0)
        lines += [
            "",
            f"*Best Signal*",
            f"  {best['symbol']}: {best['pnl_pct']:+.2f}%",
            "",
            f"*Worst Signal*",
            f"  {worst['symbol']}: {worst['pnl_pct']:+.2f}%",
        ]

    lines += ["", "_Refreshes every 5 minutes_"]
    await msg.edit_text("\n".join(lines), reply_markup=rm, parse_mode="Markdown")


async def monitor_signal_performance(app: Application):
    """Background task — close expired signals and update P&L."""
    from ave.http import api_get
    import time

    while True:
        try:
            history = load_signal_history()
            changed = False
            now = time.time()

            for s in history:
                if s["status"] != "active":
                    continue
                if now < s["expiry_time"]:
                    continue

                # Signal expired — fetch final price
                ta = s.get("token_addr", "")
                chain = s.get("chain", "bsc")
                sym = s["symbol"]
                entry = s["entry_price"]

                if ta:
                    try:
                        pr = await api_get(f"/tokens/{ta}-{chain}")
                        if pr.status_code == 200 and pr.json().get("data"):
                            curr_price = float(pr.json()["data"].get("token", {}).get("current_price_usd", 0))
                        else:
                            curr_price = 0
                    except:
                        curr_price = 0
                else:
                    curr_price = 0

                if curr_price > 0 and entry > 0:
                    pnl_pct = ((curr_price - entry) / entry) * 100
                else:
                    pnl_pct = 0

                s["status"] = "won" if pnl_pct > 0 else "lost"
                s["close_price"] = curr_price
                s["pnl_pct"] = round(pnl_pct, 2)
                s["closed_at"] = now
                changed = True

                # Notify channel
                emoji = "🟢" if s["status"] == "won" else "🔴"
                conf = s.get("confidence", 0)
                duration = s.get("duration_hrs", 4)
                lines = [
                    f"📡 *Signal Closed — {sym}*\n",
                    f"{emoji} Result: *{s['status'].upper()}* ({pnl_pct:+.2f}%)\n",
                    f"Entry: ${entry:.8f} → Close: ${curr_price:.8f}\n",
                    f"Confidence: {conf:.0f}% | Duration: {duration}h\n",
                    f"Time: {duration}h | Signal ID: `{s['signal_id']}`",
                ]
                try:
                    await app.bot.send_message(
                        chat_id=ALERT_CHANNEL,
                        text="\n".join(lines),
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

            if changed:
                save_signal_history(history)

        except Exception as e:
            print(f"Signal Performance Monitor error: {e}")

        await asyncio.sleep(60)


async def monitor_signal_alerts(app: Application):
    """Background scanner — pushes 85%+ BUY signals to all users on BSC."""
    seen_signals = set()
    ALERT_THRESHOLD = 85
    SCAN_INTERVAL = 120  # seconds

    while True:
        try:
            users = load_users()
            if not users:
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            # Collect all registered user IDs
            user_ids = [uid for uid, u in users.items() if u.get("assets_id")]

            # Fetch live signals
            signals_url = "https://data.ave-api.xyz/v2/signals/public/list?chain=bsc&pageSize=50&pageNO=1"
            req = urllib.request.Request(
                signals_url,
                headers={"X-API-KEY": AVE_API_KEY}
            )
            r = await asyncio.get_event_loop().run_in_executor(
                None, lambda: urllib.request.urlopen(req, timeout=10)
            )
            d = json.loads(r.read())

            new_signals = []
            for s in d.get("data", []):
                if s.get("signal_type") != "buy":
                    continue
                conf = float(s.get("confidence", 0) or 0)
                if conf < ALERT_THRESHOLD:
                    continue
                ta = s.get("token", "")
                a = ta.split("-")[0] if "-" in ta else ta
                if not a or a in seen_signals:
                    continue
                seen_signals.add(a)
                new_signals.append({
                    "conf": conf,
                    "sym": s.get("symbol", "?"),
                    "addr": a,
                    "price": float(s.get("current_price", 0) or 0),
                    "chg_24h": float(s.get("price_change_24h", 0) or 0),
                    "token_addr": ta,
                })

            if not new_signals:
                await asyncio.sleep(SCAN_INTERVAL)
                continue

            for sig in new_signals:
                # Build alert message
                d = "🟢 BUY" if sig["chg_24h"] < -3 else "🔴 BUY"
                msg = (
                    f"🔔 *HIGH-CONFIDENCE BUY SIGNAL*\n\n"
                    f"{d} [{sig['conf']:.0f}%] *{sig['sym']}*\n"
                    f"Price: `${sig['price']:.8f}` | 24h: {sig['chg_24h']:+.1f}%\n\n"
                    f"Chain: BSC\n"
                    f"Token: `{sig['addr']}`"
                )

                # Inline auto-trade button
                cb_data = f"auto_bsc_{sig['addr'][:10]}_{sig['sym']}_{sig['price']:.8f}"
                kb = [
                    [InlineKeyboardButton(f"⚡ Auto-Trade {sig['sym']} (TP/SL)", callback_data=cb_data)],
                    [InlineKeyboardButton(f"📊 Analyse {sig['sym']}", callback_data=f"cb_analyse_{sig['sym']}")]
                ]
                rm = InlineKeyboardMarkup(kb)

                # Store signal in history for tracking
                _store_signal(sig["sym"], "bsc", "buy", sig["conf"], sig["price"], duration_hrs=4)

                # Update message with expiry info
                msg = (
                    f"🔔 *HIGH-CONFIDENCE BUY SIGNAL*\n\n"
                    f"{d} [{sig['conf']:.0f}%] *{sig['sym']}*\n"
                    f"Price: `${sig['price']:.8f}` | 24h: {sig['chg_24h']:+.1f}%\n\n"
                    f"⏱️ Track P&L for 4h → result posted when expired\n\n"
                    f"Chain: BSC | Token: `{sig['addr']}`"
                )

                # Broadcast to channel once
                try:
                    await app.bot.send_message(
                        chat_id=ALERT_CHANNEL,
                        text=msg,
                        reply_markup=rm,
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    print(f"Channel broadcast failed: {e}")

        except Exception as e:
            print(f"Signal Alert Monitor error: {e}")

        await asyncio.sleep(SCAN_INTERVAL)


def main():
    if not BOT_TOKEN: print("ERROR: TELEGRAM_BOT_TOKEN not set"); return
    app = Application.builder().token(BOT_TOKEN).build()
    for cmd, fn in [
        ("start", cmd_start), ("register", cmd_register), ("deposit", cmd_deposit),
        ("balance", cmd_balance), ("signal", cmd_signal),
        ("trade", cmd_trade), ("topwallets", cmd_topwallets), ("track", cmd_track),
        ("help", cmd_help), ("analyse", cmd_analyse), ("analytics", cmd_analytics)
    ]:
        app.add_handler(CommandHandler(cmd, fn))
    
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Start TP/SL background monitor
    import asyncio
    
    async def run_tasks():
        asyncio.create_task(monitor_tp_sl(app))
        asyncio.create_task(monitor_copy_trades(app))
        asyncio.create_task(monitor_signal_performance(app))
        asyncio.create_task(monitor_signal_alerts(app))
    
    app.post_init = lambda a: run_tasks()
    
    print("Avegram v2 running on proxy wallet mode...")
    app.run_polling()

if __name__ == "__main__": main()


