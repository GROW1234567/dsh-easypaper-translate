# dsh-easypaper-translate · 简易论文翻译

> 个人开发的 DeepSeek Harness 插件。起因很朴素：免费的翻译读论文不够用，索性自己写了一个，目前够用。
>
> 把英文论文做成**中英对照 PDF**——奇数页原文、偶数页中文，正文、表格与图内文字原位替换，全程本地渲染。

**EasyPaper Translate** — a personal DSH plugin that turns English papers into a
bilingual PDF: odd pages keep the original, even pages carry the Chinese version,
with body text, tables and figure labels replaced in place. Rendering is local.

## ⚖️ 法律声明 / Legal notice

**中文**

- 本项目**仅提供工具**，不包含任何论文、译本或第三方数据。
- 使用者须自行确保对处理内容拥有**合法使用权**，并遵守文献的版权/许可协议及当地法律。
- 翻译由使用者**自行配置的模型服务**完成，内容会发送至该服务；请勿用于涉密材料或未经授权传播的内容。
- 软件按**现状**提供，不附带任何担保，作者不承担使用后果。

**English**

- The tool only. No papers, translations or third-party data are included.
- You are responsible for ensuring you may lawfully process your input, and for
  complying with its copyright and licence terms and with local law.
- Translation runs on the model service you configure, so the content is sent
  there; do not use it on confidential material or content you may not redistribute.
- Provided as-is, without warranty; the author accepts no liability for its use.

---

把英文论文做成**中英对照 PDF**，用来快速读懂外文文献。

- **奇数页 = 原文**（矢量原样嵌入，可搜索、可复制、不损失清晰度）
- **偶数页 = 译文**（正文、表格、图内文字都换成中文）
- 全部**本地渲染**，不联网、不调用第三方服务

> 它不是"出版级排版工具"，目标是**看得懂**，不是"能直接投稿"。

---

## 1. 它做什么

| 元素 | 处理方式 |
|---|---|
| 正文 | 逐块擦除原文、按原位置重排中文（字号自适应） |
| 表格 | 模型读懂表格结构 → 重建成**统一三线表**，宽高受原表墨迹约束，避免撑满全页 |
| 图内文字 | 检测墨迹框 → 编号 → 按编号原位替换；带**反色描边**保证对比度 |
| 公式 | 保留原始数学排版，不硬塞中文（避免叠字） |
| 图表（曲线/柱状） | 检测到长条墨迹就**整框跳过**，宁可少译也不涂白图表 |
| 参考文献 | 标题译中文加《》，作者/期刊/DOI 保留 |
| 页眉 | 作为可译块抽取，期刊名译中文 |

---

## 2. 安装

```powershell
# 1) 装进当前 profile（DSH 界面里或用 CLI）
dsh plugin --profile desktop add <本目录路径>
```

装完**重启 DSH**（插件在启动时加载）。

首次使用前检查 Python 依赖：

```
调用工具 paper_translate_env，action = "check"
```

缺依赖就 `action = "install"`（从 PyPI 下一次 wheel，之后离线可用）。

依赖：`pymupdf`、`scipy`、`pyyaml`（约 210 MB，装在插件目录内，不污染系统 Python）。

---

## 3. 怎么用

插件提供两个工具，**模型可直接调用**：

### `paper_translate`

| 参数 | 说明 |
|---|---|
| `action` | `prepare` / `build` / `status` / `batch` |
| `pdfPath` | 源 PDF 绝对路径 |
| `workDir` | 工作目录（默认 `./work`），每篇论文用独立目录 |
| `dpi` | **译文页 DPI**：150 / 200 / 300（默认 150，最快） |
| `imageDpi` | **图片/表格裁剪 DPI**：默认 200 |
| `nameTemplate` | 输出命名模板，见下 |
| `batchDir` | `action=batch` 时扫描的文件夹 |

### 典型流程

```
1. paper_translate(action="prepare", pdfPath="D:\papers\xxx.pdf", workDir="D:\papers\xxx_work")
   → 抽文字块、裁表格、裁插图（纯本地，几秒）

2. 模型翻译（这一步由会话模型完成，不是插件做的）
   → 译文落到 workDir/zh/、表格矩阵落到 workDir/tables/matrices.json

3. paper_translate(action="build", pdfPath="...", workDir="...", dpi=200, nameTemplate="...")
   → 生成中英对照 PDF
```

`action="status"` 随时查看：已译/待译页数、表格与插图是否就绪。

---

## 4. 输出命名

默认：

```
[中英对照]{zh_title}+{en_title}.pdf
```

可用字段：

| 字段 | 含义 |
|---|---|
| `{zh_title}` | 论文中文标题（自动从首页译文取） |
| `{en_title}` | 英文标题（源文件名） |
| `{stem}` | 同上（源文件名，不含扩展名） |
| `{dpi}` | 本次渲染 DPI |
| `{pages}` | 页数 |
| `{date}` | 输出日期 `YYYY-MM-DD` |

示例模板：

```
[中英对照]{zh_title}+{en_title}          （默认）
{date}_{zh_title}_{dpi}dpi               （按日期归档）
{zh_title}（{pages}页_{dpi}dpi）           （中文优先）
```

字段写错会自动回退到默认命名，不会报错。

---

## 5. 批量翻译

```
paper_translate(action="batch", batchDir="D:\papers\")
→ 返回文件夹内所有 PDF 列表
```

批量是**串行**的，一篇一篇处理，每篇独立工作目录：

```
for pdf in 列表:
    prepare → 翻译 → build → 输出该篇 PDF
```

**为什么串行**：每篇要 5–15 分钟、十几万 token，并行会互相抢并发额度，反而更慢，且中途失败难以定位。

建议一次 5–10 篇，放在一个文件夹里跑。

---

## 6. 关于"8 批并发"

指**单篇论文内部**的翻译并发：

- 20 页的论文拆成 **8 批**（每批 2–3 页）同时翻译
- 8 是当前环境的子智能体并发上限
- 批次越多单批越短，但固定开销（每个子任务都要读提示词）会上升

实测：22 页论文，7 批并发，约 3–8 分钟完成翻译。

---

## 7. 性能实测

测试样本：22 页论文（8.6 万字符、23 张图、8 处表格）

| 环节 | 耗时 |
|---|---|
| 抽取 + 裁图 + 检测 | 8 s |
| 模型翻译 | 3–8 min |
| 渲染构建 | **8–11 s**（200dpi） |

### DPI 对构建的影响

| DPI | 构建耗时 | 文件体积 | 建议 |
|---|---|---|---|
| 150 | 8 s | 21 MB | **默认**，屏幕阅读够用 |
| 200 | 11 s | 25 MB | 需要放大看时用 |
| 300 | 19 s | 35 MB | 打印/投屏 |
| 600+ | 2 分钟+ | 90 MB+ | 不推荐（内存压力大） |

**DPI 不影响 token 消耗**，只影响渲染时间和文件体积。

---

## 8. 成本估算

单篇 20 页论文：

| 项目 | 量 |
|---|---|
| 输入 token | ≈ 9 万 |
| 输出 token | ≈ 4.7 万 |
| **费用** | **≈ ¥0.5**（按 DeepSeek 公开价，实际随套餐/缓存命中浮动） |
| **时间** | **5–15 分钟** |

图内文字翻译约占 token 的 30%，但对读懂图表帮助很大。

---

## 9. 已知限制

1. **图形表（甘特图等）会丢行** —— 一个框里多行文字只换一段译文，可能出现空白行
2. **表格裁切不全** —— 一页多张表时，目前只重建首张
3. **曲线图的图例/坐标轴文字** 在绘图区内，会被"保护图表"规则跳过（保留英文）
4. **跨块断句** —— 原文被 PDF 切开的句子，译文也按原切分点断开
5. **译文页是图片**，不可搜索复制（原文页可以）

---

## 10. 注意事项

- **工作目录不要复用**：每篇论文一个 `workDir`，否则译文会串
- **首次运行要装依赖**（约 210 MB），装一次即可
- **译文质量取决于模型**，术语一致性靠翻译时的提示词约束
- **大批量前先试一篇**：不同期刊的版式差异很大（双栏/单栏、表格样式）
- 中途中断可续跑：已完成的 `zh/pNN.json` 不会重译

---

## 11. 优缺点

**优点**

- 奇偶对照，双页阅读即可对照原文
- 表格重建为三线表，比原表更易读
- 全程本地渲染，无外部服务依赖
- 单篇成本极低（约 ¥0.5）

**缺点**

- 译文页是位图，不可搜索
- 复杂版式（多栏混排、图形表）需要人工抽查
- 首次配置依赖较重
- 翻译由会话模型驱动，速度受模型输出速度限制

---

## 12. 实测记录

本机验证（2026-11，22 页论文）：

| 动作 | 结果 |
|---|---|
| `paper_translate_env check` | `deps ok: pymupdf 2.1, scipy 1.18.1` |
| `paper_translate status` | `pages 22, translated 22, pending 0, tables ready, figures ready` |
| `paper_translate build` | `build: ok` → 自定义命名模板 `{zh_title}_{dpi}dpi` 正确渲染 |
| `paper_translate batch` | 列出文件夹内 7 个 PDF |

**注意**：`batch` 会列出文件夹内**所有** PDF，包括已生成的中英对照文件。
批量前请自行排除文件名含 `[中英对照]` 的产物，否则会重复翻译。

**依赖位置**：`paper_translate_env install` 把包装到 `<插件根>/.pylibs`（约 200 MB），
脚本启动时会自动把这个目录加入 `sys.path`，不依赖 `PYTHONPATH` 环境变量。

**改代码后必须重启 DSH**：插件在启动时加载，`lib/index.js` 的改动不会热更新；
Python 端（`python/*.py`）是每次调用时执行的，改完即生效。

---

## 13. 目录结构

```
dsh-easypaper-translate/
├── lib/index.js          插件入口（注册 paper_translate 工具）
├── cordis.patch.yml      插件挂载声明
├── python/               本地流水线
│   ├── translate.py      统一入口（extract/tables/figures/build）
│   ├── engine.py         渲染与合成
│   ├── helpers.py        文字度量/擦除/绘制
│   ├── extract_blocks.py 文字块抽取
│   ├── crop_tables.py    表格裁切
│   ├── crop_figs.py      插图裁切
│   ├── fig_boxes.py      图内文字框检测
│   ├── probe.py          文档探测
│   ├── verify.py         覆盖率校验
│   └── install_wheel.py  离线依赖安装
└── README.md
```
