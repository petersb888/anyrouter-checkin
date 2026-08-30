"""Select the first Mihomo node that can use the supplied LinuxDO session.

The proxy itself being reachable is not enough for LinuxDO: a node can return
an HTTP response while Cloudflare still serves a challenge page.  This helper
switches the Mihomo select group one node at a time and probes the Discourse
session endpoint through the selected node.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

DEFAULT_CONTROLLER_URL = 'http://127.0.0.1:9090'
DEFAULT_GROUP = 'CHECKIN'
DEFAULT_COOKIE_ENV = 'PROXY_NODE_PROBE_COOKIE'
DEFAULT_SWITCH_TIMEOUT = 8.0
DEFAULT_REQUEST_TIMEOUT = 20.0
MAX_RESPONSE_BYTES = 2_000_000
CONTROLLER_OPENER = build_opener(ProxyHandler({}))


@dataclass(frozen=True)
class ProbeResult:
	"""Safe, non-sensitive result metadata for one node probe."""

	status: int | None
	classification: str


def _read_response(response: Any) -> bytes:
	return response.read(MAX_RESPONSE_BYTES + 1)[:MAX_RESPONSE_BYTES]


def _request_controller(
	url: str,
	*,
	method: str = 'GET',
	payload: dict[str, str] | None = None,
	timeout: float = DEFAULT_REQUEST_TIMEOUT,
) -> tuple[int, bytes]:
	data = json.dumps(payload).encode('utf-8') if payload is not None else None
	headers = {'Accept': 'application/json'}
	if data is not None:
		headers['Content-Type'] = 'application/json'
	request = Request(url, data=data, headers=headers, method=method)
	try:
		with CONTROLLER_OPENER.open(request, timeout=timeout) as response:
			return int(response.status), _read_response(response)
	except HTTPError as exc:
		raise RuntimeError(f'Mihomo controller returned HTTP {exc.code} for {method} {url}') from exc
	except (URLError, TimeoutError, OSError) as exc:
		raise RuntimeError(f'Mihomo controller request failed for {method} {url}: {exc}') from exc


def _controller_json(controller_url: str, path: str) -> dict[str, Any]:
	status, body = _request_controller(f'{controller_url.rstrip("/")}{path}')
	if status < 200 or status >= 300:
		raise RuntimeError(f'Mihomo controller returned HTTP {status} for {path}')
	try:
		data = json.loads(body)
	except json.JSONDecodeError as exc:
		raise RuntimeError(f'Mihomo controller returned invalid JSON for {path}') from exc
	if not isinstance(data, dict):
		raise RuntimeError(f'Mihomo controller returned an unexpected response for {path}')
	return data


def _get_group_state(controller_url: str, group: str) -> tuple[list[str], str]:
	data = _controller_json(controller_url, f'/proxies/{quote(group, safe="")}')
	all_nodes = data.get('all')
	if not isinstance(all_nodes, list):
		raise RuntimeError(f'Mihomo group {group!r} did not return a node list')
	nodes = [node for node in all_nodes if isinstance(node, str) and node.strip()]
	current = data.get('now')
	return nodes, current if isinstance(current, str) else ''


def _select_node(controller_url: str, group: str, node: str) -> None:
	status, _ = _request_controller(
		f'{controller_url.rstrip("/")}/proxies/{quote(group, safe="")}',
		method='PUT',
		payload={'name': node},
	)
	if status < 200 or status >= 300:
		raise RuntimeError(f'Mihomo controller returned HTTP {status} while selecting {node}')


def _wait_for_node(
	controller_url: str,
	group: str,
	node: str,
	*,
	timeout: float,
) -> bool:
	deadline = time.monotonic() + timeout
	while time.monotonic() < deadline:
		try:
			_, current = _get_group_state(controller_url, group)
		except RuntimeError:
			current = ''
		if current == node:
			return True
		time.sleep(0.25)
	return False


def _wait_for_candidates(
	controller_url: str,
	group: str,
	*,
	timeout: float,
) -> tuple[list[str], str]:
	"""Wait for Mihomo to fetch the provider before starting probes."""

	deadline = time.monotonic() + timeout
	last_error = 'unknown controller error'
	while time.monotonic() < deadline:
		try:
			nodes, current = _get_group_state(controller_url, group)
			if nodes:
				return nodes, current
			last_error = f'group {group!r} has no provider nodes yet'
		except RuntimeError as exc:
			last_error = str(exc)
		time.sleep(0.5)
	raise RuntimeError(f'Mihomo provider did not become ready within {timeout:g}s: {last_error}')


def classify_probe_response(status: int | None, body: bytes) -> str:
	"""Classify a response without returning any session or page contents."""

	text = body.decode('utf-8', errors='replace')
	lower_text = text.lower()
	try:
		data = json.loads(text)
	except json.JSONDecodeError:
		data = None

	if (
		status is not None
		and 200 <= status < 300
		and isinstance(data, dict)
		and isinstance(data.get('current_user'), dict)
		and data['current_user'].get('id')
	):
		return 'authenticated'
	if any(marker in lower_text for marker in ('cloudflare', 'cf-chl', 'just a moment', 'access denied')):
		return 'cloudflare-challenge'
	if status is None:
		return 'network-error'
	if isinstance(data, dict):
		return 'json-without-authentication'
	return 'non-json-response'


def _probe_node(
	proxy_url: str,
	probe_url: str,
	cookie: str,
	*,
	timeout: float,
) -> ProbeResult:
	opener = build_opener(
		ProxyHandler({'http': proxy_url, 'https': proxy_url}),
	)
	request = Request(
		probe_url,
		headers={
			'Accept': 'application/json',
			'Cookie': cookie,
			'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
		},
	)
	try:
		with opener.open(request, timeout=timeout) as response:
			status = int(response.status)
			body = _read_response(response)
	except HTTPError as exc:
		status = int(exc.code)
		body = _read_response(exc)
	except (URLError, TimeoutError, OSError):
		return ProbeResult(status=None, classification='network-error')
	return ProbeResult(status=status, classification=classify_probe_response(status, body))


def probe_nodes(
	controller_url: str,
	group: str,
	proxy_url: str,
	probe_url: str,
	cookie: str,
	*,
	switch_timeout: float = DEFAULT_SWITCH_TIMEOUT,
	request_timeout: float = DEFAULT_REQUEST_TIMEOUT,
	node_limit: int = 0,
) -> str | None:
	"""Try nodes in group order and leave the successful node selected."""

	nodes, _ = _wait_for_candidates(controller_url, group, timeout=max(30.0, switch_timeout))
	if node_limit > 0:
		nodes = nodes[:node_limit]
	if not nodes:
		print(f'[FAILED] Mihomo group {group!r} contains no candidate nodes', file=sys.stderr)
		return None

	print(f'[INFO] Probing {len(nodes)} subscription node(s) against LinuxDO session API')
	for index, node in enumerate(nodes, start=1):
		print(f'[INFO] Testing node {index}/{len(nodes)}: {node}')
		try:
			_select_node(controller_url, group, node)
		except RuntimeError as exc:
			print(f'[WARN] Node {node} could not be selected: {exc}')
			continue
		if not _wait_for_node(controller_url, group, node, timeout=switch_timeout):
			print(f'[WARN] Node {node} did not become active within {switch_timeout:g}s')
			continue

		result = _probe_node(proxy_url, probe_url, cookie, timeout=request_timeout)
		status_text = str(result.status) if result.status is not None else '000'
		if result.classification == 'authenticated':
			print(f'[SUCCESS] Node {node} returned an authenticated LinuxDO session (HTTP {status_text})')
			return node
		print(f'[WARN] Node {node} rejected the session probe: HTTP {status_text}, {result.classification}')

	print('[FAILED] No subscription node returned an authenticated LinuxDO session without a challenge', file=sys.stderr)
	return None


def main() -> int:
	parser = argparse.ArgumentParser(description='Probe Mihomo nodes against the LinuxDO session endpoint')
	parser.add_argument('--controller-url', default=DEFAULT_CONTROLLER_URL)
	parser.add_argument('--group', default=DEFAULT_GROUP)
	parser.add_argument('--proxy-url', required=True)
	parser.add_argument('--probe-url', required=True)
	parser.add_argument('--cookie-env', default=DEFAULT_COOKIE_ENV)
	parser.add_argument('--switch-timeout', type=float, default=DEFAULT_SWITCH_TIMEOUT)
	parser.add_argument('--request-timeout', type=float, default=DEFAULT_REQUEST_TIMEOUT)
	parser.add_argument('--node-limit', type=int, default=0)
	args = parser.parse_args()

	cookie = os.getenv(args.cookie_env, '').strip()
	if not cookie:
		print(f'[FAILED] {args.cookie_env} is required for an authenticated node probe', file=sys.stderr)
		return 1
	if args.switch_timeout <= 0 or args.request_timeout <= 0 or args.node_limit < 0:
		print('[FAILED] Probe timeouts must be positive and node limit must be non-negative', file=sys.stderr)
		return 1

	try:
		selected = probe_nodes(
			args.controller_url,
			args.group,
			args.proxy_url,
			args.probe_url,
			cookie,
			switch_timeout=args.switch_timeout,
			request_timeout=args.request_timeout,
			node_limit=args.node_limit,
		)
	except RuntimeError as exc:
		print(f'[FAILED] {exc}', file=sys.stderr)
		return 1
	return 0 if selected else 1


if __name__ == '__main__':
	raise SystemExit(main())
