# paper-to-patent

**一个 Claude Code Skill：将英文学术论文自动转换为中国发明专利技术交底书。**

输入 PDF 或 LaTeX 项目目录，输出完整、规范的专利技术交底书（Markdown + Word `.docx` + PNG 附图）。

---

## 目录

- [快速开始](#快速开始)
- [安装依赖](#安装依赖)
- [使用方法](#使用方法)
- [工作流详解](#工作流详解)
- [脚本说明](#脚本说明)
- [设计原理](#设计原理)
- [输出示例](#输出示例)
- [常见问题](#常见问题)

---

## 快速开始

```bash
# 1. 克隆仓库，放入 Claude Code skills 目录
git clone https://github.com/wyxsjtu/paper-to-patent.git \
  .claude/skills/patent-disclosure

# 2. 安装依赖
bash .claude/skills/patent-disclosure/scripts/setup.sh

# 3. 在 Claude Code 中触发 skill
# 直接输入：
/patent-disclosure
# Claude 会询问论文路径，或直接提供：
/patent-disclosure /path/to/paper.pdf
```

---

## 安装依赖

### 自动安装

```bash
bash scripts/setup.sh
```

### 手动安装

```bash
# Python 包（必须）
pip install requests beautifulsoup4

# Python 包（推荐，提升 PDF 解析质量）
pip install pymupdf pdfminer.six python-docx playwright lxml

# Pandoc（Word 输出最佳质量）
sudo apt install pandoc          # Ubuntu/Debian
brew install pandoc              # macOS

# Mermaid CLI（本地流程图渲染，无网络时使用）
npm install -g @mermaid-js/mermaid-cli

# Playwright Chromium（备用 CNIPA 检索源，可选）
python3 -m playwright install chromium
```

### 依赖自检

```bash
python3 scripts/check_env.py
```

输出示例：
```
[OK  ] python:requests              CNIPA/Google patent search
[OK  ] python:bs4                   CNIPA HTML parsing
[OK  ] python:fitz                  best PDF parsing (PyMuPDF)
[OK  ] bin:pandoc                   /usr/bin/pandoc
[OK  ] bin:mmdc                     /usr/local/bin/mmdc
...
Required dependencies are available.
```

---

## 使用方法

### 作为 Claude Code Skill 使用（推荐）

将本仓库克隆到 `.claude/skills/patent-disclosure/`，然后在 Claude Code 中输入：

```
/patent-disclosure
```

Claude 会交互式地完成整个流程，包括：
- 自动解析论文
- 检索 CNIPA 相关专利
- 与你确认术语译法和核心技术思路
- 生成并自查交底书

### 单独使用各脚本

```bash
PAPER_DIR="/path/to/paper_dir"
OUT_DIR="${PAPER_DIR}/patent_disclosure"
mkdir -p "${OUT_DIR}"

# Step 1: 解析论文（PDF 或 LaTeX 目录）
python3 scripts/parse_paper.py "${PAPER_DIR}" -o "${OUT_DIR}/paper_parsed.json"

# Step 2: 检索 CNIPA 专利
python3 scripts/patent_search.py \
  --query "深度学习 目标检测" \
  --query "特征金字塔 实时识别" \
  --max 8 --source all \
  -o "${OUT_DIR}/patent_results.json"

# Step 3: （由 Claude 撰写 disclosure.md）

# Step 4: Mermaid 流程图 → PNG
bash scripts/mermaid_to_png.sh "${OUT_DIR}/disclosure.md" "${OUT_DIR}"
cp "${OUT_DIR}/_updated.md" "${OUT_DIR}/disclosure.md"

# Step 5: Markdown → Word
python3 scripts/md_to_docx.py "${OUT_DIR}/disclosure.md" "${OUT_DIR}/disclosure.docx"

# Step 6: 自查
python3 scripts/check_disclosure.py "${OUT_DIR}/disclosure.md"
```

---

## 工作流详解

```
论文 PDF / LaTeX 目录
        │
        ▼
┌─────────────────┐
│  parse_paper.py │  提取标题、摘要、贡献点、公式、图题、实验结果
└────────┬────────┘
         │
         ▼
┌──────────────────┐
│ patent_search.py │  检索 CNIPA 公布公告（gov → epub → Google Patents）
└────────┬─────────┘
         │
         ▼
┌──────────────────────────────────────────┐
│  Claude（核心撰写步骤）                   │
│  1. 建立权利要求要素矩阵                  │
│  2. 术语确认（与用户交互）                │
│  3. 确认核心技术思路（与用户交互）        │
│  4. 按模板撰写 disclosure.md             │
└────────┬─────────────────────────────────┘
         │
         ▼
┌──────────────────┐
│ mermaid_to_png.sh│  Mermaid 代码块 → PNG（mmdc 或 mermaid.ink API）
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│  md_to_docx.py   │  Markdown → Word（pandoc 优先，python-docx 兜底）
└────────┬─────────┘
         │
         ▼
┌───────────────────────┐
│  check_disclosure.py  │  结构、字数、禁用词、附图一致性自查
└───────────────────────┘
         │
         ▼
  patent_disclosure/
  ├── disclosure.md       ← 交底书正文
  ├── disclosure.docx     ← Word 文档（宋体/黑体/TNR）
  ├── fig_01_*.png        ← 系统架构图
  ├── fig_02_*.png        ← 方法流程图
  ├── paper_parsed.json   ← 论文解析中间结果
  └── patent_results.json ← 专利检索结果
```

### 交底书模板结构

生成的交底书严格遵循中国发明专利申请规范，包含以下章节：

| 章节 | 字数约束 | 内容要点 |
|------|----------|----------|
| 技术领域 | 60–100 字 | 领域定位 + 核心技术手段 |
| 背景技术 | 100–200 字 | 现有方法 + 具体不足 |
| 发明内容 | 500–800 字 | 技术方案定义（所述的…是指：） |
| 技术效果 | 80–150 字 | 量化指标对比 |
| 附图说明 | 每图一行 | 与 Mermaid 块一一对应 |
| 具体实施方式 | 200–400 字 | ①②③步骤 + 数据流说明 |
| 权利要求书草稿 | — | 独立权 + 从属权 + 系统权 |

---

## 脚本说明

### `parse_paper.py`

从 PDF 或 LaTeX 目录提取结构化内容。

- **PDF 解析优先级**：PyMuPDF → pdfminer.six → pdftotext
- **LaTeX 解析**：自动识别根文件（`\documentclass`），递归展开 `\input` / `\include`，提取标题、摘要、关键词、各节内容、公式、图题、贡献列表
- **输出**：JSON 文件，字段包括 `title`, `abstract`, `contributions`, `sections`, `key_formulas`, `figure_captions`

```bash
python3 scripts/parse_paper.py /path/to/paper.pdf -o output.json
python3 scripts/parse_paper.py /path/to/latex_dir/ -o output.json
```

### `patent_search.py`

多源 CNIPA 专利检索，支持三个检索源：

| 源 | 说明 | 环境要求 |
|----|------|----------|
| `gov` | 国家政务服务平台 CNIPA 接口 | 无需显示器，服务器可用 |
| `epub` | epub.cnipa.gov.cn 公布公告 | 需要本地显示器（Playwright） |
| `google` | Google Patents JSON API | 需访问 Google |

长查询（>2词）自动拆分为两两组合子查询重试，所有源均无结果时提示使用 WebSearch。

```bash
python3 scripts/patent_search.py \
  --query "卷积神经网络 目标检测" \
  --query "特征融合 实时推理" \
  --max 8 --source gov \
  -o results.json
```

### `mermaid_to_png.sh`

将 Markdown 中的 ` ```mermaid ` 代码块转换为 PNG 图片，并将文件中的代码块替换为 `![...](fig_NN_*.png)` 引用。

- **转换优先级**：本地 `mmdc` → `mermaid.ink` 在线 API
- **文件命名**：`fig_01_<标签>.png`，标签从附图说明中自动提取

```bash
bash scripts/mermaid_to_png.sh input.md output_dir/
cp output_dir/_updated.md input.md
```

### `md_to_docx.py`

将交底书 Markdown 转换为符合中文专利规范的 Word 文档。

- **转换优先级**：pandoc（最佳质量）→ python-docx（兜底）
- **字体设置**：中文正文宋体、标题黑体、西文和数字 Times New Roman
- **自动修补** `reference.docx` 的 `eastAsia` 字体，防止 MS Gothic 覆盖宋体
- **数学公式**：pandoc 路径用 MathML，python-docx 路径用 LaTeX → MathML → OMML 转换链

```bash
python3 scripts/md_to_docx.py disclosure.md disclosure.docx
```

### `check_disclosure.py`

对生成的 Markdown 交底书执行 15 项结构自查：

| 检查项 | 级别 | 说明 |
|--------|------|------|
| 发明名称规范性 | FAIL/WARN | 长度、无评价性用语 |
| 必要章节完整性 | FAIL | 7 个必要章节 |
| 禁用词 | FAIL | "本文/我们/作者/新颖/先进" |
| 需替换词 | WARN | "攻击" → "分析" 等合规表达 |
| 标准过渡句 | WARN | "本发明是通过以下技术方案实现的" |
| 段落编号 | WARN | `[0001]` 风格 |
| 各节字数 | WARN | 超出建议范围时提示 |
| 量化效果 | WARN | 技术效果节含数字指标 |
| 附图引用 | WARN | 具体实施方式含"如图N所示" |
| 步骤编号 | WARN | 具体实施方式含①②③ |
| 附图数量一致性 | FAIL | 附图说明条目数 = Mermaid/PNG 块数 |

```bash
python3 scripts/check_disclosure.py disclosure.md
# 输出示例：
# [PASS] [发明名称] 发明名称合规: 一种基于…
# [PASS] [必要章节] 必要章节齐全
# [WARN] [章节字数] 「发明内容」字数偏多(1200字，建议400–1200字)
# 总计: 13 PASS / 2 WARN / 0 FAIL
```

---

## 设计原理

### 核心理念：论文语言 → 专利语言

学术论文与专利申请文件的写作逻辑截然不同：

| 维度 | 学术论文 | 专利交底书 |
|------|----------|------------|
| 结构逻辑 | 问题→方法→实验→结论 | 技术问题→技术方案→有益效果 |
| 表达方式 | "我们提出…""实验表明…" | "本发明涉及…""所述的…是指：" |
| 重点 | 创新性证明、与他人工作对比 | 技术特征可实施性、权利边界 |
| 数学内容 | 理论推导 | 工程化描述（变量含义、计算对象、系统作用） |

本 skill 的撰写规则将论文贡献点映射为**权利要求要素矩阵**，再按专利审查逻辑组织内容：

```
论文贡献
    │
    ▼
权利要求要素矩阵
    ├── 核心独立特征  →  发明内容 + 独立权利要求
    ├── 从属限定      →  具体实施方式 + 从属权利要求
    ├── 实施例证据    →  技术效果 + 实施例
    └── 区别特征      →  背景技术 + 技术问题
```

### 专利检索设计

检索采用三源降级策略：

```
CNIPA 政务平台 (gov)
  └─ 无结果 → epub.cnipa.gov.cn (需显示器)
        └─ 无结果 → Google Patents API
              └─ 全部失败 → 提示 WebSearch
```

查询词过长（>2词）时自动拆分为两两组合，提升召回率。检索结果按**相关性评分**（标题命中/摘要命中/IPC匹配/时间/申请人）筛选 3–5 篇，用于背景技术的"现有技术缺陷"分析，专利号仅在交底书末尾代理人参考区列出，不堆砌于正文。

### Mermaid 图渲染策略

```
本地 mmdc（@mermaid-js/mermaid-cli）
    └─ 未安装 → mermaid.ink 在线 API（无需任何本地工具）
```

流程图强制黑白风格（专利附图规范），不允许 `style fill:#` 或 `classDef` 彩色定义。图数量与附图说明条目数由 `check_disclosure.py` 严格校验。

### Word 字体保障机制

pandoc 默认使用 `reference.docx` 模板中的字体，但 OOXML 的 `w:eastAsiaTheme` 属性会覆盖显式的 `w:eastAsia` 设置（导致宋体被 MS Gothic 替换）。`md_to_docx.py` 在每次调用 pandoc 前自动修补 `reference.docx`：移除所有 `*Theme` 字体属性，显式写入宋体/黑体，确保在任意 Office 版本中正确渲染。

---

## 输出示例

以一篇关于 ML-KEM 侧信道分析的论文为例，生成的交底书包含：

- **发明名称**：一种基于对抗迁移学习的 ML-KEM 免建模设备软分析侧信道分析方法及系统
- **权利要求**：1 项方法独立权（5 步骤）+ 3 项从属权 + 1 项系统权
- **附图**：整体框架流程图 + 对抗域适应网络结构图
- **自查结果**：13 PASS / 3 WARN / 0 FAIL

---

## 常见问题

**Q：PDF 解析效果差怎么办？**

优先安装 PyMuPDF：`pip install pymupdf`。若论文为扫描版，建议提供 LaTeX 源文件目录。

**Q：CNIPA 检索无结果？**

gov 源依赖国家政务服务平台接口，偶有不稳定。可尝试 `--source google` 或让 Claude 直接调用 WebSearch 工具补充检索。

**Q：Mermaid 图生成失败？**

安装 mmdc：`npm install -g @mermaid-js/mermaid-cli`。无法安装时 mermaid.ink API 作为备选（需要网络访问）。

**Q：Word 文档中文显示为 MS Gothic？**

运行 `python3 scripts/md_to_docx.py` 时脚本会自动修补字体。若仍有问题，删除 `templates/reference.docx` 后重新运行 `setup.sh` 重建模板。

**Q：如何作为 Claude Code Skill 安装？**

```bash
mkdir -p .claude/skills
git clone https://github.com/wyxsjtu/paper-to-patent.git .claude/skills/patent-disclosure
```

然后在 Claude Code 中输入 `/patent-disclosure` 即可触发。

---

## License

MIT License. See [LICENSE](LICENSE) for details.
