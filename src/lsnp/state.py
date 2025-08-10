from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import time


@dataclass
class Peer:
    user_id: str
    display_name: str
    status: str = ""
    last_seen: float = field(default_factory=lambda: time.time())


@dataclass
class MessageRecord:
    type: str
    user_id: str
    content: str
    message_id: str
    timestamp: float


class LSNPState:
    def __init__(self):
        self.peers: Dict[str, Peer] = {}
        self.posts: List[MessageRecord] = []
        self.dms: List[MessageRecord] = []

    def update_peer(self, user_id: str, display_name: str, status: str):
        p = self.peers.get(user_id)
        now = time.time()
        if p:
            p.display_name = display_name or p.display_name
            p.status = status or p.status
            p.last_seen = now
        else:
            self.peers[user_id] = Peer(user_id=user_id, display_name=display_name, status=status, last_seen=now)

    def add_post(self, user_id: str, content: str, message_id: str):
        self.posts.append(MessageRecord(type="POST", user_id=user_id, content=content, message_id=message_id, timestamp=time.time()))

    def add_dm(self, user_id: str, content: str, message_id: str):
        self.dms.append(MessageRecord(type="DM", user_id=user_id, content=content, message_id=message_id, timestamp=time.time()))

    def list_peers(self):
        return list(self.peers.values())

    def list_posts(self):
        return list(self.posts)

    def list_dms(self):
        return list(self.dms)
