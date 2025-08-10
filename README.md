# CSNETWK_MP

Local Social Networking Protocol (LSNP) — Milestone 1 base scaffold.

This repo contains a minimal, runnable Python implementation for Milestone 1:

- Clean architecture and logging
- Key-value message parsing/formatting for all listed types (PROFILE, POST, DM, PING, ACK, FOLLOW, UNFOLLOW)
- UDP send/receive with broadcast and unicast helpers
- In-memory peer and message lists
- Simple CLI to run a node and send a broadcast post

## Structure

```
src/
	lsnp/
		__init__.py
		config.py       # constants & defaults
		messages.py     # parse/format + light validation
		transport.py    # UDP socket wrapper
		state.py        # peer & message storage
		node.py         # glue logic & handlers
		cli.py          # CLI entrypoint
tests/
	test_messages.py  # basic parsing tests
pyproject.toml       # setuptools (src layout)
```

## Quick start (Windows cmd.exe)

Python 3.10+ recommended.

```
python -m unittest -v
python -m src.lsnp.cli run
```

To send a broadcast POST:

```
python -m src.lsnp.cli --name YourName post "Hello from LSNP!"
```

Single-device test (one terminal running, another sends to localhost):

```
python -m src.lsnp.cli run
# in another terminal
python -m src.lsnp.cli local-post "Hello to myself!"
```

Notes:

- UDP broadcast uses port 50999. Ensure firewall allows UDP on this port for local testing.
- Messages end with a blank line (\n\n) as per RFC.
- Verbose logging is on by default; use --quiet to reduce output.

## RFC Coverage (Milestone 1)

- Parsing and formatting: PROFILE, POST, DM, PING, ACK, FOLLOW, UNFOLLOW
- Non-verbose printing honored for PING/ACK (suppressed) and reduced info for others
- Periodic PING while running; PROFILE broadcast on start
- Lists peers, posts, and DMs in memory

## Next steps

- Add a richer CLI to show peers/posts/dms on demand
- Add proper token validation rules and TTL checks
- Add mDNS/auto-discovery refinements and timers per rubric
