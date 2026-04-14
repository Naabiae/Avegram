"""
TradeBot v1 - Telegram-Ready Spot Trading Bot
Flow: Quote -> Confirm -> Execute

Usage (CLI):
    export AVE_API_KEY=your_key
    export API_PLAN=free
    python trade_bot.py buy --chain bsc --in-token 0x55d398326f99059fF775485246999027B3197955 --out-token 0x70daa947bebed0a0df80bb32f63b86d6e4160e9d --in-amount 1000000 --dry-run
    python trade_bot.py sell --chain bsc --in-token 0x70daa947bebed0a0df80bb32f63b86d6e4160e9d --out-token 0x55d398326f99059fF775485246999027B3197955 --in-amount 1000000000000000000 --dry-run
"""

import argparse
import asyncio
import json
import sys
import os
from decimal import Decimal, ROUND_DOWN

AVENUE_SCRIPTS = "/home/workspace/ave-cloud-skill/scripts"
sys.path.insert(0, AVENUE_SCRIPTS)

from ave.config import get_api_key, get_api_plan, CHAIN_ID, EVM_CHAINS
from ave.http import trade_post, api_get
from ave.output import response_ok

NATIVE_COIN = "0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"

DECIMALS = {
    "0x55d398326f99059fF775485246999027B3197955": 18,  # USDT
    "0xe9e7CEA3DedcA5984780Bafc599bD0b788a164cBb0c": 18,  # BUSD
    "0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c": 18,  # BTCB
    "0x2170Ed0880ac9A75580c2Fb7882AcFBe7e9bBD49": 18,  # ETH
    "0x0E09FaBB73Bd3Ade0a17ECC321fD13a19e81cE82": 18,  # CAKE
}

CHAIN_IDS = {v: k for k, v in CHAIN_ID.items()}


def format_amount(raw_amount: str, decimals: int) -> str:
    """Convert raw wei-like amount to human-readable string."""
    if not raw_amount or raw_amount == "0":
        return "0"
    d = Decimal(raw_amount) / Decimal(10 ** decimals)
    if d >= 1000:
        return f"{d:,.2f}"
    elif d >= 1:
        return f"{d:.4f}"
    elif d >= 0.0001:
        return f"{d:.6f}"
    else:
        return f"{d:.10f}"


def parse_amount(amount_str: str, decimals: int) -> str:
    """Convert human-readable amount to raw integer string."""
    d = Decimal(amount_str) * Decimal(10 ** decimals)
    return str(int(d.quantize(ROUND_DOWN)))


async def get_token_decimals(token_address: str, chain: str) -> int:
    """Get token decimals from Ave API or cache."""
    token_id = f"{token_address}-{chain}"
    if token_address.lower() in (NATIVE_COIN.lower(), "bnb"):
        return 18
    if token_address in DECIMALS:
        return DECIMALS[token_address]
    try:
        resp = await api_get(f"/tokens/{token_id}")
        if response_ok(resp.json()):
            data = resp.json().get("data", {})
            token_data = data.get("token", data)
            decimals_str = token_data.get("decimals", "18")
            dec = int(decimals_str)
            DECIMALS[token_address] = dec
            return dec
    except Exception:
        pass
    return 18


async def get_quote(chain: str, in_token: str, out_token: str, in_amount: str, swap_type: str) -> dict:
    """
    Get a swap quote: how much will I receive?
    swap_type: 'buy' (in_token -> out_token) or 'sell'
    """
    payload = {
        "chain": chain,
        "inAmount": in_amount,
        "inTokenAddress": in_token,
        "outTokenAddress": out_token,
        "swapType": swap_type,
    }
    resp = await trade_post("/v1/thirdParty/chainWallet/getAmountOut", payload)
    result = {"ok": False, "error": None, "data": None, "raw_response": resp.json()}

    if resp.status_code >= 400:
        result["error"] = f"HTTP {resp.status_code}: {resp.text}"
        return result

    json_resp = resp.json()
    if not response_ok(json_resp):
        result["error"] = json_resp.get("msg", "Unknown error")
        return result

    data = json_resp.get("data", {})
    estimate_out = data.get("estimateOut", "0")
    decimals = int(data.get("decimals", "18"))
    if decimals == 0:
        decimals = 18  # fallback for tokens that don't report decimals

    result["ok"] = True
    result["data"] = {
        "estimate_out": estimate_out,
        "decimals": decimals,
        "estimate_readable": format_amount(estimate_out, decimals),
        "spender": data.get("spender"),
    }
    return result


async def execute_swap(chain: str, creator_address: str, in_token: str, out_token: str,
                       in_amount: str, swap_type: str, signed_tx: str = None,
                       request_tx_id: str = None, dry_run: bool = True) -> dict:
    """
    Execute a swap. If dry_run=True, creates unsigned tx and returns it for review.
    If dry_run=False, expects signed_tx to be provided (full execution flow).
    """
    payload = {
        "chain": chain,
        "creatorAddress": creator_address,
        "inAmount": in_amount,
        "inTokenAddress": in_token,
        "outTokenAddress": out_token,
        "swapType": swap_type,
        "slippage": "0.5",  # 0.5% slippage
    }
    resp = await trade_post("/v1/thirdParty/chainWallet/createEvmTx", payload)
    result = {"ok": False, "error": None, "data": None, "dry_run": dry_run}

    if resp.status_code >= 400:
        result["error"] = f"HTTP {resp.status_code}: {resp.text}"
        return result

    json_resp = resp.json()
    if not response_ok(json_resp):
        result["error"] = json_resp.get("msg", "Unknown error")
        return result

    data = json_resp.get("data", {})
    result["ok"] = True
    result["data"] = {
        "request_tx_id": data.get("requestTxId"),
        "creator_address": data.get("creatorAddress"),
        "tx_content": data.get("txContent"),
        "gas_limit": data.get("gasLimit"),
    }

    if dry_run:
        result["message"] = "DRY RUN - No transaction executed"
        result["data"]["unsigned_tx"] = {
            "to": data.get("txContent", {}).get("to"),
            "data": data.get("txContent", {}).get("data"),
            "value": data.get("txContent", {}).get("value"),
        }
    else:
        if not signed_tx:
            result["ok"] = False
            result["error"] = "signed_tx required for live execution"
            return result
        send_resp = await trade_post("/v1/thirdParty/chainWallet/sendSignedEvmTx", {
            "chain": chain,
            "requestTxId": request_tx_id or data.get("requestTxId"),
            "signedTx": signed_tx,
        })
        if send_resp.status_code >= 400 or not response_ok(send_resp.json()):
            result["ok"] = False
            result["error"] = f"Send failed: {send_resp.text}"
        else:
            result["data"]["tx_hash"] = send_resp.json().get("data", {}).get("txHash")

    return result


async def build_confirmation_message(token_in: str, token_out: str, amount_in: str,
                                     amount_out: str, swap_type: str, chain: str) -> str:
    """Build a human-readable confirmation message."""
    in_dec = await get_token_decimals(token_in, chain)
    out_dec = await get_token_decimals(token_out, chain)
    in_display = format_amount(amount_in, in_dec)
    out_display = format_amount(amount_out, out_dec)
    action = "BUY" if swap_type == "buy" else "SELL"
    return (
        f"Confirm {action} on {chain.upper()}?\n\n"
        f"  You pay: {in_display} {token_in[:10]}...\n"
        f"  You receive: ~{out_display} {token_out[:10]}...\n"
        f"  Slippage: 0.5%\n\n"
        f"Reply with 'yes' to execute or 'no' to cancel."
    )


async def cli_trade(args):
    """CLI trade flow: quote -> confirm -> (dry-run) execute."""
    print(f"TradeBot | Chain: {args.chain} | Plan: {get_api_plan()}", file=sys.stderr)

    swap_type = "buy" if args.action == "buy" else "sell"
    in_tok = args.in_token
    out_tok = args.out_token

    # Step 1: Get quote
    print(f"\n[1] Getting quote...", file=sys.stderr)
    quote = await get_quote(args.chain, in_tok, out_tok, args.in_amount, swap_type)

    if not quote["ok"]:
        print(f"ERROR: {quote['error']}", file=sys.stderr)
        return

    qdata = quote["data"]
    print(f"  Estimate: {qdata['estimate_readable']} (raw: {qdata['estimate_out']})", file=sys.stderr)
    print(f"  Spender: {qdata['spender']}", file=sys.stderr)

    # Step 2: Show confirmation
    msg = await build_confirmation_message(
        in_tok, out_tok, args.in_amount, qdata["estimate_out"], swap_type, args.chain
    )
    print(f"\n[2] Confirmation:\n{msg}\n", file=sys.stderr)

    if args.dry_run:
        # Step 3a: Dry-run execute
        print(f"[3a] DRY RUN - Simulating transaction...", file=sys.stderr)
        # Use a placeholder creator address for dry run
        creator = "0x0000000000000000000000000000000000000001"
        exec_result = await execute_swap(
            args.chain, creator, in_tok, out_tok, args.in_amount, swap_type,
            dry_run=True
        )
        if exec_result["ok"]:
            print(f"  Status: {exec_result['message']}", file=sys.stderr)
            tx = exec_result["data"].get("unsigned_tx", {})
            print(f"  To: {tx.get('to')}", file=sys.stderr)
            print(f"  Data: {tx.get('data', '')[:80]}...", file=sys.stderr)
        else:
            print(f"  ERROR: {exec_result['error']}", file=sys.stderr)
    else:
        # Step 3b: Real execution (requires private key setup)
        print(f"[3b] LIVE EXECUTION - Requires AVE_EVM_PRIVATE_KEY env var", file=sys.stderr)
        pk = os.environ.get("AVE_EVM_PRIVATE_KEY")
        if not pk:
            print("  ERROR: AVE_EVM_PRIVATE_KEY not set. Cannot execute live trade.", file=sys.stderr)
            return
        from ave.trade.signing import get_evm_account
        account = get_evm_account()
        exec_result = await execute_swap(
            args.chain, account.address, in_tok, out_tok, args.in_amount, swap_type,
            dry_run=False, signed_tx="PLACEHOLDER_SIGNED_TX"
        )
        if exec_result["ok"]:
            print(f"  Tx submitted: {exec_result['data'].get('tx_hash')}", file=sys.stderr)
        else:
            print(f"  ERROR: {exec_result['error']}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="TradeBot - Spot Trading with Ave API")
    sub = parser.add_subparsers(dest="action", help="Trade action")

    buy = sub.add_parser("buy", help="Buy tokens")
    buy.add_argument("--chain", default="bsc", choices=["bsc", "eth", "base"])
    buy.add_argument("--in-token", required=True, help="Token to spend (address)")
    buy.add_argument("--out-token", required=True, help="Token to receive (address)")
    buy.add_argument("--in-amount", required=True, help="Amount in smallest unit (wei-like)")
    buy.add_argument("--dry-run", action="store_true", default=True, help="Dry run (default)")

    sell = sub.add_parser("sell", help="Sell tokens")
    sell.add_argument("--chain", default="bsc", choices=["bsc", "eth", "base"])
    sell.add_argument("--in-token", required=True, help="Token to spend (address)")
    sell.add_argument("--out-token", required=True, help="Token to receive (address)")
    sell.add_argument("--in-amount", required=True, help="Amount in smallest unit (wei-like)")
    sell.add_argument("--dry-run", action="store_true", default=True)

    parser.add_argument("--json", action="store_true", help="Output JSON")

    args = parser.parse_args()

    if args.action:
        asyncio.run(cli_trade(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
