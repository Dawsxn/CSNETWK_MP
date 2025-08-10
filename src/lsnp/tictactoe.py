from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import time


@dataclass
class TicTacToeGame:
    game_id: str
    player1: str  # user_id of player who initiated
    player2: str  # user_id of opponent
    player1_symbol: str  # X or O
    player2_symbol: str  # X or O
    board: List[str]  # 9 positions, empty string means unoccupied
    current_turn: int  # turn number, starts at 1
    whose_turn: str  # user_id of whose turn it is
    started: bool = False
    finished: bool = False
    winner: Optional[str] = None  # user_id of winner, or "DRAW"
    winning_line: Optional[List[int]] = None
    
    def __post_init__(self):
        if not self.board:
            self.board = [""] * 9


class TicTacToeManager:
    def __init__(self):
        self.games: Dict[str, TicTacToeGame] = {}
    
    def create_game(self, game_id: str, inviter: str, invitee: str, inviter_symbol: str) -> TicTacToeGame:
        """Create a new game with the inviter's symbol"""
        invitee_symbol = "O" if inviter_symbol == "X" else "X"
        
        game = TicTacToeGame(
            game_id=game_id,
            player1=inviter,
            player2=invitee,
            player1_symbol=inviter_symbol,
            player2_symbol=invitee_symbol,
            board=[""] * 9,
            current_turn=1,
            whose_turn=inviter if inviter_symbol == "X" else invitee,  # X always goes first
        )
        
        self.games[game_id] = game
        return game
    
    def get_game(self, game_id: str) -> Optional[TicTacToeGame]:
        """Get a game by ID"""
        return self.games.get(game_id)
    
    def make_move(self, game_id: str, player: str, position: int, symbol: str, turn: int) -> Tuple[bool, str]:
        """
        Make a move in the game.
        Returns (success, message)
        """
        game = self.games.get(game_id)
        if not game:
            return False, "Game not found"
        
        if game.finished:
            return False, "Game already finished"
        
        if player not in (game.player1, game.player2):
            return False, "Player not in this game"
        
        if player != game.whose_turn:
            return False, "Not your turn"
        
        if turn != game.current_turn:
            return False, f"Invalid turn number, expected {game.current_turn}"
        
        # Validate symbol matches player's assigned symbol
        expected_symbol = game.player1_symbol if player == game.player1 else game.player2_symbol
        if symbol != expected_symbol:
            return False, f"Wrong symbol, expected {expected_symbol}"
        
        if position < 0 or position > 8:
            return False, "Invalid position"
        
        if game.board[position] != "":
            return False, "Position already occupied"
        
        # Make the move
        game.board[position] = symbol
        game.current_turn += 1
        game.started = True
        
        # Switch turns
        game.whose_turn = game.player2 if player == game.player1 else game.player1
        
        # Check for win or draw
        winner, winning_line = self._check_winner(game.board)
        if winner:
            game.finished = True
            if winner == "DRAW":
                game.winner = "DRAW"
            else:
                # Find which player has the winning symbol
                game.winner = game.player1 if winner == game.player1_symbol else game.player2
                game.winning_line = winning_line
        
        return True, "Move successful"
    
    def _check_winner(self, board: List[str]) -> Tuple[Optional[str], Optional[List[int]]]:
        """
        Check if there's a winner.
        Returns (winner_symbol_or_draw, winning_line_positions)
        """
        # Winning lines
        lines = [
            [0, 1, 2], [3, 4, 5], [6, 7, 8],  # rows
            [0, 3, 6], [1, 4, 7], [2, 5, 8],  # columns
            [0, 4, 8], [2, 4, 6]              # diagonals
        ]
        
        for line in lines:
            symbols = [board[i] for i in line]
            if symbols[0] != "" and symbols[0] == symbols[1] == symbols[2]:
                return symbols[0], line
        
        # Check for draw (board full)
        if all(pos != "" for pos in board):
            return "DRAW", None
        
        return None, None
    
    def format_board(self, game_id: str) -> str:
        """Format the board for display"""
        game = self.games.get(game_id)
        if not game:
            return "Game not found"
        
        board = game.board
        lines = []
        for row in range(3):
            cells = []
            for col in range(3):
                pos = row * 3 + col
                cell = board[pos] if board[pos] else str(pos)
                cells.append(cell)
            lines.append(" | ".join(cells))
        
        result = "\n---------\n".join(lines)
        
        # Add game status
        if game.finished:
            if game.winner == "DRAW":
                result += "\nGame ended in a draw!"
            else:
                winner_name = game.winner
                result += f"\nGame over! {winner_name} wins!"
        else:
            whose_turn = game.whose_turn
            result += f"\nTurn {game.current_turn}: {whose_turn}'s turn"
        
        return result
    
    def remove_game(self, game_id: str):
        """Remove a finished game"""
        if game_id in self.games:
            del self.games[game_id]