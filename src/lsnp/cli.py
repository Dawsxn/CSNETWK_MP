from __future__ import annotations
import argparse
import socket
import sys
import time

from .node import Node
from . import config


def main(argv=None):
    parser = argparse.ArgumentParser(prog="lsnp", description="LSNP Milestone 1 CLI")
    parser.add_argument("--user", required=False, help="USER_ID like name@ip; defaults to hostname@localip")
    parser.add_argument("--name", required=False, help="Display name", default=None)
    parser.add_argument("--status", required=False, help="Status text", default="Exploring LSNP!")
    parser.add_argument("--quiet", action="store_true", help="Non-verbose printing")

    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run", help="Run node (broadcast profile, receive, print events)")
    p_post = sub.add_parser("post", help="Broadcast a post")
    p_post.add_argument("content")

    p_show_cmd = sub.add_parser("show", help="Show peers/posts/dms once and exit")
    p_show_cmd.add_argument("what", choices=["peers", "posts", "dms"], help="What to show")

    args = parser.parse_args(argv)

    user_id = args.user or default_user_id()
    display_name = args.name or user_id.split("@")[0]

    node = Node(user_id=user_id, display_name=display_name, status=args.status, verbose=not args.quiet)

    if args.cmd == "post":
        node.start()
        node.send_post(content=args.content, message_id=hex(int(time.time()*1000))[2:], token=f"{user_id}|{int(time.time())+config.DEFAULT_TTL}|broadcast")
        print("Post sent. Listening for a bit...")
        try:
            time.sleep(2)
        finally:
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
            for p in peers:
                print(f"- {p.display_name} ({p.user_id}) — {p.status}")
        elif args.what == "posts":
            for m in node.state.list_posts():
                print(f"- {m.user_id}: {m.content} [{m.message_id}]")
        else:  # dms
            for m in node.state.list_dms():
                print(f"- {m.user_id}: {m.content} [{m.message_id}]")
    return 0

    # default: run
    node.start()
    print("LSNP node running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(2)
            node.send_ping()
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()
    return 0


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


if __name__ == "__main__":
    raise SystemExit(main())
