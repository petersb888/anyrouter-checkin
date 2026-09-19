"""临时探针：用浏览器会话查明 AnyRouter 的真实用户编号。用完即删。"""

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
	try:
		context = await browser.new_context()
		merged = {**(waf_cookies or {}), **session_cookies}
		await context.add_cookies(
			[
				{'name': name, 'value': value, 'domain': 'anyrouter.top', 'path': '/'}
				for name, value in merged.items()
			]
		)
		page = await context.new_page()
		await prepare_browser_page(page)
		await page.goto(f'{DOMAIN}/console', wait_until='domcontentloaded')
		await page.wait_for_timeout(8000)

		storage = await page.evaluate(
			"() => Object.fromEntries(Object.entries(localStorage))"
		)
		print(f'[probe] localStorage keys={sorted(storage.keys())}')
		user = storage.get('user')
		if user:
			print(f'[probe] localStorage.user={user[:600]}')

		fetched = await page.evaluate(
			f"""async () => {{
				const r = await fetch('{DOMAIN}/api/user/self', {{credentials: 'include'}});
				return r.status + ' ' + (await r.text()).slice(0, 300);
			}}"""
		)
		print(f'[probe] page fetch /api/user/self -> {fetched}')
		print(f'[probe] page url={page.url}')
	finally:
		await browser.close()


if __name__ == '__main__':
	asyncio.run(main())
