from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import time
import base64


@dataclass
class AvatarData:
    """Avatar information"""
    mime_type: str
    encoding: str  # currently always 'base64'
    data: str      # base64 encoded image data
    
    def decode_image(self) -> bytes:
        """Decode the base64 image data to bytes"""
        if self.encoding == 'base64':
            return base64.b64decode(self.data)
        else:
            raise ValueError(f"Unsupported encoding: {self.encoding}")
    
    def size_bytes(self) -> int:
        """Get the size of the decoded image in bytes"""
        return len(self.decode_image())
    
    def __str__(self) -> str:
        return f"{self.mime_type} ({self.size_bytes()} bytes)"


@dataclass
class Peer:
    user_id: str
    display_name: str
    status: str = ""
    last_seen: float = field(default_factory=lambda: time.time())
    avatar: Optional[AvatarData] = None
    
    @property
    def has_avatar(self) -> bool:
        """Check if this peer has an avatar"""
        return self.avatar is not None
    
    def save_avatar(self, filepath: str) -> bool:
        """Save avatar to file. Returns True if successful."""
        if not self.avatar:
            return False
        
        try:
            image_data = self.avatar.decode_image()
            with open(filepath, 'wb') as f:
                f.write(image_data)
            return True
        except Exception:
            return False


@dataclass
class MessageRecord:
    type: str
    user_id: str
    content: str
    message_id: str
    timestamp: float
    expires_at: float | None = None


class LSNPState:
    def __init__(self):
        # Known peers by user_id
        self.peers = {}
        # Public posts we've seen
        self.posts = []
        # Direct messages tracked
        self.dms = []
        # Groups: group_id -> {'name': str, 'members': set[str]}
        self.groups = {}

    def update_peer(self, user_id: str, display_name: str, status: str, 
                   avatar_type: str = None, avatar_encoding: str = None, avatar_data: str = None):
        """Update peer information including optional avatar data"""
        p = self.peers.get(user_id)
        now = time.time()
        
        # Handle avatar data
        avatar = None
        if avatar_type and avatar_encoding and avatar_data:
            try:
                avatar = AvatarData(
                    mime_type=avatar_type,
                    encoding=avatar_encoding,
                    data=avatar_data
                )
            except Exception:
                # If avatar data is malformed, ignore it
                avatar = None
        
        if p:
            p.display_name = display_name or p.display_name
            p.status = status or p.status
            p.last_seen = now
            # Update avatar (could be None to remove avatar)
            if avatar or (avatar_type and avatar_encoding and avatar_data):
                p.avatar = avatar
        else:
            self.peers[user_id] = Peer(
                user_id=user_id, 
                display_name=display_name, 
                status=status, 
                last_seen=now,
                avatar=avatar
            )

    def add_post(self, user_id: str, content: str, message_id: str, *, timestamp: float | None = None, expires_at: float | None = None):
        ts = timestamp if timestamp is not None else time.time()
        self.posts.append(
            MessageRecord(
                type="POST",
                user_id=user_id,
                content=content,
                message_id=message_id,
                timestamp=ts,
                expires_at=expires_at,
            )
        )

    def add_dm(self, user_id: str, content: str, message_id: str, *, timestamp: float | None = None, expires_at: float | None = None):
        ts = timestamp if timestamp is not None else time.time()
        self.dms.append(
            MessageRecord(
                type="DM",
                user_id=user_id,
                content=content,
                message_id=message_id,
                timestamp=ts,
                expires_at=expires_at,
            )
        )

    def list_peers(self):
        return list(self.peers.values())

    def list_posts(self):
        return list(self.posts)

    def list_dms(self):
        return list(self.dms)
    
    # Filtered views
    def list_posts_by_user(self, user_id: str, *, only_valid: bool = True) -> List[MessageRecord]:
        now = time.time()
        out: List[MessageRecord] = []
        for m in self.posts:
            if m.user_id != user_id:
                continue
            if only_valid and m.expires_at is not None and m.expires_at < now:
                continue
            out.append(m)
        return out

    def list_dms_by_user(self, user_id: str, *, only_valid: bool = True) -> List[MessageRecord]:
        now = time.time()
        out: List[MessageRecord] = []
        for m in self.dms:
            if m.user_id != user_id:
                continue
            if only_valid and m.expires_at is not None and m.expires_at < now:
                continue
            out.append(m)
        return out

    def resolve_user_id(self, query: str) -> Optional[str]:
        """Resolve a user by user_id or display_name (case-insensitive exact match)."""
        if query in self.peers:
            return query
        qlower = query.lower()
        for uid, peer in self.peers.items():
            if peer.display_name.lower() == qlower:
                return uid
        return None

    def find_post_by_user_and_timestamp(self, user_id: str, post_timestamp: int) -> Optional[MessageRecord]:
        """Find a post authored by user_id with given integer timestamp (seconds)."""
        for m in self.posts:
            try:
                if m.user_id == user_id and int(m.timestamp) == int(post_timestamp):
                    return m
            except Exception:
                continue
        return None
    
    def get_peer_avatar(self, user_id: str) -> Optional[AvatarData]:
        """Get avatar data for a specific peer"""
        peer = self.peers.get(user_id)
        return peer.avatar if peer else None
    
    def list_peers_with_avatars(self) -> List[Peer]:
        """Get list of peers that have avatars"""
        return [p for p in self.peers.values() if p.has_avatar]

    # --- Groups ---
    def create_or_update_group(self, group_id: str, *, name: str | None = None, members: List[str] | None = None):
        g = self.groups.get(group_id)
        if not g:
            g = { 'name': name or group_id, 'members': set() }
            self.groups[group_id] = g
        if name:
            g['name'] = name
        if members is not None:
            for m in members:
                if m:
                    g['members'].add(m)

    def group_add_members(self, group_id: str, add: List[str]):
        if group_id not in self.groups:
            self.groups[group_id] = { 'name': group_id, 'members': set() }
        for m in add:
            if m:
                self.groups[group_id]['members'].add(m)

    def group_remove_members(self, group_id: str, remove: List[str]):
        if group_id not in self.groups:
            return
        for m in remove:
            self.groups[group_id]['members'].discard(m)

    def list_groups_for_user(self, user_id: str) -> List[tuple[str, str]]:
        out = []
        for gid, g in self.groups.items():
            if user_id in g['members']:
                out.append((gid, g['name']))
        return out

    def list_group_members(self, group_id: str) -> List[str]:
        g = self.groups.get(group_id)
        if not g:
            return []
        return sorted(g['members'])