#!/bin/bash
# ============================================================
# 同步 etf-trend-signal 技能 → CTAAgents/etf 仓库
# 每次修改完此技能后运行：
#     bash sync_etf_skill.sh
# ============================================================
set -e

SKILL_SRC="/c/Users/yangd/.workbuddy/skills/etf-trend-signal"
REPO_DIR="/c/Users/yangd/quant-bare/etf-work"
SKILL_DEST="$REPO_DIR/etf-trend-signal"

echo "============================================"
echo " 同步 etf-trend-signal → CTAAgents/etf"
echo "============================================"

# 1. 复制文件（跳过 .workbuddy 内部配置）
echo "[1] 复制技能文件..."
rsync -av --delete \
  --exclude='.workbuddy/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='sync_etf_skill.sh' \
  "$SKILL_SRC/" "$SKILL_DEST/"

# 2. Git 提交
echo ""
echo "[2] 提交到 git..."
cd "$REPO_DIR"

git add -A
git status --short

# 获取变更摘要
SUMMARY=$(git status --short | head -20)
MSG="etf-trend-signal: $(date +%Y-%m-%d) update"
if [ -n "$SUMMARY" ]; then
  MSG="$MSG

$SUMMARY"
fi

git commit -m "$MSG"

# 3. 推送到 GitHub（使用 cta_deploy 密钥）
echo ""
echo "[3] 推送到 GitHub..."
GIT_SSH_COMMAND="ssh -i ~/.ssh/cta_deploy_ed25519" git push origin master

echo ""
echo "============================================"
echo " ✅ 同步完成!"
echo "============================================"
