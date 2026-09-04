#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
督办系统 — bat/cmd 编码守卫
======================================
检查所有 .bat / .cmd 是否同时满足两个硬性要求：

    1. 编码为 GBK（cmd.exe 默认按 GBK 解码）
    2. 换行符为 CRLF

为什么必须检查：
    cmd.exe 用 GBK 解码 bat 文件。如果文件是 UTF-8（哪怕带 BOM）或用 LF 换行，
    中文会变成乱码，且乱码会被当成命令去执行 —— 表现为各种莫名其妙的启动失败。
    用 Edit / Write 工具直接改 bat 极易踩这个坑（它们默认写 UTF-8）。

用法：
    python scripts/check_bat_encoding.py            # 检查整个仓库
    python scripts/check_bat_encoding.py <目录>      # 只检查某个目录

退出码：0 = 全部合格；1 = 有不合格文件。
"""
import os
import sys

# 不检查这些目录（构建产物、归档、依赖包）
SKIP_DIRS = {'.git', 'build', 'dist', '_archive', '__pycache__',
             'node_modules', '.workbuddy', '_internal'}


def check_file(path):
    """返回 None 表示合格，否则返回问题描述字符串。"""
    with open(path, 'rb') as f:
        data = f.read()

    problems = []
    try:
        data.decode('gbk')
    except UnicodeDecodeError:
        problems.append('非 GBK 编码（很可能是 UTF-8，cmd.exe 会读成乱码）')

    if b'\r\n' not in data:
        problems.append('没有 CRLF 换行')
    elif data.replace(b'\r\n', b'').count(b'\n') > 0:
        problems.append('混入了 LF-only 换行')

    return '；'.join(problems) if problems else None


def find_bats(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn.lower().endswith(('.bat', '.cmd')):
                yield os.path.join(dirpath, fn)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    bad = 0
    total = 0

    for path in sorted(find_bats(root)):
        total += 1
        rel = os.path.relpath(path, root)
        problem = check_file(path)
        if problem:
            bad += 1
            print(f'  [不合格] {rel}')
            print(f'           {problem}')

    print()
    if bad:
        print(f'检查结果：{total} 个 bat，{bad} 个不合格 ❌')
        print('修复方法：用 Python 以 GBK 编码、CRLF 换行重新写入，'
              '或从已知正确的文件字节复制（不要读文本再写）。')
        return 1
    print(f'检查结果：{total} 个 bat，全部为 GBK + CRLF ✅')
    return 0


if __name__ == '__main__':
    sys.exit(main())
