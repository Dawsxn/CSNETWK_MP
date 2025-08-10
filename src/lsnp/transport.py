import socket
import threading
from typing import Callable, Optional, Tuple
import sys
import os

from . import config


class UDPTransport:
    def __init__(self, port: int = None, bind: str = "0.0.0.0"):
        # Allow port override from environment (for Mac compatibility)
        self.port = port or int(os.environ.get('LSNP_PORT', config.PORT))
        self.bind = bind
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # On macOS, try SO_REUSEPORT for better compatibility
        if sys.platform == "darwin":
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass  # Not available or permission denied
        
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            pass
            
        try:
            self.sock.bind((self.bind, self.port))
        except OSError as e:
            if "Address already in use" in str(e):
                print(f"Error: Port {self.port} is already in use.")
                if sys.platform == "darwin":
                    print("On Mac, you cannot run multiple LSNP commands simultaneously.")
                    print("Either:")
                    print("1. Stop the running 'lsnp run' command first")
                    print("2. Use different ports: LSNP_PORT=51000 python -m src.lsnp.cli <command>")
                raise
            else:
                raise
                
        self._rx_thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self.on_message: Optional[Callable[[bytes, Tuple[str, int]], None]] = None

    def start(self):
        self._running.set()
        self._rx_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._rx_thread.start()

    def stop(self):
        self._running.clear()
        if self._rx_thread:
            self._rx_thread.join(timeout=1)
        try:
            self.sock.close()
        except OSError:
            pass

    def _recv_loop(self):
        while self._running.is_set():
            try:
                data, addr = self.sock.recvfrom(config.RECV_BUFSIZE)
            except OSError:
                break
            if not data:
                continue
            if self.on_message:
                self.on_message(data, addr)

    def send_broadcast(self, payload: bytes):
        # Use the same port we're listening on for broadcasts
        self.sock.sendto(payload, (config.BROADCAST_ADDR, self.port))

    def send_unicast(self, payload: bytes, host: str, port: Optional[int] = None):
        # Use the same port we're listening on for unicast
        self.sock.sendto(payload, (host, port or self.port))