# 任务小抄：worker_disable_site_r2

## 军令复诵
- 任务目标：修复 utils/config.py 第 394 行语法损坏；为 checkin.py 接入 DISABLED_PROVIDERS 通用站点开关；补 workflow env、测试用例与 README 说明。
- 文件白名单（只允许改这些）：
  1. utils/config.py
  2. checkin.py
  3. .github/workflows/checkin.yml
  4. tests/test_provider_config.py
  5. README.md
  6. active_task_checkpoint/worker_disable_site_r2.md
- 铁律：严禁触碰无关文件（browser.py/notify.py/auth.py/popups.py/linuxdo-checkin.yml/pr-check.yml/scripts/其它 tests）；严禁修改或删除任何 Secret/凭据；严禁回滚他人改动；只做最小 diff，禁止整块覆盖；每改完一个文件立即跑编译检查。
- 保留前任已写好的 load_disabled_providers() 与 filter_disabled_providers()，不重复造轮子。

## 当前进度
- [x] 开工：已确认 utils/config.py 第 394 行存在多余裸签名行（SyntaxError: '(' was never closed）
- [x] A0 修复语法损坏：删除 config.py 旧 394-395 行（多余裸签名 + 空行），compileall 通过；保留前任 load_disabled_providers/filter_disabled_providers 未改
- [x] A1 接入 checkin.py：扩展 utils.config 导入；新增 is_disabled_provider_target()；main() 内读开关→打印 Disabled providers→完整列表 select→filter→Skipped 日志→全禁用 exit(0)→select 返回 None 且 target 指向禁用 provider 时 exit(0) 不告警
- [x] B workflow：checkin.yml「执行签到」step env 末尾新增 DISABLED_PROVIDERS: ${{ vars.DISABLED_PROVIDERS }}（job 已是 environment: production）
- [x] C 测试：tests/test_provider_config.py 新增 10 条用例（逗号/空格、JSON 数组、非字符串项、非法值降级、过滤顺序、未设置零变化、select+filter 序号语义、target 判定）
- [x] D README：新增「临时关闭某个站点的签到（可选）」小节（配置位置、三种写法、行为说明、不需删 Secret）
- [x] 验证：compileall 通过；ruff --no-fix（白名单文件）All checks passed；pytest test_provider_config + test_checkin_state = 42 passed；离线烟测 4+2 条路径全部符合预期（exit 0、零告警）
- [!] 事故已回滚：pyproject 里 tool.ruff 设了 fix = true，导致仓库级 `uv run ruff check .` 自动改写了白名单外文件 scripts/probe_mihomo_nodes.py 与 tests/test_update_linuxdo_cookie.py，已用 git restore 恢复，最终 git status 仅白名单 5 个文件被改
