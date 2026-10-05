# c4a-skill-evaluator —— C4 提交自动评审器

一句话：输入一个装着同学 C4 提交的本地文件夹，输出中文评审报告——**谁交了、五件套齐不齐、四条件各得几分、全班排名与改进建议**。

本仓库是 EdUseed Elite20 课程 C4A 挑战的交付物：不是"做一个技能"，而是"做一个能评审所有人技能的自动评审器"。

## 评审口径从哪来

`references/c4_rubric.yaml`（官方 starter 提供，原样沿用未改动）：

- **完整性**：五件套——Skill 说明文档 / 可执行内容 / Demo / 教学说明 / AI 生成日志
- **质量**：四条件——可复用 / 可执行 / 可验证 / IO 明确，各占 0.25
- **综合分** = 完整性 × 0.4 + 质量分 × 0.6

## 环境要求

- Python 3.8+
- **必需**：`pip install pyyaml`
- 推荐：`pip install openpyxl`（缺省时唯一变化是 Excel 详表自动跳过，Markdown 报告照常产出）
- 可选：`pip install python-docx pypdf`（缺省时 .docx/.pdf 仅按文件名匹配，不读正文）

平台无关：macOS / Linux / Windows 均可运行，代码内无硬编码绝对路径。

## 安装

```bash
git clone https://github.com/Raymond-Lao/c4a-skill-evaluator.git
cd c4a-skill-evaluator
pip install pyyaml openpyxl python-docx pypdf
```

## 快速开始（3 条命令）

```bash
# 1) 规则层评审，产出 Markdown 报告
python c4a_evaluator.py "D:\提交文件夹" -o 评审报告.md

# 2) 同时导出中间结果与 Excel 详表
python c4a_evaluator.py "D:\提交文件夹" -o 评审报告.md --json 结果.json --excel 评审详表.xlsx

# 3) AI 深审三步
python c4a_evaluator.py "D:\提交文件夹" --ai-prepare      # ① 导出 ai_review_tasks.json
#    ② 把 ai_review_tasks.json 交给 AI（WorkBuddy / Claude / ChatGPT），
#       按 JSON 内 task 字段说明逐文件评级，写回 ai_review_results.json
python c4a_evaluator.py "D:\提交文件夹" -o 评审报告.md --ai-merge ai_review_results.json   # ③ 合并终判
```

## 输入约定

- 输入就是一个**本地文件夹路径**（命令行传入，代码内零硬编码路径）
- 作者识别：优先 Elite20 命名规范 `姓名拼音_C4_内容.扩展名`，回退子文件夹名
- 同名 `_v2/_v3` 自动取最新版
- 支持 .md / .py / .skill / .docx / .pdf / .png / .mp4 等；**`.skill` 包会解包**，读取包内 SKILL.md、脚本与参考文件后再参与匹配与评分
- 中文内容 UTF-8 优先、GBK 回退；单文件 > 50MB 只做文件名匹配，不读内容

## 输出

- **Markdown 评审报告**：总览 / 逐人详情 / 全班排名 / 改进建议
- 可选 **JSON 中间结果** 与 **Excel 样式化详表**
- 每条 AI 改判都必须引用原文依据并写入报告，供人工抽查

## 实测结果（真实数据，可复现）

用真实提交跑出的终版 v3 三方排名：

| 样本 | 综合分 |
|---|---|
| 李瑞翔 C4 技能包 | 1.00 |
| 官方 starter：skill-explainer | 0.76 |
| 官方 starter：wechat-doc-mapper | 0.68 |

（拆包评审前 .skill 包只能按文件名评分，得分 0.23；v3 解包读取内部内容后升至 0.68 / 0.76）

## 降级与熔断

- **规则 + AI 混合**：规则管确定性检查（文件在不在、硬编码路径、语法错误），AI 管语义质量；AI 超时或未参与时，报告自动降级为纯规则结果，不会崩
- 微信群取件不稳定 → 提供 **mock 提交兜底**，无网络也能验证评审器本身

## 目录结构

```
c4a-skill-evaluator/
├── SKILL.md                  # 技能说明（触发词 / 用途 / 使用方法 / 边界情况）
├── c4a_evaluator.py          # 单文件评审器主程序（约 630 行）
├── references/c4_rubric.yaml # 四条件评审口径（官方 starter 原样沿用）
└── README.md                 # 本文件：安装 / 使用 / 边界
```

## 已知限制

- 语义类问题（如"IO 章节与正文脱节"）仍以词面与结构信号为主，泛化能力有限
- 四条件打分为规则初判，语义质量判定依赖可选的 AI 深审环节
- 超大文件（>50MB）与二进制文件不做内容解析

## 来源与致谢

- 官方 starter 的四步 SKILL.md 结构与 `references/c4_rubric.yaml` 原样沿用，综合分公式沿用
- 移植自 `wechat-doc-mapper.skill` 的 3 个函数模块：docx/pdf 全文抽取、Excel 样式化导出、文件夹扫描作者归组；在其上新增 `--ai-prepare` / `--ai-merge`、`.skill` 包文本抽取、降级熔断等增量
