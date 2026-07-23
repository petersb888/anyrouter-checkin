"""Send the LinuxDO result through the repository's existing ServerChan secret."""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.request import Request, urlopen


def server_push_url(server_push_key: str) -> str:
    if server_push_key.startswith(("http://", "https://")):
        return server_push_key
    return f"https://sctapi.ftqq.com/{server_push_key}.send"


def send_notification(server_push_key: str, title: str, content: str) -> None:
    payload = json.dumps({"title": title, "desp": content}).encode("utf-8")
    request = Request(
        server_push_url(server_push_key),
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "anyrouter-checkin-linuxdo-notifier/1.0",
        },
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"ServerChan returned HTTP {response.status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a LinuxDO completion notification.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--content", required=True)
    args = parser.parse_args()

    server_push_key = os.environ.get("SERVERPUSHKEY", "").strip()
    if not server_push_key:
        print("SERVERPUSHKEY is not configured", file=sys.stderr)
        return 1

    try:
        send_notification(server_push_key, args.title, args.content)
    except Exception as exc:
        print(f"LinuxDO notification failed: {exc}", file=sys.stderr)
        return 1

    print("LinuxDO success notification sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
