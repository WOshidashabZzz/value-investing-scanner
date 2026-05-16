#!/bin/bash
# ============================================================
# 港股数据自动更新 Shell 包装脚本
#
# 用途：
#   供 systemd timer / cron 调用的入口脚本。
#   自动激活虚拟环境（如果存在），执行 auto_update_hk.py。
#
# 用法：
#   ./scripts/update_hk_stocks.sh              # 执行更新
#   ./scripts/update_hk_stocks.sh --force      # 强制更新
#   ./scripts/update_hk_stocks.sh --check      # 仅检查
#   ./scripts/update_hk_stocks.sh --status     # 查看状态
#   ./scripts/update_hk_stocks.sh --rollback   # 手动回滚
#
# 定时配置（crontab）：
#   每天北京时间 16:30 执行更新（港股收盘后）
#   30 16 * * 1-5 /path/to/scripts/update_hk_stocks.sh >> /path/to/logs/cron_update_hk.log 2>&1
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

# 激活虚拟环境（如果存在）
if [ -d "${PROJECT_ROOT}/venv" ]; then
    source "${PROJECT_ROOT}/venv/bin/activate"
elif [ -d "${PROJECT_ROOT}/.venv" ]; then
    source "${PROJECT_ROOT}/.venv/bin/activate"
fi

# 切换到项目根目录
cd "${PROJECT_ROOT}"

# 执行自动更新脚本
exec python3 -m collector.auto_update_hk "$@"
