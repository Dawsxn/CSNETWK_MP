from __future__ import annotations
import socket
import threading
import time
from typing import Tuple, Optional, Dict

from . import config, messages, transport, state as store
from .tictactoe import TicTacToeManager


class Node:
    def __init__(self, user_id: str, display_name: str, status: str = "Exploring LSNP!", 
                 avatar_data: Optional[Dict[str, str]] = None, verbose: bool = True):
        self.user_id = user_id
        self.display_name = display_name
        self.status = status
        self.avatar_data = avatar_data  # Dict with 'type', 'encoding', 'data' keys
        self.verbose = verbose
        self.state = store.LSNPState()
        self.tictactoe = TicTacToeManager()
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
        """Always log - for important messages that should show even in quiet mode"""
        print(msg)

    def _log_verbose(self, msg: str):
        """Only log in verbose mode"""
        if self.verbose:
            print(msg)

    def _log_verbose_message(self, pm: messages.ParsedMessage):
        """Log the full message details in verbose mode"""
        if self.verbose:
            # Format the message in a readable way, showing all fields
            formatted_msg = []
            for key, value in pm.kv.items():
                # Truncate avatar data for readability
                if key == "AVATAR_DATA" and len(value) > 50:
                    formatted_msg.append(f"{key}: {value[:50]}... ({len(value)} chars total)")
                else:
                    formatted_msg.append(f"{key}: {value}")
            
            full_msg = "\n".join(formatted_msg)
            print(f"[RECEIVED] Full message:\n{full_msg}")
            print("-" * 40)  # separator line

    def _on_udp(self, data: bytes, addr: Tuple[str, int]):
        try:
            text = data.decode(config.ENCODING, errors="ignore")
            parsed = messages.parse_message(text)
            parsed.addr = addr
        except Exception as e:
            self._log_verbose(f"[parse-error] from {addr}: {e}")
            return

        with self._lock:
            self._handle(parsed)

    def _handle(self, pm: messages.ParsedMessage):
        kv = pm.kv
        t = pm.type
        
        # Show full message details in verbose mode
        if self.verbose:
            self._log_verbose_message(pm)
        
        if t == "PROFILE":
            # Extract avatar fields if present
            avatar_type = kv.get("AVATAR_TYPE")
            avatar_encoding = kv.get("AVATAR_ENCODING")
            avatar_data = kv.get("AVATAR_DATA")
            
            self.state.update_peer(
                kv["USER_ID"], 
                kv.get("DISPLAY_NAME", kv["USER_ID"]), 
                kv.get("STATUS", ""),
                avatar_type=avatar_type,
                avatar_encoding=avatar_encoding,
                avatar_data=avatar_data
            )
            
            # Create display message for PROFILE - ALWAYS show this with PFP indicator
            display_name = kv.get("DISPLAY_NAME", kv["USER_ID"])
            status = kv.get("STATUS", "")
            
            # Add [PFP] indicator if user has avatar
            pfp_indicator = ""
            if avatar_type and avatar_data:
                pfp_indicator = " [PFP]"
            
            # Always show PROFILE messages (not just in verbose mode) with PFP indicator
            self._log(f"[PROFILE] {display_name}: {status}{pfp_indicator}")
            
            # In verbose mode, also show detailed avatar info
            if self.verbose and avatar_type and avatar_data:
                avatar_size_kb = len(avatar_data) * 3 // 4 // 1024  # rough base64 to bytes conversion
                self._log_verbose(f"          Avatar details: {avatar_type}, ~{avatar_size_kb}KB")
            
        elif t == "POST":
            self.state.add_post(kv["USER_ID"], kv.get("CONTENT", ""), kv.get("MESSAGE_ID", ""))
            peer = self.state.peers.get(kv["USER_ID"])
            if peer:
                name_with_pfp = peer.display_name + (" [PFP]" if peer.has_avatar else "")
            else:
                name_with_pfp = kv["USER_ID"]
            # Always show POST messages with PFP indicator
            self._log(f"[POST] {name_with_pfp}: {kv.get('CONTENT','')}")
        elif t == "DM":
            self.state.add_dm(kv["FROM"], kv.get("CONTENT", ""), kv.get("MESSAGE_ID", ""))
            peer = self.state.peers.get(kv["FROM"])
            if peer:
                name_with_pfp = peer.display_name + (" [PFP]" if peer.has_avatar else "")
            else:
                name_with_pfp = kv["FROM"]
            # Always show DM messages with PFP indicator
            self._log(f"[DM] {name_with_pfp}: {kv.get('CONTENT','')}")
        elif t == "PING":
            # Only show in verbose mode; reply with PROFILE to the sender host (unicast)
            self._log_verbose(f"[PING] from {kv.get('USER_ID', 'unknown')}")
            try:
                host = pm.addr[0] if pm.addr else None
                if host:
                    self._send_profile_unicast(host)
            except Exception:
                pass
        elif t == "ACK":
            self._log_verbose(f"[ACK] {kv.get('MESSAGE_ID', 'unknown')} - {kv.get('STATUS', 'unknown')}")
        elif t in ("FOLLOW", "UNFOLLOW"):
            actor = kv.get("FROM", "")
            verb = "followed" if t == "FOLLOW" else "unfollowed"
            # Always show FOLLOW/UNFOLLOW messages
            self._log(f"[INFO] User {actor} has {verb} you")
        elif t == "TICTACTOE_INVITE":
            self._handle_tictactoe_invite(kv)
        elif t == "TICTACTOE_MOVE":
            self._handle_tictactoe_move(kv)
        elif t == "TICTACTOE_RESULT":
            self._handle_tictactoe_result(kv)
        elif t == "TICTACTOE_MOVE_RESPONSE":
            self._handle_tictactoe_move_response(kv)
        else:
            self._log_verbose(f"[UNKNOWN] {t}")

    def _handle_tictactoe_move(self, kv: dict):
        """Handle incoming tic-tac-toe move"""
        from_user = kv.get("FROM", "")
        game_id = kv.get("GAMEID", "")
        position = int(kv.get("POSITION", "0"))
        symbol = kv.get("SYMBOL", "")
        turn_str = kv.get("TURN", "1")
        
        # Handle AUTO symbol and turn
        game = self.tictactoe.get_game(game_id)
        
        if symbol == "AUTO" or turn_str == "AUTO":
            if not game:
                self._log_verbose(f"[TICTACTOE] Cannot auto-determine symbol/turn for unknown game {game_id}")
                return
            
            # Auto-determine symbol and turn
            if from_user == game.player1:
                symbol = game.player1_symbol
            elif from_user == game.player2:
                symbol = game.player2_symbol
            else:
                self._log_verbose(f"[TICTACTOE] Player {from_user} not in game {game_id}")
                return
            
            turn = game.current_turn
        else:
            turn = int(turn_str)
        
        if not game:
            # Try to recreate the game - this could be the invitee's first move
            # If we sent an invitation, we should be able to recreate it
            # The from_user is making a move, so they're the invitee
            our_symbol = "O" if symbol == "X" else "X"
            
            # Create game with us as inviter (player1) and them as invitee (player2)
            game = self.tictactoe.create_game(game_id, self.user_id, from_user, our_symbol)
            self._log(f"Game {game_id} recreated! You are {our_symbol}, opponent is {symbol}")
        
        success, message = self.tictactoe.make_move(game_id, from_user, position, symbol, turn)
        
        if success:
            # Display the board
            board_display = self.tictactoe.format_board(game_id)
            self._log(board_display)
            
            # Send a response back to the move sender so they can see the board too
            # (This helps when they're using CLI from a different terminal)
            if from_user != self.user_id:  # Don't send to ourselves
                self.send_tictactoe_move_response(
                    to_user=from_user,
                    game_id=game_id,
                    board_state=game.board,
                    current_turn=game.current_turn,
                    whose_turn=game.whose_turn,
                    finished=game.finished,
                    winner=game.winner
                )
            
            # Check if game is finished
            game = self.tictactoe.get_game(game_id)
            if game and game.finished:
                # Send result message
                self.send_tictactoe_result(
                    game_id=game_id,
                    to_user=from_user,
                    result="WIN" if game.winner == self.user_id else "LOSS" if game.winner == from_user else "DRAW",
                    symbol=game.player1_symbol if self.user_id == game.player1 else game.player2_symbol,
                    winning_line=game.winning_line
                )
        else:
            self._log_verbose(f"[TICTACTOE] Invalid move: {message}")
            # Debug information
            if game:
                self._log_verbose(f"[TICTACTOE] Game state - Player1: {game.player1} ({game.player1_symbol}), Player2: {game.player2} ({game.player2_symbol})")
                self._log_verbose(f"[TICTACTOE] Current turn: {game.current_turn}, Whose turn: {game.whose_turn}")
                self._log_verbose(f"[TICTACTOE] Move attempt - From: {from_user}, Symbol: {symbol}, Turn: {turn}")

    def _handle_tictactoe_move_response(self, kv: dict):
        """Handle move response to recreate/update local game state"""
        from_user = kv.get("FROM", "")
        game_id = kv.get("GAMEID", "")
        board_str = kv.get("BOARD", "")
        current_turn = int(kv.get("CURRENT_TURN", "1"))
        whose_turn = kv.get("WHOSE_TURN", "")
        finished = kv.get("FINISHED", "false").lower() == "true"
        winner = kv.get("WINNER", "")
        
        # Get or create the game
        game = self.tictactoe.get_game(game_id)
        if not game:
            # Create a minimal game state just for display
            # We'll assume we're the other player
            our_symbol = "X"  # This will be corrected based on whose_turn
            game = self.tictactoe.create_game(game_id, self.user_id, from_user, our_symbol)
        
        # Update the game state
        game.board = board_str.split(",")
        game.current_turn = current_turn
        game.whose_turn = whose_turn
        game.finished = finished
        if winner:
            game.winner = winner
        
        # Display the board
        board_display = self.tictactoe.format_board(game_id)
        self._log(board_display)

    def _handle_tictactoe_invite(self, kv: dict):
        """Handle incoming tic-tac-toe game invitation"""
        from_user = kv.get("FROM", "")
        game_id = kv.get("GAMEID", "")
        symbol = kv.get("SYMBOL", "")  # This is the inviter's symbol
        
        # Create the game with the inviter as player1 and us as player2
        invitee_symbol = "O" if symbol == "X" else "X"
        game = self.tictactoe.create_game(game_id, from_user, self.user_id, symbol)
        
        peer = self.state.peers.get(from_user)
        if peer:
            from_name_with_pfp = peer.display_name + (" [PFP]" if peer.has_avatar else "")
        else:
            from_name_with_pfp = from_user
        
        self._log(f"{from_name_with_pfp} is inviting you to play tic-tac-toe.")
        
        if self.verbose:
            self._log_verbose(f"Game ID: {game_id}, You are: {invitee_symbol}, {from_name_with_pfp} is: {symbol}")
            self._log_verbose("Use 'tictactoe move <game_id> <position>' to play (positions 0-8)")

    def _handle_tictactoe_result(self, kv: dict):
        """Handle game result message"""
        from_user = kv.get("FROM", "")
        game_id = kv.get("GAMEID", "")
        result = kv.get("RESULT", "")
        
        game = self.tictactoe.get_game(game_id)
        if game:
            board_display = self.tictactoe.format_board(game_id)
            self._log(board_display)
            
            # Clean up finished game
            self.tictactoe.remove_game(game_id)

    def send_tictactoe_move_response(self, to_user: str, game_id: str, board_state: list, current_turn: int, whose_turn: str, finished: bool, winner: str = None):
        """Send a move response so the sender can see the updated board"""
        kv = {
            "TYPE": "TICTACTOE_MOVE_RESPONSE",
            "FROM": self.user_id,
            "TO": to_user,
            "GAMEID": game_id,
            "MESSAGE_ID": hex(int(time.time()*1000))[2:],
            "BOARD": ",".join(board_state),
            "CURRENT_TURN": str(current_turn),
            "WHOSE_TURN": whose_turn,
            "FINISHED": str(finished).lower(),
            "TIMESTAMP": str(int(time.time())),
        }
        
        if winner:
            kv["WINNER"] = winner
        
        host = to_user.split("@")[-1] if "@" in to_user else to_user
        from . import messages
        data = messages.format_message(kv).encode(config.ENCODING)
        self.udp.send_unicast(data, host=host)

    # --- sending helpers ---
    def broadcast_profile(self):
        kv = {
            "TYPE": "PROFILE",
            "USER_ID": self.user_id,
            "DISPLAY_NAME": self.display_name,
            "STATUS": self.status,
        }
        
        # Add avatar fields if we have avatar data
        if self.avatar_data:
            kv["AVATAR_TYPE"] = self.avatar_data.get("type", "")
            kv["AVATAR_ENCODING"] = self.avatar_data.get("encoding", "")
            kv["AVATAR_DATA"] = self.avatar_data.get("data", "")
        
        data = messages.format_message(kv).encode(config.ENCODING)
        self.udp.send_broadcast(data)

    def _send_profile_unicast(self, host: str):
        kv = {
            "TYPE": "PROFILE",
            "USER_ID": self.user_id,
            "DISPLAY_NAME": self.display_name,
            "STATUS": self.status,
        }
        
        # Add avatar fields if we have avatar data
        if self.avatar_data:
            kv["AVATAR_TYPE"] = self.avatar_data.get("type", "")
            kv["AVATAR_ENCODING"] = self.avatar_data.get("encoding", "")
            kv["AVATAR_DATA"] = self.avatar_data.get("data", "")
        
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

    def send_tictactoe_invite(self, to_user_host: str, game_id: str, symbol: str, message_id: str, token: str):
        """Send tic-tac-toe game invitation"""
        kv = {
            "TYPE": "TICTACTOE_INVITE",
            "FROM": self.user_id,
            "TO": to_user_host,
            "GAMEID": game_id,
            "MESSAGE_ID": message_id,
            "SYMBOL": symbol,
            "TIMESTAMP": str(int(time.time())),
            "TOKEN": token,
        }
        host = to_user_host.split("@")[-1] if "@" in to_user_host else to_user_host
        self.udp.send_unicast(messages.format_message(kv).encode(config.ENCODING), host=host)

    def send_tictactoe_move(self, to_user_host: str, game_id: str, position: int, symbol: str, turn: int, message_id: str, token: str):
        """Send tic-tac-toe move"""
        kv = {
            "TYPE": "TICTACTOE_MOVE",
            "FROM": self.user_id,
            "TO": to_user_host,
            "GAMEID": game_id,
            "MESSAGE_ID": message_id,
            "POSITION": str(position),
            "SYMBOL": symbol,
            "TURN": str(turn),
            "TOKEN": token,
        }
        host = to_user_host.split("@")[-1] if "@" in to_user_host else to_user_host
        self.udp.send_unicast(messages.format_message(kv).encode(config.ENCODING), host=host)

    def send_tictactoe_result(self, game_id: str, to_user: str, result: str, symbol: str, winning_line: list = None):
        """Send tic-tac-toe game result"""
        kv = {
            "TYPE": "TICTACTOE_RESULT",
            "FROM": self.user_id,
            "TO": to_user,
            "GAMEID": game_id,
            "MESSAGE_ID": hex(int(time.time()*1000))[2:],
            "RESULT": result,
            "SYMBOL": symbol,
            "TIMESTAMP": str(int(time.time())),
        }
        
        if winning_line:
            kv["WINNING_LINE"] = ",".join(map(str, winning_line))
        
        host = to_user.split("@")[-1] if "@" in to_user else to_user
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