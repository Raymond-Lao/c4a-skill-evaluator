# C4A 教学说明（怎么装、怎么用）

> 作者：李瑞翔（LiRuixiang）｜ 面向读者：老师、助教、任何想用它评 C4 提交的人

---

## 一句话介绍

给它一个装着 C4 提交的文件夹，它还你一份评审报告：谁交了、五件套齐不齐、
质量打几分、每个人该怎么改。

## 安装（2 分钟）

1. 电脑装 Python 3.8 或更高（python.org 下载，安装时勾选 "Add to PATH"）
2. 装两个依赖：
   ```
   pip install pyyaml openpyxl
   ```
3. 把技能包文件夹 `LiRuixiang_C4A_skill-evaluator\` 整个放到任意位置（比如桌面）
   ——里面应该有 `c4a_evaluator.py`、`SKILL.md`、`references\c4_rubric.yaml`

## 基本用法（30 秒上手）

```bash
python c4a_evaluator.py "D:\微信群文件\C4提交" -o 评审报告.md --excel 详表.xlsx
```

把路径换成你自己的文件夹就行。跑完当前目录会多出两个文件：
- **评审报告.md**——用记事本/VS Code/浏览器打开，就是完整评审结果
- **详表.xlsx**——用 Excel/WPS 打开，全班评分表

## 进阶用法：开启 AI 深审（推荐）

规则层只能认关键词，AI 深审能"读懂内容"。三步：

```bash
# 第 1 步：导出需要深审的文件（自动挑出规则层拿不准的）
python c4a_evaluator.py "D:\微信群文件\C4提交" --ai-prepare

# 第 2 步：把生成的 ai_review_tasks.json 发给任意 AI（WorkBuddy / Claude / ChatGPT），
#         说一句"按这个任务包逐文件评审，按 JSON 里的说明返回结果"，
#         把 AI 返回的结果存成 ai_review_results.json

# 第 3 步：合并终判，生成最终报告
python c4a_evaluator.py "D:\微信群文件\C4提交" -o 评审报告.md --ai-merge ai_review_results.json --excel 详表.xlsx
```

第 2 步不想动手？在 WorkBuddy 里直接说"帮我深审这个任务包"即可。

## 输入什么 → 得到什么（速查）

| 你输入 | 你得到 |
|---|---|
| 装着 `姓名_C4_xxx` 文件的文件夹路径 | 每位作者的五件套检查表（✅/❌ + 缺什么） |
| （自动） | 四条件质量分：可复用/可执行/可验证/IO明确，各 ✅/⚠️/❌ |
| （自动） | 全班排名 + 每人改进建议 + 全班最常缺失文件统计 |
| `--excel` | Excel 评分详表 |
| `--ai-prepare` / `--ai-merge` | AI 终判（报告里可见 AI 引用的原文依据） |

## 常见坑

1. **路径有空格** → 记得像上面示例一样加英文双引号
2. **文件名没有 `_C4_`** → 会被当成"非 C4 文件"列在报告末尾；放进以作者命名的子文件夹也能被认出来
3. **中文乱码** → 工具已内置 UTF-8/GBK 自动回退，一般不会遇到；真遇到请反馈
4. **AI 深审没生效** → 确认 `--ai-merge` 的 JSON 里 `author` 和 `file` 与任务包中完全一致
5. **Python 报 `No module named yaml`** → 第 2 步的 pip install 没装成功，重装

## 验证安装成功

仓库自带模拟测试数据（`LiRuixiang_C4A_测试用模拟提交\`），跑：

```bash
python c4a_evaluator.py LiRuixiang_C4A_测试用模拟提交 -o test.md
```

输出"评审完成：3 位作者"且 test.md 里有排名表，就说明装好了。

---

## v3 新增能力（2026-10-05）

- **.skill 拆包**：直接把同学的 `.skill` 包放进文件夹即可，评审器会自动解 zip 读包内 SKILL.md/脚本参与评分
- **docx/pdf 支持**：提交里有 .docx/.pdf 也能读出内容参与评审（建议先 `pip install python-docx pypdf`，不装则按文件名评审）
- **Excel 详表升级**：两张表（班级总览 + 质量明细），冻结首行、自动列宽

可选依赖：

```bash
pip install python-docx pypdf
```
