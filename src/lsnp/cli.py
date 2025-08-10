from __future__ import annotations
import argparse
import socket
import sys
import time
import random
import base64
import os

from .node import Node
from . import config


def default_user_id():
    host = socket.gethostname()
    ip = get_local_ip()
    return f"{host}@{ip}"


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def load_avatar(avatar_path: str) -> tuple[str, str, str]:
    """Load avatar from file and return (mime_type, encoding, base64_data)"""
    if not os.path.exists(avatar_path):
        raise FileNotFoundError(f"Avatar file not found: {avatar_path}")
    
    # Get file size and check limit (~20KB)
    file_size = os.path.getsize(avatar_path)
    if file_size > 20 * 1024:
        raise ValueError(f"Avatar file too large: {file_size} bytes (max ~20KB)")
    
    # Determine MIME type from file extension
    ext = os.path.splitext(avatar_path)[1].lower()
    mime_types = {
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.bmp': 'image/bmp',
        '.webp': 'image/webp'
    }
    
    mime_type = mime_types.get(ext, 'application/octet-stream')
    
    # Read and encode file
    with open(avatar_path, 'rb') as f:
        image_data = f.read()
    
    base64_data = base64.b64encode(image_data).decode('ascii')
    
    return mime_type, 'base64', base64_data


def main(argv=None):
    parser = argparse.ArgumentParser(prog="lsnp", description="LSNP CLI")
    parser.add_argument("--user", required=False, help="USER_ID like name@ip; defaults to hostname@localip")
    parser.add_argument("--name", required=False, help="Display name", default=None)
    parser.add_argument("--status", required=False, help="Status text", default="Exploring LSNP!")
    parser.add_argument("--avatar", required=False, help="Path to avatar image file (PNG, JPG, etc., max ~20KB)")
    parser.add_argument("--quiet", action="store_true", help="Non-verbose printing")

    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run", help="Run node (broadcast profile, periodic presence, receive, print events)")
    p_post = sub.add_parser("post", help="Broadcast a post")
    p_post.add_argument("content")
    p_post.add_argument("--ttl", type=int, help="Override TTL for POST (seconds)")

    p_dm = sub.add_parser("dm", help="Send a direct message to a host/user")
    p_dm.add_argument("to", help="Destination user_id or host/ip")
    p_dm.add_argument("content")

    p_follow = sub.add_parser("follow", help="Follow a user")
    p_follow.add_argument("to", help="Destination user_id or host/ip")

    p_unfollow = sub.add_parser("unfollow", help="Unfollow a user")
    p_unfollow.add_argument("to", help="Destination user_id or host/ip")

    p_show_cmd = sub.add_parser("show", help="Show peers/posts/dms once and exit")
    p_show_cmd.add_argument("what", choices=["peers", "posts", "dms"], help="What to show")

    # Tic-tac-toe commands
    p_tictactoe = sub.add_parser("tictactoe", help="Tic-tac-toe game commands")
    ttt_sub = p_tictactoe.add_subparsers(dest="ttt_cmd")
    
    p_invite = ttt_sub.add_parser("invite", help="Invite someone to play tic-tac-toe")
    p_invite.add_argument("to", help="Destination user_id or host/ip")
    p_invite.add_argument("--symbol", choices=["X", "O"], default="X", help="Your symbol (X or O)")
    
    p_move = ttt_sub.add_parser("move", help="Make a move in tic-tac-toe")
    p_move.add_argument("game_id", help="Game ID (e.g., g123)")
    p_move.add_argument("position", type=int, help="Position (0-8)")

    args = parser.parse_args(argv)

    user_id = args.user or default_user_id()
    display_name = args.name or user_id.split("@")[0]

    # Load avatar if provided
    avatar_data = None
    if args.avatar:
        try:
            avatar_type, avatar_encoding, avatar_b64 = load_avatar(args.avatar)
            avatar_data = {
                'type': avatar_type,
                'encoding': avatar_encoding,
                'data': avatar_b64
            }
            print(f"Avatar loaded: {avatar_type}, {len(avatar_b64)} characters")
        except Exception as e:
            print(f"Error loading avatar: {e}")
            return 1

    node = Node(user_id=user_id, display_name=display_name, status=args.status, 
                avatar_data=avatar_data, verbose=not args.quiet)

    # Handle tic-tac-toe commands
    if args.cmd == "tictactoe":
        if args.ttt_cmd == "invite":
            game_id = f"g{random.randint(0, 255)}"
            expiry = int(time.time()) + config.DEFAULT_TTL
            token = f"{user_id}|{expiry}|game"
            message_id = hex(int(time.time()*1000))[2:]
            
            node.start()
            node.send_tictactoe_invite(
                to_user_host=args.to,
                game_id=game_id,
                symbol=args.symbol,
                message_id=message_id,
                token=token
            )
            print(f"Tic-tac-toe invitation sent to {args.to} (Game ID: {game_id})")
            try:
                time.sleep(2)
            finally:
                node.stop()
            return 0
            
        elif args.ttt_cmd == "move":
            expiry = int(time.time()) + config.DEFAULT_TTL
            token = f"{user_id}|{expiry}|game"
            message_id = hex(int(time.time()*1000))[2:]
            
            node.start()
            
            # Brief pause to receive any pending messages (like invitations)
            time.sleep(0.5)
            
            # Get the game to determine opponent and our symbol
            game = node.tictactoe.get_game(args.game_id)
            if not game:
                # Game not found locally - send move anyway and let the network handle it
                print(f"Game {args.game_id} not found locally. Sending move...")
                
                # Send the move via broadcast - the opponent's node will handle it
                from . import messages
                kv = {
                    "TYPE": "TICTACTOE_MOVE",
                    "FROM": user_id,
                    "TO": "broadcast",
                    "GAMEID": args.game_id,
                    "MESSAGE_ID": message_id,
                    "POSITION": str(args.position),
                    "SYMBOL": "AUTO",  # Let the receiving end determine our symbol
                    "TURN": "AUTO",    # Let the receiving end determine the turn
                    "TOKEN": token,
                }
                data = messages.format_message(kv).encode(config.ENCODING)
                node.udp.send_broadcast(data)
                
                print(f"Move sent for position {args.position}")
                
                # Wait a bit longer to receive the response and see if game gets created
                time.sleep(2)
                
                # Check if we now have the game (from the response)
                game = node.tictactoe.get_game(args.game_id)
                if game:
                    board_display = node.tictactoe.format_board(args.game_id)
                    print(board_display)
                
                try:
                    time.sleep(1)
                finally:
                    node.stop()
                return 0
            
            # If we have the game locally, proceed normally
            our_symbol = game.player1_symbol if user_id == game.player1 else game.player2_symbol
            opponent = game.player2 if user_id == game.player1 else game.player1
            
            # Make the move locally first to validate
            success, message = node.tictactoe.make_move(args.game_id, user_id, args.position, our_symbol, game.current_turn)
            if not success:
                print(f"Invalid move: {message}")
                node.stop()
                return 1
            
            # Show the board immediately after our move
            board_display = node.tictactoe.format_board(args.game_id)
            print(board_display)
            
            # Send the move to opponent
            node.send_tictactoe_move(
                to_user_host=opponent,
                game_id=args.game_id,
                position=args.position,
                symbol=our_symbol,
                turn=game.current_turn - 1,  # current_turn was incremented
                message_id=message_id,
                token=token
            )
            
            # Check if game finished
            if game.finished:
                # Send result to opponent
                result = "WIN" if game.winner == user_id else "LOSS" if game.winner else "DRAW"
                node.send_tictactoe_result(
                    game_id=args.game_id,
                    to_user=opponent,
                    result="LOSS" if result == "WIN" else "WIN" if result == "LOSS" else "DRAW",
                    symbol=game.player1_symbol if opponent == game.player1 else game.player2_symbol,
                    winning_line=game.winning_line
                )
            
            try:
                time.sleep(2)
            finally:
                node.stop()
            return 0
        else:
            print("Use 'tictactoe invite <user>' or 'tictactoe move <game_id> <position>'")
            return 1

    if args.cmd == "post":
        ttl = int(args.ttl) if getattr(args, "ttl", None) else config.DEFAULT_TTL
        expiry = int(time.time()) + int(ttl)
        token = f"{user_id}|{expiry}|broadcast"

        node.start()
        node.send_post(content=args.content, message_id=hex(int(time.time()*1000))[2:], token=token, ttl=ttl)
        print(f"Post sent (TTL={ttl}s). Listening for a bit...")
        try:
            time.sleep(2)
        finally:
            node.stop()
        return 0

    if args.cmd == "dm":
        expiry = int(time.time()) + config.DEFAULT_TTL
        token = f"{user_id}|{expiry}|chat"
        node.start()
        node.send_dm(to_user_host=args.to, content=args.content, message_id=hex(int(time.time()*1000))[2:], token=token)
        print("DM sent. Listening briefly for replies...")
        try:
            time.sleep(2)
        finally:
            node.stop()
        return 0

    if args.cmd == "follow":
        expiry = int(time.time()) + config.DEFAULT_TTL
        token = f"{user_id}|{expiry}|follow"
        node.start()
        node.send_follow(to_user_host=args.to, message_id=hex(int(time.time()*1000))[2:], token=token)
        print("FOLLOW sent.")
        time.sleep(1)
        node.stop()
        return 0

    if args.cmd == "unfollow":
        expiry = int(time.time()) + config.DEFAULT_TTL
        token = f"{user_id}|{expiry}|follow"
        node.start()
        node.send_unfollow(to_user_host=args.to, message_id=hex(int(time.time()*1000))[2:], token=token)
        print("UNFOLLOW sent.")
        time.sleep(1)
        node.stop()
        return 0

    if args.cmd == "show":
        # Start briefly to receive any messages for a short window
        node.start()
        try:
            time.sleep(1)
        finally:
            node.stop()

        if args.what == "peers":
            peers = node.state.list_peers()
            if peers:
                for p in peers:
                    pfp_indicator = " [PFP]" if p.has_avatar else ""
                    print(f"- {p.display_name} ({p.user_id}) — {p.status}{pfp_indicator}")
            else:
                print("No peers found.")
        elif args.what == "posts":
            posts = node.state.list_posts()
            if posts:
                for m in posts:
                    peer = node.state.peers.get(m.user_id)
                    if peer:
                        name_with_pfp = peer.display_name + (" [PFP]" if peer.has_avatar else "")
                    else:
                        name_with_pfp = m.user_id
                    print(f"- {name_with_pfp}: {m.content} [{m.message_id}]")
            else:
                print("No posts found.")
        else:  # dms
            dms = node.state.list_dms()
            if dms:
                for m in dms:
                    peer = node.state.peers.get(m.user_id)
                    if peer:
                        name_with_pfp = peer.display_name + (" [PFP]" if peer.has_avatar else "")
                    else:
                        name_with_pfp = m.user_id
                    print(f"- {name_with_pfp}: {m.content} [{m.message_id}]")
            else:
                print("No DMs found.")
        return 0

    # default: run (if args.cmd == "run" or no subcommand supplied)
    node.start()
    avatar_status = " (with avatar)" if avatar_data else ""
    print(f"LSNP node running{avatar_status}. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())