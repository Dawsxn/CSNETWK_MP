from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Tuple, Optional
import time

from . import config

REQUIRED_FIELDS = {
    "PROFILE": ["TYPE", "USER_ID", "DISPLAY_NAME", "STATUS"],
    "POST": ["TYPE", "USER_ID", "CONTENT", "TTL", "MESSAGE_ID", "TOKEN"],
    "DM": ["TYPE", "FROM", "TO", "CONTENT", "TIMESTAMP", "MESSAGE_ID", "TOKEN"],
    "PING": ["TYPE", "USER_ID"],
    "ACK": ["TYPE", "MESSAGE_ID", "STATUS"],
    "FOLLOW": ["TYPE", "FROM", "TO", "TIMESTAMP", "MESSAGE_ID", "TOKEN"],
    "UNFOLLOW": ["TYPE", "FROM", "TO", "TIMESTAMP", "MESSAGE_ID", "TOKEN"],
}

OPTIONAL_FIELDS = {
    "PROFILE": ["AVATAR_TYPE", "AVATAR_ENCODING", "AVATAR_DATA"],
}


@dataclass
class ParsedMessage:
    type: str
    kv: Dict[str, str]
    raw: str
    addr: Optional[Tuple[str, int]] = None


def format_message(kv: Dict[str, str]) -> str:
    lines = [f"{k}: {v}" for k, v in kv.items()]
    return "\n".join(lines) + config.MSG_TERMINATOR


def parse_message(raw: str) -> ParsedMessage:
    raw = raw.replace("\r\n", "\n")
    if raw.endswith(config.MSG_TERMINATOR):
        body = raw[: -len(config.MSG_TERMINATOR)]
    else:
        body = raw.strip("\n")
    kv: Dict[str, str] = {}
    for line in body.split("\n"):
        if not line.strip():
            continue
        if ":" not in line:
            # ignore malformed line pieces for M1, but keep raw
            continue
        key, value = line.split(":", 1)
        kv[key.strip().upper()] = value.lstrip()

    msg_type = kv.get("TYPE", "").upper()
    if not msg_type:
        raise ValueError("Missing TYPE")

    # Light validation for M1
    required = REQUIRED_FIELDS.get(msg_type)
    if required:
        missing = [f for f in required if f not in kv]
        if missing:
            raise ValueError(f"Missing fields for {msg_type}: {missing}")

    # Defaults
    if msg_type == "POST" and "TTL" not in kv:
        kv["TTL"] = str(config.DEFAULT_TTL)
    if msg_type == "DM" and "TIMESTAMP" not in kv:
        kv["TIMESTAMP"] = str(int(time.time()))

    return ParsedMessage(type=msg_type, kv=kv, raw=raw)


def is_token_like(token: str) -> bool:
    # Basic structure check: user_id|timestamp|scope or user_id|expiry|scope
    parts = token.split("|")
    if len(parts) != 3:
        return False
    user, ts, scope = parts
    if not user or not scope:
        return False
    try:
        int(ts)
    except ValueError:
        return False
    return True
