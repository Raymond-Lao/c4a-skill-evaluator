---
name: c4a-skill-evaluator
description: >
  Scan a local folder of Elite20 C4 skill submissions (from a WeChat group),
  group them by author, check the 5 required deliverables, grade quality against
  the C4 four-criteria rubric (rule layer), optionally hand flagged files to an
  AI deep-reviewer, and generate a Markdown report + Excel score sheet.
  Trigger when the user says "评审C4提交", "检查技能提交", "C4评审报告",
  "evaluate C4 submissions", or gives a folder of _C4_ files to review.
---

# C4 提交自动评审器（c4a-skill-evaluator）

## 用途

输入一个装着同学 C4 提交的本地文件夹，输出自动评审报告：谁交了、五件套齐不齐、
四条件质量打几分（规则初判 + AI 深审终判）、全班排名和改进建议。

## 环境要求

- Python 3.8+
- 依赖：`pip install pyyaml openpyxl`（openpyxl 缺失时 Excel 导出自动跳过）
- 可选：`pip install python-docx pypdf`（缺失时 .docx/.pdf 提交仅按文件名评审，不读内容）

## v3 能力说明

- **.skill 拆包评审**：.skill 包（zip 容器）内的 SKILL.md/脚本/参考文件会被解包读取参与五件套匹配与四条件评分，不再只看包文件名
- **混合格式**：.docx/.pdf 提交可提取正文（含 docx 表格）参与内容评审——Level 1 混合格式要求

## 使用方法

```bash
# 1. 基础评审（规则层，产出 Markdown 报告）
python c4a_evaluator.py <提交文件夹> -o 报告.md

# 2. 加导出中间结果和 Excel 详表
python c4a_evaluator.py <提交文件夹> -o 报告.md --json 结果.json --excel 详表.xlsx

# 3. AI 深审（三步）
python c4a_evaluator.py <提交文件夹> --ai-prepare      # ① 导出深审任务包
#    ② 把 ai_review_tasks.json 交给 AI（WorkBuddy/Claude/ChatGPT），
#       按 JSON 内 task 字段说明逐文件评级，写回 ai_review_results.json
python c4a_evaluator.py <提交文件夹> -o 报告.md --ai-merge ai_review_results.json  # ③ 合并终判
```

## 输入 / 输出

- **输入**：一个本地文件夹路径。文件按 Elite20 命名规范 `姓名拼音_C4_内容.扩展名`
  识别作者（回退：子文件夹名）；支持 .md/.py/.skill/.png/.mp4 等，同名 `_v2/_v3` 自动取最新版。
- **输出**：Markdown 评审报告（总览/详情/排名/建议）+ 可选 JSON 与 Excel。
  每条 AI 改判必须引用原文依据，报告中可见，供人工抽查。

## 评审标准来源

`references/c4_rubric.yaml`（来自官方 starter 包）：五件套检测信号、四条件
评分信号、综合分公式 = 完整性 × 0.4 + 质量分 × 0.6。

## 设计要点

- 规则 + AI 混合：规则管确定性检查（文件在不在、硬编码路径、语法错误），
  AI 管语义质量；AI 超时/缺位时报告自动降级为纯规则结果，不会崩。
- 文件夹路径一律命令行参数传入，代码零硬编码。
- 中文内容 UTF-8 优先、GBK 回退；>50MB 文件只做文件名匹配。

## 边界情况

空文件夹 / 不规范命名 / 超大文件 / 二进制文件 / 非 C4 文件混入 / 多版本 /
中文编码——处理策略见 `c4a_evaluator.py` 模块注释与源码内 Edge Cases 实现。
