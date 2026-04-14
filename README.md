# Avegram — Crypto Signal Bot + Spot Trading on Telegram

Crypto trading bot that scans tokens for signals, tracks portfolios in USD, and executes spot trades — all from Telegram.

---

## What It Does

**Signal Scanner** — Scans 30+ trending tokens on BSC and Solana, checks honeypot/rug/liq/risk, generates signals at 60%+ confidence with BUY/SELL/WATCH + entry/TP/SL.

**Portfolio Tracker** — Multi-chain wallet per user. Shows all token holdings valued in USD using real-time Ave price feeds.

**Spot Trading** — Quote → Confirm → Execute flow. Users deposit USDT to their bot-managed wallet, trade any token on BSC/Solana by name.

---

## Architecture

```
Telegram Bot (signal_telegram.py)
├── bot_wallet.py         — HD wallet generation, user store (users.json)
├── signal_bot.py          — CLI scanner (used by /signal command)
└── trade_bot.py           — Quote/confirm/execute flow (used by /trade)

Ave Cloud API
├── /tokens               — Token search + price data
├── /contracts            — Honeypot, rug, LP lock, risk level
├── /address/walletinfo/tokens  — Portfolio holdings + USD values
└── /v1/thirdParty/chainWallet/getAmountOut — Quote swap

Blockchain (user's key)
└── BSC / Solana — bot signs trades on user's behalf via chain wallet
```

---

## Quick Start

### Prerequisites

- Python 3.10+
- Telegram bot token ([create via @BotFather](https://t.me/BotFather))
- Ave Cloud API key ([get free at cloud.ave.ai](https://cloud.ave.ai))

### Installation

```bash
git clone https://github.com/uzochukwuV/Avegram.git
cd Avegram
pip install python-telegram-bot eth_account
```

### Configuration

```bash
export TELEGRAM_BOT_TOKEN="your_telegram_bot_token"
export AVE_API_KEY="your_ave_api_key"
export API_PLAN="free"  # free | normal | pro
```

### Run

```bash
python3 signal_telegram.py
```

---

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/register` | Generate BSC wallet + address |
| `/deposit` | Show deposit address (BSC BEP20 USDT) |
| `/balance` | Portfolio — all tokens valued in USD |
| `/chain bsc\|eth\|sol` | Switch network + generate new address |
| `/signal` | Scan 30 tokens for signals ≥60% confidence |
| `/trade SYMBOL AMOUNT` | Quote USDT→token, then confirm to execute |
| `/help` | All commands |

---

## Signal Scoring (60–100% confidence)

Each token scored across 5 checks:

| Check | Weight | Pass if |
|---|---|---|
| Liquidity | +30 | TVL > $50K |
| 24h Volume | +30 | Vol > $10K |
| Price Movement | +20 | \|24h change\| > 5% |
| Risk Level | +20 | Ave risk = 0 (clean) |

Honeypot tokens (is_honeypot = 1) are skipped entirely.

Output: BUY/SELL/WATCH + Entry price + TP1/TP2 + SL + Ave Pro link.

---

## Trading Flow

```
/trade ODIC 10
  → Search ODIC on BSC via Ave
  → Get quote: 10 USDT → ~954 ODIC (via Ave DEX routing)
  → Show confirmation with amounts + slippage
  → User clicks ✅ Confirm
  → Bot signs transaction with user's private key (stored locally)
  → Broadcasts to BSC network via public RPC
  → Returns tx hash
```

---

## Multi-Chain Support

| Chain | Signals | Portfolio | Trading |
|---|---|---|---|
| BSC | ✅ | ✅ | ✅ |
| Solana | ✅ | ✅ | ✅ |
| ETH | ✅ | ⚠️ Ave free tier | ⚠️ Ave free tier |

Switch chains: `/chain solana` — generates new Solana wallet, all balances separate per chain.

---

## Tech Stack

- **Bot**: python-telegram-bot v21+, asyncio
- **Wallet**: eth_account (HD wallet,secp256k1)
- **API**: Ave Cloud API (REST + trade endpoints)
- **Chain**: BSC (web3py), Solana (solders)
- **Config**: environment variables

---

## File Structure

```
signal-bot/
├── signal_telegram.py     # Telegram bot (main entrypoint)
├── bot_wallet.py          # HD wallet generation + user store
├── trade_bot.py           # Quote/confirm/execute for CLI testing
├── scripts/
│   └── signal_bot.py      # CLI scanner (used by /signal)
├── users.json             # User wallet store (created on /register)
└── ROC.md                 # Revenue model + competitor research
```

---

## Revenue Model

See [ROC.md](./ROC.md) for full analysis. Summary:

- **Free tier**: signal alerts only
- **Premium ($9.99/mo)**: full trading + portfolio + unlimited signals
- **Copy trading**: follow top smart wallets (phase 2)

Competitors: Maestro (free), Banana (14 ETH/mo), Phantom (free).

---

## Limitations (Free Plan)

- `/address/balance/{addr}-eth` — 404 (ETH chain data not available on free)
- Proxy wallet — requires API_PLAN=normal or pro
- Data WSS streams — requires API_PLAN=pro

---

## License

MIT