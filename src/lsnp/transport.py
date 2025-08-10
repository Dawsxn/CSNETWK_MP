import socket
import threading
from typing import Callable, Optional, Tuple

from . import config


class UDPTransport:
    def __init__(self, port: int = config.PORT, bind: str = "0.0.0.0"):
        self.port = port
        self.bind = bind
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except OSError:
            pass
        self.sock.bind((self.bind, self.port))
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
        self.sock.sendto(payload, (config.BROADCAST_ADDR, self.port))

    def send_unicast(self, payload: bytes, host: str, port: Optional[int] = None):
        self.sock.sendto(payload, (host, port or self.port))
