import unittest
import os
import sys

# Ensure src/ is on sys.path for direct imports without installation
ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lsnp.node import Node
from lsnp import messages


class TestPeerListing(unittest.TestCase):
    def test_node_collects_peer_names_from_profiles(self):
        node = Node(user_id="self@127.0.0.1", display_name="Self", verbose=False)

        # Simulate receiving two PROFILE messages
        raw1 = (
            "TYPE: PROFILE\n"
            "USER_ID: alice@192.168.1.11\n"
            "DISPLAY_NAME: Alice\n"
            "STATUS: Hello\n\n"
        )
        raw2 = (
            "TYPE: PROFILE\n"
            "USER_ID: bob@192.168.1.12\n"
            "DISPLAY_NAME: Bob\n"
            "STATUS: Yo\n\n"
        )
        pm1 = messages.parse_message(raw1)
        pm2 = messages.parse_message(raw2)

        node._handle(pm1)
        node._handle(pm2)

        names = sorted([p.display_name for p in node.state.list_peers()])
        self.assertEqual(names, ["Alice", "Bob"])  # order sorted for stability


if __name__ == "__main__":
    unittest.main()
