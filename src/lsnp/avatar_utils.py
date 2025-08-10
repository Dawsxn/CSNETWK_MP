#!/usr/bin/env python3
"""
Avatar utility functions for LSNP
Save this as: src/lsnp/avatar_utils.py

Usage examples:
  python -m src.lsnp.avatar_utils save dave@192.168.1.10 dave_avatar.png
  python -m src.lsnp.avatar_utils list
  python -m src.lsnp.avatar_utils info dave@192.168.1.10
"""

from __future__ import annotations
import argparse
import sys
import os
import time
import socket


def default_user_id():
    """Get default user ID (hostname@ip)"""
    host = socket.gethostname()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return f"{host}@{ip}"


def list_avatars(lsnp_node):
    """List all peers with avatars"""
    peers_with_avatars = lsnp_node.state.list_peers_with_avatars()
    
    if not peers_with_avatars:
        print("No peers with avatars found.")
        print("\nTip: Make sure other nodes are running with avatars.")
        return
    
    print("Peers with avatars:")
    print("-" * 50)
    for peer in peers_with_avatars:
        avatar_info = str(peer.avatar)
        print(f"{peer.display_name} ({peer.user_id})")
        print(f"  Avatar: {avatar_info}")
        print(f"  Status: {peer.status}")
        print()


def save_avatar(lsnp_node, user_id: str, output_path: str):
    """Save a peer's avatar to file"""
    peer = lsnp_node.state.peers.get(user_id)
    
    if not peer:
        print(f"Peer {user_id} not found.")
        print("\nAvailable peers:")
        peers = lsnp_node.state.list_peers()
        if peers:
            for p in peers:
                avatar_status = "[has avatar]" if p.has_avatar else "[no avatar]"
                print(f"  - {p.display_name} ({p.user_id}) {avatar_status}")
        else:
            print("  No peers found. Make sure other nodes are running.")
        return False
    
    if not peer.has_avatar:
        print(f"Peer {user_id} does not have an avatar.")
        return False
    
    # Determine file extension from MIME type if not provided
    if not os.path.splitext(output_path)[1]:
        mime_to_ext = {
            'image/png': '.png',
            'image/jpeg': '.jpg',
            'image/gif': '.gif',
            'image/bmp': '.bmp',
            'image/webp': '.webp'
        }
        ext = mime_to_ext.get(peer.avatar.mime_type, '.bin')
        output_path += ext
    
    success = peer.save_avatar(output_path)
    if success:
        print(f"Avatar saved to: {output_path}")
        print(f"Size: {peer.avatar.size_bytes()} bytes")
        print(f"Type: {peer.avatar.mime_type}")
        return True
    else:
        print(f"Failed to save avatar for {user_id}")
        return False


def show_avatar_info(lsnp_node, user_id: str):
    """Show detailed avatar information for a peer"""
    peer = lsnp_node.state.peers.get(user_id)
    
    if not peer:
        print(f"Peer {user_id} not found.")
        print("\nAvailable peers:")
        peers = lsnp_node.state.list_peers()
        if peers:
            for p in peers:
                avatar_status = "[has avatar]" if p.has_avatar else "[no avatar]"
                print(f"  - {p.display_name} ({p.user_id}) {avatar_status}")
        else:
            print("  No peers found. Make sure other nodes are running.")
        return
    
    print(f"Peer: {peer.display_name} ({peer.user_id})")
    print(f"Status: {peer.status}")
    
    if peer.has_avatar:
        avatar = peer.avatar
        print(f"Avatar:")
        print(f"  MIME Type: {avatar.mime_type}")
        print(f"  Encoding: {avatar.encoding}")
        print(f"  Size: {avatar.size_bytes()} bytes")
        print(f"  Base64 length: {len(avatar.data)} characters")
        
        # Show first few characters of base64 data
        preview = avatar.data[:50] + "..." if len(avatar.data) > 50 else avatar.data
        print(f"  Data preview: {preview}")
    else:
        print("No avatar available.")


def discover_peers(lsnp_node, timeout_seconds=10):
    """Actively discover peers by sending PING and waiting for responses"""
    print(f"Discovering peers for {timeout_seconds} seconds...")
    
    # Send a few PINGs to help discover peers
    for i in range(3):
        lsnp_node.send_ping()
        time.sleep(0.5)
    
    # Wait for responses
    start_time = time.time()
    last_count = 0
    
    while time.time() - start_time < timeout_seconds:
        current_count = len(lsnp_node.state.peers)
        if current_count != last_count:
            print(f"Found {current_count} peer(s)...")
            last_count = current_count
        time.sleep(1)
    
    final_count = len(lsnp_node.state.peers)
    print(f"Discovery complete. Found {final_count} peer(s) total.")
    return final_count


def main():
    parser = argparse.ArgumentParser(description="LSNP Avatar Utilities")
    parser.add_argument("--user", help="Your USER_ID (defaults to hostname@ip)")
    parser.add_argument("--timeout", type=int, default=10, help="Seconds to wait for peer discovery (default: 10)")
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # List command
    list_parser = subparsers.add_parser("list", help="List all peers with avatars")
    
    # Save command
    save_parser = subparsers.add_parser("save", help="Save a peer's avatar to file")
    save_parser.add_argument("user_id", help="User ID of the peer")
    save_parser.add_argument("output_path", help="Output file path")
    
    # Info command
    info_parser = subparsers.add_parser("info", help="Show avatar info for a peer")
    info_parser.add_argument("user_id", help="User ID of the peer")
    
    # Discover command
    discover_parser = subparsers.add_parser("discover", help="Discover all peers on network")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Import the LSNP modules
    try:
        from . import node
    except ImportError:
        # If relative import fails, try to add parent to path
        import sys
        import os
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, parent_dir)
        try:
            from src.lsnp import node
        except ImportError:
            print("Error: Cannot import LSNP modules. Make sure you're in the right directory.")
            return 1
    
    # Create a temporary node to access peer state
    user_id = args.user or default_user_id()
    display_name = user_id.split("@")[0]
    
    temp_node = node.Node(user_id=user_id, display_name=display_name, verbose=False)
    
    # Start node to receive peer information
    print("Starting node to receive peer information...")
    temp_node.start()
    
    try:
        if args.command == "discover":
            discover_peers(temp_node, args.timeout)
            peers = temp_node.state.list_peers()
            if peers:
                print("\nAll discovered peers:")
                for p in peers:
                    avatar_status = "[PFP]" if p.has_avatar else ""
                    print(f"  - {p.display_name} ({p.user_id}) — {p.status} {avatar_status}")
            else:
                print("No peers discovered.")
        else:
            # For other commands, do active discovery first
            peer_count = discover_peers(temp_node, args.timeout)
            
            if peer_count == 0:
                print("No peers found. Make sure other LSNP nodes are running on the network.")
                return 1
            
            if args.command == "list":
                list_avatars(temp_node)
            elif args.command == "save":
                save_avatar(temp_node, args.user_id, args.output_path)
            elif args.command == "info":
                show_avatar_info(temp_node, args.user_id)
    finally:
        temp_node.stop()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())