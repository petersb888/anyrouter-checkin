from __future__ import annotations

from pathlib import Path


def test_notification_push_block_is_not_nested_under_debug_screenshot_branch() -> None:
	"""Regression guard: the push block must run for every needed notification.

	The block was once accidentally indented into ``if screenshot_paths:``
	(debug-only), which silently suppressed every check-in push when
	``DEBUG_MODE=false`` — including failure alerts.
	"""

	source = (Path(__file__).resolve().parents[1] / 'checkin.py').read_text(encoding='utf-8')
	push_lines = [line for line in source.splitlines() if line.strip().startswith('notify.push_message(notification_title')]
	assert len(push_lines) == 1, 'checkin.py should push the notification exactly once'
	indent = push_lines[0][: len(push_lines[0]) - len(push_lines[0].lstrip())]
	assert indent == '\t\t', (
		'the push block must sit directly inside the need_notify branch (2 tabs); '
		f'found {len(indent)} tab(s), meaning it is nested under a debug-only branch'
	)
