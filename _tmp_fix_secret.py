"""临时脚本：把 AnyRouter 账号配置里的 api_user 修正为已验证的编号。用完即删。"""

import json
import os

TARGET_API_USER = '79297'


def main() -> None:
	raw = os.environ['ANYROUTER_ACCOUNTS']
	data = json.loads(raw)
	if isinstance(data, dict):
		data = [data]

	before = [str(item.get('api_user')) for item in data]
	for item in data:
		item['api_user'] = TARGET_API_USER

	with open('fixed_accounts.json', 'w', encoding='utf-8') as handle:
		json.dump(data, handle, ensure_ascii=False)

	print(f'[fix] accounts={len(data)} before={before} after={TARGET_API_USER}')


if __name__ == '__main__':
	main()
