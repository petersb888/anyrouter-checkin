from __future__ import annotations

import argparse
from pathlib import Path

IMPORT_NEEDLE = "import os\n"
IMPORT_REPLACEMENT = "import json\nimport os\n"

PROXY_NEEDLE = "        self.browser = Chromium(co)"
PROXY_REPLACEMENT = "\n".join(
    [
        '        proxy_url = os.environ.get("CHECKIN_PROXY_URL", "").strip()',
        "        if proxy_url:",
        "            co.set_proxy(proxy_url)",
        "        self.browser = Chromium(co)",
    ]
)

COOKIE_VALIDATION_NEEDLE = """        # 验证登录状态
        try:
            user_ele = self.page.ele("@id=current-user")
        except Exception as e:
            logger.warning(f"Cookie 登录验证异常: {str(e)}")
            return True
        if not user_ele:
            if "avatar" in self.page.html:
                logger.info("Cookie 登录验证成功 (通过 avatar)")
                return True
            logger.error("Cookie 登录验证失败 (未找到 current-user)，Cookie 可能已过期")
            return False
        else:
            logger.info("Cookie 登录验证成功")
            return True"""

COOKIE_VALIDATION_REPLACEMENT = """        # 先检查页面元素，再使用 Discourse 会话 API，避免页面结构变化造成误判。
        home_html = self.page.html or ""
        try:
            user_ele = self.page.ele("@id=current-user")
        except Exception as exc:
            logger.warning(
                f"Cookie DOM 登录验证异常: {type(exc).__name__}; 继续验证会话 API"
            )
            user_ele = None

        if not user_ele:
            # 前端水合有延迟，首帧常常还没有用户菜单，短轮询避免误判。
            for _ in range(8):
                time.sleep(1)
                try:
                    user_ele = self.page.ele("@id=current-user")
                except Exception:
                    user_ele = None
                if user_ele:
                    break

        if user_ele:
            logger.info("Cookie 登录验证成功 (通过 current-user)")
            return True

        # 重试后重新取 HTML：Discourse 的 head 里只有已登录会话才写
        # <meta id="data-current-user" data-user-id="...">，它不受 API 挑战影响。
        home_html = self.page.html or ""
        lower_home = home_html.lower()
        if 'id="data-current-user"' in lower_home or "data-current-user-id" in lower_home:
            logger.info("Cookie 登录验证成功 (通过 data-current-user)")
            return True

        try:
            home_url = str(self.page.url or "")
        except Exception:
            home_url = "unknown"
        try:
            home_title = str(self.page.title or "")
        except Exception:
            home_title = "unknown"

        lower_home = home_html.lower()
        lower_title = home_title.lower()
        waf_markers = [
            label
            for label, marker in (
                ("cloudflare", "cloudflare"),
                ("challenge", "cf-chl"),
                ("just-a-moment", "just a moment"),
                ("access-denied", "access denied"),
                ("rate-limit", "too many requests"),
            )
            if marker in lower_home or marker in lower_title
        ]

        current_user = None
        session_json_ok = False
        try:
            self.page.get(HOME_URL.rstrip("/") + "/session/current.json")
            time.sleep(2)
            session_html = self.page.html or ""
            session_text = BeautifulSoup(session_html, "html.parser").get_text().strip()
            session_data = json.loads(session_text)
            session_json_ok = isinstance(session_data, dict)
            if session_json_ok:
                current_user = session_data.get("current_user")
        except Exception as exc:
            logger.warning(f"Cookie 会话 API 验证异常: {type(exc).__name__}")

        if isinstance(current_user, dict) and current_user.get("id"):
            logger.info("Cookie 登录验证成功 (通过 session/current.json)")
            self.page.get(HOME_URL)
            time.sleep(2)
            return True

        # Discourse 只在已登录会话中把未读通知数写进标题，例如 "(2) LINUX DO - ..."。
        # Cloudflare 会挑战 session API，但首页标题仍是可靠的登录信号。
        title_head = home_title.strip()
        if (
            title_head.startswith("(")
            and ")" in title_head[:8]
            and "linux do" in lower_title
        ):
            logger.info("Cookie 登录验证成功 (通过未读计数标题)")
            self.page.get(HOME_URL)
            time.sleep(2)
            return True

        logger.error(
            "Cookie 登录验证失败: "
            f"home_url={home_url!r}, title={home_title[:120]!r}, "
            f"home_html_size={len(home_html)}, "
            f"waf={','.join(waf_markers) or 'none'}, "
            f"session_json={session_json_ok}, current_user={bool(current_user)}"
        )
        return False"""

COOKIE_FALLBACK_NEEDLE = """                if not login_res:
                    logger.warning("Cookie 登录失败，尝试账号密码登录...")
                    login_res = self.login()"""

COOKIE_FALLBACK_REPLACEMENT = """                if not login_res:
                    logger.error("Cookie 登录失败，停止任务以避免额外登录请求")
                    return"""

TOPIC_LIST_NEEDLE = """    def click_topic(self):
        topic_list = self.page.ele("@id=list-area").eles(".:title")
        if not topic_list:"""

TOPIC_LIST_REPLACEMENT = """    def click_topic(self):
        # Cloudflare 挑战会让首页列表延迟渲染，先轮询等待再取元素，避免直接抛异常。
        topic_list = None
        for _attempt in range(12):
            try:
                topic_list = self.page.ele("@id=list-area", timeout=5).eles(".:title")
                if topic_list:
                    break
            except Exception:
                topic_list = None
            time.sleep(2)
        if not topic_list:
            # WAF 有时只放行首屏壳页面，刷新一次让 Discourse 重新拉取列表数据。
            try:
                self.page.refresh()
            except Exception:
                pass
            time.sleep(5)
            for _attempt in range(6):
                try:
                    topic_list = self.page.ele("@id=list-area", timeout=5).eles(".:title")
                    if topic_list:
                        break
                except Exception:
                    topic_list = None
                time.sleep(2)
        if not topic_list:"""

LOGIN_FAILURE_NEEDLE = """            if not login_res:  # 登录
                logger.warning("登录验证失败")"""

LOGIN_FAILURE_REPLACEMENT = """            if not login_res:  # 登录
                logger.error("登录验证失败，停止任务")
                return"""

AUTH_TEST_NEEDLE = "            if BROWSE_ENABLED:\n"
AUTH_TEST_REPLACEMENT = """            auth_test_only = os.environ.get(
                "LINUXDO_AUTH_TEST_ONLY", "false"
            ).strip().lower() in {"true", "1", "on"}
            if auth_test_only:
                success_marker = os.environ.get("LINUXDO_SUCCESS_MARKER", "").strip()
                if not success_marker:
                    raise RuntimeError("认证测试缺少 LINUXDO_SUCCESS_MARKER")
                with open(success_marker, "w", encoding="utf-8") as marker_file:
                    marker_file.write("authenticated\\n")
                logger.success("LinuxDO Cookie 认证测试通过")
                return

            if BROWSE_ENABLED:
"""

COMPLETION_NEEDLE = "            self.send_notifications(BROWSE_ENABLED)  # 发送通知"
COMPLETION_REPLACEMENT = "\n".join(
    [
        COMPLETION_NEEDLE,
        '            success_marker = os.environ.get("LINUXDO_SUCCESS_MARKER", "").strip()',
        "            if success_marker:",
        '                with open(success_marker, "w", encoding="utf-8") as marker_file:',
        '                    marker_file.write("completed\\n")',
    ]
)


def _replace_once(source: str, needle: str, replacement: str, label: str) -> str:
    count = source.count(needle)
    if count != 1:
        raise RuntimeError(f"LinuxDO 上游源码结构已变化，{label}匹配数应为 1，实际为 {count}")
    return source.replace(needle, replacement, 1)


def patch_source(source: str) -> str:
    source = _replace_once(source, IMPORT_NEEDLE, IMPORT_REPLACEMENT, "json import")
    source = _replace_once(source, PROXY_NEEDLE, PROXY_REPLACEMENT, "代理配置")
    source = _replace_once(
        source,
        COOKIE_VALIDATION_NEEDLE,
        COOKIE_VALIDATION_REPLACEMENT,
        "Cookie 登录验证",
    )
    source = _replace_once(
        source,
        COOKIE_FALLBACK_NEEDLE,
        COOKIE_FALLBACK_REPLACEMENT,
        "Cookie 失败保护",
    )
    source = _replace_once(
        source,
        TOPIC_LIST_NEEDLE,
        TOPIC_LIST_REPLACEMENT,
        "首页主题列表等待",
    )
    source = _replace_once(
        source,
        LOGIN_FAILURE_NEEDLE,
        LOGIN_FAILURE_REPLACEMENT,
        "登录失败保护",
    )
    source = _replace_once(source, AUTH_TEST_NEEDLE, AUTH_TEST_REPLACEMENT, "认证测试入口")
    return _replace_once(source, COMPLETION_NEEDLE, COMPLETION_REPLACEMENT, "完成标记")


def patch_file(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    patched = patch_source(source)
    compile(patched, str(path), "exec")
    path.write_text(patched, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch the pinned LinuxDO runtime safely")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    patch_file(args.path)


if __name__ == "__main__":
    main()
