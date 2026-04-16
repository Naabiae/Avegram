"""
Avegram API Server
==================
Exposes the bot's internal state and Ave API calls over HTTP so you can
test and inspect every layer without running the Telegram bot.

Run:
    uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload

Endpoints
---------
GET  /health                       – liveness check
GET  /status                       – DB + Ave API connectivity
GET  /users                        – all registered users (no secrets)
GET  /trades                       – all active TP/SL trades
GET  /copy_trades                  – all active copy-trade configs
GET  /signals?chain=bsc&limit=25   – run a live signal scan
GET  /quote?sym=PEPE&amount=10     – get a swap quote (10 USDT → token)
GET  /errors?limit=20              – recent bot_errors rows
GET  /heartbeats                   – task heartbeat status
GET  /swap_orders?limit=20         – recent swap order log
GET  /token?addr=0x...&chain=bsc   – fetch token info from Ave API
POST /trigger/tpsl                 – run one TP/SL monitor cycle (dry-run)
"""

import asyncio
import datetime
import json
import urllib.request
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from avegram.config import AVE_API_KEY
from avegram.db import (
    db_init,
    load_copy_trades,
    load_trades,
    load_users,
    _get_pool,
)
from avegram.proxy import proxy_get, proxy_post
from ave.http import api_get


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    db_init()
    yield
    pool = _get_pool()
    if pool and not pool.closed:
        pool.close()


app = FastAPI(
    title="Avegram API",
    version="1.0.0",
    description="HTTP interface for testing the Avegram trading bot",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_proxy_get(path, params=None):
    try:
        return proxy_get(path, params)
    except Exception as e:
        return {"error": str(e)}


def _ave_url(path, params=None):
    base = "https://data.ave-api.xyz/v2"
    url = base.rstrip("/") + "/" + path.lstrip("/")
    if params:
        import urllib.parse
        url += "?" + urllib.parse.urlencode(params)
    return url


async def _ave_get(path, params=None, timeout=10):
    try:
        r = await api_get(path, params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        return {"error": f"HTTP {r.status_code}", "body": r.text[:300]}
    except Exception as e:
        return {"error": str(e)}


def _row_to_dict(row) -> dict:
    if hasattr(row, "_asdict"):
        return row._asdict()
    if isinstance(row, dict):
        return dict(row)
    return row


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok", "ts": datetime.datetime.utcnow().isoformat()}


@app.get("/status")
async def status():
    result: dict[str, Any] = {}

    # DB
    try:
        pool = _get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM users")
                user_count = cur.fetchone()[0]
        result["db"] = {"status": "ok", "user_count": user_count}
    except Exception as e:
        result["db"] = {"status": "error", "detail": str(e)}

    # Ave data API
    try:
        r = await api_get("/tokens", {"keyword": "BNB", "limit": 1, "chain": "bsc"}, timeout=8)
        result["ave_data_api"] = {
            "status": "ok" if r.status_code == 200 else "error",
            "http_status": r.status_code,
        }
    except Exception as e:
        result["ave_data_api"] = {"status": "error", "detail": str(e)}

    # Ave bot API (HMAC)
    try:
        r2 = _safe_proxy_get("/v1/thirdParty/user/getUserByAssetsId")
        result["ave_bot_api"] = {
            "status": "ok" if "error" not in r2 else "error",
            "detail": r2.get("error") if "error" in r2 else r2.get("status"),
        }
    except Exception as e:
        result["ave_bot_api"] = {"status": "error", "detail": str(e)}

    return result


@app.get("/users")
def get_users():
    users = load_users()
    # Strip sensitive session data; keep only wallet info
    safe = {}
    for uid, u in users.items():
        addr_list = u.get("address_list") or []
        safe[uid] = {
            "username": u.get("username"),
            "chain": u.get("chain"),
            "has_wallet": bool(u.get("assets_id")),
            "bsc_address": next((a.get("address") for a in addr_list if a.get("chain") == "bsc"), None),
            "state": u.get("state"),
        }
    return {"count": len(safe), "users": safe}


@app.get("/trades")
def get_trades():
    trades = load_trades()
    active = {}
    for uid, toks in trades.items():
        active_toks = {ta: t for ta, t in toks.items() if t.get("status") == "active"}
        if active_toks:
            active[uid] = active_toks
    return {"count": sum(len(v) for v in active.values()), "trades": active}


@app.get("/copy_trades")
def get_copy_trades():
    ct = load_copy_trades()
    active = {uid: {w: c for w, c in wals.items() if c.get("status") == "active"} for uid, wals in ct.items()}
    active = {k: v for k, v in active.items() if v}
    return {"count": sum(len(v) for v in active.values()), "copy_trades": active}


@app.get("/errors")
def get_errors(limit: int = Query(20, ge=1, le=200)):
    try:
        pool = _get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, telegram_id, area, message, context, created_at FROM bot_errors ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            if isinstance(r.get("created_at"), datetime.datetime):
                r["created_at"] = r["created_at"].isoformat()
        return {"count": len(rows), "errors": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/heartbeats")
def get_heartbeats():
    try:
        pool = _get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT task_name, last_ok_at, last_error_at, error_count, last_error, updated_at FROM task_heartbeats")
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            for k in ("last_ok_at", "last_error_at", "updated_at"):
                if isinstance(r.get(k), datetime.datetime):
                    r[k] = r[k].isoformat()
        return {"heartbeats": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/swap_orders")
def get_swap_orders(limit: int = Query(20, ge=1, le=200)):
    try:
        pool = _get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, telegram_id, order_id, chain, in_token, out_token, in_amount, swap_type, status, ave_status, ave_msg, created_at FROM swap_orders ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for r in rows:
            if isinstance(r.get("created_at"), datetime.datetime):
                r["created_at"] = r["created_at"].isoformat()
        return {"count": len(rows), "orders": rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/signals")
async def get_signals(
    chain: str = Query("bsc", pattern="^(bsc|eth|solana|base)$"),
    limit: int = Query(25, ge=1, le=50),
):
    """Fetch and score live signals from Ave API."""
    tokens: list[dict] = []
    seen: set[str] = set()

    # 1. Public signals endpoint
    try:
        url = f"https://data.ave-api.xyz/v2/signals/public/list?chain={chain}&pageSize=20&pageNO=1"
        req = urllib.request.Request(url, headers={"X-API-KEY": AVE_API_KEY})
        loop = asyncio.get_running_loop()
        r = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=10))
        d = json.loads(r.read())
        for s in d.get("data", []):
            ta = s.get("token", "")
            chain_tok = s.get("chain", chain)
            a = ta.split("-")[0] if "-" in ta else ta
            if a and a not in seen:
                seen.add(a)
                tokens.append({"addr": a, "chain": chain_tok, "sym": s.get("symbol", "?")})
    except Exception:
        pass

    # 2. Keyword search fallback
    for kw in ["PEPE", "SHIB", "DOGE", "BNB", "CAKE"]:
        try:
            data = await _ave_get("/tokens", {"keyword": kw, "limit": 3, "chain": chain})
            for t in data.get("data", []):
                a = (t.get("token") or "").split("-")[0]
                if a and a not in seen:
                    seen.add(a)
                    tokens.append({"addr": a, "chain": chain, "sym": t.get("symbol", "?")})
        except Exception:
            pass

    if not tokens:
        return {"signals": [], "message": "No tokens found to scan"}

    scored = []
    loop = asyncio.get_running_loop()
    for tok in tokens[:limit]:
        try:
            ta = tok["addr"]
            ct = tok["chain"]
            tid = f"{ta}-{ct}"

            d1 = await _ave_get(f"/tokens/{tid}")
            d2 = await _ave_get(f"/contracts/{tid}")

            pd = (d1.get("data") or {}).get("token", {})
            rd = d2.get("data") or {}

            price = float(pd.get("current_price_usd") or 0)
            liq = float(pd.get("liquidity") or pd.get("tvl") or 0)
            vol = float(pd.get("tx_volume_u_24h") or 0)
            chg = float(pd.get("price_change_24h") or 0)

            if rd.get("is_honeypot") == 1 or price == 0:
                continue

            conf = 0
            if liq > 50000:
                conf += 30
            if vol > 10000:
                conf += 30
            if abs(chg) > 5:
                conf += 20
            if rd.get("risk_score", 50) < 30:
                conf += 20
            conf = min(100, conf)

            if conf >= 60:
                direction = "buy" if chg < -3 else "sell" if chg > 5 else "watch"
                scored.append({
                    "sym": tok["sym"],
                    "addr": ta,
                    "chain": ct,
                    "confidence": conf,
                    "direction": direction,
                    "price_usd": price,
                    "change_24h_pct": round(chg, 2),
                    "liquidity_usd": round(liq, 0),
                    "volume_24h_usd": round(vol, 0),
                    "risk_score": rd.get("risk_score"),
                    "is_honeypot": bool(rd.get("is_honeypot")),
                })
        except Exception:
            continue

    scored.sort(key=lambda x: x["confidence"], reverse=True)
    return {"count": len(scored), "signals": scored}


@app.get("/quote")
async def get_quote(
    sym: str = Query(..., description="Token symbol, e.g. PEPE"),
    amount: float = Query(10.0, description="Amount of USDT to swap"),
    chain: str = Query("bsc", pattern="^(bsc|eth)$"),
):
    """Get an estimated swap output (USDT → token)."""
    sr = await _ave_get("/tokens", {"keyword": sym, "limit": 5, "chain": chain})
    tok_data = sr.get("data", [])
    if not tok_data:
        raise HTTPException(status_code=404, detail=f"Token '{sym}' not found on {chain.upper()}")

    ta = None
    for t in tok_data:
        if t.get("symbol", "").upper() == sym.upper():
            ta = t.get("token", "").split("-")[0]
            break
    if not ta:
        ta = tok_data[0].get("token", "").split("-")[0]

    usdt_bsc = "0x55d398326f99059fF775485246999027B3197955"
    usdt_eth = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
    in_token = usdt_eth if chain == "eth" else usdt_bsc
    in_amount = str(int(amount * 1e18))

    try:
        qr = proxy_post("/v1/thirdParty/chainWallet/getAmountOut", {
            "chain": chain,
            "inAmount": in_amount,
            "inTokenAddress": in_token,
            "outTokenAddress": ta,
        })
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ave bot-API error: {e}")

    if qr.get("status") not in (200, 0) or not qr.get("data"):
        raise HTTPException(status_code=502, detail=f"Quote failed: {qr.get('msg', 'unknown')}")

    d = qr["data"]
    estimate_raw = int(d.get("estimateOut", 0))
    token_amount = estimate_raw / (10 ** 6)
    price_usd = amount / token_amount if token_amount > 0 else 0

    return {
        "sym": sym.upper(),
        "chain": chain,
        "usdt_in": amount,
        "token_out": round(token_amount, 6),
        "price_usd_per_token": round(price_usd, 8),
        "token_address": ta,
        "spender": d.get("spender"),
    }


@app.get("/token")
async def get_token(
    addr: str = Query(..., description="Token contract address"),
    chain: str = Query("bsc", pattern="^(bsc|eth|solana|base)$"),
):
    """Fetch full token info + contract risk data from Ave API."""
    tid = f"{addr}-{chain}"
    token_data = await _ave_get(f"/tokens/{tid}")
    contract_data = await _ave_get(f"/contracts/{tid}")
    return {
        "token": (token_data.get("data") or {}).get("token", {}),
        "contract": contract_data.get("data") or {},
    }


@app.post("/trigger/tpsl")
async def trigger_tpsl():
    """
    Dry-run one iteration of the TP/SL monitor: returns which trades would
    have triggered without executing any swap.
    """
    usdt_addr = "0x55d398326f99059fF775485246999027B3197955"
    trades = load_trades()
    users = load_users()
    would_trigger = []

    for uid, user_trades in trades.items():
        if uid not in users or not users[uid].get("assets_id"):
            continue
        for ta, t in user_trades.items():
            if t.get("status") != "active":
                continue
            chain = t.get("chain", "bsc")
            entry = float(t.get("entry_price") or 0)
            if entry == 0:
                continue
            try:
                pr = await api_get(f"/tokens/{ta}-{chain}")
                if pr.status_code != 200 or not pr.json().get("data"):
                    continue
                curr = float(pr.json()["data"].get("token", {}).get("current_price_usd", 0))
                if curr == 0:
                    continue
                tp = entry * (1 + t["tp_pct"] / 100)
                sl = entry * (1 + t["sl_pct"] / 100)
                hit = None
                if curr >= tp:
                    hit = "take_profit"
                elif curr <= sl:
                    hit = "stop_loss"
                would_trigger.append({
                    "uid": uid,
                    "token": ta,
                    "symbol": t.get("symbol"),
                    "chain": chain,
                    "entry_price": entry,
                    "current_price": curr,
                    "tp_target": round(tp, 8),
                    "sl_target": round(sl, 8),
                    "pnl_pct": round((curr - entry) / entry * 100, 2),
                    "would_trigger": hit,
                })
            except Exception:
                continue

    return {"checked": len(would_trigger), "would_trigger": would_trigger}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=True)
