"""Credential-based HTTP authentication helpers."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from utils.proxy import get_proxy_server


@dataclass(frozen=True)
class CredentialLoginResult:
	"""验证成功后的会话 Cookie 与用户标识。"""

	cookies: dict[str, str]
	api_user: str | None = None


def _endpoint(domain: str, path: str) -> str:
	return f'{domain.rstrip("/")}/{path.lstrip("/")}'


def _extract_profile(payload: object) -> dict | None:
	if not isinstance(payload, dict):
		return None
	data = payload.get('data')
	if isinstance(data, dict):
		return data
	if payload.get('id') is not None:
		return payload
	return None


def _response_is_successful(payload: object) -> bool:
	if not isinstance(payload, dict):
		return False
	if payload.get('success') is False:
		return False
	if payload.get('code') not in (None, 0):
		return False
	if payload.get('ret') not in (None, 1):
		return False
	return True


async def login_with_api_credentials(
	domain: str,
	login_path: str,
	user_info_path: str,
	username: str,
	password: str,
	*,
	account_name: str,
	use_proxy: bool = False,
) -> CredentialLoginResult | None:
	"""通过 New-API 登录接口刷新 session，并用用户信息接口验证。"""
	client_kwargs: dict = {'http2': True, 'timeout': 30.0, 'follow_redirects': True}
	proxy_url = get_proxy_server(use_proxy=use_proxy)
	if proxy_url:
		client_kwargs['proxy'] = proxy_url
		if use_proxy:
			print(f'[INFO] {account_name}: API credential login proxy enabled')

	login_url = _endpoint(domain, login_path)
	user_info_url = _endpoint(domain, user_info_path)
	headers = {
		'User-Agent': (
			'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
			'(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
		),
		'Accept': 'application/json, text/plain, */*',
		'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
		'Origin': domain.rstrip('/'),
		'Referer': f'{domain.rstrip("/")}/sign-in',
		'X-Requested-With': 'XMLHttpRequest',
	}

	try:
		async with httpx.AsyncClient(**client_kwargs) as client:
			response = await client.post(
				login_url,
				headers={**headers, 'Content-Type': 'application/json'},
				json={'username': username, 'password': password},
			)
			if response.status_code != 200:
				print(f'[FAILED] {account_name}: API credential login failed - HTTP {response.status_code}')
				return None

			try:
				login_payload = response.json()
			except ValueError:
				print(f'[FAILED] {account_name}: API credential login returned invalid JSON')
				return None
			if not _response_is_successful(login_payload):
				print(f'[FAILED] {account_name}: API credential login was rejected')
				return None

			verify_response = await client.get(
				user_info_url,
				headers={**headers, 'Cache-Control': 'no-cache, no-store', 'Pragma': 'no-cache'},
			)
			if verify_response.status_code != 200:
				print(f'[FAILED] {account_name}: API credential session verification failed - HTTP {verify_response.status_code}')
				return None
			try:
				verify_payload = verify_response.json()
			except ValueError:
				print(f'[FAILED] {account_name}: API credential session verification returned invalid JSON')
				return None

			profile = _extract_profile(verify_payload)
			if not profile:
				print(f'[FAILED] {account_name}: API credential session verification was rejected')
				return None

			cookies = {name: value for name, value in client.cookies.items() if name and value}
			if not cookies:
				print(f'[FAILED] {account_name}: API credential login returned no session cookie')
				return None

			api_user = str(profile['id']) if profile.get('id') is not None else None
			print(f'[SUCCESS] {account_name}: API credential login verified')
			return CredentialLoginResult(cookies=cookies, api_user=api_user)
	except Exception as exc:
		print(f'[FAILED] {account_name}: API credential login error - {type(exc).__name__}')
		return None
