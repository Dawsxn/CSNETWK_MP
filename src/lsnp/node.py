from __future__ import annotations
import socket
import threading
import time
from typing import Tuple

from . import config, messages, transport, state as store


class Node:
    def __init__(self, user_id: str, display_name: str, status: str = "Exploring LSNP!", verbose: bool = True):
        self.user_id = user_id
        self.display_name = display_name
        self.status = status
        self.verbose = verbose
        self.state = store.LSNPState()
        self.udp = transport.UDPTransport()
        self.udp.on_message = self._on_udp
        self._lock = threading.Lock()

    def start(self):
        self.udp.start()
        # announce profile on start
        self.broadcast_profile()

    def stop(self):
        self.udp.stop()

    def _log(self, msg: str):
        if self.verbose:
            print(msg)

    def _on_udp(self, data: bytes, addr: Tuple[str, int]):
        try:
            text = data.decode(config.ENCODING, errors="ignore")
            parsed = messages.parse_message(text)
            parsed.addr = addr
        except Exception as e:
            self._log(f"[parse-error] from {addr}: {e}")
            return

        with self._lock:
            self._handle(parsed)

    def _handle(self, pm: messages.ParsedMessage):
        kv = pm.kv
        t = pm.type
        if t == "PROFILE":
            self.state.update_peer(kv["USER_ID"], kv.get("DISPLAY_NAME", kv["USER_ID"]), kv.get("STATUS", ""))
            self._log(f"[PROFILE] {kv.get('DISPLAY_NAME', kv['USER_ID'])}: {kv.get('STATUS','')}")
        elif t == "POST":
            self.state.add_post(kv["USER_ID"], kv.get("CONTENT", ""), kv.get("MESSAGE_ID", ""))
            name = self.state.peers.get(kv["USER_ID"], store.Peer(kv["USER_ID"], kv["USER_ID"]))
            self._log(f"[POST] {name.display_name}: {kv.get('CONTENT','')}")
        elif t == "DM":
            self.state.add_dm(kv["FROM"], kv.get("CONTENT", ""), kv.get("MESSAGE_ID", ""))
            name = self.state.peers.get(kv["FROM"], store.Peer(kv["FROM"], kv["FROM"]))
            self._log(f"[DM] {name.display_name}: {kv.get('CONTENT','')}")
        elif t == "PING":
            # do not print
            pass
        elif t == "ACK":
            pass
        elif t in ("FOLLOW", "UNFOLLOW"):
            actor = kv.get("FROM", "")
            verb = "followed" if t == "FOLLOW" else "unfollowed"
            self._log(f"[INFO] User {actor} has {verb} you")
        else:
            self._log(f"[UNKNOWN] {t}")

    # --- sending helpers ---
    def broadcast_profile(self):
        kv = {
            "TYPE": "PROFILE",
            "USER_ID": self.user_id,
            "DISPLAY_NAME": self.display_name,
            "STATUS": self.status,
        }
        data = messages.format_message(kv).encode(config.ENCODING)
        self.udp.send_broadcast(data)

    def send_post(self, content: str, message_id: str, token: str, ttl: int | None = None):
        kv = {
            "TYPE": "POST",
            "USER_ID": self.user_id,
            "CONTENT": content,
            "TTL": str(ttl if ttl is not None else config.DEFAULT_TTL),
            "MESSAGE_ID": message_id,
            "TOKEN": token,
        }
        self.udp.send_broadcast(messages.format_message(kv).encode(config.ENCODING))

    def send_dm(self, to_user_host: str, content: str, message_id: str, token: str):
        # to_user_host is host/ip from user_id or discovered addr; for M1, accept host string
        kv = {
            "TYPE": "DM",
            "FROM": self.user_id,
            "TO": to_user_host,  # simplification
            "CONTENT": content,
            "TIMESTAMP": str(int(time.time())),
            "MESSAGE_ID": message_id,
            "TOKEN": token,
        }
        self.udp.send_unicast(messages.format_message(kv).encode(config.ENCODING), host=to_user_host.split("@")[-1] if "@" in to_user_host else to_user_host)

    def send_ping(self):
        kv = {"TYPE": "PING", "USER_ID": self.user_id}
        self.udp.send_broadcast(messages.format_message(kv).encode(config.ENCODING))
