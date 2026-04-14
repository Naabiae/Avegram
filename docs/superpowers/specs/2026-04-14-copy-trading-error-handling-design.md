# Smart Money Copy-Trading & Robust Error Handling Design Spec

## 1. Overview
This specification details the implementation of a Smart Money Copy-Trading engine and a comprehensive overhaul of the bot's error handling. The copy-trading engine allows users to mirror the buys and sells of profitable wallets automatically, based on percentage and maximum USDT allocations. The error handling ensures the bot never crashes and provides interactive, actionable feedback to users on Telegram.

## 2. Architecture & Data Flow (Copy-Trading)
- **Data Storage**: A new JSON file (`copy_trades.json`) will be introduced to persist active copy-trade configurations.
  - Schema:
    ```json
    {
      "user_id": {
        "target_wallet_address": {
          "chain": "bsc",
          "pct_allocation": 10.0,
          "max_usdt_per_trade": 50.0,
          "last_tx_hash": "0x...",
          "status": "active"
        }
      }
    }
    ```
- **Execution Engine**: An `asyncio` background task (`monitor_copy_trades`) will be spawned when the bot starts. It will loop continuously (e.g., every 60 seconds).
  - It will iterate through all active `target_wallet_address` entries.
  - It will fetch the latest transactions for that wallet via the Ave Cloud API.
  - If a new transaction (hash not equal to `last_tx_hash`) is a **BUY**, the bot calculates the investment amount: `min(user_usdt_balance * (pct_allocation / 100), max_usdt_per_trade)`.
  - It executes the BUY swap on the user's proxy wallet.
  - If the new transaction is a **SELL**, the bot checks the user's portfolio and mirrors the sell proportionally (e.g., if the target sells 50% of their holdings, the bot sells 50% of the user's holdings).
  - Updates `last_tx_hash` to prevent duplicate executions.

## 3. UX Components (Copy-Trading)
- **Wallet View (`/track` or `[Smart Money Wallets]`)**:
  - The output showing a wallet's holdings will now include an inline button: `[👥 Copy Trade]`.
- **Configuration Flow**:
  - Clicking the button sets the user's state to `awaiting_copy_pct`.
  - The bot prompts: "Enter the % of your USDT balance to use per copied trade (e.g., 10 for 10%):"
  - State changes to `awaiting_copy_max`.
  - The bot prompts: "Enter the maximum USDT to spend per trade (e.g., 50):"
  - Upon receiving the max USDT, the bot saves the config to `copy_trades.json` and replies with a success message confirming the active copy-trade.
- **Portfolio Integration**:
  - Active copy-trades will be displayed on the `[My Portfolio]` screen under a "Copy-Trading" section.

## 4. Robust Error Handling (Interactive)
- **Global Try/Catch**: All `asyncio` background tasks (`monitor_tp_sl`, `monitor_copy_trades`) will have an outer `try/except Exception as e` block inside their `while True` loop. This guarantees the polling engine never crashes due to unexpected network or parsing errors.
- **Interactive API Errors**: When a trade fails (e.g., `status: 3001, msg: "Not enough BNB to cover gas fees"`), the bot will catch the `msg` payload from the Ave Cloud API.
  - It will send a formatted message: 
    ```
    ❌ **Trade Failed**
    Reason: Not enough BNB to cover gas fees, please keep at least 0.01 BNB in wallet
    ```
  - It will attach inline buttons: `[🔄 Retry]` and `[❌ Dismiss]`.
  - The `[🔄 Retry]` button will re-trigger the exact trade payload that failed.
  - The `[❌ Dismiss]` button will delete the error message.

## 5. Implementation Steps
1. Create `copy_trades.json` utility functions (`load_copy_trades`, `save_copy_trades`).
2. Update `cmd_track` to include the `[👥 Copy Trade]` inline button.
3. Update `handle_callback` and `handle_text` to support the multi-step copy-trade configuration state machine (pct -> max_usdt).
4. Build the `monitor_copy_trades` background `asyncio` task and integrate it into `main()`.
5. Implement the global interactive error catching system, wrapping swap executions and updating `handle_callback` to handle the new `[🔄 Retry]` and `[❌ Dismiss]` actions.