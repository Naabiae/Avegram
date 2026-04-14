# Auto-Signal Execution & TP/SL Engine Design

## 1. Overview
This specification details the implementation of an automated Take-Profit/Stop-Loss (TP/SL) trading engine integrated directly into the Telegram Bot's signal scanner. It allows users to automatically execute a trade from a signal and set predefined exit parameters to secure profits or limit losses.

## 2. Architecture & Data Flow
- **Data Storage**: A new JSON file (`trades.json`) will be introduced to persist active TP/SL configurations.
  - Schema:
    ```json
    {
      "user_id": {
        "token_address": {
          "chain": "bsc",
          "symbol": "PEPE",
          "entry_price": 0.005,
          "invested_usdt": 50,
          "tp_pct": 50.0,
          "sl_pct": -20.0,
          "status": "active"
        }
      }
    }
    ```
- **Execution Engine**: An `asyncio` background task (`monitor_tp_sl`) will be spawned when the bot starts. It will loop continuously (e.g., every 30-60 seconds) to fetch the latest token prices for all active trades across all users.
- **Trigger Conditions**:
  - `tp_target = entry_price * (1 + (tp_pct / 100))`
  - `sl_target = entry_price * (1 + (sl_pct / 100))`
  - If `current_price >= tp_target` or `current_price <= sl_target`, the engine will initiate a SELL swap for 100% of the token balance.

## 3. UX Components
- **Signal Results (`/signal`)**:
  - Each high-confidence signal will now include an inline button: `[⚡ Auto-Trade (TP/SL)]`.
- **Configuration Flow**:
  - Clicking the button sets the user's state to `awaiting_auto_trade_amount`.
  - The bot prompts: "Enter amount of USDT to invest:"
  - State changes to `awaiting_auto_trade_tp`.
  - The bot prompts: "Enter Take-Profit % (e.g., 50):"
  - State changes to `awaiting_auto_trade_sl`.
  - The bot prompts: "Enter Stop-Loss % (e.g., -20):"
  - Upon receiving the SL, the bot immediately executes the BUY order via Ave Cloud API and saves the config to `trades.json`.
- **Portfolio View (`/balance`)**:
  - Active TP/SL targets will be appended to the user's portfolio display:
    `[⚡ TP: +50% | SL: -20%]`
- **Notifications**:
  - When a TP/SL is triggered, the bot will push a message to the user:
    "🚨 **TP Hit!** Sold X tokens for Y USDT (+Z%)."

## 4. Error Handling & Edge Cases
- **Failed Swaps**: If the initial BUY fails, the TP/SL config is aborted and not saved. If the automated SELL fails (e.g., due to slippage or insufficient liquidity), the bot will retry on the next polling cycle and optionally notify the user of the failure after 3 failed attempts.
- **Price Fetch Failures**: The polling engine will gracefully handle API timeouts or missing data by continuing to the next token.
- **Missing Balances**: If the user manually sold the token outside the bot, the engine will detect the 0 balance during a trigger event, clear the config from `trades.json`, and silently exit.

## 5. Implementation Steps
1. Create `trades.json` utility functions (`load_trades`, `save_trades`).
2. Update `cmd_signal` to generate `[⚡ Auto-Trade]` buttons with callback data containing the token address/symbol.
3. Update `handle_callback` and `handle_text` to support the multi-step configuration state machine (amount -> TP -> SL).
4. Build the `monitor_tp_sl` async loop and integrate it into `main()`.
5. Update `cmd_balance` to read from `trades.json` and display active limits.