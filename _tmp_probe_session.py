"""临时探针：判断 AnyRouter session 是否仍然有效。用完即删。"""

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
	print(f'[probe] real session length={len(real_session or "")}')

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
		'Referer': f'{DOMAIN}/login',
		'X-Requested-With': 'XMLHttpRequest',
	}

	cases = [
		('no session at all', None, None),
		('fake session', 'totally-invalid-session-value', None),
		('real session, no id', real_session, None),
		('real session, id=79296', real_session, '79296'),
	]

	with httpx.Client(timeout=30.0, follow_redirects=False) as client:
		for label, session, user_id in cases:
			client.cookies.clear()
			if waf_cookies:
				client.cookies.update(waf_cookies)
			if session:
				client.cookies.set('session', session, domain='anyrouter.top')
			req_headers = dict(headers)
			if user_id:
				req_headers['New-Api-User'] = user_id
			resp = client.get(f'{DOMAIN}/api/user/self', headers=req_headers)
			body = ' '.join(resp.text.split())[:160]
			print(f'[probe] {label} -> HTTP {resp.status_code} | {body}')
			print(f'[probe] {label} -> location={resp.headers.get("location")!r}')


if __name__ == '__main__':
	asyncio.run(main())
