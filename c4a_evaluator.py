#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
c4a_evaluator.py — C4 提交自动评审器（C4A 挑战产出）

流水线：
  模块① 采集与识别（L1）：扫描文件夹、提取作者、按人分组、识别版本
  模块② 完整性检查（L2）：对照 c4_rubric.yaml 查五件套
  模块③ 质量初判（L3 规则层）：四条件检查项打分（AI 深审由外部环节补充）
  模块④ 报告生成（L4）：Markdown 评审报告（总览/详情/排名/建议）

用法：
  python c4a_evaluator.py <文件夹路径> [-o 输出报告.md]

设计约束（对应评分表"技术实现"维度）：
  - 文件夹路径一律由命令行参数传入，代码中无硬编码路径
  - 中文文件名：UTF-8 优先（Python 3 默认），内容读取失败时 GBK 回退
  - 超过 50MB 的文件只做文件名/类型匹配，不读内容
"""

import argparse
import ast
import datetime
import io
import json
import re
import sys
import zipfile
from pathlib import Path

try:
    import yaml
except ImportError:
    print("缺少 pyyaml，请先安装：pip install pyyaml", file=sys.stderr)
    sys.exit(1)

MAX_CONTENT_BYTES = 50 * 1024 * 1024  # 超过 50MB 不读内容（starter Edge Cases 规定）
TEXT_EXTS = {".md", ".txt", ".py", ".yaml", ".yml", ".json", ".html", ".csv", ".skill"}
DEMO_EXTS = {".mp4", ".mov", ".webm", ".png", ".jpg", ".jpeg", ".gif"}
# v3 移植自 wechat_doc_mapper.py（基座 extract_title 的多格式思路）：
# .docx / .pdf 提交现在也能提取正文参与完整性匹配与质量评审（L1 混合格式要求）
DOCX_EXTS = {".docx"}
PDF_EXTS = {".pdf"}

# ---------------------------------------------------------------- 工具函数

def read_text_safe(path: Path):
    """读文本文件内容：UTF-8 优先，GBK 回退；超限或二进制返回 None。"""
    try:
        if path.stat().st_size > MAX_CONTENT_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    for enc in ("utf-8", "gbk"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return None  # 二进制（图片/视频等）

def extract_docx_text(path: Path):
    """移植自基座 _title_from_docx：用 python-docx 提取全部段落文本。失败返回 None。"""
    try:
        from docx import Document
        doc = Document(str(path))
        parts = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:  # 表格里的文字也算内容（如 IO 说明常写在表格里）
            for row in table.rows:
                parts.append(" ".join(c.text for c in row.cells))
        return "\n".join(parts) if parts else None
    except Exception:
        return None

def extract_pdf_text(path: Path):
    """移植自基座 _title_from_pdf：用 pypdf 提取全文（前 10 页，防超长）。失败返回 None。"""
    try:
        from pypdf import PdfReader
        r = PdfReader(str(path))
        pages = [(pg.extract_text() or "") for pg in r.pages[:10]]
        text = "\n".join(pages).strip()
        return text or None
    except Exception:
        return None

def extract_content(path: Path, ext: str):
    """统一内容提取入口：文本类直接读，docx/pdf 走移植的提取器，其余返回 None。"""
    if ext in TEXT_EXTS:
        return read_text_safe(path)
    if ext in DOCX_EXTS:
        return extract_docx_text(path)
    if ext in PDF_EXTS:
        return extract_pdf_text(path)
    return None

def extract_skill_package_text(path: Path):
    """v3 新增：.skill 包是 zip 容器——解包读取内部文件内容参与评审。

    背景：实测两个官方技能包（wechat-doc-mapper / skill-explainer）时发现，
    包内的 SKILL.md / 脚本 / 参考文件才是内容主体，不拆包会严重低估提交质量。
    返回 (拼接文本, 包内文件名列表)；失败返回 (None, [])。
    """
    try:
        if path.stat().st_size > MAX_CONTENT_BYTES:
            return None, []
        with zipfile.ZipFile(str(path)) as z:
            names = [n for n in z.namelist()
                     if not n.endswith("/") and not Path(n).name.startswith(".")]
            parts, inner = [], []
            for n in sorted(names):
                try:
                    data = z.read(n)
                except Exception:
                    continue
                ext = Path(n).suffix.lower()
                text = None
                if ext in TEXT_EXTS:
                    for enc in ("utf-8", "gbk"):
                        try:
                            text = data.decode(enc)
                            break
                        except (UnicodeDecodeError, ValueError):
                            continue
                elif ext in DOCX_EXTS:
                    import tempfile
                    with tempfile.TemporaryDirectory() as td:
                        p = Path(td) / Path(n).name
                        p.write_bytes(data)
                        text = extract_docx_text(p)
                if text and text.strip():
                    parts.append(f"=== 包内文件 {n} ===\n{text[:6000]}")
                    inner.append(n)
            return ("\n\n".join(parts) if parts else None), inner
    except Exception:
        return None, []

def extract_author(filename: str, parent_dir: Path, root_dir: Path) -> str:
    """作者识别链（starter 规定）：文件名 _C4_ 前缀 → 子文件夹名 → Unknown。"""
    m = re.search(r"_C4[_A-Za-z]*_", filename, re.IGNORECASE)
    if m:
        prefix = filename[: m.start()].strip()
        if prefix:
            return prefix
    if parent_dir != root_dir and parent_dir.name:
        return parent_dir.name
    return "Unknown"

def extract_version(filename: str) -> int:
    """识别 _v2 / _v3 等迭代版本号，无版本号视为 v1。"""
    m = re.search(r"_v(\d+)", filename, re.IGNORECASE)
    return int(m.group(1)) if m else 1

# ---------------------------------------------------------------- 模块① 采集与识别

def scan_folder(root: Path):
    """递归扫描，返回 authors: {author: [file_record]} 与 non_c4 文件列表。"""
    authors, non_c4 = {}, []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        rel = path.relative_to(root)
        fname = path.name
        is_c4 = bool(re.search(r"_C4[_A-Za-z]*_", fname, re.IGNORECASE)) or ".skill" in fname.lower()
        if not is_c4:
            non_c4.append(str(rel))
            continue
        ext = path.suffix.lower()
        text = extract_content(path, ext)
        inner_files = []
        if ext == ".skill":  # v3：拆包读取内部内容
            text, inner_files = extract_skill_package_text(path)
        rec = {
            "path": path,
            "rel": str(rel),
            "name": fname,
            "ext": ext,
            "version": extract_version(fname),
            "author": extract_author(fname, path.parent, root),
            "text": text,
            "inner_files": inner_files,
        }
        authors.setdefault(rec["author"], []).append(rec)
    return authors, non_c4

def keep_latest_versions(author_files):
    """同一作者多版本：取每个文件角色的最新版本（版本号大者优先，其次文件名）。"""
    best = {}
    for rec in author_files:
        key = _role_key(rec["name"])
        cur = best.get(key)
        if cur is None or (rec["version"], rec["name"]) > (cur["version"], cur["name"]):
            best[key] = rec
    return list(best.values())

def _role_key(fname: str) -> str:
    """去掉版本号后作为同一文件角色的 key。"""
    return re.sub(r"_v\d+", "", fname, flags=re.IGNORECASE)

# ---------------------------------------------------------------- 模块② 完整性检查

def check_completeness(files, rubric):
    """对一位作者的文件查五件套，返回 {item: {status, matched}}。"""
    result = {}
    for item, spec in rubric["required_deliverables"].items():
        det = spec["detection"]
        fname_pats = [p.lower() for p in det.get("filename_patterns", [])]
        content_sigs = det.get("content_signals", [])
        pref_exts = [e.lower() for e in det.get("preferred_extensions", [])]
        matched, media_ok = [], False
        for rec in files:
            low = rec["name"].lower()
            hit = any(p in low for p in fname_pats)
            if not hit and rec["ext"] in pref_exts and rec["ext"] in DEMO_EXTS:
                hit, media_ok = True, True  # demo 类：媒体扩展名直接命中
            if not hit and rec["text"] and content_sigs and not is_rule_definition_file(rec):
                plain = strip_code_fences(rec["text"])
                plain_lower = plain.lower()
                # 英文信号大小写不敏感（v2.1：修复大写 Input/Output 漏匹配），中文信号精确匹配
                hits = sum(1 for s in content_sigs
                           if ((s.lower() in plain_lower) if s.isascii() else (s in plain)))
                if hits >= 2:
                    hit = True
            if hit:
                matched.append(rec["rel"])
        result[item] = {
            "label": spec.get("label_cn", item),
            "matched": matched,
            "status": "ok" if matched else "missing",
        }
    return result

# ---------------------------------------------------------------- 模块③ 质量初判（规则层）

HARDCODED_PATH_RE = re.compile(r"C:\\\\|C:/|/Users/|/home/|E:\\\\")
IO_ONE_LINER_RE = re.compile(r"输入.{1,40}(输出|得到|返回)|input.{1,40}output|接受.{1,20}返回", re.IGNORECASE | re.DOTALL)

# --- v2 修复：信号自匹配误报 ---
# 背景（真实数据测评发现的两类误报）：
#   ①c4_rubric.yaml 把 step by step/ChatGPT 等列为检测信号，yaml 自身内容包含这些词，
#     导致规则文件被误判"有教学说明/有 AI 日志"；
#   ②本文件自身的硬编码路径正则定义行（含 C:\ 字面量）被自己的硬编码检测命中。
# 修复：规则定义文件跳过内容信号匹配；硬编码扫描跳过正则/信号定义行。
RULE_FILE_MARKERS = ("rubric", "signal")

def is_rule_definition_file(rec) -> bool:
    n = rec["name"].lower()
    return any(m in n for m in RULE_FILE_MARKERS)

def find_hardcoded_lines(texts):
    """逐行扫描硬编码路径，跳过正则/信号定义行（含 re.compile、_RE、signal、pattern 等标记）。"""
    hits = []
    for t in texts:
        for line in t.splitlines():
            if HARDCODED_PATH_RE.search(line) and not re.search(
                    r"re\.compile|_RE\b|signals?|patterns?|硬编码|hardcoded", line, re.IGNORECASE):
                hits.append(line.strip()[:80])
    return hits

def strip_code_fences(text: str) -> str:
    """v2 修复：剔除 ``` 围栏内的文本——围栏里通常是信号定义/示例，不应作为内容信号证据。"""
    out, in_fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)

def quality_review(files, rubric):
    """四条件规则初判。返回 {criterion: {grade(2/1/0), checks:[(name,passed)], evidence}}"""
    texts = [rec["text"] for rec in files if rec["text"] and not is_rule_definition_file(rec)]
    joined = "\n".join(texts)
    py_files = [rec for rec in files if rec["ext"] == ".py"]
    qc = rubric["quality_criteria"]
    out = {}

    # --- 可复用 ---
    checks = []
    checks.append(("有安装/环境说明", _sig_hit(joined, qc["reusable"]["positive_signals"])))
    bad_lines = find_hardcoded_lines(texts)
    has_bad_path = bool(bad_lines)
    checks.append(("无硬编码绝对路径", not has_bad_path))
    checks.append(("有依赖说明(pip/requirements/兼容)", bool(re.search(r"pip install|requirements|依赖|兼容", joined, re.I))))
    ev = "发现: " + " / ".join(bad_lines[:2]) if has_bad_path else "未发现"
    out["reusable"] = _grade(qc["reusable"]["label_cn"], checks, evidence=ev)

    # --- 可执行 ---
    parse_ok, parse_fail = 0, []
    for rec in py_files:
        try:
            ast.parse(rec["text"] or "")
            parse_ok += 1
        except SyntaxError as e:
            parse_fail.append(f"{rec['name']}: 语法错误第{e.lineno}行")
    has_code = _sig_hit(joined, qc["executable"]["positive_signals"]) or any(
        "```" in t or "def " in t for t in texts)
    checks = [
        ("含可运行代码/prompt/workflow", has_code),
        (f"Python 语法检查通过({parse_ok}/{len(py_files)})", len(py_files) == 0 or not parse_fail),
        (".md 含 YAML frontmatter", any(t.lstrip().startswith("---") for t in texts)),
    ]
    ev = "；".join(parse_fail[:3]) if parse_fail else "语法全部通过" if py_files else "无 .py 文件"
    out["executable"] = _grade(qc["executable"]["label_cn"], checks, evidence=ev)

    # --- 可验证 ---
    has_demo = any(rec["ext"] in DEMO_EXTS or "demo" in rec["name"].lower() for rec in files)
    checks = [
        ("有测试/示例/用例信号", _sig_hit(joined, qc["verifiable"]["positive_signals"])),
        ("有预期结果/结果说明", bool(re.search(r"预期|expected|运行结果|成功标准", joined, re.I))),
        ("有 Demo 文件", has_demo),
    ]
    out["verifiable"] = _grade(qc["verifiable"]["label_cn"], checks)

    # --- IO 明确 ---
    checks = [
        ("有'输入X输出Y'一句话描述", bool(IO_ONE_LINER_RE.search(joined))),
        ("出现输入/输出关键词", _sig_hit(joined, qc["clear_io"]["positive_signals"])),
    ]
    out["clear_io"] = _grade(qc["clear_io"]["label_cn"], checks)
    return out

def _sig_hit(text, signals):
    return any(s in text for s in signals)

def _grade(label, checks, evidence=""):
    """命中 2+ 项 = ✅(2分)，1 项 = ⚠️(1分)，0 项 = ❌(0分) — c4_rubric.yaml 评分规则。"""
    passed = sum(1 for _, ok in checks if ok)
    grade = 2 if passed >= 2 else (1 if passed == 1 else 0)
    return {"label": label, "grade": grade, "checks": checks, "evidence": evidence}

# ---------------------------------------------------------------- 模块③b AI 深审层

AI_TASK_SNIPPET_CHARS = 6000  # 每个文件给 AI 的内容截断长度

def ai_prepare(root, authors, completeness_all, quality_all, out_path):
    """把规则层拿不准的文件导出成 AI 深审任务包（JSON）。

    触发条件：作者被标 Unknown、某条件规则初判为 ⚠️、或完整性出现需人工确认的文件。
    深审由外部 AI 完成，结果按 ai_review_results.json 的格式写回，再用 --ai-merge 合并。
    """
    tasks, seen = [], set()
    for author, files in authors.items():
        flagged = False
        for k, v in quality_all[author].items():
            if v["grade"] == 1:  # ⚠️ 规则拿不准
                flagged = True
        if author == "Unknown":
            flagged = True
        if not flagged:
            continue
        for rec in files:
            if rec["text"] is None:
                continue  # 二进制文件没有内容可深审
            key = (author, rec["rel"])
            if key in seen:
                continue
            seen.add(key)
            content = rec["text"][:AI_TASK_SNIPPET_CHARS]
            tasks.append({
                "author": author,
                "file": rec["rel"],
                "content": content,
                "truncated": len(rec["text"]) > AI_TASK_SNIPPET_CHARS,
            })
    pkg = {
        "task": "按 C4 四条件（reusable 可复用 / executable 可执行 / verifiable 可验证 / clear_io IO明确）"
                "阅读每个文件内容，给出终审判级。grade 取值：2=✅ 达标，1=⚠️ 部分达标，0=❌ 未达标。"
                "evidence 必须引用文件原文片段作为依据；suggestion 给一条可执行的改进建议。",
        "note": "AI 的评级优先于规则层初判（AI 是终判）。没有深审任务的作者保持规则层结果。",
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "tasks": tasks,
    }
    Path(out_path).write_text(json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(tasks)

def ai_merge(quality_all, results_path):
    """把 AI 深审结果合并进 quality_all：每个条件记 ai_grade/ai_evidence/ai_suggestion。

    同一作者多个文件被深审时按条件聚合：grade 取均值四舍五入，依据合并去重。
    """
    pkg = json.loads(Path(results_path).read_text(encoding="utf-8"))
    reviews = pkg.get("reviews", [])
    # 先按 (author, criterion) 收集
    bucket = {}
    for rev in reviews:
        author = rev.get("author")
        if author not in quality_all:
            continue
        for k, item in rev.get("quality", {}).items():
            if k not in quality_all[author]:
                continue
            bucket.setdefault((author, k), []).append(item)
    # 再聚合写回
    for (author, k), items in bucket.items():
        v = quality_all[author][k]
        v["ai_grade"] = int(round(sum(int(i.get("grade", 0)) for i in items) / len(items)))
        evs = list(dict.fromkeys(str(i.get("evidence", ""))[:150] for i in items))
        v["ai_evidence"] = " ｜ ".join(evs)[:400]
        sug = list(dict.fromkeys(str(i.get("suggestion", ""))[:150] for i in items if i.get("suggestion")))
        v["ai_suggestion"] = "；".join(sug)[:300]
    return len(reviews), {a for a, _ in bucket}

def final_grade(v):
    """终判：AI 深审优先，其次规则层。"""
    return v.get("ai_grade") if v.get("ai_grade") is not None else v["grade"]

# ---------------------------------------------------------------- 模块④b Excel 详表

def export_excel(path, authors, completeness_all, quality_all):
    """Excel 详表。表头样式/冻结首行/自动列宽移植自基座 wechat_doc_mapper.generate_excel。"""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        print("提示：未安装 openpyxl，跳过 Excel 导出（pip install openpyxl）")
        return False
    # --- 基座移植的样式定义 ---
    header_font = Font(name="Arial", bold=True, size=11, color="FFFFFF")
    header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    cell_font = Font(name="Arial", size=10)
    thin_border = Border(left=Side(style="thin"), right=Side(style="thin"),
                         top=Side(style="thin"), bottom=Side(style="thin"))

    def write_table(ws, headers, records, wrap_cols=()):
        for col, h in enumerate(headers, 1):
            c = ws.cell(row=1, column=col, value=h)
            c.font, c.fill, c.border = header_font, header_fill, thin_border
            c.alignment = Alignment(horizontal="center", wrap_text=True)
        for i, row_data in enumerate(records, 2):
            for col, val in enumerate(row_data, 1):
                c = ws.cell(row=i, column=col, value=val)
                c.font, c.border = cell_font, thin_border
                if col in wrap_cols:
                    c.alignment = Alignment(wrap_text=True)
        for col in range(1, len(headers) + 1):
            max_len = max((len(str(ws.cell(row=r, column=col).value or ""))
                           for r in range(1, len(records) + 2)), default=8)
            ws.column_dimensions[get_column_letter(col)].width = min(max_len + 4, 40)
        ws.freeze_panes = "A2"  # 基座移植：冻结首行

    wb = Workbook()
    all_authors = sorted(authors.keys())
    # --- Sheet1 班级总览 ---
    ws1 = wb.active
    ws1.title = "班级总览"
    headers1 = ["排名", "作者", "文件数", "五件套齐全数", "完整性得分",
                "可复用", "可执行", "可验证", "IO明确", "质量分(满2)", "综合分", "质量来源"]
    rows = []
    for author in all_authors:
        comp, qual = completeness_all[author], quality_all[author]
        n_ok = sum(1 for v in comp.values() if v["status"] == "ok")
        grades = {k: final_grade(v) for k, v in qual.items()}
        q_score = sum(grades.values()) / 8.0
        composite = (n_ok / 5.0) * 0.4 + q_score * 0.6
        src = "AI深审+规则" if any(v.get("ai_grade") is not None for v in qual.values()) else "纯规则"
        rows.append([author, len(authors[author]), n_ok, n_ok / 5.0,
                     grades["reusable"], grades["executable"], grades["verifiable"],
                     grades["clear_io"], round(q_score, 2), round(composite, 2), src])
    rows.sort(key=lambda r: r[9], reverse=True)
    write_table(ws1, headers1, [[i] + r for i, r in enumerate(rows, 1)])
    # --- Sheet2 质量明细（基座"Coverage"表思路：逐人逐条件列出评级与依据） ---
    ws2 = wb.create_sheet("质量明细")
    headers2 = ["作者", "条件", "终判", "规则初判", "AI深审", "AI依据/规则证据"]
    detail_rows = []
    for author in all_authors:
        for k, v in quality_all[author].items():
            ai_cell = (f"{GRADE_CN[v['ai_grade']]} {v.get('ai_evidence', '')}".strip()
                       if v.get("ai_grade") is not None else "—")
            evidence = v.get("ai_evidence") or v.get("evidence") or ""
            detail_rows.append([author, v["label"], GRADE_CN[final_grade(v)],
                                GRADE_CN[v["grade"]], ai_cell, evidence[:120]])
    write_table(ws2, headers2, detail_rows, wrap_cols=(5, 6))
    wb.save(path)
    return True

# ---------------------------------------------------------------- 模块④ 报告生成

GRADE_CN = {2: "✅", 1: "⚠️", 0: "❌"}

def build_report(root, authors, non_c4, completeness_all, quality_all):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    n_files = sum(len(v) for v in authors.values())
    lines = [
        "# C4 提交自动评审报告", "",
        f"- 生成时间：{now}",
        f"- 扫描路径：`{root}`",
        f"- 识别提交：{len(authors)} 位作者，{n_files} 个文件（另有 {len(non_c4)} 个非 C4 文件未计入）",
        "", "## 一、班级总览", "",
        "| 作者 | 五件套 | 完整性 | 质量分 | 综合分 | 排名 |",
        "|---|---|---|---|---|---|",
    ]
    rows = []
    for author, files in authors.items():
        comp = completeness_all[author]
        n_ok = sum(1 for v in comp.values() if v["status"] == "ok")
        qual = quality_all[author]
        q_score = sum(final_grade(v) for v in qual.values()) / 8.0  # 4 条件 × 满分 2，AI 深审优先
        composite = (n_ok / 5.0) * 0.4 + q_score * 0.6
        rows.append((author, n_ok, q_score, composite, comp, qual, len(files)))
    rows.sort(key=lambda r: r[3], reverse=True)
    for rank, (author, n_ok, q_score, composite, comp, qual, n_files_a) in enumerate(rows, 1):
        lines.append(f"| {author} | {n_ok}/5 | {n_ok/5:.0%} | {q_score:.2f}/2.0 | {composite:.2f} | {rank} |")

    lines += ["", "## 二、作者详情", ""]
    for author, n_ok, q_score, composite, comp, qual, n_files_a in rows:
        lines += [f"### {author}", "", f"共 {n_files_a} 个文件。", "", "**完整性检查：**", "",
                  "| 文件 | 状态 | 匹配 |", "|---|---|---|"]
        for item, v in comp.items():
            m = "、".join(v["matched"]) if v["matched"] else "—"
            lines.append(f"| {v['label']} | {'✅' if v['matched'] else '❌'} | {m} |")
        lines += ["", "**质量评审（规则初判 + AI 深审终判）：**", "",
                  "| 条件 | 终判 | 规则初判 | AI 深审依据 |", "|---|---|---|---|"]
        for k, v in qual.items():
            detail = "；".join(f"{'✅' if ok else '❌'}{name}" for name, ok in v["checks"])
            if v["evidence"]:
                detail += f"（{v['evidence']}）"
            if v.get("ai_grade") is not None:
                ai_cell = f"{GRADE_CN[v['ai_grade']]} {v.get('ai_evidence', '')}".strip()
            else:
                ai_cell = "—（规则层判定）"
            lines.append(f"| {v['label']} | {GRADE_CN[final_grade(v)]} | {GRADE_CN[v['grade']]} | {ai_cell} |")
        lines += ["", "**改进建议：**"]
        for item, v in comp.items():
            if not v["matched"]:
                lines.append(f"1. 补交缺失文件：{v['label']}")
        for k, v in qual.items():
            if v.get("ai_suggestion"):
                lines.append(f"- [{v['label']}·AI] {v['ai_suggestion']}")
            for name, ok in v["checks"]:
                if not ok:
                    lines.append(f"- [{v['label']}] 待改进：{name}")
        lines.append("")

    lines += ["## 三、全班改进建议", ""]
    missing_count = {}
    for comp in completeness_all.values():
        for item, v in comp.items():
            if not v["matched"]:
                missing_count[v["label"]] = missing_count.get(v["label"], 0) + 1
    if missing_count:
        top = max(missing_count, key=missing_count.get)
        lines.append(f"- 最常缺失的文件：**{top}**（{missing_count[top]} 位作者缺失）")
    weak = {}
    for qual in quality_all.values():
        for k, v in qual.items():
            weak[v["label"]] = weak.get(v["label"], 0) + (2 - final_grade(v))
    if weak:
        lines.append(f"- 最弱质量维度：**{max(weak, key=weak.get)}**")
    lines.append("- 建议每位同学提交前先用本工具自检一遍。")
    return "\n".join(lines)

# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(description="C4 提交自动评审器")
    ap.add_argument("folder", help="包含 C4 提交的本地文件夹路径")
    ap.add_argument("-o", "--output", default="C4A_评审报告.md", help="输出报告路径")
    ap.add_argument("--json", dest="json_out", default=None, help="同时输出中间结果 JSON")
    ap.add_argument("--ai-prepare", dest="ai_prepare", nargs="?", const="ai_review_tasks.json",
                    metavar="任务包.json", help="导出 AI 深审任务包（规则层 ⚠️ 的文件内容）后退出")
    ap.add_argument("--ai-merge", dest="ai_merge", metavar="AI结果.json",
                    help="合并 AI 深审结果（AI 终判优先于规则层）")
    ap.add_argument("--excel", dest="excel", nargs="?", const="C4A_评审详表.xlsx",
                    metavar="详表.xlsx", help="同时导出 Excel 详表")
    args = ap.parse_args()

    root = Path(args.folder)
    if not root.is_dir():
        print(f"错误：{root} 不是文件夹", file=sys.stderr)
        sys.exit(1)

    rubric_path = Path(__file__).parent / "references" / "c4_rubric.yaml"
    rubric = yaml.safe_load(rubric_path.read_text(encoding="utf-8"))

    authors_raw, non_c4 = scan_folder(root)
    if not authors_raw:
        print(f"未找到 C4 相关文件（扫描路径：{root}）。匹配规则：文件名含 _C4_ 或扩展名 .skill")
        sys.exit(0)

    completeness_all, quality_all = {}, {}
    for author, files in authors_raw.items():
        files = keep_latest_versions(files)
        authors_raw[author] = files
        completeness_all[author] = check_completeness(files, rubric)
        quality_all[author] = quality_review(files, rubric)

    # --- AI 深审：导出任务包模式 ---
    if args.ai_prepare:
        n = ai_prepare(root, authors_raw, completeness_all, quality_all, args.ai_prepare)
        print(f"AI 深审任务包已导出：{args.ai_prepare}（{n} 个待深审文件）")
        print(f"下一步：把任务包交给 AI 评审，结果存为 JSON 后执行 --ai-merge")
        sys.exit(0)

    # --- AI 深审：合并结果模式 ---
    if args.ai_merge:
        n_reviews, merged = ai_merge(quality_all, args.ai_merge)
        print(f"已合并 AI 深审 {n_reviews} 条结果，覆盖作者：{', '.join(sorted(merged)) or '无'}")

    report = build_report(root, authors_raw, non_c4, completeness_all, quality_all)
    Path(args.output).write_text(report, encoding="utf-8")
    print(f"评审完成：{len(authors_raw)} 位作者，报告已写入 {args.output}")

    if args.excel:
        if export_excel(args.excel, authors_raw, completeness_all, quality_all):
            print(f"Excel 详表已写入 {args.excel}")

    if args.json_out:
        data = {
            "authors": {
                a: {
                    "files": [r["rel"] for r in fs],
                    "completeness": completeness_all[a],
                    "quality": {k: {"grade": v["grade"], "ai_grade": v.get("ai_grade"),
                                    "label": v["label"],
                                    "checks": [[n, o] for n, o in v["checks"]],
                                    "evidence": v["evidence"],
                                    "ai_evidence": v.get("ai_evidence"),
                                    "ai_suggestion": v.get("ai_suggestion")} for k, v in quality_all[a].items()},
                } for a, fs in authors_raw.items()
            },
            "non_c4_files": non_c4,
        }
        Path(args.json_out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"中间结果已写入 {args.json_out}")

if __name__ == "__main__":
    main()
