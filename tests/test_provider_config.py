import json

from checkin import is_disabled_provider_target
from utils.config import (
	AccountConfig,
	AppConfig,
	ProviderConfig,
	filter_disabled_providers,
	load_accounts_config,
	load_disabled_providers,
	select_accounts_for_target,
)


def test_builtin_provider_profile_persistence_defaults(monkeypatch):
	monkeypatch.delenv('PROVIDERS', raising=False)

	config = AppConfig.load_from_env()

	assert config.providers['anyrouter'].persist_profile is True
	assert config.providers['agentrouter'].persist_profile is False
	assert config.providers['psyche'].persist_profile is False


def test_psyche_provider_uses_new_api_checkin_endpoint(monkeypatch):
	monkeypatch.delenv('PROVIDERS', raising=False)

	provider = AppConfig.load_from_env().providers['psyche']

	assert provider.domain == 'https://welfare.0xpsyche.me'
	assert provider.sign_in_path == '/api/user/checkin'
	assert provider.user_info_path == '/api/user/self'
	assert provider.api_user_key == 'new-api-user'
	assert provider.needs_waf_cookies() is False


def test_apichatgpt_provider_uses_session_checkin_endpoint(monkeypatch):
	monkeypatch.delenv('PROVIDERS', raising=False)

	provider = AppConfig.load_from_env().providers['apichatgpt']

	assert provider.domain == 'https://api.apichatgpt.top'
	assert provider.login_path == '/sign-in'
	assert provider.sign_in_path == '/api/user/checkin'
	assert provider.login_api_path == '/api/user/login'
	assert provider.user_info_path == '/api/user/self'
	assert provider.api_user_key == 'New-Api-User'
	assert provider.requires_api_user is False
	assert provider.needs_waf_cookies() is False


def test_provider_profile_persistence_can_override_builtin(monkeypatch):
	monkeypatch.setenv(
		'PROVIDERS',
		json.dumps(
			{
				'anyrouter': {'domain': 'https://anyrouter.top', 'persist_profile': False},
				'agentrouter': {'domain': 'https://agentrouter.org', 'persist_profile': True},
			}
		),
	)

	config = AppConfig.load_from_env()

	assert config.providers['anyrouter'].persist_profile is False
	assert config.providers['agentrouter'].persist_profile is True


def test_custom_provider_profile_persistence_defaults_to_false(monkeypatch):
	monkeypatch.setenv('PROVIDERS', json.dumps({'custom': {'domain': 'https://custom.example.com'}}))

	config = AppConfig.load_from_env()

	assert config.providers['custom'].persist_profile is False


def test_provider_from_dict_inherits_profile_persistence_from_defaults():
	defaults = ProviderConfig(name='custom', domain='https://old.example.com', persist_profile=True)

	provider = ProviderConfig.from_dict(
		'custom',
		{'domain': 'https://new.example.com'},
		defaults=defaults,
	)

	assert provider.persist_profile is True


def test_accounts_can_be_loaded_from_separate_site_secrets(monkeypatch):
	monkeypatch.delenv('ANYROUTER_ACCOUNTS', raising=False)
	monkeypatch.setenv(
		'PSYCHE_ACCOUNTS',
		json.dumps([{'name': '公益站', 'cookies': {'session': 'session-value'}, 'api_user': '12345'}]),
	)

	accounts = load_accounts_config()

	assert accounts is not None
	assert len(accounts) == 1
	assert accounts[0].provider == 'psyche'
	assert accounts[0].get_display_name(0) == '公益站'


def test_single_account_object_is_accepted_for_site_secret(monkeypatch):
	monkeypatch.delenv('ANYROUTER_ACCOUNTS', raising=False)
	monkeypatch.setenv(
		'PSYCHE_ACCOUNTS',
		json.dumps({'name': '公益站', 'cookies': {'session': 'session-value'}, 'api_user': '12345'}),
	)

	accounts = load_accounts_config()

	assert accounts is not None
	assert len(accounts) == 1
	assert accounts[0].provider == 'psyche'


def test_psyche_name_recovers_from_powershell_question_mark_encoding(monkeypatch):
	monkeypatch.delenv('ANYROUTER_ACCOUNTS', raising=False)
	monkeypatch.setenv(
		'PSYCHE_ACCOUNTS',
		json.dumps({'name': '?????', 'cookies': {'session': 'session-value'}, 'api_user': '12345'}),
	)

	accounts = load_accounts_config()

	assert accounts is not None
	assert accounts[0].get_display_name(0) == '无名公益站'


def test_accounts_from_both_secrets_are_combined_without_overwriting(monkeypatch):
	monkeypatch.setenv(
		'ANYROUTER_ACCOUNTS',
		json.dumps([{'name': 'AnyRouter', 'cookies': {'session': 'a'}, 'api_user': '1'}]),
	)
	monkeypatch.setenv(
		'PSYCHE_ACCOUNTS',
		json.dumps([{'name': '公益站', 'cookies': {'session': 'b'}, 'api_user': '2'}]),
	)

	accounts = load_accounts_config()

	assert accounts is not None
	assert [(account.provider, account.get_display_name(index)) for index, account in enumerate(accounts)] == [
		('anyrouter', 'AnyRouter'),
		('psyche', '公益站'),
	]


def test_apichatgpt_accounts_allow_session_only_configuration(monkeypatch):
	monkeypatch.delenv('ANYROUTER_ACCOUNTS', raising=False)
	monkeypatch.delenv('PSYCHE_ACCOUNTS', raising=False)
	monkeypatch.setenv(
		'APICHATGPT_ACCOUNTS',
		json.dumps(
			[
				{
					'name': 'APIChatGPT',
					'cookies': {'session': 'session-value'},
				}
			]
		),
	)

	accounts = load_accounts_config()

	assert accounts is not None
	assert len(accounts) == 1
	assert accounts[0].provider == 'apichatgpt'
	assert accounts[0].api_user is None
	assert accounts[0].cookies == {'session': 'session-value'}


def test_apichatgpt_accounts_accept_username_password_login(monkeypatch):
	monkeypatch.delenv('ANYROUTER_ACCOUNTS', raising=False)
	monkeypatch.delenv('PSYCHE_ACCOUNTS', raising=False)
	monkeypatch.setenv(
		'APICHATGPT_ACCOUNTS',
		json.dumps(
			[
				{
					'name': 'APIChatGPT',
					'username': 'synthetic-user',
					'password': 'synthetic-password',
				}
			]
		),
	)

	accounts = load_accounts_config()

	assert accounts is not None
	assert len(accounts) == 1
	assert accounts[0].provider == 'apichatgpt'
	assert accounts[0].has_login_credentials() is True
	assert accounts[0].email == 'synthetic-user'
	assert accounts[0].password == 'synthetic-password'


def test_account_delay_seconds_is_loaded_and_normalized(monkeypatch):
	monkeypatch.delenv('ANYROUTER_ACCOUNTS', raising=False)
	monkeypatch.delenv('PSYCHE_ACCOUNTS', raising=False)
	monkeypatch.setenv(
		'APICHATGPT_ACCOUNTS',
		json.dumps(
			{
				'name': 'APIChatGPT',
				'username': 'synthetic-user',
				'password': 'synthetic-password',
				'delay_seconds': '60',
			}
		),
	)

	accounts = load_accounts_config()

	assert accounts is not None
	assert accounts[0].delay_seconds == 60


def test_account_delay_seconds_rejects_invalid_value(monkeypatch):
	monkeypatch.delenv('ANYROUTER_ACCOUNTS', raising=False)
	monkeypatch.delenv('PSYCHE_ACCOUNTS', raising=False)
	monkeypatch.setenv(
		'APICHATGPT_ACCOUNTS',
		json.dumps(
			{
				'name': 'APIChatGPT',
				'username': 'synthetic-user',
				'password': 'synthetic-password',
				'delay_seconds': -1,
			}
		),
	)

	assert load_accounts_config() is None


def test_checkin_target_selects_individual_apichatgpt_account(monkeypatch):
	monkeypatch.delenv('ANYROUTER_ACCOUNTS', raising=False)
	monkeypatch.delenv('PSYCHE_ACCOUNTS', raising=False)
	monkeypatch.setenv(
		'APICHATGPT_ACCOUNTS',
		json.dumps(
			[
				{'name': 'APIChatGPT-1', 'username': 'user-1', 'password': 'pass-1'},
				{'name': 'APIChatGPT-2', 'username': 'user-2', 'password': 'pass-2'},
			]
		),
	)

	accounts = load_accounts_config()
	selected = select_accounts_for_target(accounts or [], 'apichatgpt-2')

	assert selected is not None
	assert len(selected) == 1
	assert selected[0].get_display_name(0) == 'APIChatGPT-2'
	assert selected[0].email == 'user-2'


def test_checkin_target_keeps_non_apichatgpt_accounts(monkeypatch):
	monkeypatch.setenv(
		'ANYROUTER_ACCOUNTS',
		json.dumps([{'name': 'AnyRouter', 'cookies': {'session': 'a'}, 'api_user': '1'}]),
	)
	monkeypatch.setenv(
		'APICHATGPT_ACCOUNTS',
		json.dumps([{'name': 'APIChatGPT', 'username': 'user', 'password': 'pass'}]),
	)

	accounts = load_accounts_config()
	selected = select_accounts_for_target(accounts or [], 'non-apichatgpt')

	assert selected is not None
	assert [(account.provider, account.get_display_name(0)) for account in selected] == [('anyrouter', 'AnyRouter')]


def test_checkin_target_rejects_missing_apichatgpt_account(monkeypatch, capsys):
	monkeypatch.delenv('ANYROUTER_ACCOUNTS', raising=False)
	monkeypatch.delenv('PSYCHE_ACCOUNTS', raising=False)
	monkeypatch.setenv(
		'APICHATGPT_ACCOUNTS',
		json.dumps([{'name': 'APIChatGPT', 'username': 'user', 'password': 'pass'}]),
	)

	accounts = load_accounts_config()
	selected = select_accounts_for_target(accounts or [], 'apichatgpt-2')

	assert selected is None
	assert 'only 1 account(s) are configured' in capsys.readouterr().out


def _make_account(provider: str, name: str) -> AccountConfig:
	return AccountConfig(cookies={'session': 'synthetic'}, api_user='1', provider=provider, name=name)


def test_disabled_providers_defaults_to_empty_set(monkeypatch):
	monkeypatch.delenv('DISABLED_PROVIDERS', raising=False)

	assert load_disabled_providers() == set()


def test_disabled_providers_accepts_comma_and_space_separated_names(monkeypatch):
	monkeypatch.setenv('DISABLED_PROVIDERS', ' APICHATGPT , psyche anyrouter\t')

	assert load_disabled_providers() == {'apichatgpt', 'psyche', 'anyrouter'}


def test_disabled_providers_accepts_json_array(monkeypatch):
	monkeypatch.setenv('DISABLED_PROVIDERS', '["ApichatGPT", "psyche"]')

	assert load_disabled_providers() == {'apichatgpt', 'psyche'}


def test_disabled_providers_ignores_non_string_json_entries(monkeypatch):
	monkeypatch.setenv('DISABLED_PROVIDERS', '["apichatgpt", 5, null]')

	assert load_disabled_providers() == {'apichatgpt'}


def test_disabled_providers_falls_back_to_empty_set_on_invalid_value(monkeypatch, capsys):
	for raw in ('{"provider": "apichatgpt"}', 'apichatgpt}', '["unclosed', '   '):
		monkeypatch.setenv('DISABLED_PROVIDERS', raw)

		assert load_disabled_providers() == set(), raw

	assert 'WARNING' in capsys.readouterr().out


def test_filter_disabled_providers_removes_only_disabled_providers():
	accounts = [_make_account('anyrouter', 'A'), _make_account('apichatgpt', 'B'), _make_account('psyche', 'C')]

	kept = filter_disabled_providers(accounts, {'apichatgpt'})

	assert [account.provider for account in kept] == ['anyrouter', 'psyche']


def test_filter_disabled_providers_is_noop_when_switch_unused():
	accounts = [_make_account('apichatgpt', 'B')]

	assert filter_disabled_providers(accounts, set()) is accounts
	assert filter_disabled_providers(accounts, None) is accounts


def test_select_then_filter_keeps_apichatgpt_numbering_then_drops_disabled(monkeypatch):
	monkeypatch.delenv('ANYROUTER_ACCOUNTS', raising=False)
	monkeypatch.delenv('PSYCHE_ACCOUNTS', raising=False)
	monkeypatch.delenv('DISABLED_PROVIDERS', raising=False)
	monkeypatch.setenv(
		'APICHATGPT_ACCOUNTS',
		json.dumps(
			[
				{'name': 'APIChatGPT-1', 'username': 'user-1', 'password': 'pass-1'},
				{'name': 'APIChatGPT-2', 'username': 'user-2', 'password': 'pass-2'},
			]
		),
	)

	accounts = load_accounts_config() or []
	monkeypatch.setenv('DISABLED_PROVIDERS', 'apichatgpt')

	# numbering is resolved on the full list first, so apichatgpt-2 stays the second account
	assert select_accounts_for_target(accounts, 'apichatgpt-2')[0].email == 'user-2'

	selected = select_accounts_for_target(accounts, 'all') or []
	assert filter_disabled_providers(selected, load_disabled_providers()) == []


def test_is_disabled_provider_target_matches_only_disabled_providers():
	assert is_disabled_provider_target('apichatgpt-2', {'apichatgpt'}) is True
	assert is_disabled_provider_target('apichatgpt', {'apichatgpt'}) is True
	assert is_disabled_provider_target('apichatgpt2', {'apichatgpt'}) is True
	assert is_disabled_provider_target('all', {'apichatgpt'}) is False
	assert is_disabled_provider_target('non-apichatgpt', {'apichatgpt'}) is False
	assert is_disabled_provider_target('apichatgpt-2', set()) is False
	assert is_disabled_provider_target('psyche-1', {'apichatgpt'}) is False
