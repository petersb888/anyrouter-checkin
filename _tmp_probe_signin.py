"""临时探针：判断 AnyRouter 的 sign_in 返回是否可信，并寻找其他身份线索。用完即删。"""

import asyncio
import json
import os

import httpx

from checkin import get_waf_cookies_with_browser

DOMAIN = 'https://anyrouter.top'


def _load_account() -> dict:
	raw = os.environ.get('ANYROUTER_ACCOUNTS', '').strip()
	data = json.loads(raw)
	if isinstance(data, dict):
		data = [data]
	return data[0]


async def main() -> None:
	account = _load_account()
	real_session = (account.get('cookies') or {}).get('session')

	waf_cookies = await get_waf_cookies_with_browser(
		'AnyRouter',
		f'{DOMAIN}/login',
		['acw_tc', 'cdn_sec_tc', 'acw_sc__v2'],
		use_proxy=False,
	)
	print(f'[probe] waf={sorted(waf_cookies or {})}')

	headers = {
		'User-Agent': (
			'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
			'(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
		),
		'Accept': 'application/json, text/plain, */*',
		'Origin': DOMAIN,
		'Referer': f'{DOMAIN}/console',
		'X-Requested-With': 'XMLHttpRequest',
		'Content-Type': 'application/json',
	}

	print('[probe] === 1) sign_in 是否会对无效会话假报成功 ===')
	with httpx.Client(timeout=30.0, follow_redirects=False) as client:
		for label, session in (('no session', None), ('fake session', 'invalid-session-xyz'), ('real session', real_session)):
			client.cookies.clear()
			if waf_cookies:
				client.cookies.update(waf_cookies)
			if session:
				client.cookies.set('session', session, domain='anyrouter.top')
			resp = client.post(f'{DOMAIN}/api/user/sign_in', headers=headers)
			body = ' '.join(resp.text.split())[:120]
			print(f'[probe] sign_in / {label} -> HTTP {resp.status_code} | {body}')

	print('[probe] === 2) 是否存在账号密码登录接口 ===')
	with httpx.Client(timeout=30.0, follow_redirects=False) as client:
		if waf_cookies:
			client.cookies.update(waf_cookies)
		for path in ('/api/user/login', '/api/user/auth/login'):
			resp = client.post(
				f'{DOMAIN}{path}',
				headers=headers,
				json={'username': 'probe-not-real@example.com', 'password': 'probe-not-real'},
			)
			body = ' '.join(resp.text.split())[:160]
			print(f'[probe] POST {path} -> HTTP {resp.status_code} | {body}')

	print('[probe] === 3) 其他可能返回身份的接口 ===')
	with httpx.Client(timeout=30.0, follow_redirects=False) as client:
		if waf_cookies:
			client.cookies.update(waf_cookies)
		client.cookies.set('session', real_session, domain='anyrouter.top')
		for path in ('/api/user/info', '/api/user/self/info', '/api/user/token', '/api/user/aff/invite', '/api/user/amount'):
			resp = client.get(f'{DOMAIN}{path}', headers=headers)
			body = ' '.join(resp.text.split())[:160]
			print(f'[probe] GET {path} -> HTTP {resp.status_code} | {body}')


if __name__ == '__main__':
	asyncio.run(main())
