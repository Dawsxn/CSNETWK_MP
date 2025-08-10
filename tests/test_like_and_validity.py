import unittest
import os
import sys
import time

# Ensure src/ is on sys.path for direct imports without installation
ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from lsnp import messages
from lsnp.state import LSNPState


class TestLikeAndValidity(unittest.TestCase):
    def test_like_parsing_defaults(self):
        raw = (
            "TYPE: LIKE\n"
            "FROM: alice@1.2.3.4\n"
            "TO: bob@5.6.7.8\n"
            "POST_TIMESTAMP: 1728938500\n"
            "ACTION: LIKE\n"
            "TOKEN: alice@1.2.3.4|9999999999|broadcast\n\n"
        )
        pm = messages.parse_message(raw)
        self.assertEqual(pm.type, "LIKE")
        # parser should add TIMESTAMP default
        self.assertIn("TIMESTAMP", pm.kv)

    def test_validity_filtering(self):
        st = LSNPState()
        now = time.time()
        # Add one expired post and one valid post
        st.add_post("u1", "expired", "m1", timestamp=now - 100, expires_at=now - 10)
        st.add_post("u1", "valid", "m2", timestamp=now, expires_at=now + 100)
        posts = st.list_posts_by_user("u1", only_valid=True)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].content, "valid")

        # DMs validity
        st.add_dm("u1", "expired dm", "d1", timestamp=now - 50, expires_at=now - 1)
        st.add_dm("u1", "ok dm", "d2", timestamp=now, expires_at=now + 50)
        dms = st.list_dms_by_user("u1", only_valid=True)
        self.assertEqual(len(dms), 1)
        self.assertEqual(dms[0].content, "ok dm")


if __name__ == "__main__":
    unittest.main()
