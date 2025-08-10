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
        # file transfer buffers: file_id -> {
        #   'from': uid, 'to': uid, 'filename': str, 'filesize': int,
        #   'filetype': str, 'total_chunks': int|None, 'chunks': dict[int, bytes],
        #   'received_count': int, 'save_path': Optional[str]
        # }
        self._file_buffers = {}

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
            # Determine expiry using TTL relative to the POST timestamp
            try:
                ttl = int(kv.get("TTL", str(config.DEFAULT_TTL)))
            except ValueError:
                ttl = config.DEFAULT_TTL
            try:
                ts = float(kv.get("TIMESTAMP", str(int(time.time()))))
            except ValueError:
                ts = time.time()
            expires_at = ts + max(0, ttl)
            self.state.add_post(
                kv["USER_ID"], kv.get("CONTENT", ""), kv.get("MESSAGE_ID", ""), timestamp=ts, expires_at=expires_at
            )
            peer = self.state.peers.get(kv["USER_ID"])
            if peer:
                name_with_pfp = peer.display_name + (" [PFP]" if peer.has_avatar else "")
            else:
                name_with_pfp = kv["USER_ID"]
            # Always show POST messages with PFP indicator
            self._log(f"[POST] {name_with_pfp}: {kv.get('CONTENT','')}")
        elif t == "DM":
            # Use provided TIMESTAMP if present; compute expiry from token timestamp
            try:
                ts = float(kv.get("TIMESTAMP", str(int(time.time()))))
            except ValueError:
                ts = time.time()
            token = kv.get("TOKEN", "")
            expires_at = None
            if token:
                parts = token.split("|")
                if len(parts) == 3:
                    try:
                        expires_at = float(parts[1])
                    except ValueError:
                        expires_at = None
            self.state.add_dm(kv["FROM"], kv.get("CONTENT", ""), kv.get("MESSAGE_ID", ""), timestamp=ts, expires_at=expires_at)
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
        elif t == "LIKE":
            # Non-verbose printing guidance in RFC: show who liked your post
            actor = kv.get("FROM", "")
            action = kv.get("ACTION", "LIKE").upper()
            post_ts = kv.get("POST_TIMESTAMP", "")
            extra = ""
            try:
                pt = int(post_ts)
                # Try to find our own post content to show short context
                post = self.state.find_post_by_user_and_timestamp(self.user_id, pt)
                if post and post.content:
                    snippet = post.content[:30]
                    extra = f" — \"{snippet}\""
            except Exception:
                pass
            if action == "LIKE":
                self._log(f"[INFO] {actor} likes your post{extra} (ts={post_ts})")
            elif action == "UNLIKE":
                self._log(f"[INFO] {actor} unliked your post{extra} (ts={post_ts})")
        elif t == "TICTACTOE_INVITE":
            self._handle_tictactoe_invite(kv)
        elif t == "TICTACTOE_MOVE":
            self._handle_tictactoe_move(kv)
        elif t == "TICTACTOE_RESULT":
            self._handle_tictactoe_result(kv)
        elif t == "TICTACTOE_MOVE_RESPONSE":
            self._handle_tictactoe_move_response(kv)
        elif t == "GROUP_CREATE":
            gid = kv.get("GROUP_ID", "")
            gname = kv.get("GROUP_NAME", gid)
            members = [m for m in kv.get("MEMBERS", "").split(",") if m]
            self.state.create_or_update_group(gid, name=gname, members=members)
            if self.user_id in members:
                self._log(f"You've been added to {gname}")
        elif t == "GROUP_UPDATE":
            gid = kv.get("GROUP_ID", "")
            add = [m for m in kv.get("ADD", "").split(",") if m]
            remove = [m for m in kv.get("REMOVE", "").split(",") if m]
            if add:
                self.state.group_add_members(gid, add)
            if remove:
                self.state.group_remove_members(gid, remove)
            self._log(f'The group "{self.state.groups.get(gid, {}).get("name", gid)}" member list was updated.')
        elif t == "GROUP_MESSAGE":
            gid = kv.get("GROUP_ID", "")
            content = kv.get("CONTENT", "")
            from_user = kv.get("FROM", "")
            # Only print incoming messages to groups we belong to
            if from_user == self.user_id:
                return
            g = self.state.groups.get(gid)
            if not g or self.user_id not in g.get('members', set()):
                return
            group_name = g.get('name', gid)
            self._log(f"[GROUP:{group_name}] {from_user}: {content}")
        elif t == "FILE_OFFER":
            self._handle_file_offer(pm)
        elif t == "FILE_CHUNK":
            self._handle_file_chunk(pm)
        elif t == "FILE_RECEIVED":
            # Silent in non-verbose mode per RFC
            self._log_verbose(f"[FILE_RECEIVED] {kv.get('FILEID','')} status={kv.get('STATUS','')}")
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
        now_ts = int(time.time())
        kv = {
            "TYPE": "POST",
            "USER_ID": self.user_id,
            "CONTENT": content,
            "TTL": str(ttl if ttl is not None else config.DEFAULT_TTL),
            "MESSAGE_ID": message_id,
            "TOKEN": token,
            "TIMESTAMP": str(now_ts),
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

    # --- File transfer helpers ---
    def send_file_offer(self, to_user: str, filename: str, filesize: int, filetype: str, file_id: str, description: str | None, token: str):
        kv = {
            "TYPE": "FILE_OFFER",
            "FROM": self.user_id,
            "TO": to_user,
            "FILENAME": filename,
            "FILESIZE": str(int(filesize)),
            "FILETYPE": filetype,
            "FILEID": file_id,
            "TIMESTAMP": str(int(time.time())),
            "TOKEN": token,
        }
        if description:
            kv["DESCRIPTION"] = description
        host = to_user.split("@")[-1] if "@" in to_user else to_user
        self.udp.send_unicast(messages.format_message(kv).encode(config.ENCODING), host=host)

    def send_file_chunk(self, to_user: str, file_id: str, chunk_index: int, total_chunks: int, chunk_bytes: bytes, token: str):
        import base64
        kv = {
            "TYPE": "FILE_CHUNK",
            "FROM": self.user_id,
            "TO": to_user,
            "FILEID": file_id,
            "CHUNK_INDEX": str(int(chunk_index)),
            "TOTAL_CHUNKS": str(int(total_chunks)),
            "CHUNK_SIZE": str(len(chunk_bytes)),
            "TOKEN": token,
            "DATA": base64.b64encode(chunk_bytes).decode("ascii"),
        }
        host = to_user.split("@")[-1] if "@" in to_user else to_user
        self.udp.send_unicast(messages.format_message(kv).encode(config.ENCODING), host=host)

    def send_file_received(self, to_user: str, file_id: str, status: str = "COMPLETE"):
        kv = {
            "TYPE": "FILE_RECEIVED",
            "FROM": self.user_id,
            "TO": to_user,
            "FILEID": file_id,
            "STATUS": status,
            "TIMESTAMP": str(int(time.time())),
        }
        host = to_user.split("@")[-1] if "@" in to_user else to_user
        self.udp.send_unicast(messages.format_message(kv).encode(config.ENCODING), host=host)

    def _handle_file_offer(self, pm: messages.ParsedMessage):
        kv = pm.kv
        file_id = kv.get("FILEID", "")
        from_uid = kv.get("FROM", "")
        filename = kv.get("FILENAME", "file")
        filesize = int(kv.get("FILESIZE", "0") or 0)
        filetype = kv.get("FILETYPE", "application/octet-stream")
        desc = kv.get("DESCRIPTION", "")
        # Prepare buffer but don't auto-accept/deny; RFC says prompt user. In this CLI app, we accept by default.
        self._file_buffers[file_id] = {
            'from': from_uid,
            'to': kv.get("TO", ""),
            'filename': filename,
            'filesize': filesize,
            'filetype': filetype,
            'total_chunks': None,
            'chunks': {},
            'received_count': 0,
            'save_path': None,
        }
        # Non-verbose print: prompt-like message
        self._log(f"[INFO] {from_uid} is sending you a file do you accept? ({filename}, {filesize} bytes)")

    def _handle_file_chunk(self, pm: messages.ParsedMessage):
        import base64, os
        kv = pm.kv
        file_id = kv.get("FILEID", "")
        buf = self._file_buffers.get(file_id)
        if not buf:
            # If we never saw an offer, create a minimal buffer
            buf = self._file_buffers[file_id] = {
                'from': kv.get("FROM", ""),
                'to': kv.get("TO", ""),
                'filename': f"{file_id}.bin",
                'filesize': None,
                'filetype': "application/octet-stream",
                'total_chunks': None,
                'chunks': {},
                'received_count': 0,
                'save_path': None,
            }
        try:
            idx = int(kv.get("CHUNK_INDEX", "0"))
            total = int(kv.get("TOTAL_CHUNKS", "0"))
            data_b64 = kv.get("DATA", "")
            chunk = base64.b64decode(data_b64) if data_b64 else b""
        except Exception:
            return
        buf['chunks'][idx] = chunk
        buf['received_count'] = len(buf['chunks'])
        if not buf['total_chunks']:
            buf['total_chunks'] = total
        # If complete, assemble and save
        if buf['total_chunks'] and buf['received_count'] >= buf['total_chunks']:
            # Ensure all indices exist
            ordered = [buf['chunks'].get(i, b"") for i in range(buf['total_chunks'])]
            if any(len(x) == 0 and (i not in buf['chunks']) for i, x in enumerate(ordered)):
                return  # missing chunks
            data = b"".join(ordered)
            # Save next to cwd with filename (de-dupe)
            filename = buf['filename'] or f"{file_id}.bin"
            save_name = filename
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(save_name):
                save_name = f"{base}({counter}){ext}"
                counter += 1
            try:
                with open(save_name, 'wb') as f:
                    f.write(data)
                self._log(f"File transfer of {filename} is complete")
                # Notify sender
                self.send_file_received(to_user=buf['from'], file_id=file_id, status="COMPLETE")
                buf['save_path'] = save_name
            except Exception as e:
                self._log_verbose(f"[FILE_SAVE_ERROR] {e}")

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

    def send_like(self, to_user: str, post_timestamp: int, action: str = "LIKE"):
        """Send LIKE/UNLIKE for a post to its author over unicast per RFC."""
        expiry = int(time.time()) + config.DEFAULT_TTL
        token = f"{self.user_id}|{expiry}|broadcast"
        kv = {
            "TYPE": "LIKE",
            "FROM": self.user_id,
            "TO": to_user,
            "POST_TIMESTAMP": str(int(post_timestamp)),
            "ACTION": action.upper(),
            "TIMESTAMP": str(int(time.time())),
            "TOKEN": token,
        }
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