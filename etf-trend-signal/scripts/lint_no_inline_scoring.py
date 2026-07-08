#!/usr/bin/env python3
"""
合规检测：检查所有脚本是否内联了L1-L4评分逻辑。

评分逻辑只能存在于 scoring_system.py。任何其他文件出现
score_L1_germination / score_L2_volume_price / score_L3_structure
/ score_L4_confirmation 等函数定义，或内联"if score += ..."模式，即违规。

使用：
    python scripts/lint_no_inline_scoring.py
    退出码0=通过, 1=发现违规
"""

import os
import re
import sys

# 评分相关的关键词（出现在scoring_system.py之外即为违规）
SCORING_PATTERNS = [
    r'def score_L1_germination\b',
    r'def score_L2_volume_price\b',
    r'def score_L3_structure\b',
    r'def score_L4_confirmation\b',
    r'def score_veto_dimension\b',
    r'def calculate_composite_score\b',
    r'def _determine_direction\b',
    r'score\s*\+=\s*\d+\s*;.*\([+-]\d+\)',  # e.g. score += 5; reasons.append('xxx(+5)')
]

# 允许的文件（只有 scoring_system.py 和 测试文件）
ALLOWED_FILES = {'scoring_system.py', 'lint_no_inline_scoring.py'}

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))


def check_file(filepath: str) -> list:
    """检查单个文件是否包含内联评分逻辑。返回违规行列表。"""
    filename = os.path.basename(filepath)
    if filename in ALLOWED_FILES:
        return []
    if filename.startswith('test_'):
        return []
    if 'backtest' in filepath and filename == 'evaluate.py':
        return []  # evaluate.py 引用评分函数但不定义

    violations = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        # 检查是否定义评分函数
        for pattern in SCORING_PATTERNS:
            matches = re.finditer(pattern, content)
            for m in matches:
                # 找到行号
                line_num = content[:m.start()].count('\n') + 1
                violations.append((filepath, line_num, m.group()))
    except Exception as e:
        violations.append((filepath, 0, f"读取失败: {e}"))

    return violations


def main():
    all_violations = []
    py_files = [os.path.join(SKILL_DIR, f) for f in os.listdir(SKILL_DIR)
                if f.endswith('.py')]

    # 递归查找 scripts/ 子目录
    scripts_dir = os.path.join(SKILL_DIR, 'scripts')
    if os.path.isdir(scripts_dir):
        for root, dirs, files in os.walk(scripts_dir):
            for f in files:
                if f.endswith('.py'):
                    py_files.append(os.path.join(root, f))

    for fp in sorted(set(py_files)):
        violations = check_file(fp)
        all_violations.extend(violations)

    if all_violations:
        print(f"❌ 发现 {len(all_violations)} 处违规：")
        for filepath, line, pattern in all_violations:
            rel = os.path.relpath(filepath, SKILL_DIR)
            print(f"  {rel}:{line} — {pattern}")
        print("\n评分逻辑只能存在于 scoring_system.py！")
        sys.exit(1)
    else:
        print("✅ 合规: 所有脚本通过内联评分检测")
        sys.exit(0)


if __name__ == '__main__':
    main()
