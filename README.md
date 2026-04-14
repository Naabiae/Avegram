# Avegram — Crypto Signal Bot + Spot Trading on Telegram

**Telegram-native crypto trading: signal alerts + DEX execution via AVE Cloud API**

[View on GitHub](https://github.com/uzochukwuV/Avegram) | [Try the Bot](https://t.me/Clawbuns_bot)

---

## What It Does

Avegram is a Telegram bot that monitors on-chain data for trading opportunities and lets users execute spot trades directly in chat — no KYC, no separate app.

### Features

- 🔔 **Signal Alerts** — Scans tokens by volume/liquidity, filters by honeypot risk and holder concentration, rates confidence 0–100%
- 🐾 **Smart Money Tracking** — Follow top-performing wallets (900%+ profit trades) across BSC and Solana
- 💹 **Spot Trading** — Quote → Confirm → Execute flow with AVE's 300+ DEX routing
- 👛 **Multi-Chain Wallet** — HD wallet per user on BSC, ETH, Solana, Base
- 💰 **Portfolio View** — Live USDT valuation of all holdings

---

## AVE Cloud Skills Integration

This project uses the [AVE Cloud Skills](https://github.com/AveCloud/ave-cloud-skill) agent skill suite:

| AVE Skill | Script | Used For |
|---|---|---|
| `ave-data-rest` | `ave_data_rest.py` | Token search, price/kline, honeypot checks, risk scoring |
| `ave-trade-chain-wallet` | `ave_trade_rest.py` | Quote generation and transaction execution |
| `ave-wallet-suite` | (routing) | Routes data vs. trade requests to correct skill |

### How It Works

1. **Signal Generation** (`ave-data-rest`)
   - Token list via `GET /tokens?keyword=...&chain=bsc`
   - Risk data via `GET /contracts/{token}-{chain}`
   - Price + volume via `POST /tokens/price`
   - Confidence score = liquidity (30pt) + volume (30pt) + price change (20pt) + no risk flags (20pt)

2. **Quote** (`ave-trade-chain-wallet`)
   - `POST /v1/thirdParty/chainWallet/getAmountOut`
   - Returns estimated output, decimals, spender address

3. **Execute** (`ave-trade-chain-wallet`)
   - `POST /v1/thirdParty/chainWallet/createEvmTx` — build unsigned tx
   - Client-side sign with ETH private key
   - `POST /v1/thirdParty/chainWallet/sendSignedEvmTx` — broadcast

---

## Supported Chains

| Chain | Data | Signals | Trading |
|---|---|---|---|
| BSC | ✅ | ✅ | ✅ |
| Solana | ✅ | ✅ | ✅ |
| ETH | ✅ | ✅ | Partial (Ave data only, no write on free plan) |
| Base | ✅ | ✅ | ✅ |

---

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/register` | Create HD wallet (shows address) |
| `/deposit` | Show deposit address |
| `/balance` | Holdings + USDT valuation |
| `/chain bsc\|eth\|sol` | Switch active chain |
| `/signal` | Scan top tokens for signals (≥60% confidence) |
| `/trade SYMBOL AMOUNT` | Get quote for USDT → token |
| `/help` | Full command reference |

---

## Signal Confidence Scoring

```
Confidence Score (0–100):
  + Liquidity > $50k       → 30 pts
  + 24h Volume > $10k      → 30 pts
  + Price change |Δ| > 5% → 20 pts
  + No honeypot/risk flags → 20 pts
  = Signal generated if ≥ 60 pts
```

Signal levels:
- 🟢 **BUY** — price down >3% (dip entry)
- 🔴 **SELL** — price up >5% (take profit)
- 🟡 **WATCH** — momentum building, monitor

---

## Architecture

```
Telegram User
    │
    ▼
signal_telegram.py       ← Main bot (python-telegram-bot)
    │
    ├── bot_wallet.py     ← HD wallet generation (eth_account)
    │
    └── scripts/
          └── signal_bot.py  ← AVE API integration (ave-cloud-skill)
                │
                ▼
          ┌─────────────────────────────────┐
          │    AVE Cloud API (cloud.ave.ai)   │
          │  data.ave-api.xyz  +  bot-api.ave.ai  │
          └─────────────────────────────────┘
                │
                ▼
          ┌─────────────────────────────────┐
          │    BSC / Solana / ETH / Base     │
          │    DEX (PancakeSwap, Raydium…)   │
          └─────────────────────────────────┘
```

---

## Setup

### Prerequisites

- Python 3.10+
- Telegram Bot Token ([get from @BotFather](https://t.me/BotFather))
- AVE API Key ([get from cloud.ave.ai](https://cloud.ave.ai))

### Install

```bash
git clone https://github.com/uzochukwuV/Avegram.git
cd Avegram
pip install python-telegram-bot eth_account aiohttp
```

### Run

```bash
export TELEGRAM_BOT_TOKEN="your_token_here"
export AVE_API_KEY="your_ave_key_here"
export API_PLAN="free"   # free | normal | pro
python signal_telegram.py
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | Telegram bot token from @BotFather |
| `AVE_API_KEY` | ✅ | Ave Cloud API key |
| `API_PLAN` | ✅ | `free`, `normal`, or `pro` |
| `AVE_BSC_RPC_URL` | Optional | BSC JSON-RPC URL (default: public RPC) |
| `AVE_ETH_RPC_URL` | Optional | ETH JSON-RPC URL |
| `AVE_BASE_RPC_URL` | Optional | Base JSON-RPC URL |

---

## Trading Flow

```
1. /register          → Generates HD wallet, stores encrypted locally
2. User deposits USDT → To their unique wallet address (BSC BEP20)
3. /trade ODIC 10     → Bot calls Ave quote API
                       → Displays: "You pay 10 USDT → ~954,341 ODIC"
4. User confirms      → Bot builds unsigned tx
                       → Signs locally with user's private key
                       → Broadcasts via Ave API
5. Done               → TX hash returned in chat
```

---

## Demo Video

> **Recording instructions:** Open Telegram → start Avegram bot → run `/register` → `/signal` → `/trade ODIC 10` → confirm. Total walkthrough: ~3 min.

*[Record a screen share of the Telegram bot interaction. Max 5 minutes.]*

---

## Hackathon Context

**Track:** AVE Ecosystem — Trading + Monitoring Skills  
**What we built:** SignalBot v2 — combines AVE `ave-data-rest` (signal generation) + `ave-trade-chain-wallet` (quote/execute) into a single Telegram-native product  
**Innovation:** First Telegram-first DEX trading bot with integrated on-chain signal monitoring. Users get signal alerts AND can execute trades without leaving Telegram.

---

## Known Limitations

1. **No testnet** — Ave API runs on mainnet only. For hackathon demo, quote flow is shown without execution. Full execution works on mainnet with deposited funds.
2. **Proxy wallet** (managed server-side wallet) requires API_PLAN=normal or pro — upgrade unlocks /withdraw and limit orders.
3. **ETH write API** — ETH chain write operations are blocked on free plan. BSC/Solana/Base are fully functional.
4. **RPC dependency** — Balance checks require a public BSC RPC. If the default RPC is rate-limited, set `AVE_BSC_RPC_URL` manually.

---

## Roadmap

- [ ] **v1.1** — Record demo video + submit to hackathon
- [ ] **v1.2** — Upgrade to API_PLAN=normal for proxy wallet (/withdraw)
- [ ] **v2.0** — `/track <wallet>` — follow specific smart money wallets
- [ ] **v2.1** — `/subscribe <token>` — get Telegram alert when a token hits signal threshold
- [ ] **v2.2** — Limit orders via proxy wallet (TP/SL)
- [ ] **v3.0** — Mobile-optimized web dashboard + Telegram mini app

---

## License

MIT — see [LICENSE](./LICENSE)