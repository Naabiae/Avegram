# Revenue Operating Model — SignalBot

## Competitor Research (2026)

### Telegram Trading Bot Landscape
| Bot | Chains | Fee Model | Unique Feature |
|-----|--------|-----------|----------------|
| Maestro | ETH, BSC, SOL, Base, Arbitrum, TRON, Sonic | 1% per tx | Signals — auto-buy from Telegram call channels |
| Banana Gun | SOL, ETH, BSC, Base, Arbitrum | ~1% per tx | Multi-chain, DCA, limit orders |
| Trojan | SOL | 1% per tx | Solana-focused sniper |
| GMGN.ai | SOL | ~1% per tx | Copy trading, anti-MEV, wallet tracker |
| BONKbot | SOL | 1% per tx | BONK-branded Solana sniper |

### Signal Provider Subscription Pricing
| Provider | Tier | Price |
|----------|------|-------|
| 4C Trading | BTC Spot | $60/mo |
| 4C Trading | BTC+Alt Spot | $120/mo |
| 4C Trading | Futures | $150/mo |
| Crypto Inner Circle | Futures | $99-149/mo |
| Learn 2 Trade | 5 signals/day | $40-80/mo |
| Free channels | — | Free (unverified) |

---

## Recommended Pricing Model

### Phase 1 — Hackathon MVP (BSC only, free tier)
**Revenue: 0 (gather users first)**

### Phase 2 — Launch ($9.99-14.99/month)
- **Signal alerts** — daily picks via Telegram bot
- **On-chain scanner** — honeypot/rug checks
- **Smart money tracker** — whale wallet monitoring
- No trading execution yet (wait for proxy wallet)

### Phase 3 — Trading Enabled ($0.99-1.5% per tx)
- Trade execution via Ave proxy wallet (Option B)
- **1% per successful transaction** (matches industry)
- No subscription fee initially — let volume grow
- Add subscription tiers once user base established

### Phase 4 — Tiered Subscriptions
| Tier | Price | Features |
|------|-------|----------|
| Free | $0 | 10 scans/day, alerts only |
| Pro | $9.99/mo | Unlimited scans, smart money, auto-alerts |
| VIP | $29.99/mo | All Pro + copy trading, whale mirror, TP/SL alerts |

---

## Key Learnings from Competitors

1. **1% fee is industry standard** — don't go lower, it signals quality
2. **Signals → execution loop is the killer feature** — Maestro proved this with their Telegram call channel integration (users paste a signal, bot auto-executes)
3. **Anti-rug + honeypot checks convert skeptics** — leading indicator before any trade
4. **Multi-chain matters** — start BSC (low gas), add SOL and ETH as you scale
5. **Non-custodial builds trust** — Ave's proxy wallet means you never touch user funds
6. **Copy trading is the sticky feature** — hardest to build, highest retention

---

## Hackathon Differentiation Angles
1. **Smart money alpha** — whale wallet signals before the crowd
2. **Telegram-first UX** — `/trade PEPE 10` is easier than any DEX UI
3. **Safety-first** — every trade auto-runs honeypot check (most bots skip this)
4. **Streaming income** — subscription + per-trade fee = predictable revenue
