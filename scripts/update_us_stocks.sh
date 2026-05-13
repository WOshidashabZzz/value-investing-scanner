#!/bin/bash
# ============================================================
# 美股数据自动更新 Shell 包装脚本
#
# 用途：
#   供 systemd timer / cron 调用的入口脚本。
#   自动激活虚拟环境（如果存在），执行 auto_update.py。
#
# 用法：
#   ./scripts/update_us_stocks.sh              # 执行更新
#   ./scripts/update_us_stocks.sh --force      # 强制更新
#   ./scripts/update_us_stocks.sh --check      # 仅检查
#   ./scripts/update_us_stocks.sh --status     # 查看状态
#   ./scripts/update_us_stocks.sh --rollback   # 手动回滚
#
# 定时配置（crontab）：
#   每天北京时间 6:00 执行更新（美股收盘后）
#   0 6 * * 1-5 /path/to/scripts/update_us_stocks.sh >> /path/to/logs/cron_update.log 2>&1
#
# systemd timer 配置见同目录下的 .timer 文件。
# ============================================================

set -euo pipefail

# 获取脚本所在目录的上级（项目根目录）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# 日志
LOG_DIR="${PROJECT_ROOT}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/cron_update.log"

log() {
    local timestamp
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[${timestamp}] $*" | tee -a "${LOG_FILE}"
}

# 切换到项目目录
cd "${PROJECT_ROOT}"

log "========================================"
log "美股数据自动更新开始"
log "项目目录: ${PROJECT_ROOT}"

# 检测 Python
PYTHON=""
for cmd in python3 python; do
    if command -v "${cmd}" &>/dev/null; then
        PYTHON="${cmd}"
        break
    fi
done

if [ -z "${PYTHON}" ]; then
    log "❌ 未找到 Python"
    exit 1
fi

log "Python: ${PYTHON} ($(${PYTHON} --version 2>&1))"

# 检测虚拟环境
if [ -d "${PROJECT_ROOT}/venv" ]; then
    log "激活虚拟环境: venv"
    source "${PROJECT_ROOT}/venv/bin/activate"
elif [ -d "${PROJECT_ROOT}/.venv" ]; then
    log "激活虚拟环境: .venv"
    source "${PROJECT_ROOT}/.venv/bin/activate"
fi

# 执行更新
log "执行: ${PYTHON} -m collector.auto_update $*"
${PYTHON} -m collector.auto_update "$@" 2>&1 | tee -a "${LOG_FILE}"
EXIT_CODE="${PIPESTATUS[0]}"

if [ "${EXIT_CODE}" -eq 0 ]; then
    log "✅ 美股数据自动更新完成"
else
    log "❌ 美股数据自动更新失败 (exit_code=${EXIT_CODE})"
fi

log "========================================"
echo ""

exit "${EXIT_CODE}"
