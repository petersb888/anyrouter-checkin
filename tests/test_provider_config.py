import json

from utils.config import AppConfig, ProviderConfig, load_accounts_config


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
