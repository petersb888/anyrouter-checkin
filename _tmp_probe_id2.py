"""临时探针：在云端浏览器里读取 AnyRouter 前端实际发送的 New-Api-User 编号。用完即删。"""

import asyncio
import json
import os

from cloakbrowser import launch_async

from checkin import get_waf_cookies_with_browser
from utils.browser import prepare_browser_page

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

	waf_cookies = await get_waf_cookies_with_browser(
		'AnyRouter',
		f'{DOMAIN}/login',
		['acw_tc', 'cdn_sec_tc', 'acw_sc__v2'],
		use_proxy=False,
	)
	print(f'[probe] waf={sorted(waf_cookies or {})}')

	browser = await launch_async(headless=True)
	seen: set[str] = set()
	try:
		context = await browser.new_context()
		merged = {**(waf_cookies or {}), **session_cookies}
		await context.add_cookies(
			[
				{
					'name': name,
					'value': value,
					'domain': 'anyrouter.top',
					'path': '/',
					'secure': True,
					'sameSite': 'Lax',
				}
				for name, value in merged.items()
			]
		)

		def on_request(request) -> None:
			for key, value in request.headers.items():
				if key.lower() == 'new-api-user':
					line = f'[probe] req {request.method} {request.url} -> New-Api-User={value}'
					if line not in seen:
						seen.add(line)
						print(line)

		page = await context.new_page()
		page.on('request', on_request)
		await prepare_browser_page(page)
		await page.goto(f'{DOMAIN}/console', wait_until='domcontentloaded')
		await page.wait_for_timeout(20000)
		print(f'[probe] final url={page.url}')
		print(f'[probe] matched request count={len(seen)}')

		storage = await page.evaluate(
			"() => Object.fromEntries(Object.entries(localStorage))"
		)
		print(f'[probe] localStorage keys={sorted(storage.keys())}')
		user = storage.get('user')
		if user:
			print(f'[probe] localStorage.user={user[:400]}')

		fetched = await page.evaluate(
			f"""async () => {{
				const r = await fetch('{DOMAIN}/api/user/self', {{credentials: 'include'}});
				return r.status + ' ' + (await r.text()).slice(0, 240);
			}}"""
		)
		print(f'[probe] direct fetch /api/user/self -> {fetched}')
	finally:
		await browser.close()


if __name__ == '__main__':
	asyncio.run(main())
