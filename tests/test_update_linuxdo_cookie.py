import json
import subprocess

import pytest

from scripts.update_linuxdo_cookie import build_agentrouter_update
from scripts.update_linuxdo_cookie import (
    AnyRouterUpdate,
    ApiChatGPTUpdate,
    CookieFormatError,
    CookieUpdate,
    build_anyrouter_update,
    build_apichatgpt_update,
    build_cookie_update,
    set_github_secret,
)

ANYROUTER_SESSION = "session-value"


def test_build_anyrouter_update_keeps_session_and_drops_runner_bound_waf_cookies() -> None:
    raw = json.dumps(
        [
            {"domain": ".anyrouter.top", "name": "session", "value": ANYROUTER_SESSION},
            {"domain": ".anyrouter.top", "name": "acw_tc", "value": "old-acw"},
            {"domain": ".anyrouter.top", "name": "cdn_sec_tc", "value": "old-cdn"},
            {"domain": ".anyrouter.top", "name": "acw_sc__v2", "value": "old-sc"},
            {"domain": ".anyrouter.top", "name": "cf_clearance", "value": "cf"},
            {"domain": "example.com", "name": "session", "value": "wrong-domain"},
        ]
    )

    update = build_anyrouter_update(raw, "79296")

    assert isinstance(update, AnyRouterUpdate)
    assert json.loads(update.secret_value) == [
        {"name": "AnyRouter", "cookies": {"session": ANYROUTER_SESSION}, "api_user": "79296"}
    ]
    assert update.cookie_names == ("session",)
    assert update.input_count == 6
    assert update.ignored_names == ("acw_sc__v2", "acw_tc", "cdn_sec_tc", "cf_clearance")


def test_build_anyrouter_update_accepts_cookie_header() -> None:
    update = build_anyrouter_update(
        "acw_tc=old; session=session-value; cdn_sec_tc=old2", "79296"
    )

    assert json.loads(update.secret_value)[0]["cookies"] == {"session": "session-value"}
    assert set(update.ignored_names) == {"acw_tc", "cdn_sec_tc"}


def test_build_apichatgpt_update_keeps_target_session_only() -> None:
    raw = json.dumps(
        [
            {
                "domain": ".api.apichatgpt.top",
                "name": "session",
                "value": "api-session-value",
            },
            {
                "domain": ".api.apichatgpt.top",
                "name": "cf_clearance",
                "value": "browser-bound",
            },
            {
                "domain": "example.com",
                "name": "session",
                "value": "wrong-domain",
            },
            {
                "domain": ".api.apichatgpt.top",
                "name": "other",
                "value": "discarded",
            },
        ]
    )

    update = build_apichatgpt_update(raw, "5155")

    assert isinstance(update, ApiChatGPTUpdate)
    assert json.loads(update.secret_value) == [
        {
            "name": "APIChatGPT",
            "provider": "apichatgpt",
            "cookies": {"session": "api-session-value"},
            "api_user": "5155",
        }
    ]
    assert update.cookie_names == ("session",)
    assert update.input_count == 4
    assert update.ignored_names == ("cf_clearance",)
    assert update.api_user == "5155"


def test_build_apichatgpt_update_accepts_cookie_header_without_api_user() -> None:
    update = build_apichatgpt_update(
        "foo=discarded; session=session-value-with=equals; cf_clearance=old"
    )

    assert json.loads(update.secret_value) == [
        {
            "name": "APIChatGPT",
            "provider": "apichatgpt",
            "cookies": {"session": "session-value-with=equals"},
        }
    ]
    assert update.api_user is None
    assert update.ignored_names == ("cf_clearance",)


@pytest.mark.parametrize(
    "raw, api_user, message",
    [
        ("[]", "", "缺少 session"),
        ('[{"name":"session","value":""}]', "", "缺少 session"),
        ('[{"name":"session","value":"x"}]', "-1", "正整数"),
        ('[{"name":"session","value":"x"}]', "not-a-number", "正整数"),
    ],
)
def test_build_apichatgpt_update_rejects_invalid_input(
    raw: str, api_user: str, message: str
) -> None:
    with pytest.raises(CookieFormatError, match=message):
        build_apichatgpt_update(raw, api_user)


@pytest.mark.parametrize(
    "raw, api_user, message",
    [
        ('[{"name":"session","value":"x"}]', "", "New-Api-User"),
        ('[{"name":"session","value":"x"}]', "-1", "New-Api-User"),
        ('[{"name":"other","value":"x"}]', "79296", "缺少 session"),
        ('[{"name":"session","value":""}]', "79296", "缺少 session"),
    ],
)
def test_build_anyrouter_update_rejects_invalid_input(raw: str, api_user: str, message: str) -> None:
    with pytest.raises(CookieFormatError, match=message):
        build_anyrouter_update(raw, api_user)


def test_build_cookie_update_keeps_only_linuxdo_session_cookies() -> None:
    raw = json.dumps(
        [
            {
                "domain": ".linux.do",
                "path": "/",
                "name": "_t",
                "value": "token-value",
                "secure": True,
            },
            {
                "domain": ".linux.do",
                "path": "/",
                "name": "_forum_session",
                "value": "session-value",
                "secure": True,
            },
            {
                "domain": ".linux.do",
                "path": "/",
                "name": "cf_clearance",
                "value": "browser-bound",
            },
            {
                "domain": "example.com",
                "name": "_t",
                "value": "wrong-domain",
            },
        ]
    )

    update = build_cookie_update(raw)

    assert update.header == "_t=token-value; _forum_session=session-value"
    assert update.names == ("_t", "_forum_session")
    assert update.input_count == 4
    assert update.ignored_names == ("cf_clearance",)


def test_build_cookie_update_accepts_cookie_editor_wrapper_and_prefers_root() -> None:
    raw = json.dumps(
        {
            "cookies": [
                {
                    "domain": "sub.linux.do",
                    "path": "/",
                    "name": "_t",
                    "value": "sub-token",
                },
                {
                    "domain": "linux.do",
                    "path": "/",
                    "name": "_t",
                    "value": "root-token",
                },
                {
                    "domain": "linux.do",
                    "path": "/",
                    "name": "_forum_session",
                    "value": "session",
                },
            ]
        }
    )

    assert build_cookie_update(raw).header == "_t=root-token; _forum_session=session"


@pytest.mark.parametrize(
    "raw, message",
    [
        ("", "输入为空"),
        ("[]", "缺少 LinuxDO 必需 Cookie"),
        (
            '[{"domain": ".linux.do", "name": "_t", "value": "x"}]',
            "_forum_session",
        ),
        (
            '[{"domain": ".linux.do", "name": "_t", "value": "x;bad"},'
            '{"domain": ".linux.do", "name": "_forum_session", "value": "y"}]',
            "非法分隔符",
        ),
    ],
)
def test_build_cookie_update_rejects_invalid_input(raw: str, message: str) -> None:
    with pytest.raises(CookieFormatError, match=message):
        build_cookie_update(raw)


def test_set_github_secret_reads_value_from_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], str | None]] = []

    def fake_run_gh(
        args: list[str], *, stdin: str | None = None, timeout: int = 120
    ) -> subprocess.CompletedProcess[str]:
        calls.append((args, stdin))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("scripts.update_linuxdo_cookie.run_gh", fake_run_gh)
    update = CookieUpdate(
        header="_t=token; _forum_session=session",
        names=("_t", "_forum_session"),
        input_count=2,
        ignored_names=(),
    )

    result = set_github_secret(
        update,
        repository="owner/repo",
        environment="production",
    )

    assert result.returncode == 0
    assert calls == [
        (
            [
                "gh",
                "secret",
                "set",
                "LINUXDO_COOKIES",
                "--repo",
                "owner/repo",
                "--env",
                "production",
            ],
            "_t=token; _forum_session=session",
        )
    ]


def test_set_github_secret_accepts_apichatgpt_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], str | None]] = []

    def fake_run_gh(
        args: list[str], *, stdin: str | None = None, timeout: int = 120
    ) -> subprocess.CompletedProcess[str]:
        calls.append((args, stdin))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr("scripts.update_linuxdo_cookie.run_gh", fake_run_gh)
    update = build_apichatgpt_update(
        '[{"domain":".api.apichatgpt.top","name":"session","value":"secret"}]'
    )

    result = set_github_secret(
        update,
        repository="owner/repo",
        environment="production",
        secret_name="APICHATGPT_ACCOUNTS",
    )

    assert result.returncode == 0
    assert calls[0][0] == [
        "gh",
        "secret",
        "set",
        "APICHATGPT_ACCOUNTS",
        "--repo",
        "owner/repo",
        "--env",
        "production",
    ]
    assert calls[0][1] == update.secret_value


def test_build_agentrouter_update_accepts_session_and_ignores_waf_cookies() -> None:
    import json as _json

    raw = _json.dumps(
        [
            {"name": "session", "value": "sess-value", "domain": "agentrouter.org"},
            {"name": "acw_tc", "value": "waf-value", "domain": "agentrouter.org"},
            {"name": "cf_clearance", "value": "cf", "domain": ".agentrouter.org"},
        ]
    )

    update = build_agentrouter_update(raw, api_user="12345")

    assert update.cookie_names == ("session",)
    assert "cf_clearance" in update.ignored_names
    assert _json.loads(update.secret_value) == [
        {"name": "AgentRouter", "provider": "agentrouter", "cookies": {"session": "sess-value"}, "api_user": "12345"}
    ]


def test_build_agentrouter_update_requires_session() -> None:
    import pytest as _pytest

    from scripts.update_linuxdo_cookie import CookieFormatError as _Err

    with _pytest.raises(_Err):
        build_agentrouter_update('[{"name": "acw_tc", "value": "x", "domain": "agentrouter.org"}]')
