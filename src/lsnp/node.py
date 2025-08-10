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
        # presence scheduler fields
        self._presence_thread = None
        self._presence_stop = threading.Event()
        self._last_profile_sent = 0.0

    def start(self):
        self.udp.start()
        # announce profile on start
        self.broadcast_profile()
        self._last_profile_sent = time.time()
        # presence scheduler thread
        self._presence_stop.clear()
        self._presence_thread = threading.Thread(target=self._presence_loop, daemon=True)
        self._presence_thread.start()

    def stop(self):
        self._presence_stop.set()
        if self._presence_thread:
            self._presence_thread.join(timeout=1)
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
            # do not print; reply with PROFILE to the sender host (unicast)
            try:
                host = pm.addr[0] if pm.addr else None
                if host:
                    self._send_profile_unicast(host)
            except Exception:
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

    def _send_profile_unicast(self, host: str):
        kv = {
            "TYPE": "PROFILE",
            "USER_ID": self.user_id,
            "DISPLAY_NAME": self.display_name,
            "STATUS": self.status,
        }
        data = messages.format_message(kv).encode(config.ENCODING)
        self.udp.send_unicast(data, host=host)

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

    def send_follow(self, to_user_host: str, message_id: str, token: str):
        kv = {
            "TYPE": "FOLLOW",
            "MESSAGE_ID": message_id,
            "FROM": self.user_id,
            "TO": to_user_host,
            "TIMESTAMP": str(int(time.time())),
            "TOKEN": token,
        }
        host = to_user_host.split("@")[-1] if "@" in to_user_host else to_user_host
        self.udp.send_unicast(messages.format_message(kv).encode(config.ENCODING), host=host)

    def send_unfollow(self, to_user_host: str, message_id: str, token: str):
        kv = {
            "TYPE": "UNFOLLOW",
            "MESSAGE_ID": message_id,
            "FROM": self.user_id,
            "TO": to_user_host,
            "TIMESTAMP": str(int(time.time())),
            "TOKEN": token,
        }
        host = to_user_host.split("@")[-1] if "@" in to_user_host else to_user_host
        self.udp.send_unicast(messages.format_message(kv).encode(config.ENCODING), host=host)

    # background presence loop (RFC: every 300s)
    def _presence_loop(self):
        last_tick = time.time()
        while not self._presence_stop.is_set():
            self._presence_stop.wait(timeout=1.0)
            now = time.time()
            if now - last_tick >= config.PRESENCE_INTERVAL:
                # Default to PING unless a PROFILE is needed in this interval
                if now - self._last_profile_sent >= config.PRESENCE_INTERVAL:
                    self.broadcast_profile()
                    self._last_profile_sent = now
                else:
                    self.send_ping()
                last_tick = now
