# Avegram — Crypto Signal Bot + Spot Trading on Telegram

**Telegram bot** that combines AI-driven signal generation, smart money tracking, and spot trading in one seamless experience — powered by AVE Cloud API.

![Python](https://img.shields.io/badge/Python-3.12+-blue) ![Telegram](https://img.shields.io/badge/Telegram-Bot%20API-green) ![AVE Cloud](https://img.shields.io/badge/AVE%20Cloud-API-orange)

## What It Does

1. **Signal Scanner** — Scans top BSC tokens, runs honeypot/rug checks, scores confidence (60%+ threshold), flags BUY/SELL/WATCH
2. **Smart Money Tracker** — Shows top-performing wallets (300%+/900%+ profit), tracks their holdings and P/L per token
3. **Spot Trading** — Quote → Confirm → Execute flow with Ave's DEX aggregator routing across 300+ DEXs
4. **Multi-Chain** — BSC (default), Solana, ETH support

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/register` | Create HD wallet (BIP-39) |
| `/deposit` | Show deposit address |
| `/balance` | Portfolio with USD values |
| `/signal` | Scan tokens for signals (60%+ conf) |
| `/topwallets [chain]` | List top smart money wallets |
| `/track <address> [chain]` | Track a wallet's holdings + txs |
| `/trade <SYMBOL> <AMOUNT>` | Get quote + confirm + execute |
| `/chain <bsc\|eth\|solana>` | Switch blockchain network |
| `/help` | All commands |

## Architecture

```
┌─────────────────────────────────────────────┐
│              Telegram User                   │
└─────────────────┬───────────────────────────┘
                  │ Telegram Bot API
┌─────────────────▼───────────────────────────┐
│         signal_telegram.py (Bot Core)         │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐ │
│  │/register │ │/signal   │ │/topwallets    │ │
│  │/balance  │ │/trade    │ │/track         │ │
│  └────┬─────┘ └────┬─────┘ └──────┬───────┘ │
│       │            │              │          │
│  bot_wallet.py   Ave Cloud API         │
│  (HD wallet)     (ave-cloud-skill)     │
└─────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
┌────────────────┐   ┌─────────────────────────┐
│  Wallet Store  │   │   AVE Cloud API v2       │
│  (users.json)  │   │ /address/smart_wallet    │
└────────────────┘   │ /address/walletinfo/tokens│
                      │ /contracts/{token}       │
                      │ /v1/thirdParty/chainWallet │
                      └─────────────────────────┘
```

## Signal Scoring

Each token is scored 0–100 based on:
- **Liquidity** — +30 if TVL > $50K
- **24h Volume** — +30 if volume > $10K
- **Momentum** — +20 if |24h change| > 5%
- **Risk Score** — +20 if risk_score < 30 (from Ave)

Signals ≥60% confidence are shown. Direction is BUY (price dropped >3%), SELL (rose >5%), or WATCH.

## Tech Stack

- **Language**: Python 3.12+
- **Bot Framework**: python-telegram-bot v21+
- **Wallet**: eth_account (HD key generation, EVM signing)
- **API**: Ave Cloud (`ave-cloud-skill` repo)
- **Exchange**: Ave DEX aggregator (300+ DEXs, 160+ chains)

## Setup

```bash
# 1. Install dependencies
pip install python-telegram-bot eth_account aiohttp

# 2. Set environment variables
export TELEGRAM_BOT_TOKEN="your_telegram_bot_token"
export AVE_API_KEY="your_ave_cloud_key"        # cloud.ave.ai
export API_PLAN="free"                          # free | normal | pro

# 3. Run the bot
python signal_telegram.py
```

## Ave Cloud API

Avegram builds on the [ave-cloud-skill](https://github.com/AveCloud/ave-cloud-skill) skill suite:

| Ave Skill | Used For |
|---|---|
| `ave-data-rest` | Token search, /signal honeypot checks, /balance |
| `ave-trade-chain-wallet` | `/trade` quote + execution via Ave DEX router |

Get API key at [cloud.ave.ai](https://cloud.ave.ai) — free plan available.

## Smart Money Tracking

The `/topwallets` command queries Ave's `smart_wallet/list` endpoint — wallets ranked by:
- Number of trades with 300–900% profit
- Number of trades with 900%+ profit
- Total USD profit

`/track <address>` then shows what those pro wallets are currently holding, with per-token P/L.

## Security

- Private keys generated client-side (BIP-39)
- Keys stored locally in `users.json` (server-side managed wallet)
- No private keys ever sent to Ave API
- Trade execution requires explicit confirmation

## Hackathon

Submitted to **AVE Claw Hackathon 2026** — Demo video coming soon.

## Project Structure

```
signal-bot/
├── signal_telegram.py   # Telegram bot (all commands)
├── bot_wallet.py        # HD wallet generation + user store
├── README.md            # This file
├── ROC.md               # Revenue operating model
└── users.json           # User wallet store (git-ignored)
```

## License

MIT