"""临时探针：寻找 AnyRouter 上无需用户编号即可返回自身信息的接口。用完即删。"""

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
	session = (account.get('cookies') or {}).get('session')

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
	}

	endpoints = [
		('GET', '/api/user/self'),
		('GET', '/api/user/aff'),
		('GET', '/api/user/dashboard'),
		('GET', '/api/log/self'),
		('GET', '/api/token/'),
		('GET', '/api/user/groups'),
		('GET', '/api/user/self/groups'),
		('GET', '/api/status'),
		('POST', '/api/user/sign_in'),
		('POST', '/api/user/checkin'),
		('GET', '/api/user/checkin'),
	]

	with httpx.Client(timeout=30.0, follow_redirects=False) as client:
		if waf_cookies:
			client.cookies.update(waf_cookies)
		client.cookies.set('session', session, domain='anyrouter.top')

		for method, path in endpoints:
			try:
				resp = client.request(method, f'{DOMAIN}{path}', headers=headers)
			except Exception as exc:
				print(f'[probe] {method} {path} -> ERR {type(exc).__name__}')
				continue
			body = ' '.join(resp.text.split())[:220]
			print(f'[probe] {method} {path} -> HTTP {resp.status_code} | {body}')


if __name__ == '__main__':
	asyncio.run(main())
