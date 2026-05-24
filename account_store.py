import json
import os
import re

from config import DB_FILE, INITIAL_CAPITAL

ACCOUNTS_DIR = os.getenv("ACCOUNTS_DIR", "accounts")


def default_account() -> dict:
    return {
        "cash": INITIAL_CAPITAL,
        "invested_capital": INITIAL_CAPITAL,
        "portfolio": [],
        "cooldowns": {},
    }


def resolve_account_id(account_id: str | None = None) -> str | None:
    return account_id or os.getenv("ACCOUNT_ID")


def account_path(account_id: str | None = None) -> str:
    account_id = resolve_account_id(account_id)
    if not account_id:
        return DB_FILE

    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", str(account_id))
    return os.path.join(ACCOUNTS_DIR, f"{safe_id}.json")


def load_account(account_id: str | None = None) -> dict:
    path = account_path(account_id)
    if not os.path.exists(path):
        return default_account()

    with open(path, "r", encoding="utf-8") as f:
        account = json.load(f)

    account.setdefault("cash", INITIAL_CAPITAL)
    account.setdefault("invested_capital", INITIAL_CAPITAL)
    account.setdefault("portfolio", [])
    account.setdefault("cooldowns", {})
    return account


def save_account(account_data: dict, account_id: str | None = None) -> None:
    path = account_path(account_id)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    tmp_file = path + ".tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(account_data, f, indent=4, ensure_ascii=False)
    os.replace(tmp_file, path)
