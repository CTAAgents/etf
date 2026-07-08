#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""generate_readme.py — 从各 skill 的 SKILL.md 元数据自动生成仓库根 README.md。

扫描每个子目录的 SKILL.md 文件，提取 frontmatter（name/version/description），
生成包含技能列表的 README.md。

用法:
    python generate_readme.py              # 生成并覆盖 README.md
    python generate_readme.py --check      # 仅检查是否需要更新（CI用）
"""

import os
import re
import sys
from datetime import date

REPO_DIR = os.path.dirname(os.path.abspath(__file__))

# README 模板
README_TEMPLATE = '''# ETF 量化策略技能库

A股 ETF 量化交易 WorkBuddy 技能集。

## 技能列表

| 技能 | 版本 | 说明 | 核心指标 |
|:--|:--:|:--|:--|
{skill_rows}

## 快速开始

每个技能独立安装到 WorkBuddy 的 `~/.workbuddy/skills/` 目录：

```bash
# 克隆仓库
git clone git@github.com:CTAAgents/etf.git

# 安装技能（以 etf-trend-signal 为例）
cp -r etf/etf-trend-signal ~/.workbuddy/skills/
```

在 WorkBuddy 对话中通过 `/skill-name` 或自然语言调用。

## 仓库结构

```
etf/
├── README.md
{folder_tree}
```

## 维护

本 README 由 `generate_readme.py` 自动生成，提交前运行：

```bash
python generate_readme.py
```

---

*数据源：通达信 TQ-Local · 执行平台：妙想模拟交易 · 自动调度：WorkBuddy Automation*
'''

# 每个 skill 的核心指标（手动维护，用于 README 表格最后一列）
SKILL_HIGHLIGHTS = {
    'etf-trend-signal': {
        'highlight': '31行业扫描，周频调仓，完整执行管道',
        'description': '行业ETF通道突破策略 — 唐奇安通道+布林带+成交量评分，31行业轮动',
    },
    'a-share-etf-momentum': {
        'highlight': '年化44.30%，夏普1.275',
    },
    'quantitative-momentum-stock-selection': {
        'highlight': '全市场扫描，T+1适配，北向资金',
    },
}


def get_skill_description(meta: dict, skill_name: str) -> str:
    """获取技能描述，优先用 SKILL_HIGHLIGHTS 覆盖。"""
    override = SKILL_HIGHLIGHTS.get(skill_name, {})
    if 'description' in override:
        return override['description']
    desc = meta.get('description', '')
    if len(desc) > 90:
        desc = desc[:87] + '...'
    return desc


def get_skill_highlight(skill_name: str) -> str:
    """获取技能核心指标。"""
    override = SKILL_HIGHLIGHTS.get(skill_name, {})
    return override.get('highlight', '-')


def parse_skill_frontmatter(skill_dir: str) -> dict:
    """解析 SKILL.md frontmatter，提取 name / version / description。"""
    skill_md = os.path.join(skill_dir, 'SKILL.md')
    if not os.path.exists(skill_md):
        return {}

    with open(skill_md, 'r', encoding='utf-8') as f:
        content = f.read()

    meta = {}
    # 提取 YAML frontmatter（--- 之间的内容）
    fm_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).split('\n'):
            m = re.match(r'^(\w+):\s*(.*)', line)
            if m:
                meta[m.group(1)] = m.group(2).strip()

    # 如果没有 frontmatter，尝试从标题提取版本
    if 'version' not in meta:
        title_match = re.search(r'v(\d+\.\d+\.\d+)', content.split('\n')[0])
        if title_match:
            meta['version'] = title_match.group(1)
    if 'name' not in meta:
        meta['name'] = os.path.basename(skill_dir)
    if 'description' not in meta:
        # 取第一段非标题文字
        lines = content.split('\n')
        desc_lines = []
        in_desc = False
        for line in lines[3:15]:
            if line.startswith('**') and '—' in line:
                desc_lines.append(line.strip('*').strip())
                break
            if line.strip() and not line.startswith('#'):
                desc_lines.append(line.strip())
                in_desc = True
            elif in_desc:
                break
        meta['description'] = ' '.join(desc_lines)[:100]

    return meta


def discover_skills() -> list:
    """发现仓库中的所有 skill 目录（含 SKILL.md 的子目录）。"""
    skills = []
    for entry in sorted(os.listdir(REPO_DIR)):
        path = os.path.join(REPO_DIR, entry)
        if os.path.isdir(path) and not entry.startswith('.') and not entry.startswith('__'):
            if os.path.exists(os.path.join(path, 'SKILL.md')):
                skills.append(entry)
    return skills


def generate_folder_tree(skills: list) -> str:
    """生成仓库结构树（仅显示顶层和脚本目录）。"""
    lines = []
    for skill in sorted(skills):
        path = os.path.join(REPO_DIR, skill)
        lines.append(f'├── {skill}/')
        # 列出子目录
        subdirs = []
        for entry in sorted(os.listdir(path)):
            full = os.path.join(path, entry)
            if os.path.isdir(full) and not entry.startswith('.'):
                subdirs.append(entry)
        for i, sd in enumerate(subdirs):
            prefix = '└──' if i == len(subdirs) - 1 else '├──'
            lines.append(f'│   {prefix} {sd}/')
    return '\n'.join(lines)


def generate_readme(skills: list) -> str:
    """生成完整 README 内容。"""
    rows = []
    for skill in sorted(skills):
        meta = parse_skill_frontmatter(os.path.join(REPO_DIR, skill))
        name = meta.get('name', skill)
        version = meta.get('version', '?')
        desc = get_skill_description(meta, skill)
        highlight = get_skill_highlight(skill)
        rows.append(
            f'| [{name}](./{skill}/) | {version} | {desc} | {highlight} |'
        )

    folder_tree = generate_folder_tree(skills)

    return README_TEMPLATE.format(
        skill_rows='\n'.join(rows),
        folder_tree=folder_tree,
    )


def main():
    check_only = '--check' in sys.argv

    skills = discover_skills()
    if not skills:
        print('❌ 未发现任何 skill 目录')
        sys.exit(1)

    new_content = generate_readme(skills)

    readme_path = os.path.join(REPO_DIR, 'README.md')

    if check_only:
        if os.path.exists(readme_path):
            with open(readme_path, 'r', encoding='utf-8') as f:
                old = f.read()
            if old.strip() == new_content.strip():
                print('✅ README.md 已是最新')
                sys.exit(0)
            else:
                print('⚠ README.md 需要更新，请运行 generate_readme.py')
                sys.exit(1)
        else:
            print('⚠ README.md 不存在，请运行 generate_readme.py')
            sys.exit(1)

    # 写入
    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f'✅ README.md 已生成 ({len(skills)} 个技能)')


if __name__ == '__main__':
    main()
