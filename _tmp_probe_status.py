"""临时探针：读取 AnyRouter 站点配置并对比连续两次签到的返回差异。用完即删。"""

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
		'Content-Type': 'application/json',
	}

	with httpx.Client(timeout=30.0, follow_redirects=False) as client:
		if waf_cookies:
			client.cookies.update(waf_cookies)
		client.cookies.set('session', real_session, domain='anyrouter.top')

		status = client.get(f'{DOMAIN}/api/status', headers=headers)
		print(f'[probe] status HTTP {status.status_code}')
		try:
			data = status.json().get('data') or {}
			keys = sorted(data.keys())
			print(f'[probe] status keys={keys}')
			for key in keys:
				if any(word in key.lower() for word in ('check', 'sign', 'quota', 'reward', 'money')):
					print(f'[probe] status[{key}]={data[key]!r}')
		except Exception as exc:
			print(f'[probe] status parse failed: {type(exc).__name__} | {status.text[:150]}')

		for attempt in (1, 2, 3):
			resp = client.post(f'{DOMAIN}/api/user/sign_in', headers=headers)
			print(f'[probe] sign_in #{attempt} HTTP {resp.status_code} | {resp.text[:200]}')

		self_resp = client.get(f'{DOMAIN}/api/user/self', headers=headers)
		if self_resp.status_code == 200:
			data = self_resp.json().get('data') or {}
			print(f'[probe] quota={data.get("quota")} used_quota={data.get("used_quota")} request_count={data.get("request_count")}')


if __name__ == '__main__':
	asyncio.run(main())
