"""Update the GitHub Environment Secret used by the LinuxDO workflow.

The input format is the JSON exported by the Cookie-Editor browser extension.
Only the Discourse session cookies required by the workflow are uploaded:
``_t`` and ``_forum_session``.  WAF/browser-bound cookies such as
``cf_clearance`` are deliberately ignored.

Run on Windows with:

    python scripts/update_linuxdo_cookie.py

The GUI never writes the cookie value to a file and passes it to ``gh`` via
stdin instead of putting it in the process command line.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from tkinter import BOTH, DISABLED, END, NORMAL, StringVar, Text, Tk, filedialog, messagebox, ttk
from typing import Any, Iterable

DEFAULT_REPOSITORY = os.environ.get(
    "GITHUB_REPOSITORY", "petersb888/anyrouter-checkin"
)
DEFAULT_ENVIRONMENT = os.environ.get("GITHUB_ENVIRONMENT", "production")
DEFAULT_SECRET_NAME = "LINUXDO_COOKIES"
DEFAULT_WORKFLOW = "linuxdo-checkin.yml"
REQUIRED_COOKIE_NAMES = ("_t", "_forum_session")
IGNORED_WAF_COOKIE_NAMES = {
    "cf_clearance",
    "__cf_bm",
    "cf_chl_2",
    "cf_chl_prog",
    "cf_chl_rc_ni",
    "cf_chl_seq",
}


class CookieFormatError(ValueError):
    """Raised when Cookie-Editor JSON cannot produce a valid session header."""


@dataclass(frozen=True)
class CookieUpdate:
    """The sanitized data that will be uploaded to GitHub."""

    header: str
    names: tuple[str, ...]
    input_count: int
    ignored_names: tuple[str, ...]


def _load_json(value: str) -> Any:
    text = value.strip()
    if not text:
        raise CookieFormatError("输入为空，请粘贴 Cookie-Editor 导出的 JSON。")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CookieFormatError(
            f"JSON 格式错误：第 {exc.lineno} 行第 {exc.colno} 列。"
        ) from exc

    # Some clipboard helpers wrap the exported JSON in a JSON string.
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as exc:
            raise CookieFormatError("输入是 JSON 字符串，但内部内容不是有效 JSON。") from exc
    return data


def _cookie_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("cookies")
        if items is None:
            # A single Cookie-Editor item is also accepted.
            items = [data] if "name" in data else None
    else:
        items = None

    if not isinstance(items, list):
        raise CookieFormatError(
            "未找到 Cookie-Editor cookie 数组；应为 JSON 数组或包含 cookies 数组的对象。"
        )

    result: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise CookieFormatError(f"第 {index} 个条目不是对象。")
        result.append(item)
    return result


def _is_linuxdo_domain(domain: str) -> bool:
    normalized = domain.strip().lower().lstrip(".")
    return not normalized or normalized == "linux.do" or normalized.endswith(".linux.do")


def _candidate_score(item: dict[str, Any]) -> tuple[int, int, int, int]:
    """Prefer LinuxDO root cookies and the root path when duplicate names exist."""

    domain = str(item.get("domain", "") or "").strip().lower().lstrip(".")
    path = str(item.get("path", "/") or "/")
    return (
        1 if domain == "linux.do" else 0,
        1 if _is_linuxdo_domain(domain) else 0,
        1 if path == "/" else 0,
        1 if bool(item.get("secure")) else 0,
    )


def _normalise_cookie_value(value: Any, name: str) -> str:
    if value is None:
        raise CookieFormatError(f"Cookie {name} 的 value 为空。")
    normalised = str(value).strip()
    if not normalised:
        raise CookieFormatError(f"Cookie {name} 的 value 为空。")
    if any(char in normalised for char in "\r\n;"):
        raise CookieFormatError(f"Cookie {name} 的 value 包含非法分隔符。")
    return normalised


def build_cookie_update(raw_json: str) -> CookieUpdate:
    """Parse Cookie-Editor JSON and build the minimal LinuxDO Cookie header."""

    items = _cookie_items(_load_json(raw_json))
    candidates: dict[str, list[dict[str, Any]]] = {name: [] for name in REQUIRED_COOKIE_NAMES}
    ignored_names: set[str] = set()

    for item in items:
        name = str(item.get("name", "") or "").strip()
        if not name:
            continue
        if name in IGNORED_WAF_COOKIE_NAMES:
            ignored_names.add(name)
        if name not in candidates:
            continue
        domain = str(item.get("domain", "") or "")
        if _is_linuxdo_domain(domain):
            candidates[name].append(item)

    missing = [name for name in REQUIRED_COOKIE_NAMES if not candidates[name]]
    if missing:
        raise CookieFormatError(
            "缺少 LinuxDO 必需 Cookie："
            + ", ".join(missing)
            + "。请在 linux.do 登录后重新从 Cookie-Editor 导出。"
        )

    selected: dict[str, str] = {}
    for name in REQUIRED_COOKIE_NAMES:
        item = max(candidates[name], key=_candidate_score)
        selected[name] = _normalise_cookie_value(item.get("value"), name)

    header = "; ".join(f"{name}={selected[name]}" for name in REQUIRED_COOKIE_NAMES)
    return CookieUpdate(
        header=header,
        names=REQUIRED_COOKIE_NAMES,
        input_count=len(items),
        ignored_names=tuple(sorted(ignored_names)),
    )


def redact(text: str, secrets: Iterable[str]) -> str:
    """Remove cookie values from command output before it reaches the GUI."""

    result = text
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[REDACTED]")
    return result


def gh_command(*args: str) -> list[str]:
    return ["gh", *args]


def run_gh(
    args: list[str],
    *,
    stdin: str | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    if shutil.which("gh") is None:
        raise RuntimeError(
            "找不到 GitHub CLI（gh）。请先安装 GitHub CLI，并执行 gh auth login。"
        )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        args,
        input=stdin,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        creationflags=creationflags,
    )


def set_github_secret(
    update: CookieUpdate,
    *,
    repository: str,
    environment: str,
    secret_name: str = DEFAULT_SECRET_NAME,
) -> subprocess.CompletedProcess[str]:
    """Set an Environment Secret without exposing the header in argv."""

    args = gh_command(
        "secret",
        "set",
        secret_name,
        "--repo",
        repository,
        "--env",
        environment,
    )
    return run_gh(args, stdin=update.header)


def trigger_auth_test(
    *,
    repository: str,
    workflow: str = DEFAULT_WORKFLOW,
) -> subprocess.CompletedProcess[str]:
    """Trigger the existing Cookie-only validation workflow."""

    return run_gh(
        gh_command(
            "workflow",
            "run",
            workflow,
            "--repo",
            repository,
            "--ref",
            "main",
            "-f",
            "notification_test=false",
            "-f",
            "auth_test_only=true",
        )
    )


def _read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


class CookieUpdaterApp:
    """Small Tkinter front-end for parsing and uploading the cookie header."""

    def __init__(
        self,
        root: Tk,
        *,
        repository: str = DEFAULT_REPOSITORY,
        environment: str = DEFAULT_ENVIRONMENT,
        secret_name: str = DEFAULT_SECRET_NAME,
        workflow: str = DEFAULT_WORKFLOW,
    ) -> None:
        self.root = root
        self.root.title("LinuxDO Cookie 一键更新")
        self.root.geometry("900x690")
        self.root.minsize(760, 560)

        self.repository = StringVar(value=repository)
        self.environment = StringVar(value=environment)
        self.secret_name = StringVar(value=secret_name)
        self.workflow = StringVar(value=workflow)
        self.status = StringVar(value="请粘贴 Cookie-Editor JSON，或点击“读取剪贴板”。")

        self._last_update: CookieUpdate | None = None
        self._busy = False
        self._build_widgets()

    def _build_widgets(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill=BOTH, expand=True)

        config = ttk.LabelFrame(outer, text="GitHub 目标", padding=8)
        config.pack(fill="x", pady=(0, 8))
        self._add_entry(config, "仓库", self.repository, row=0, column=0)
        self._add_entry(config, "Environment", self.environment, row=0, column=2)
        self._add_entry(config, "Secret 名称", self.secret_name, row=1, column=0)
        self._add_entry(config, "验证工作流", self.workflow, row=1, column=2)

        hint = ttk.Label(
            outer,
            text=(
                "Cookie Editor 导出格式应为 JSON 数组。脚本只上传 _t 和 _forum_session，"
                "会自动忽略 cf_clearance 等绑定本地浏览器/IP 的 WAF Cookie。"
            ),
            wraplength=850,
            justify="left",
        )
        hint.pack(fill="x", pady=(0, 6))

        input_frame = ttk.LabelFrame(outer, text="Cookie-Editor JSON", padding=8)
        input_frame.pack(fill=BOTH, expand=True)
        self.input_text = Text(input_frame, height=15, wrap="none", undo=True)
        self.input_text.pack(side="left", fill=BOTH, expand=True)
        input_scroll = ttk.Scrollbar(input_frame, orient="vertical", command=self.input_text.yview)
        input_scroll.pack(side="right", fill="y")
        self.input_text.configure(yscrollcommand=input_scroll.set)

        preview_frame = ttk.LabelFrame(outer, text="预览（不会显示 Cookie 值）", padding=8)
        preview_frame.pack(fill="x", pady=(8, 8))
        self.preview = Text(preview_frame, height=4, state=DISABLED, wrap="word")
        self.preview.pack(fill="x", expand=True)

        actions = ttk.Frame(outer)
        actions.pack(fill="x")
        self.clipboard_button = ttk.Button(actions, text="读取剪贴板", command=self.read_clipboard)
        self.clipboard_button.pack(side="left", padx=(0, 6))
        self.file_button = ttk.Button(actions, text="打开 JSON 文件", command=self.open_file)
        self.file_button.pack(side="left", padx=(0, 6))
        self.preview_button = ttk.Button(actions, text="解析预览", command=self.preview_cookie)
        self.preview_button.pack(side="left", padx=(0, 6))
        self.update_button = ttk.Button(
            actions, text="更新 GitHub Secret", command=lambda: self.update_secret(trigger=False)
        )
        self.update_button.pack(side="right", padx=(6, 0))
        self.update_verify_button = ttk.Button(
            actions, text="更新并触发验证", command=lambda: self.update_secret(trigger=True)
        )
        self.update_verify_button.pack(side="right")
        self.clear_button = ttk.Button(actions, text="清空", command=self.clear)
        self.clear_button.pack(side="right", padx=(0, 6))

        ttk.Separator(outer).pack(fill="x", pady=(10, 6))
        ttk.Label(outer, textvariable=self.status, wraplength=850, justify="left").pack(fill="x")

    @staticmethod
    def _add_entry(
        parent: ttk.Frame,
        label: str,
        variable: StringVar,
        *,
        row: int,
        column: int,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=column, padx=(0, 4), pady=2, sticky="w")
        entry = ttk.Entry(parent, textvariable=variable, width=25)
        entry.grid(row=row, column=column + 1, padx=(0, 12), pady=2, sticky="ew")
        parent.columnconfigure(column + 1, weight=1)

    def _set_preview(self, text: str) -> None:
        self.preview.configure(state=NORMAL)
        self.preview.delete("1.0", END)
        self.preview.insert("1.0", text)
        self.preview.configure(state=DISABLED)

    def _get_input(self) -> str:
        return self.input_text.get("1.0", END).strip()

    def read_clipboard(self) -> None:
        try:
            content = self.root.clipboard_get()
        except Exception as exc:
            messagebox.showerror("读取失败", f"无法读取系统剪贴板：{exc}", parent=self.root)
            return
        self.input_text.delete("1.0", END)
        self.input_text.insert("1.0", content)
        self.status.set("已读取剪贴板，点击“解析预览”检查 Cookie。")
        self.preview_cookie(show_errors=False)

    def open_file(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择 Cookie-Editor JSON",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if not path:
            return
        try:
            content = _read_text_file(Path(path))
        except OSError as exc:
            messagebox.showerror("打开失败", str(exc), parent=self.root)
            return
        self.input_text.delete("1.0", END)
        self.input_text.insert("1.0", content)
        self.status.set(f"已读取文件：{Path(path).name}")
        self.preview_cookie(show_errors=False)

    def clear(self) -> None:
        self.input_text.delete("1.0", END)
        self._set_preview("")
        self._last_update = None
        self.status.set("已清空。")

    def preview_cookie(self, *, show_errors: bool = True) -> CookieUpdate | None:
        try:
            update = build_cookie_update(self._get_input())
        except CookieFormatError as exc:
            self._last_update = None
            self._set_preview("")
            self.status.set(f"解析失败：{exc}")
            if show_errors:
                messagebox.showerror("Cookie 格式错误", str(exc), parent=self.root)
            return None

        self._last_update = update
        ignored = (
            f"；已忽略 WAF Cookie：{', '.join(update.ignored_names)}"
            if update.ignored_names
            else ""
        )
        self._set_preview(
            f"将上传 Cookie：{', '.join(update.names)}\n"
            f"输入条目：{update.input_count}；上传条目：{len(update.names)}{ignored}\n"
            "Cookie 值已隐藏，不会写入本地文件。"
        )
        self.status.set("Cookie 解析成功，可以更新 GitHub Secret。")
        return update

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = DISABLED if busy else NORMAL
        for button in (
            self.clipboard_button,
            self.file_button,
            self.preview_button,
            self.update_button,
            self.update_verify_button,
            self.clear_button,
        ):
            button.configure(state=state)

    def update_secret(self, *, trigger: bool) -> None:
        if self._busy:
            return
        update = self.preview_cookie()
        if update is None:
            return

        repository = self.repository.get().strip()
        environment = self.environment.get().strip()
        secret_name = self.secret_name.get().strip()
        workflow = self.workflow.get().strip()
        if not repository or not environment or not secret_name:
            messagebox.showerror("配置不完整", "仓库、Environment、Secret 名称不能为空。", parent=self.root)
            return

        action = "更新 Secret 并触发 Cookie 验证" if trigger else "更新 GitHub Environment Secret"
        if not messagebox.askyesno(
            "确认操作",
            f"{action}？\n\n目标：{repository}/{environment}\n"
            f"上传名称：{', '.join(update.names)}\n"
            "不会上传 cf_clearance 等 WAF Cookie。",
            parent=self.root,
        ):
            return

        self._set_busy(True)
        self.status.set("正在更新 GitHub Secret，请稍候……")

        def worker() -> None:
            try:
                result = set_github_secret(
                    update,
                    repository=repository,
                    environment=environment,
                    secret_name=secret_name,
                )
                if result.returncode != 0:
                    details = redact(
                        (result.stderr or result.stdout or "").strip(),
                        [update.header, *[part.split("=", 1)[1] for part in update.header.split("; ")]],
                    )
                    raise RuntimeError(details or f"gh secret set 退出码 {result.returncode}")

                verify_text = ""
                if trigger:
                    if not workflow:
                        raise RuntimeError("验证工作流名称不能为空。")
                    verify = trigger_auth_test(repository=repository, workflow=workflow)
                    if verify.returncode != 0:
                        details = redact(
                            (verify.stderr or verify.stdout or "").strip(),
                            [update.header, *[
                                part.split("=", 1)[1] for part in update.header.split("; ")
                            ]],
                        )
                        raise RuntimeError(
                            "Secret 已更新，但触发验证失败："
                            + (details or f"gh workflow run 退出码 {verify.returncode}")
                        )
                    verify_text = f"\n已触发验证工作流：{workflow}"

                self.root.after(
                    0,
                    lambda: self._operation_done(
                        True,
                        f"GitHub Secret 更新成功。上传 {len(update.names)} 个 Cookie。{verify_text}",
                    ),
                )
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                error_text = str(exc)
                self.root.after(0, lambda: self._operation_done(False, error_text))

        threading.Thread(target=worker, daemon=True).start()

    def _operation_done(self, success: bool, message: str) -> None:
        self._set_busy(False)
        self.status.set(message)
        if success:
            messagebox.showinfo("完成", message, parent=self.root)
        else:
            messagebox.showerror("更新失败", message, parent=self.root)


def run_gui(args: argparse.Namespace) -> int:
    root = Tk()
    CookieUpdaterApp(
        root,
        repository=args.repo,
        environment=args.environment,
        secret_name=args.secret_name,
        workflow=args.workflow,
    )
    root.mainloop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Update the LinuxDO GitHub Cookie secret.")
    parser.add_argument("--repo", default=DEFAULT_REPOSITORY, help="GitHub repository, e.g. owner/name")
    parser.add_argument("--environment", default=DEFAULT_ENVIRONMENT)
    parser.add_argument("--secret-name", default=DEFAULT_SECRET_NAME)
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument(
        "--file",
        type=Path,
        help="预填充 Cookie-Editor JSON 文件；不指定时打开空白 UI。",
    )
    args = parser.parse_args()

    if args.file:
        content = _read_text_file(args.file)
    else:
        content = None

    if content is not None:
        # Keep the normal GUI flow, but prefill the text area before the event loop.
        root = Tk()
        app = CookieUpdaterApp(
            root,
            repository=args.repo,
            environment=args.environment,
            secret_name=args.secret_name,
            workflow=args.workflow,
        )
        app.input_text.insert("1.0", content)
        app.preview_cookie(show_errors=False)
        root.mainloop()
        return 0

    return run_gui(args)


if __name__ == "__main__":
    raise SystemExit(main())
