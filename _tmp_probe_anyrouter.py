"""临时探针：查明 AnyRouter 会话对应的真实用户编号。用完即删。"""

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
	session_cookies = account.get('cookies') or {}
	configured_id = account.get('api_user')
	print(f'[probe] configured api_user={configured_id!r}')

	waf_cookies = await get_waf_cookies_with_browser(
		'AnyRouter',
		f'{DOMAIN}/login',
		['acw_tc', 'cdn_sec_tc', 'acw_sc__v2'],
		use_proxy=False,
	)
	print(f'[probe] waf cookies={sorted(waf_cookies or {})}')
	if not waf_cookies:
		print('[probe] WAF cookies unavailable, aborting')
		return

	base_headers = {
		'User-Agent': (
			'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
			'(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
		),
		'Accept': 'application/json, text/plain, */*',
		'Origin': DOMAIN,
		'Referer': f'{DOMAIN}/login',
		'X-Requested-With': 'XMLHttpRequest',
	}

	candidates = [configured_id, '79296', 'linuxdo_79296', None]

	with httpx.Client(timeout=30.0, follow_redirects=True) as client:
		client.cookies.update(waf_cookies)
		client.cookies.update(session_cookies)

		response = client.post(
			f'{DOMAIN}/api/user/sign_in',
			headers={**base_headers, 'Content-Type': 'application/json'},
		)
		print(f'[probe] sign_in -> HTTP {response.status_code}')
		print(f'[probe] sign_in body: {" ".join(response.text.split())[:300]}')

		for candidate in candidates:
			headers = dict(base_headers)
			if candidate:
				headers['New-Api-User'] = str(candidate)
			info = client.get(f'{DOMAIN}/api/user/self', headers=headers)
			body = ' '.join(info.text.split())[:220]
			print(f'[probe] self candidate={candidate!r} -> HTTP {info.status_code} | {body}')


if __name__ == '__main__':
	asyncio.run(main())
