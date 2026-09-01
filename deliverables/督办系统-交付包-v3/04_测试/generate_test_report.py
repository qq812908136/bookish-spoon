#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
督办系统 - 测试报告 / 测试用例 实时生成器
============================================
从 test_suite 中真实加载并运行全部用例，输出：
  - 督办系统-测试报告.md        （Markdown 测试报告）
  - 督办系统-测试用例报告-<日期>.html  （HTML 测试报告，含逐用例明细）
  - 督办系统-测试用例-<日期>.md        （逐用例清单）

用法：
  python generate_test_report.py [输出目录]
默认输出到 04_测试/（相对仓库根）。
"""
import os
import sys
import json
import datetime
import traceback
import unittest

import test_suite  # 项目测试套件（与仓库同目录）

DATE = datetime.date.today().strftime("%Y-%m-%d")
NOW = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Collector(unittest.TestResult):
    """收集每个用例的运行结果（含 docstring 与失败明细）。"""

    def __init__(self):
        super().__init__()
        self.rows = []  # [id, class, method, doc, outcome, detail]

    def _key(self, test):
        return test.id()

    def startTest(self, test):
        doc = test.shortDescription() or (test._testMethodDoc or "")
        self.rows.append([
            test.id(),
            test.__class__.__name__,
            test._testMethodName,
            (doc or "").strip(),
            "RUN",
            "",
        ])

    def _mark(self, test, outcome, err):
        tb = ""
        if err:
            tb = "".join(traceback.format_exception(*err))
        for r in self.rows:
            if r[0] == test.id() and r[4] == "RUN":
                r[4] = outcome
                r[5] = tb
                return

    def addSuccess(self, test):
        self._mark(test, "PASS", None)

    def addError(self, test, err):
        self._mark(test, "ERROR", err)

    def addFailure(self, test, err):
        self._mark(test, "FAIL", err)

    def addSkip(self, test, reason):
        self._mark(test, "SKIP", None)


def run():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(test_suite)
    collector = Collector()
    suite.run(collector)
    return collector.rows


def summarize(rows):
    total = len(rows)
    passed = sum(1 for r in rows if r[4] == "PASS")
    failed = sum(1 for r in rows if r[4] == "FAIL")
    errored = sum(1 for r in rows if r[4] == "ERROR")
    skipped = sum(1 for r in rows if r[4] == "SKIP")
    rate = (passed / total * 100) if total else 0.0
    return dict(total=total, passed=passed, failed=failed,
                errored=errored, skipped=skipped, rate=rate)


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def group_by_class(rows):
    groups = {}
    for r in rows:
        groups.setdefault(r[1], []).append(r)
    return groups


# ---------------------------------------------------------------------------
# 输出：Markdown 测试报告
# ---------------------------------------------------------------------------
def render_md(rows, stats):
    L = []
    L.append(f"# 督办系统 — 测试报告\n")
    L.append(f"> 生成时间：{NOW}  ")
    L.append(f"> 测试套件：`test_suite.py`（基于 unittest 真实执行）\n")
    L.append("## 一、执行概览\n")
    L.append("| 指标 | 数值 |")
    L.append("| --- | --- |")
    L.append(f"| 用例总数 | {stats['total']} |")
    L.append(f"| 通过 | {stats['passed']} |")
    L.append(f"| 失败 | {stats['failed']} |")
    L.append(f"| 错误 | {stats['errored']} |")
    L.append(f"| 跳过 | {stats['skipped']} |")
    L.append(f"| 通过率 | {stats['rate']:.1f}% |")
    L.append("")
    if stats["failed"] or stats["errored"]:
        L.append("## 二、未通过用例\n")
        for r in rows:
            if r[4] in ("FAIL", "ERROR"):
                L.append(f"- **{esc(r[0])}** [{r[4]}]\n\n```\n{esc(r[5])}\n```\n")
    L.append("## 三、用例分布（按测试类）\n")
    groups = group_by_class(rows)
    L.append("| 测试类 | 用例数 | 通过 | 失败/错误 |")
    L.append("| --- | --- | --- | --- |")
    for cls, items in groups.items():
        p = sum(1 for x in items if x[4] == "PASS")
        bad = sum(1 for x in items if x[4] in ("FAIL", "ERROR", "SKIP"))
        L.append(f"| {esc(cls)} | {len(items)} | {p} | {bad} |")
    L.append("")
    L.append("## 四、逐用例明细\n")
    L.append("| 序号 | 测试类 | 用例方法 | 说明 | 结果 |")
    L.append("| --- | --- | --- | --- | --- |")
    for i, r in enumerate(rows, 1):
        L.append(f"| {i} | {esc(r[1])} | {esc(r[2])} | {esc(r[3]) or '—'} | {r[4]} |")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# 输出：HTML 测试报告
# ---------------------------------------------------------------------------
def render_html(rows, stats):
    groups = group_by_class(rows)
    is_ok = (stats["failed"] == 0 and stats["errored"] == 0)
    badge = "success" if is_ok else "danger"
    badge_color = "#1a7f37" if is_ok else "#cf222e"
    badge_text = "全部通过" if is_ok else "存在异常"
    detail_rows = []
    for i, r in enumerate(rows, 1):
        color = {"PASS": "#1a7f37", "FAIL": "#cf222e", "ERROR": "#cf222e",
                 "SKIP": "#bf8700", "RUN": "#666"}.get(r[4], "#666")
        detail_rows.append(
            f"<tr><td>{i}</td><td>{esc(r[1])}</td><td>{esc(r[2])}</td>"
            f"<td>{esc(r[3]) or '—'}</td>"
            f"<td style='color:{color};font-weight:600'>{r[4]}</td></tr>"
        )
    group_blocks = []
    for cls, items in groups.items():
        p = sum(1 for x in items if x[4] == "PASS")
        bad = sum(1 for x in items if x[4] in ("FAIL", "ERROR", "SKIP"))
        group_blocks.append(
            f"<div class='grp'><span class='cls'>{esc(cls)}</span>"
            f"<span class='cnt'>{len(items)} 项 · 通过 {p} · 异常 {bad}</span></div>"
        )
    failed_block = ""
    if stats["failed"] or stats["errored"]:
        fb = []
        for r in rows:
            if r[4] in ("FAIL", "ERROR"):
                fb.append(f"<li><b>{esc(r[0])}</b> [{r[4]}]<pre>{esc(r[5])}</pre></li>")
        failed_block = ("<div class='section'><h2>未通过用例</h2><ul>" +
                       "".join(fb) + "</ul></div>")
    badge_css = (".badge{display:inline-block;padding:3px 10px;border-radius:20px;"
                 "color:#fff;font-size:12px;background:" + badge_color + "}")
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>督办系统 — 测试报告 {DATE}</title>
<style>
 body{{font-family:-apple-system,'Microsoft YaHei',sans-serif;margin:0;padding:32px;color:#24292f;background:#f6f8fa}}
 h1{{font-size:22px;margin:0 0 4px}} .meta{{color:#57606a;font-size:13px;margin-bottom:20px}}
 .summary{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px}}
 .card{{background:#fff;border:1px solid #d0d7de;border-radius:8px;padding:14px 18px;min-width:110px}}
 .card .n{{font-size:24px;font-weight:700}} .card .l{{font-size:12px;color:#57606a}}
 {badge_css}
 .section{{background:#fff;border:1px solid #d0d7de;border-radius:8px;padding:16px 20px;margin-bottom:20px}}
 .section h2{{font-size:16px;margin:0 0 12px}}
 table{{width:100%;border-collapse:collapse;font-size:13px}}
 th,td{{border:1px solid #d0d7de;padding:6px 8px;text-align:left}}
 th{{background:#f6f8fa}}
 .grp{{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px dashed #eaecef}}
 .grp .cls{{font-weight:600}} .grp .cnt{{color:#57606a;font-size:12px}}
 pre{{white-space:pre-wrap;font-size:12px;background:#fff5f5;padding:8px;border-radius:6px;overflow:auto}}
</style></head><body>
<h1>督办系统 — 测试报告</h1>
<div class="meta">生成时间：{NOW} ｜ 测试套件：test_suite.py（基于 unittest 真实执行）</div>
<div class="summary">
 <div class="card"><div class="n">{stats['total']}</div><div class="l">用例总数</div></div>
 <div class="card"><div class="n" style="color:#1a7f37">{stats['passed']}</div><div class="l">通过</div></div>
 <div class="card"><div class="n" style="color:#cf222e">{stats['failed']+stats['errored']}</div><div class="l">失败/错误</div></div>
 <div class="card"><div class="n">{stats['skipped']}</div><div class="l">跳过</div></div>
 <div class="card"><div class="n">{stats['rate']:.1f}%</div><div class="l">通过率</div></div>
 <div class="card"><div class="n" style="font-size:16px;padding-top:6px"><span class="badge">{badge_text}</span></div><div class="l">结论</div></div>
</div>
<div class="section"><h2>用例分布（按测试类）</h2>{''.join(group_blocks)}</div>
{failed_block}
<div class="section"><h2>逐用例明细</h2>
<table><thead><tr><th>#</th><th>测试类</th><th>用例方法</th><th>说明</th><th>结果</th></tr></thead>
<tbody>{''.join(detail_rows)}</tbody></table></div>
</body></html>"""


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join("04_测试")
    os.makedirs(out_dir, exist_ok=True)
    print("加载并运行测试套件 ...")
    rows = run()
    stats = summarize(rows)
    print(f"完成：总数 {stats['total']} / 通过 {stats['passed']} / "
          f"失败 {stats['failed']} / 错误 {stats['errored']} / 跳过 {stats['skipped']}")

    md_path = os.path.join(out_dir, "督办系统-测试报告.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_md(rows, stats))
    print("已写", md_path)

    html_path = os.path.join(out_dir, f"督办系统-测试用例报告-{DATE}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_html(rows, stats))
    print("已写", html_path)

    cases_path = os.path.join(out_dir, f"督办系统-测试用例-{DATE}.md")
    with open(cases_path, "w", encoding="utf-8") as f:
        f.write("# 督办系统 — 测试用例清单\n\n")
        f.write(f"> 由 test_suite.py 自动枚举于 {NOW}，共 {stats['total']} 项。\n\n")
        f.write("| 序号 | 测试类 | 用例方法 | 说明 | 结果 |\n")
        f.write("| --- | --- | --- | --- | --- |\n")
        for i, r in enumerate(rows, 1):
            f.write(f"| {i} | {esc(r[1])} | {esc(r[2])} | {esc(r[3]) or '—'} | {r[4]} |\n")
    print("已写", cases_path)

    # 机器可读摘要
    with open(os.path.join(out_dir, "test_summary.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_at": NOW, **stats}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
