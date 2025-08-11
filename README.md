# CSNETWK_MP (LSNP)

Local Social Networking Protocol (LSNP) reference node with CLI. Implements presence, posts, DMs, likes, follow graph, file transfer, groups, and a tic‑tac‑toe mini‑game over UDP.

Highlights

- Key‑value messages with RFC‑style formatting and defaults
- UDP broadcast and unicast transport with background receiver and presence loop
- Token validation with scopes (broadcast/chat/follow/file/group/game) and expiry
- Avatars in PROFILE via base64 image payloads, shown with [PFP] indicator
- File transfer: offer → chunked base64 transfer → received ack, with auto‑accept policy
- Groups: create/update/membership and group messages (membership‑gated)
- Tic‑tac‑toe invites/moves/results with simple board rendering
- Lightweight JSON persistence so listings survive across runs

## Structure

```
src/
	lsnp/
		__init__.py
		config.py       # constants & defaults (ports, TTL, presence interval)
		messages.py     # parse/format + token helpers
		transport.py    # UDP socket wrapper (broadcast/unicast)
		state.py        # peers/posts/dms/groups + JSON cache
		node.py         # handlers, token checks, orchestrator
		cli.py          # CLI entrypoint and commands
tests/
	test_messages.py
	test_listing.py
	test_like_and_validity.py
pyproject.toml
```

## Quick start (Windows cmd.exe)

Prereqs: Python 3.10+.

Run a node (broadcasts PROFILE, listens, periodic presence):

```bat
python -m src.lsnp.cli run
```

In another terminal, try common actions:

```bat
:: Broadcast a post (visible to followers/self)
python -m src.lsnp.cli --name Alice post "Hello from LSNP!"

:: Send a direct message to a host/IP or user@ip
python -m src.lsnp.cli --name Alice dm 127.0.0.1 "hey there"

:: Follow a peer
python -m src.lsnp.cli follow 127.0.0.1

:: Show data with a short listen window first
python -m src.lsnp.cli show peers
python -m src.lsnp.cli show posts --wait 3
python -m src.lsnp.cli show dms
python -m src.lsnp.cli show user Alice
```

Notes

- UDP broadcast uses port 50999. Allow UDP on this port in Windows Firewall for local testing.
- Messages terminate with a blank line (\n\n).
- Verbose logging is on by default; pass --quiet to reduce output.

## Avatars (PROFILE)

You can attach a small image to your profile. Supported common formats via file extension. Max size ~20KB.

```bat
python -m src.lsnp.cli --name Alice --avatar .\path\to\avatar.png run
```

Receivers show [PFP] next to names and can cache avatar bytes.

## File transfer

Offer a file, then the sender streams base64 chunks; the receiver reassembles and sends FILE_RECEIVED.

```bat
:: send a file to a specific user/host
python -m src.lsnp.cli file send 127.0.0.1 .\file.txt --desc "demo" --chunk 800
```

Details

- Token scope “file” is required and validated on OFFER/CHUNK.
- Transfers are addressed (TO gating), not broadcast.
- Auto‑accept policy can be controlled via env var below; accepted files are saved in the working folder with de‑dupe naming.
- Chunk size is honored as given (min 1 byte). Example: an 800‑byte file with --chunk 800 is sent in 1 chunk.

## Likes and social graph

```bat
:: Like a post you’ve seen (use the ts value printed in show posts)
python -m src.lsnp.cli like 127.0.0.1 1699999999

:: Unlike
python -m src.lsnp.cli like 127.0.0.1 1699999999 --unlike

:: Follow/unfollow
python -m src.lsnp.cli follow 127.0.0.1
python -m src.lsnp.cli unfollow 127.0.0.1
```

Notes

- Posts are displayed non‑verbosely only if they’re yours or authored by someone you follow (RFC‑style gating).
- show posts prints ts= and id=; ts is the integer seconds timestamp you pass to like.

## Groups

Group create/update/membership and group messages are implemented with membership checks. See CLI group features in future updates; current node prints RFC‑style messages when you’re added or when member lists change.

## Tic‑tac‑toe mini‑game

```bat
:: Invite someone (they see an invite and can respond with a move)
python -m src.lsnp.cli tictactoe invite 127.0.0.1 --symbol X

:: Make a move (0‑8). If the game exists, it validates and sends; otherwise it will broadcast a move for discovery.
python -m src.lsnp.cli tictactoe move g123 4
```

## Show/list commands

All “show …” commands briefly run the node (sending a PING), then display cached state. You can adjust the listen window.

```bat
python -m src.lsnp.cli show peers
python -m src.lsnp.cli show posts --wait 5
python -m src.lsnp.cli show dms
python -m src.lsnp.cli show user Alice
python -m src.lsnp.cli show groups
python -m src.lsnp.cli show members <GROUP_ID>
```

## Persistence and config

State (peers/posts/dms) is cached between runs.

Env variables

- LSNP_CACHE_PATH: override cache path (default: %USERPROFILE%\.lsnp\cache.json)
- LSNP_AUTO_ACCEPT_FILES: 1/0 to auto‑accept file offers (default 1)

Example:

```bat
set LSNP_AUTO_ACCEPT_FILES=0
python -m src.lsnp.cli run
```

## Testing

pytest (if available) or Python’s unittest will run the test suite.

```bat
python -m pytest -q
:: or
python -m unittest -v
```

## Troubleshooting

- If peers aren’t discovered: ensure UDP 50999 is open in firewall; try running show peers --wait 5.
- If likes or posts don’t appear: ensure you’re following the author or viewing your own posts; tokens must be unexpired.
- For file transfer on the same host, prefer unicast to 127.0.0.1 or user@127.0.0.1; large files will be chunked.

## AI usage policy

GitHub Copilot was used to guide and help during the development process. All code included in this repository was reviewed, verified, and tested by the group before submission.
