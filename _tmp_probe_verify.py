"""临时探针：用候选 New-Api-User 值验证 AnyRouter 会话与余额。用完即删。"""

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
	print(f'[probe] session length={len(real_session or "")}')
	print(f'[probe] configured api_user={account.get("api_user")!r}')

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

	candidates = ['79297', '79296', '79295', '79298']
	for candidate in candidates:
		with httpx.Client(timeout=30.0, follow_redirects=False) as client:
			if waf_cookies:
				client.cookies.update(waf_cookies)
			client.cookies.set('session', real_session, domain='anyrouter.top')
			req_headers = {**headers, 'New-Api-User': candidate}
			resp = client.get(f'{DOMAIN}/api/user/self', headers=req_headers)
			body = ' '.join(resp.text.split())[:220]
			print(f'[probe] api_user={candidate} -> HTTP {resp.status_code} | {body}')


if __name__ == '__main__':
	asyncio.run(main())
