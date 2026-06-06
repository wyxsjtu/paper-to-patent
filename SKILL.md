# 专利交底书生成技能 (patent-disclosure)

将英文学术论文（PDF 文件或 LaTeX 项目目录）转换为完整、规范的中国发明专利技术交底书。输出 Markdown、Word（.docx）和 PNG 附图。

## 何时使用

当用户提供英文学术论文、LaTeX 项目、PDF 论文，要求生成中国发明专利技术交底书、技术交底材料、权利要求书草稿、背景技术或专利检索结果时，使用本技能。

## 快速命令

```bash
# 依赖自检
python3 .claude/skills/patent-disclosure/scripts/check_env.py

# 设置输出目录（论文目录下新建 patent_disclosure/）
PAPER_DIR="/path/to/paper_dir"
OUT_DIR="${PAPER_DIR}/patent_disclosure"
mkdir -p "${OUT_DIR}"

# 解析论文
python3 .claude/skills/patent-disclosure/scripts/parse_paper.py "${PAPER_DIR}" \
  -o "${OUT_DIR}/paper_parsed.json"

# CNIPA 检索（长查询自动拆分为子查询，--source all 时先 gov 再 epub/google）
python3 .claude/skills/patent-disclosure/scripts/patent_search.py \
  --query "关键词1 关键词2" --query "关键词3 关键词4" \
  --max 8 --source all -o "${OUT_DIR}/patent_results.json"

# 生成后自查
python3 .claude/skills/patent-disclosure/scripts/check_disclosure.py "${OUT_DIR}/disclosure.md"

# 完整流程测试
python3 .claude/skills/patent-disclosure/scripts/run_e2e_test.py
```

## 工作流

1. 确认论文路径存在；若未提供路径，向用户索取 PDF 或 LaTeX 项目目录。

2. **确定输出目录**：在论文所在目录下新建 `patent_disclosure/` 子文件夹作为本次所有输出的根目录。
   ```bash
   PAPER_DIR=”<论文PDF所在目录或LaTeX项目目录>”
   OUT_DIR=”${PAPER_DIR}/patent_disclosure”
   mkdir -p “${OUT_DIR}”
   ```
   后续所有生成文件（Markdown、Word、PNG、中间 JSON）均写入 `${OUT_DIR}`，**不使用 /tmp 存放最终产物**。

3. 运行 `parse_paper.py` 提取标题、摘要、章节、贡献、公式、图题和实验结果；解析不足时直接阅读论文源文件补充。
   ```bash
   python3 .claude/skills/patent-disclosure/scripts/parse_paper.py “${PAPER_DIR}” \
     -o “${OUT_DIR}/paper_parsed.json”
   ```

4. 用 `patent_search.py` 检索 CNIPA 公开专利：
   - 查询关键词拆成 **2–3 词**为宜（脚本会自动对长查询拆分子查询重试）；
   - 用 `--query` 多次传入 2–3 组不同角度的关键词（如技术手段一组、应用场景一组）；
   - 优先 `gov/cnipa` 源，`epub` 仅作为有显示环境的备用源；
   - 若所有源均无结果，使用 WebSearch 工具补充检索，搜索格式：`”关键词 发明专利 CN”`。
   ```bash
   python3 .claude/skills/patent-disclosure/scripts/patent_search.py \
     --query “关键词1 关键词2” --query “关键词3 关键词4” \
     --max 8 --source all -o “${OUT_DIR}/patent_results.json”
   ```

5. 将论文贡献转成专利语言，形成”技术问题 -> 技术方案 -> 有益效果”的闭环。建立权利要求要素矩阵，区分核心独立特征、从属特征、实施例证据和现有技术区别。

5′. **术语确认**：扫描论文中出现的专业术语，对照下方”术语表（已确认标准译法）”使用标准译法；若遇到表中未覆盖的关键术语，**在进入步骤 6 撰写前**以列表形式向用户询问，格式为：”以下术语建议译法待确认：① XXX → 建议译为 YYY，请确认或提供其他译法”；用户确认后记入本次交底书正文开头的”本次术语补充”注释中，不再重复询问。

6. 向用户确认核心思路后，再按 `templates/disclosure_template.md` 撰写正文（严格遵守各节字数约束），保存至：
   ```
   ${OUT_DIR}/disclosure.md
   ```

7. 用 Mermaid 生成系统架构图和方法流程图，运行 `mermaid_to_png.sh` 将 PNG 输出到 `${OUT_DIR}`：
   ```bash
   bash .claude/skills/patent-disclosure/scripts/mermaid_to_png.sh \
     “${OUT_DIR}/disclosure.md” “${OUT_DIR}”
   # 使用更新后含图片引用的 Markdown
   cp “${OUT_DIR}/_updated.md” “${OUT_DIR}/disclosure.md”
   ```

8. 运行 `md_to_docx.py` 生成 Word，输出至 `${OUT_DIR}`：
   ```bash
   python3 .claude/skills/patent-disclosure/scripts/md_to_docx.py \
     “${OUT_DIR}/disclosure.md” “${OUT_DIR}/disclosure.docx”
   ```

9. 运行 `check_disclosure.py` 执行自查：
   ```bash
   python3 .claude/skills/patent-disclosure/scripts/check_disclosure.py \
     “${OUT_DIR}/disclosure.md”
   ```
   - **[FAIL] 项必须修改后重新生成**；
   - [WARN] 项根据实际情况评估调整；
   - 向用户报告自查结果摘要及输出目录路径。

## 权利要求要素矩阵

撰写前必须形成如下矩阵，并据此组织交底书正文：

| 类别 | 内容 | 来源证据 | 写入位置 |
|------|------|----------|----------|
| 核心独立特征 | 最小必要技术特征组合 | 摘要/方法章节/核心公式 | 发明内容、权利要求书草稿 |
| 从属限定 | 参数、模块变体、训练配置、优选流程 | 方法章节/消融实验 | 具体实施方式、从属要点 |
| 实施例证据 | 数据集、指标、硬件、效果提升 | 实验章节 | 有益效果、实施例 |
| 区别特征 | 相对现有技术的不同处理机制 | 专利检索和 Related Work | 背景技术、技术问题 |

## 专利检索相关性评分

检索结果按以下规则筛选 3-5 篇最相关专利：

- 标题命中核心方法或应用场景：3 分
- 摘要命中核心模块、数据类型或处理流程：3 分
- IPC 与技术领域匹配：2 分
- 公开/申请时间接近当前技术：1 分
- 申请人或场景与论文方向高度相关：1 分

背景技术只描述相关技术方案和缺陷，不在正文中堆砌专利号；专利号可列在交底书末尾的代理人参考部分。

## 写作原则

- 发明名称建议 **25–32 字**，不写评价性词语，不超过 35 字。
- 不按论文结构复述，按专利审查逻辑撰写。
- 不写”本文、我们、作者、新颖、先进”等学术或宣传表达。
- **用词合规**：专利文件使用中性客观语言；”攻击”→”分析”（如”侧信道分析方法”、”单迹分析”、”密钥恢复”），”攻击者”→”分析者”，”攻击成功率”→”分析成功率”；全文不出现”攻击”一词。
- 正文每段前加 `[000X]` 段落编号（从 [0001] 起各节连续递增），与参考 PDF 风格一致。
- 交底书正文采用真实交底书语体：标题使用”技术领域、背景技术、发明内容、技术效果、附图说明、具体实施方式”，正文以连续段落和”所述的……”定义展开，不写成论文报告或项目说明书。
- 发明内容先用一段说明本发明提出什么、通过什么技术手段、实现什么效果，再写”本发明是通过以下技术方案实现的：”，随后定义输入、参数、模块、恢复/输出过程和系统组成。
- 具体实施方式优先使用”①②③……”步骤编号，步骤之间说明数据如何传输和更新，避免空泛的”模块负责……”。
- 技术方案必须可实施：输入、输出、模块、步骤、公式、参数和替代实现要交代清楚。
- 数学内容必须工程化：公式要解释变量、计算对象和在系统中的作用。
- 有益效果优先使用量化指标；无量化数据时说明可验证的工程效果。
- Word 输出中文正文字体使用宋体，标题使用黑体，西文和数字使用 Times New Roman。
- **reference.docx 字体维护**：`md_to_docx.py` 在每次调用 pandoc 前会自动修补 `templates/reference.docx` 的 eastAsia 字体设置（Normal → 宋体，Heading → 黑体）；若手动替换了 reference.docx，无需额外操作，脚本会自动修正。

### 各节字数约束（严格遵守）

| 章节 | 字数范围 | 段落数 |
|------|----------|--------|
| 技术领域 | 60–100字 | 1段 |
| 背景技术 | 100–200字 | 1–2段 |
| 发明内容 | 500–800字 | 8–12段（含系统段）|
| 技术效果 | 80–150字 | 1段，必须含量化指标 |
| 附图说明 | 每图1行 | — |
| 具体实施方式 | 200–400字 | 引言1句 + 步骤①–⑧ |

**发明内容每个”所述的……是指：”定义段不超过3句；系统段列模块名+单句功能描述即可。**

### 附图一致性规则（严格遵守）

附图说明中”图N为…”条目数量必须与正文中 Mermaid 代码块数量**严格相等**。撰写顺序：
1. 先决定绘制几张图（不超过3张）；
2. 在正文具体实施方式中写对应数量的 Mermaid 块；
3. 附图说明中写相同数量的”图N为…”，一一对应。

**不要写”图2为……示意图”占位后不提供对应 Mermaid 块。**

### 流程图配色规则（严格遵守）

Mermaid 流程图必须使用**黑白风格**，不得指定任何彩色填充或描边色。具体要求：
- 不使用 `style NodeName fill:#xxxxxx` 或 `style NodeName stroke:#xxxxxx` 指定颜色；
- 不使用 `classDef` 定义彩色样式类；
- 若需区分节点层级，仅使用节点形状（方框 `[]`、圆角 `()`、菱形 `{}`）加以区分，不使用颜色。

---

## 术语表（已确认标准译法）

撰写前对照本表翻译专业术语；表中未覆盖的术语按步骤 5′ 询问用户。

| 英文原文 | 中文标准译法 | 备注 |
|----------|-------------|------|
| power trace / side-channel trace | 功耗曲线 | 不用”迹” |
| profiling traces | 建模曲线 | |
| attack traces | 待分析曲线 | |
| trace alignment | 曲线对齐 | |
| trace misalignment | 曲线未对齐 | |
| single-trace attack/analysis | 单曲线分析 | |
| butterfly unit | 蝴蝶单元 | |
| twiddle factor | 扭转因子 | |
| belief propagation | 置信传播（BP） | |
| factor graph | 因子图 | |
| Hamming weight | 汉明重量 | |
| Point of Interest | 兴趣点（PoI） | |
| soft analytical side-channel attack | 软分析侧信道分析方法 | 不用”攻击” |
| side-channel analysis | 侧信道分析 | |
| profiling attack | 建模侧信道分析 | |
| template attack | 模板分析法 | |
| key recovery | 密钥恢复 | |
| in-trace batch | 曲线内批次 | |
| unsupervised domain adaptation | 无监督域适应（UDA） | |
| maximum mean discrepancy | 最大均值差异（MMD） | |
