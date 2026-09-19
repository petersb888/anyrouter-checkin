"""临时探针：读取 AnyRouter 账号完整状态字段，确认签到是否到账。用完即删。"""

import asyncio
import json
import os

import httpx

from checkin import get_waf_cookies_with_browser

DOMAIN = 'https://anyrouter.top'
SENSITIVE = {'password', 'original_password', 'access_token', 'email'}


def _load_account() -> dict:
	raw = os.environ.get('ANYROUTER_ACCOUNTS', '').strip()
	data = json.loads(raw)
	if isinstance(data, dict):
		data = [data]
	return data[0]


def _summarize(payload: dict) -> str:
	data = payload.get('data') or {}
	shown = {}
	for key, value in data.items():
		if key in SENSITIVE:
			shown[key] = '<hidden>'
		elif isinstance(value, (int, float, str, bool)) or value is None:
			shown[key] = value
		else:
			shown[key] = f'<{type(value).__name__}>'
	return json.dumps(shown, ensure_ascii=False, sort_keys=True)


async def main() -> None:
	account = _load_account()
	api_user = str(account.get('api_user'))
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
		'New-Api-User': api_user,
	}

	with httpx.Client(timeout=30.0, follow_redirects=False) as client:
		if waf_cookies:
			client.cookies.update(waf_cookies)
		client.cookies.set('session', real_session, domain='anyrouter.top')

		resp = client.get(f'{DOMAIN}/api/user/self', headers=headers)
		if resp.status_code == 200:
			print(f'[probe] self = {_summarize(resp.json())}')
		else:
			print(f'[probe] self HTTP {resp.status_code} | {resp.text[:200]}')

		sign = client.post(
			f'{DOMAIN}/api/user/sign_in',
			headers={**headers, 'Content-Type': 'application/json'},
		)
		print(f'[probe] sign_in HTTP {sign.status_code} | {sign.text[:200]}')

		after = client.get(f'{DOMAIN}/api/user/self', headers=headers)
		if after.status_code == 200:
			print(f'[probe] self_after = {_summarize(after.json())}')


if __name__ == '__main__':
	asyncio.run(main())
