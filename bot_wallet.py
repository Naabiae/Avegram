"""
SignalBot Telegram Bot - User Wallet Management
Generates HD wallets, stores user state, tracks deposits.

Users deposit USDT to their bot-managed wallet address.
"""

import json
import os
import uuid
from typing import Optional

from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_keys import keys


class UserWallet:
    """HD wallet for a single user."""

    @staticmethod
    def generate() -> tuple[str, str]:
        """Generate a new EVM wallet. Returns (address, private_key_hex)."""
        acct = Account.create()
        return acct.address, acct.key.hex()

    @staticmethod
    def from_private_key(pk_hex: str) -> LocalAccount:
        return Account.from_key(pk_hex)


class UserStore:
    """JSON-backed user store. Production would use a real DB."""

    def __init__(self, path: str = "users.json"):
        self.path = path
        self._users: dict = {}  # telegram_id -> user data
        self._addresses: dict = {}  # address -> telegram_id
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    self._users = json.load(f)
                self._addresses = {v["address"]: k for k, v in self._users.items()}
            except (json.JSONDecodeError, IOError):
                self._users = {}
                self._addresses = {}

    def save(self):
        with open(self.path, "w") as f:
            json.dump(self._users, f, indent=2)

    def register(self, telegram_id: int, username: str = "") -> dict:
        """Create a new wallet for user."""
        if str(telegram_id) in self._users:
            return self._users[str(telegram_id)]

        address, pk = UserWallet.generate()
        user = {
            "id": str(telegram_id),
            "username": username,
            "address": address,
            "pk": pk,  # In production: encrypt this!
            "deposits": [],  # list of {tx_hash, amount, time}
            "trades": [],
            "created_at": str(uuid.uuid4())[:8],
        }
        self._users[str(telegram_id)] = user
        self._addresses[address.lower()] = str(telegram_id)
        self.save()
        return user

    def get(self, telegram_id: int) -> Optional[dict]:
        return self._users.get(str(telegram_id))

    def get_by_address(self, address: str) -> Optional[dict]:
        tid = self._addresses.get(address.lower())
        return self._users.get(tid) if tid else None

    def add_deposit(self, telegram_id: int, tx_hash: str, amount: str):
        user = self.get(telegram_id)
        if user:
            user["deposits"].append({"tx_hash": tx_hash, "amount": amount})
            self.save()

    def add_trade(self, telegram_id: int, trade: dict):
        user = self.get(telegram_id)
        if user:
            user["trades"].append(trade)
            self.save()

    def all_addresses(self) -> list[str]:
        return list(self._addresses.keys())

    def get_deposits(self, telegram_id: int) -> list:
        user = self.get(telegram_id)
        return user["deposits"] if user else []

    def get_trades(self, telegram_id: int) -> list:
        user = self.get(telegram_id)
        return user["trades"] if user else []