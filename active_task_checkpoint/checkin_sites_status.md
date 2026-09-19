# 任务：三个站点云签到状态核查与修复（进行中）

## 目标行为
AnyRouter / AgentRouter / APIChatGPT 的云端签到每天真正执行且到账；用户能知道各站点是否在运行。

## 已完成（勿重复）
- AgentRouter：根因是每日额度在“登录那一刻”发放，旧配置只有 session 不登录 → 永不触发。
  已改为邮箱密码走真实浏览器登录，云端实测余额 $334.41 → $359.41（+$25 到账），run 35418025057 成功。
- APIChatGPT：云端实测登录接口返回 HTTP 409（账号级登录次数上限/封禁，假账号同接口返回“密码错误”200）。
  已保持 DISABLED_PROVIDERS=apichatgpt 并回读确认。
- AnyRouter 会话四联探针已跑完：session 有效；缺 New-Api-User 报“未提供”，填 linuxdo_79296 报“格式错误”
  （那是用户名），填 79296 报“与登录用户不匹配”。
- AnyRouter 副作用结论：POST /api/user/sign_in 对无会话/假会话/真会话一律返回 {"success":true}，
  该返回不可信，不能作为签到成功或失败证据。

## 已确认问题队列
1. [阻断] AnyRouter 缺与当前 session 匹配的正整数 New-Api-User。
2. [待网络] 本机 GitHub HTTPS 全面握手失败（web / gh api / git push 均不通）。
   本地 main 领先 origin 2 个提交：bf04530、7c58d27（临时探针 + tmp workflow）。
3. [待清理] 临时探针 _tmp_probe_*.py、_tmp_getlog*.py 与 .github/workflows/tmp-anyrouter-probe.yml 用完即删。

## 唯一下一步
网络恢复后推送 7c58d27 → 手动触发 TMP AnyRouter probe（探针改为在云端浏览器里抓真实请求头
New-Api-User）→ 把正确数字 ID 写入 ANYROUTER_ACCOUNTS → 重跑签到确认余额增长。
若云端浏览器仍被重定向回登录页，则退回让用户在浏览器 F12 的 Network 面板复制 New-Api-User。

## 禁止扩展
不重跑 AgentRouter 登录验证、APIChatGPT 409 诊断、AnyRouter 会话有效性四联探针。
