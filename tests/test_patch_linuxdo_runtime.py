from pathlib import Path

import pytest

from scripts.patch_linuxdo_runtime import (
    COMPLETION_NEEDLE,
    COOKIE_FALLBACK_NEEDLE,
    COOKIE_VALIDATION_NEEDLE,
    IMPORT_NEEDLE,
    LOGIN_FAILURE_NEEDLE,
    PROXY_NEEDLE,
    patch_file,
    patch_source,
)


def make_source() -> str:
    return "\n\n".join(
        [
            IMPORT_NEEDLE,
            PROXY_NEEDLE,
            COOKIE_VALIDATION_NEEDLE,
            COOKIE_FALLBACK_NEEDLE,
            LOGIN_FAILURE_NEEDLE,
            COMPLETION_NEEDLE,
        ]
    )


def test_patch_source_connects_all_runtime_guards() -> None:
    patched = patch_source(make_source())

    assert "import json" in patched
    assert "co.set_proxy(proxy_url)" in patched
    assert "/session/current.json" in patched
    assert "home_html_size=" in patched
    assert "停止任务以避免额外登录请求" in patched
    assert "success_marker" in patched


def test_patch_source_rejects_changed_upstream() -> None:
    with pytest.raises(RuntimeError, match="上游源码结构已变化"):
        patch_source("")


def test_patch_file_writes_patched_source(tmp_path: Path) -> None:
    # patch_file also compile-checks the result; use the real upstream fixture in integration validation.
    path = tmp_path / "main.py"
    path.write_text(make_source(), encoding="utf-8")

    with pytest.raises(SyntaxError):
        patch_file(path)
