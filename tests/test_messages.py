import unittest
import os
import sys

# Ensure src/ is on sys.path for direct imports without installation
ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lsnp import messages
from lsnp import config


class TestMessages(unittest.TestCase):
    def test_parse_profile(self):
        raw = (
            "TYPE: PROFILE\n"
            "USER_ID: dave@192.168.1.10\n"
            "DISPLAY_NAME: Dave\n"
            "STATUS: Exploring LSNP!\n\n"
        )
        pm = messages.parse_message(raw)
        self.assertEqual(pm.type, "PROFILE")
        self.assertEqual(pm.kv["DISPLAY_NAME"], "Dave")

    def test_parse_post(self):
        raw = (
            "TYPE: POST\n"
            "USER_ID: dave@192.168.1.10\n"
            "CONTENT: Hello from LSNP!\n"
            "TTL: 3600\n"
            "MESSAGE_ID: f83d2b1c\n"
            "TOKEN: dave@192.168.1.10|1728941991|broadcast\n\n"
        )
        pm = messages.parse_message(raw)
        self.assertEqual(pm.type, "POST")
        self.assertTrue(messages.is_token_like(pm.kv["TOKEN"]))

    def test_parse_dm(self):
        raw = (
            "TYPE: DM\n"
            "FROM: alice@192.168.1.11\n"
            "TO: bob@192.168.1.12\n"
            "CONTENT: Hi Bob!\n"
            "TIMESTAMP: 1728938500\n"
            "MESSAGE_ID: f83d2b1d\n"
            "TOKEN: alice@192.168.1.11|1728942100|chat\n\n"
        )
        pm = messages.parse_message(raw)
        self.assertEqual(pm.type, "DM")
        self.assertTrue(messages.is_token_like(pm.kv["TOKEN"]))

    def test_parse_follow_unfollow(self):
        for t in ("FOLLOW", "UNFOLLOW"):
            raw = (
                f"TYPE: {t}\n"
                "MESSAGE_ID: f83d2b1c\n"
                "FROM: alice@192.168.1.11\n"
                "TO: dave@192.168.1.10\n"
                "TIMESTAMP: 1728939000\n"
                "TOKEN: alice@192.168.1.11|1728942600|follow\n\n"
            )
            pm = messages.parse_message(raw)
            self.assertEqual(pm.type, t)

    def test_parse_ping_ack(self):
        raw_ping = "TYPE: PING\nUSER_ID: alice@192.168.1.11\n\n"
        self.assertEqual(messages.parse_message(raw_ping).type, "PING")

        raw_ack = "TYPE: ACK\nMESSAGE_ID: f83d2b1c\nSTATUS: RECEIVED\n\n"
        self.assertEqual(messages.parse_message(raw_ack).type, "ACK")


if __name__ == "__main__":
    unittest.main()
