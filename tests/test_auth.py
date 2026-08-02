import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import utils.auth as auth


class FakeResponse:
	def __init__(self, status_code: int, payload: dict):
		self.status_code = status_code
		self._payload = payload

	def json(self):
		return self._payload


class FakeAsyncClient:
	def __init__(self, **kwargs):
		self.kwargs = kwargs
		self.cookies = {'session': 'synthetic-session'}
		self.post_calls = []
		self.get_calls = []

	async def __aenter__(self):
		return self

	async def __aexit__(self, *_args):
		return None

	async def post(self, url, **kwargs):
		self.post_calls.append((url, kwargs))
		return FakeResponse(200, {'success': True})

	async def get(self, url, **kwargs):
		self.get_calls.append((url, kwargs))
		return FakeResponse(200, {'success': True, 'data': {'id': 5155, 'username': 'synthetic'}})


def test_api_credential_login_returns_session_and_user(monkeypatch):
	client = FakeAsyncClient()
	monkeypatch.setattr(auth.httpx, 'AsyncClient', lambda **kwargs: client)
	monkeypatch.setattr(auth, 'get_proxy_server', lambda use_proxy: None)

	result = asyncio.run(
		auth.login_with_api_credentials(
			'https://example.test',
			'/api/user/login',
			'/api/user/self',
			'synthetic-user',
			'synthetic-password',
			account_name='APIChatGPT',
		)
	)

	assert result is not None
	assert result.cookies == {'session': 'synthetic-session'}
	assert result.api_user == '5155'
	assert client.post_calls[0][0] == 'https://example.test/api/user/login'
	assert client.post_calls[0][1]['json'] == {'username': 'synthetic-user', 'password': 'synthetic-password'}
	assert client.get_calls[0][0] == 'https://example.test/api/user/self'


def test_api_credential_login_rejects_failed_response(monkeypatch):
	client = FakeAsyncClient()
	client.post = _failed_post
	monkeypatch.setattr(auth.httpx, 'AsyncClient', lambda **kwargs: client)
	monkeypatch.setattr(auth, 'get_proxy_server', lambda use_proxy: None)

	result = asyncio.run(
		auth.login_with_api_credentials(
			'https://example.test',
			'/api/user/login',
			'/api/user/self',
			'synthetic-user',
			'synthetic-password',
			account_name='APIChatGPT',
		)
	)

	assert result is None


async def _failed_post(_url, **_kwargs):
	return FakeResponse(401, {'success': False})
