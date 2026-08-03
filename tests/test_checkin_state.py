import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import checkin
from checkin import (
	format_balance_snapshot_notification,
	generate_balance_hash,
	get_user_info_after_check_in,
	select_notification_content,
	should_notify_check_in_failure,
	should_notify_check_in_reward,
)


def test_balance_hash_changes_when_quota_changes():
	before = {'account_1': {'quota': 100.0, 'used': 20.0}}
	after = {'account_1': {'quota': 125.0, 'used': 20.0}}

	assert generate_balance_hash(before) != generate_balance_hash(after)


def test_balance_hash_ignores_used_quota_changes():
	before = {'account_1': {'quota': 100.0, 'used': 20.0}}
	after = {'account_1': {'quota': 100.0, 'used': 21.0}}

	assert generate_balance_hash(before) == generate_balance_hash(after)


def test_balance_hash_is_stable_for_equivalent_balances():
	left = {
		'account_2': {'quota': 50.0, 'used': 1.0},
		'account_1': {'quota': 100.0, 'used': 20.0},
	}
	right = {
		'account_1': {'used': 20.0, 'quota': 100.0},
		'account_2': {'used': 1.0, 'quota': 50.0},
	}

	assert generate_balance_hash(left) == generate_balance_hash(right)


def test_check_in_reward_notifies_when_quota_increases():
	assert should_notify_check_in_reward({'balance_change': 25.0}) is True


def test_check_in_reward_skips_when_quota_is_same():
	assert should_notify_check_in_reward({'balance_change': 0}) is False


def test_check_in_reward_skips_when_quota_decreases():
	assert should_notify_check_in_reward({'balance_change': -5.0}) is False


def test_check_in_failure_notifies():
	assert should_notify_check_in_failure(False) is True


def test_successful_check_in_does_not_notify_as_failure():
	assert should_notify_check_in_failure(True) is False


def test_failure_notification_takes_priority_over_reward_notification():
	title, content = select_notification_content(['[FAIL] AnyRouter HTTP 403'], ['[SUCCESS] 无名公益站 +$25'])

	assert title == '签到失败告警'
	assert content == ['[FAIL] AnyRouter HTTP 403']


def test_reward_notification_is_selected_without_failures():
	title, content = select_notification_content([], ['[SUCCESS] 无名公益站 +$25'])

	assert title == '签到奖励通知'
	assert content == ['[SUCCESS] 无名公益站 +$25']


def test_balance_snapshot_notification_is_selected_without_reward_or_failure():
	title, content = select_notification_content([], [], ['[BALANCE] APIChatGPT'])

	assert title == '余额变化通知'
	assert content == ['[BALANCE] APIChatGPT']


def test_reward_and_balance_notifications_are_combined():
	title, content = select_notification_content(['[FAIL] none'], ['[SUCCESS] AnyRouter'], ['[BALANCE] APIChatGPT'])

	assert title == '签到失败告警'
	assert content == ['[FAIL] none']

	title, content = select_notification_content([], ['[SUCCESS] AnyRouter'], ['[BALANCE] APIChatGPT'])

	assert title == '签到结果通知'
	assert content == ['[SUCCESS] AnyRouter', '[BALANCE] APIChatGPT']


def test_balance_snapshot_notification_mentions_delayed_settlement():
	content = format_balance_snapshot_notification(
		{
			'name': 'APIChatGPT',
			'after_quota': 2.87,
			'after_used': 0.0,
		}
	)

	assert '延迟到账' in content
	assert '当前余额: $2.87' in content


def test_account_check_in_delay_sleeps_only_when_configured(monkeypatch):
	sleep_calls = []

	async def fake_sleep(delay):
		sleep_calls.append(delay)

	monkeypatch.setattr(checkin.asyncio, 'sleep', fake_sleep)

	account = checkin.AccountConfig(cookies=None, name='APIChatGPT', delay_seconds=60)
	asyncio.run(checkin.wait_before_account_check_in(account, 'APIChatGPT'))
	assert sleep_calls == [60]

	sleep_calls.clear()
	account.delay_seconds = 0
	asyncio.run(checkin.wait_before_account_check_in(account, 'APIChatGPT'))
	assert sleep_calls == []


def test_apichatgpt_balance_polling_waits_for_delayed_settlement(monkeypatch):
	before = {
		'success': True,
		'quota': 1.45,
		'used_quota': 0.0,
		'display': ':money: Current balance: $1.45, Used: $0.0',
	}
	responses = iter(
		[
			{
				'success': True,
				'quota': 1.45,
				'used_quota': 0.0,
				'display': ':money: Current balance: $1.45, Used: $0.0',
			},
			{
				'success': True,
				'quota': 2.87,
				'used_quota': 0.0,
				'display': ':money: Current balance: $2.87, Used: $0.0',
			},
		]
	)
	headers_seen = []
	sleep_calls = []

	def fake_get_user_info(_client, headers, _url):
		headers_seen.append(headers)
		return next(responses)

	monkeypatch.setattr(checkin, 'get_user_info', fake_get_user_info)
	monkeypatch.setattr(checkin.time, 'sleep', sleep_calls.append)

	result = get_user_info_after_check_in(
		client=object(),
		headers={'User-Agent': 'test'},
		user_info_url='https://example.test/api/user/self',
		account_name='APIChatGPT',
		provider_config=SimpleNamespace(name='apichatgpt'),
		user_info_before=before,
	)

	assert result['quota'] == 2.87
	assert sleep_calls == [checkin.APICHATGPT_BALANCE_SETTLEMENT_DELAY_SECONDS]
	assert headers_seen[-1]['Cache-Control'] == 'no-cache, no-store'
	assert headers_seen[-1]['Pragma'] == 'no-cache'


def test_non_apichatgpt_balance_polling_is_not_delayed(monkeypatch):
	after = {
		'success': True,
		'quota': 1.45,
		'used_quota': 0.0,
		'display': ':money: Current balance: $1.45, Used: $0.0',
	}
	sleep_calls = []

	monkeypatch.setattr(checkin, 'get_user_info', lambda *_args, **_kwargs: after)
	monkeypatch.setattr(checkin.time, 'sleep', sleep_calls.append)

	result = get_user_info_after_check_in(
		client=object(),
		headers={},
		user_info_url='https://example.test/api/user/self',
		account_name='AnyRouter',
		provider_config=SimpleNamespace(name='anyrouter'),
		user_info_before=after,
	)

	assert result == after
	assert sleep_calls == []
