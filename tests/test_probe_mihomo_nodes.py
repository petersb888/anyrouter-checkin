from __future__ import annotations

from scripts.probe_mihomo_nodes import (
	_get_provider_nodes,
	classify_probe_response,
	probe_nodes,
)


def test_classify_probe_response_accepts_authenticated_session() -> None:
	body = b'{"current_user":{"id":123,"username":"user"}}'

	assert classify_probe_response(200, body) == 'authenticated'


def test_classify_probe_response_detects_cloudflare_challenge() -> None:
	body = b'<title>Just a moment...</title><div id="cf-chl-widget"></div>'

	assert classify_probe_response(403, body) == 'cloudflare-challenge'


def test_classify_probe_response_distinguishes_unauthenticated_json() -> None:
	assert classify_probe_response(200, b'{"current_user":null}') == 'json-without-authentication'


def test_get_provider_nodes_accepts_single_provider_response(monkeypatch) -> None:
	monkeypatch.setattr(
		'scripts.probe_mihomo_nodes._controller_json',
		lambda *_args: {
			'name': 'subscription',
			'proxies': [
				{'name': 'node-1', 'type': 'vmess'},
				{'name': 'node-2', 'type': 'trojan'},
			],
		},
	)

	assert _get_provider_nodes('http://controller', 'subscription') == ['node-1', 'node-2']


def test_get_provider_nodes_accepts_wrapped_provider_response(monkeypatch) -> None:
	monkeypatch.setattr(
		'scripts.probe_mihomo_nodes._controller_json',
		lambda *_args: {
			'providers': {
				'subscription': {
					'proxies': [{'name': 'node-1'}, {'name': 'node-1'}, 'node-2'],
				}
			}
		},
	)

	assert _get_provider_nodes('http://controller', 'subscription') == ['node-1', 'node-2']


def test_wait_for_candidates_uses_provider_nodes_not_compatible_placeholder(monkeypatch) -> None:
	from scripts.probe_mihomo_nodes import _wait_for_candidates

	monkeypatch.setattr(
		'scripts.probe_mihomo_nodes._get_provider_nodes',
		lambda *_args: ['node-1', 'node-2'],
	)
	monkeypatch.setattr(
		'scripts.probe_mihomo_nodes._get_group_state',
		lambda *_args: (['COMPATIBLE', 'node-1', 'node-2'], 'COMPATIBLE'),
	)

	assert _wait_for_candidates('http://controller', 'CHECKIN', timeout=1, provider='subscription') == (
		['node-1', 'node-2'],
		'COMPATIBLE',
	)


def test_probe_nodes_switches_until_authenticated(monkeypatch) -> None:
	state = {'current': 'node-1'}

	def fake_candidates(_controller_url, _group, *, timeout, provider):
		return ['node-1', 'node-2'], state['current']

	def fake_select(_controller_url, _group, node):
		state['current'] = node

	def fake_probe(_proxy_url, _probe_url, _cookie, *, timeout):
		from scripts.probe_mihomo_nodes import ProbeResult

		return ProbeResult(
			status=403 if state['current'] == 'node-1' else 200,
			classification=(
				'cloudflare-challenge' if state['current'] == 'node-1' else 'authenticated'
			),
		)

	monkeypatch.setattr('scripts.probe_mihomo_nodes._wait_for_candidates', fake_candidates)
	monkeypatch.setattr('scripts.probe_mihomo_nodes._select_node', fake_select)
	monkeypatch.setattr('scripts.probe_mihomo_nodes._wait_for_node', lambda *args, **kwargs: True)
	monkeypatch.setattr('scripts.probe_mihomo_nodes._probe_node', fake_probe)

	assert (
		probe_nodes(
			'http://controller',
			'CHECKIN',
			'http://proxy',
			'https://linux.do/session/current.json',
			'cookie',
			provider='subscription',
		)
		== 'node-2'
	)
