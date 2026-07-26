#!/usr/bin/env bash
# 通过 mihomo 拉取订阅、启动本地代理并探测可用节点。
# 环境变量:
#   PROXY_SUBSCRIPTION_URL  订阅链接（必填才启用）
#   PROXY_TEST_URL          探测目标，默认 https://www.google.com/generate_204
#   PROXY_REQUIRED          true 时探测失败则退出 1
#   PROXY_PORT              本地 mixed-port，默认 7890
#   PROXY_NODE_FILTER       指定节点名称的正则；设置后仅使用匹配节点，不再按延迟自动切换
#   PROXY_HEALTH_ATTEMPTS   健康检查最大次数，默认 45；4xx/5xx 会立即停止

set -euo pipefail

if [[ -z "${PROXY_SUBSCRIPTION_URL:-}" ]]; then
	echo "[INFO] PROXY_SUBSCRIPTION_URL not set, skip proxy setup"
	exit 0
fi

PROXY_DIR="${RUNNER_TEMP:-/tmp}/checkin-proxy"
PROXY_PORT="${PROXY_PORT:-7890}"
PROXY_TEST_URL="${PROXY_TEST_URL:-https://www.google.com/generate_204}"
MIHOMO_VERSION="${MIHOMO_VERSION:-v1.19.0}"
PROXY_REQUIRED="${PROXY_REQUIRED:-false}"
PROXY_NODE_FILTER="${PROXY_NODE_FILTER:-}"
PROXY_HEALTH_ATTEMPTS="${PROXY_HEALTH_ATTEMPTS:-45}"

if [[ "${PROXY_NODE_FILTER}" == *$'\n'* || "${PROXY_NODE_FILTER}" == *$'\r'* ]]; then
	echo "[FAILED] PROXY_NODE_FILTER must be a single-line regular expression" >&2
	exit 1
fi
if ! [[ "${PROXY_HEALTH_ATTEMPTS}" =~ ^[1-9][0-9]*$ ]]; then
	echo "[FAILED] PROXY_HEALTH_ATTEMPTS must be a positive integer" >&2
	exit 1
fi

mkdir -p "${PROXY_DIR}"
cd "${PROXY_DIR}"

echo "[INFO] Downloading mihomo ${MIHOMO_VERSION}..."
ARCHIVE="mihomo-linux-amd64-${MIHOMO_VERSION}.gz"
if ! curl --retry 3 --retry-delay 5 --retry-all-errors -fsSL -o "${ARCHIVE}" \
	"https://github.com/MetaCubeX/mihomo/releases/download/${MIHOMO_VERSION}/${ARCHIVE}"; then
	echo "[WARN] Failed to download mihomo ${MIHOMO_VERSION}, skip proxy setup"
	if [[ "${PROXY_REQUIRED}" == "true" ]]; then
		exit 1
	fi
	exit 0
fi
gunzip -f "${ARCHIVE}"
chmod +x "mihomo-linux-amd64-${MIHOMO_VERSION}"
MIHOMO_BIN="${PROXY_DIR}/mihomo-linux-amd64-${MIHOMO_VERSION}"

if [[ -n "${PROXY_NODE_FILTER}" ]]; then
	# select 只保留匹配节点；当过滤条件唯一时，Mihomo 不会在其它订阅节点间切换。
	CHECKIN_GROUP_TYPE="select"
	CHECKIN_GROUP_OPTIONS=$(cat <<EOF
    filter: "${PROXY_NODE_FILTER}"
EOF
)
	echo "[INFO] CHECKIN proxy is pinned by node filter"
else
	CHECKIN_GROUP_TYPE="url-test"
	CHECKIN_GROUP_OPTIONS=$(cat <<EOF
    url: "${PROXY_TEST_URL}"
    interval: 300
    tolerance: 150
    lazy: false
EOF
)
	echo "[INFO] CHECKIN proxy uses automatic url-test selection"
fi

cat > config.yaml <<EOF
mixed-port: ${PROXY_PORT}
allow-lan: false
ipv6: false
mode: rule
log-level: warning
unified-delay: true
# 仅供本 Runner 校验已选节点；不暴露到外网。
external-controller: 127.0.0.1:9090

proxy-providers:
  subscription:
    type: http
    url: "${PROXY_SUBSCRIPTION_URL}"
    interval: 3600
    path: ./subscription.yaml
    health-check:
      enable: true
      interval: 300
      url: https://www.gstatic.com/generate_204

proxy-groups:
  - name: CHECKIN
    type: ${CHECKIN_GROUP_TYPE}
${CHECKIN_GROUP_OPTIONS}
    use:
      - subscription

rules:
  - MATCH,CHECKIN
EOF

echo "[INFO] Starting mihomo on 127.0.0.1:${PROXY_PORT}..."
nohup "${MIHOMO_BIN}" -d "${PROXY_DIR}" -f config.yaml > mihomo.log 2>&1 &
echo $! > mihomo.pid

if [[ -n "${PROXY_NODE_FILTER}" ]]; then
	# select 组默认可能尚未选定成员。通过仅监听本机的 Controller 确认候选唯一，
	# 再显式选中该节点，避免悄悄回退到订阅中的其它出口。
	PINNED_NODE=""
	for attempt in $(seq 1 20); do
		mapfile -t GROUP_STATE < <(
			curl -fsS --max-time 3 "http://127.0.0.1:9090/proxies/CHECKIN" 2>/dev/null |
				python -c 'import json, sys; data = json.load(sys.stdin); nodes = data.get("all", []); print(len(nodes)); print(data.get("now", "")); print(nodes[0] if len(nodes) == 1 else "")' 2>/dev/null || true
		)
		NODE_COUNT="${GROUP_STATE[0]:-0}"
		CURRENT_NODE="${GROUP_STATE[1]:-}"
		CANDIDATE_NODE="${GROUP_STATE[2]:-}"
		if [[ "${NODE_COUNT}" == "1" && -n "${CANDIDATE_NODE}" ]]; then
			if [[ "${CURRENT_NODE}" != "${CANDIDATE_NODE}" ]]; then
				NODE_PAYLOAD=$(python -c 'import json, sys; print(json.dumps({"name": sys.argv[1]}))' "${CANDIDATE_NODE}")
				curl -fsS --max-time 3 -X PUT "http://127.0.0.1:9090/proxies/CHECKIN" \
					-H 'Content-Type: application/json' -d "${NODE_PAYLOAD}" -o /dev/null
			fi
			PINNED_NODE="${CANDIDATE_NODE}"
			break
		fi
		sleep 1
	done
	if [[ -z "${PINNED_NODE}" ]]; then
		echo "[FAILED] No unique subscription node matches PROXY_NODE_FILTER (expected exactly 1, got ${NODE_COUNT:-0})" >&2
		tail -n 30 mihomo.log || true
		kill "$(cat mihomo.pid)" 2>/dev/null || true
		exit 1
	fi
	echo "[SUCCESS] CHECKIN proxy pinned to the verified subscription node"
fi

PROXY_URL="http://127.0.0.1:${PROXY_PORT}"
READY=false
LAST_HTTP_STATUS="000"
LAST_CURL_STATUS=0
for attempt in $(seq 1 "${PROXY_HEALTH_ATTEMPTS}"); do
	if HTTP_STATUS=$(curl -sS -x "${PROXY_URL}" --max-time 20 --output /dev/null --write-out '%{http_code}' "${PROXY_TEST_URL}"); then
		LAST_CURL_STATUS=0
	else
		LAST_CURL_STATUS=$?
	fi
	LAST_HTTP_STATUS="${HTTP_STATUS:-000}"
	if [[ "${LAST_CURL_STATUS}" == "0" && "${LAST_HTTP_STATUS}" =~ ^[1-5][0-9][0-9]$ ]] && \
		(( 10#${LAST_HTTP_STATUS} >= 200 && 10#${LAST_HTTP_STATUS} < 400 )); then
		READY=true
		break
	fi
	if [[ "${LAST_HTTP_STATUS}" =~ ^[1-5][0-9][0-9]$ && "${LAST_HTTP_STATUS}" != "000" ]]; then
		echo "[FAILED] Proxy target returned HTTP ${LAST_HTTP_STATUS}; stop retrying to avoid repeated requests"
		break
	fi
	echo "[INFO] Waiting for proxy health check (${attempt}/${PROXY_HEALTH_ATTEMPTS}, curl=${LAST_CURL_STATUS}, http=${LAST_HTTP_STATUS})..."
	sleep 2
done

if [[ "${READY}" != "true" ]]; then
	echo "[FAILED] Proxy health check failed for ${PROXY_TEST_URL} (curl=${LAST_CURL_STATUS}, http=${LAST_HTTP_STATUS})"
	tail -n 30 mihomo.log || true
	if [[ -f mihomo.pid ]]; then
		kill "$(cat mihomo.pid)" 2>/dev/null || true
	fi
	if [[ "${PROXY_REQUIRED}" == "true" ]]; then
		exit 1
	fi
	exit 0
fi

echo "[SUCCESS] Proxy is ready: ${PROXY_URL}"
echo "[INFO] Proxy is scoped to CHECKIN_PROXY_URL (browser/python only, not global HTTP_PROXY)"
if [[ -n "${GITHUB_ENV:-}" ]]; then
	echo "CHECKIN_PROXY_URL=${PROXY_URL}" >> "${GITHUB_ENV}"
fi
