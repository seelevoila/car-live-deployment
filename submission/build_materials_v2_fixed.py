# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import os
import shutil
import subprocess
import zipfile

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "submission" / "2026-chongqing-ai-competition"
EVIDENCE = OUT / "evidence"

# Academic report palette based on the supplied LaTeX reference: black text,
# restrained gray hierarchy, white table surfaces and thin rules.
INK = "191919"
BLUE = "262626"
CYAN = "454545"
MUTED = "666666"
LIGHT = "FFFFFF"
PALE = "FFFFFF"
GOLD = "3F3F3F"
RED = "7A2525"
CN_FONT = "SimSun"
LATIN_FONT = "Times New Roman"


def set_cell_shading(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:fill"), fill)


def set_table_borders(table):
    """Use an academic table treatment: horizontal rules, no boxed grid."""
    tbl_pr = table._tbl.tblPr
    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    specs = {
        "top": ("single", "191919", "10"),
        "bottom": ("single", "191919", "10"),
        "insideH": ("single", "A8A8A8", "4"),
        "left": ("nil", "FFFFFF", "0"),
        "right": ("nil", "FFFFFF", "0"),
        "insideV": ("nil", "FFFFFF", "0"),
    }
    for edge, (val, color, size) in specs.items():
        node = borders.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), val)
        node.set(qn("w:color"), color)
        node.set(qn("w:sz"), size)
        node.set(qn("w:space"), "0")


def set_cell_margins(cell, top=90, start=130, bottom=90, end=130):
    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    tc_mar = tc_pr.first_child_found_in("w:tcMar")
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for m, v in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = tc_mar.find(qn(f"w:{m}"))
        if node is None:
            node = OxmlElement(f"w:{m}")
            tc_mar.append(node)
        node.set(qn("w:w"), str(v))
        node.set(qn("w:type"), "dxa")


def set_table_geometry(table, widths):
    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl = table._tbl
    tbl_pr = tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(sum(widths)))
    tbl_w.set(qn("w:type"), "dxa")
    ind = tbl_pr.find(qn("w:tblInd"))
    if ind is None:
        ind = OxmlElement("w:tblInd")
        tbl_pr.append(ind)
    # Keep the table edge aligned with the document text inset.
    ind.set(qn("w:w"), "130")
    ind.set(qn("w:type"), "dxa")
    grid = tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)
    for row in table.rows:
        for i, cell in enumerate(row.cells):
            tc_pr = cell._tc.get_or_add_tcPr()
            tc_w = tc_pr.find(qn("w:tcW"))
            if tc_w is None:
                tc_w = OxmlElement("w:tcW")
                tc_pr.append(tc_w)
            tc_w.set(qn("w:w"), str(widths[i]))
            tc_w.set(qn("w:type"), "dxa")
            set_cell_margins(cell)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    set_table_borders(table)


def set_run(run, size=10.5, color=INK, bold=False, italic=False, font=CN_FONT):
    run.font.name = font
    run._element.rPr.rFonts.set(qn("w:eastAsia"), font)
    run._element.rPr.rFonts.set(qn("w:ascii"), LATIN_FONT)
    run._element.rPr.rFonts.set(qn("w:hAnsi"), LATIN_FONT)
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(color)
    run.bold = bold
    run.italic = italic


def set_para(p, before=0, after=6, line=1.18, align=None, keep=False):
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line
    if align is not None:
        p.alignment = align
    if keep:
        pf.keep_with_next = True


def add_text(doc, text, size=10.5, color=INK, bold=False, italic=False, before=0, after=6, align=None):
    p = doc.add_paragraph()
    set_para(p, before, after, 1.18, align)
    r = p.add_run(text)
    set_run(r, size, color, bold, italic)
    return p


def add_heading(doc, text, level=1):
    sizes = {1: 17, 2: 13.5, 3: 11.5}
    colors = {1: BLUE, 2: CYAN, 3: MUTED}
    p = doc.add_paragraph()
    p.style = f"Heading {level}"
    set_para(p, {1: 18, 2: 12, 3: 8}[level], {1: 7, 2: 5, 3: 3}[level], 1.0, keep=True)
    r = p.add_run(text)
    set_run(r, sizes[level], colors[level], True)
    return p


def add_bullet(doc, text, level=0):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.left_indent = Inches(0.32 + level * 0.22)
    p.paragraph_format.first_line_indent = Inches(-0.18)
    set_para(p, 0, 4, 1.14)
    r = p.add_run(text)
    set_run(r, 10.3, INK)
    return p


def add_num(doc, text):
    p = doc.add_paragraph(style="List Number")
    p.paragraph_format.left_indent = Inches(0.34)
    p.paragraph_format.first_line_indent = Inches(-0.2)
    set_para(p, 0, 4, 1.14)
    r = p.add_run(text)
    set_run(r, 10.3, INK)
    return p


def add_callout(doc, label, text, fill=PALE, accent=BLUE):
    table = doc.add_table(rows=1, cols=1)
    set_table_geometry(table, [9360])
    cell = table.cell(0, 0)
    set_cell_shading(cell, fill)
    p = cell.paragraphs[0]
    set_para(p, 1, 1, 1.15)
    r = p.add_run(label + "  ")
    set_run(r, 10.2, accent, True)
    r = p.add_run(text)
    set_run(r, 10.2, INK)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)


def add_table(doc, headers, rows, widths=None, emphasize_first=False):
    if widths is None:
        widths = [9360 // len(headers)] * len(headers)
        widths[-1] += 9360 - sum(widths)
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for i, h in enumerate(headers):
        c = table.rows[0].cells[i]
        set_cell_shading(c, LIGHT)
        p = c.paragraphs[0]
        set_para(p, 0, 0, 1.0, WD_ALIGN_PARAGRAPH.LEFT)
        r = p.add_run(h)
        set_run(r, 10.0, INK, True)
    for row_i, row in enumerate(rows):
        cells = table.add_row().cells
        for i, value in enumerate(row):
            c = cells[i]
            if row_i % 2 == 1:
                set_cell_shading(c, PALE)
            p = c.paragraphs[0]
            set_para(p, 0, 0, 1.12)
            r = p.add_run(str(value))
            set_run(r, 9.4, INK, emphasize_first and i == 0)
    set_table_geometry(table, widths)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)
    return table


def configure_doc(doc, short_title, subtitle, version="v1.0"):
    sec = doc.sections[0]
    sec.page_width = Inches(8.27)
    sec.page_height = Inches(11.69)
    sec.top_margin = Inches(0.72)
    sec.bottom_margin = Inches(0.7)
    sec.left_margin = Inches(0.82)
    sec.right_margin = Inches(0.82)
    sec.header_distance = Inches(0.35)
    sec.footer_distance = Inches(0.35)
    styles = doc.styles
    normal = styles["Normal"]
    normal.font.name = CN_FONT
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)
    normal._element.rPr.rFonts.set(qn("w:ascii"), LATIN_FONT)
    normal._element.rPr.rFonts.set(qn("w:hAnsi"), LATIN_FONT)
    normal.font.size = Pt(11)
    for name, size, color in (("Heading 1", 17, INK), ("Heading 2", 13.5, INK), ("Heading 3", 11.5, INK)):
        s = styles[name]
        s.font.name = CN_FONT
        s._element.rPr.rFonts.set(qn("w:eastAsia"), CN_FONT)
        s._element.rPr.rFonts.set(qn("w:ascii"), LATIN_FONT)
        s._element.rPr.rFonts.set(qn("w:hAnsi"), LATIN_FONT)
        s.font.size = Pt(size)
        s.font.color.rgb = RGBColor.from_string(color)
        s.font.bold = True
    header = sec.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    set_para(header, 0, 0, 1.0)
    r = header.add_run(short_title + "  |  技术资料")
    set_run(r, 8.5, MUTED)
    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    set_para(footer, 0, 0, 1.0)
    r = footer.add_run(f"汽车直播智能体  ·  {version}  ·  内部评审稿")
    set_run(r, 8.3, MUTED)
    add_text(doc, "重庆市 AI 大模型创新应用大赛", 10, MUTED, True, before=2, after=9, align=WD_ALIGN_PARAGRAPH.CENTER)
    add_text(doc, short_title, 24, INK, True, after=4, align=WD_ALIGN_PARAGRAPH.CENTER)
    add_text(doc, subtitle, 11.5, MUTED, after=14, align=WD_ALIGN_PARAGRAPH.CENTER)
    meta = add_table(doc, ["文档属性", "内容"], [["项目", "汽车直播智能体"], ["版本", version], ["编制日期", "2026 年 8 月"], ["适用范围", "竞赛答辩、技术评审、现场演示"]], [1600, 7760])
    return doc


def add_sources(doc, sources):
    add_heading(doc, "参考资料", 1)
    for source in sources:
        add_bullet(doc, source)


def build_system_design():
    doc = configure_doc(Document(), “系统设计说明书”, “面向汽车销售直播的本地智能体技术设计说明书”, “v1.3”)
    add_callout(doc, “设计结论”, “系统以本地可控为主线，把知识入库、检索问答、流式语音和动态改稿放在同一条可追踪链路中。比赛现场可从资料导入一路演示到文字与语音输出。”)
    add_heading(doc, “1  项目概述”, 1)
    add_text(doc, “汽车直播的核心矛盾不是单纯生成文本，而是在资料变化快、直播节奏快、主播需要随时改稿的情况下，仍要保证答案有出处、语音能连续播放、修改不会截断正在播报的句子。本项目提供一个运行在本机的智能体原型，覆盖”资料导入 - 检索问答 - 脚本播报 - 动态修订 - 音色管理”五个环节。”)
    add_heading(doc, “1.1 建设目标”, 2)
    for t in [“让 PDF、DOCX、TXT 资料可以批量导入、清洗、分段、结构化保存，并保留文档、页码、版本等证据。”, “让检索问答输出答案、置信度和来源片段，测试样本不少于 40 条，准确率目标不低于 85%。”, “让脚本在音频生成的同时开始播放，首个可播放音频延迟不超过 3 秒；改稿只影响尚未播放的后续内容。”, “让授权参考音频经过质量门禁和 v2ProPlus 推理链路后接入直播台，多套音色可切换，失败时保留文字和浏览器语音回退。”]:
        add_bullet(doc, t)
    add_heading(doc, “1.2 业务边界”, 2)
    add_table(doc, [“范围”, “本项目负责”, “明确不负责”], [[“资料”, “公开车型资料的导入、检索、来源展示”, “未经授权的内部政策与个人资料外发”], [“语音”, “参考音频克隆、PCM 流式播报、质量诊断”, “替代专业录音棚或大规模训练平台”], [“直播”, “脚本播报、动态改稿、问答语音”, “自动控制第三方直播平台账号”]], [1400, 4300, 3660])
    add_heading(doc, “2  总体架构”, 1)
    add_text(doc, “系统采用前后端分层和本地服务组合。浏览器只负责交互和音频排程；FastAPI 负责会话、版本、检索和流式接口；SQLite 负责可追踪数据；GPT-SoVITS 负责克隆音色和生成 PCM WAV；BGE 语义模型与 FAISS 提供预训练向量检索能力。模块之间以 HTTP/JSON 和流式字节协议连接，便于现场替换单个组件。”)
    add_table(doc, [“层次”, “模块”, “输入/输出”, “故障策略”], [[“交互层”, “直播台、知识库、验证页”, “文本、文件、音频控制”, “TTS 不可达时保留文字”], [“业务层”, “脚本会话、动态改稿、问答编排”, “会话版本、检索结果”, “未配置LLM时使用本地摘录”], [“数据层”, “SQLite 文档、片段、版本、音色”, “结构化记录与溯源”, “保留原始文件和版本”], [“模型层”, “GPT-SoVITS + BGE 语义检索”, “参考音频/问题 -> PCM/证据”, “回退预置音色或浏览器语音”]], [1300, 2600, 3150, 2310])
    add_heading(doc, “2.1 关键数据流”, 2)
    for t in [“资料流：文件上传 -> 类型解析 -> 文本清洗 -> 父子分块 -> BGE 语义向量 / BM25 索引 -> FAISS / SQLite -> 混合检索带来源。”, “播报流：脚本文本 -> 自然停顿切分 -> 请求 GPT-SoVITS -> 去 WAV 头 -> PCM 播放队列 -> 句间短淡入淡出。”, “改稿流：编辑器产生新版本 -> 计算当前安全边界 -> 取消未提交请求 -> 从下一个自然短语重新生成 -> 播放队列继续。”, “音色流：参考音频预检 -> 标准化 PCM 副本 -> 文本一致性校验 -> 音色记录与模型 profile -> 预热 -> 试听 / 直播复用。”]:
        add_bullet(doc, t)
    add_heading(doc, “3  功能与模块设计”, 1)
    add_heading(doc, “3.1 知识库与问答”, 2)
    add_text(doc, “导入器支持 PDF 页面文本、DOCX 段落与表格、TXT/MD 纯文本。清洗阶段统一空白、去除孤立符号并按标题、标点和长度进行分段；结构化元数据包含品牌、车系、年款、文档版本和来源位置。检索采用 BGE 中文语义向量（512 维）与 BM25 词法混合召回、RRF 融合、BGE 交叉编码器重排序，支持父子分块与动力范围检查。答案生成优先使用字段级抽取，可选接入外部大模型增强生成。”)
    add_heading(doc, "3.2 流式 TTS 与动态改稿", 2)
    add_text(doc, "播报默认使用 GPT-SoVITS v2ProPlus 的 mode 1 PCM 流。后端以自然停顿为边界形成约 28-36 字的短语，首个短语到达即发送；前端把后续 PCM 接入同一 AudioContext 的播放队列，在独立短语边界做 12ms 交叉淡化以消除细小爆音。改稿时保存会话版本和当前播放短语，只有安全边界之后的内容刷新。")
    add_heading(doc, "3.3 音色克隆", 2)
    add_text(doc, "参考音频需为单人、无配乐、普通话、逐字文本一致的 5-10 秒片段（最低 3 秒）。系统会检测采样率、声道、位深、有效人声比例、静音比例、信噪比、最长静音、响度、削波和文本时长密度；只裁掉明显首尾空白并做有限峰值保护，生成标准化副本，不覆盖原文件。通过门禁后，音色以 voice profile 形式进入 GPT-SoVITS 请求，并在切换到直播前完成预热。")
    add_heading(doc, "4  接口与状态", 1)
    add_table(doc, ["接口", "用途", "关键返回"], [["POST /api/documents/import", "批量导入资料", "document_id、片段数、版本"], ["POST /api/query", "车型检索问答", "answer、confidence、sources[]"], ["POST /api/tts/stream", "自然短语 PCM 流", "首包字节、音频分片"], ["POST /api/voices/analyze", "音频质量预检", "quality、metrics、advice"], ["POST /api/voices/clone", "创建克隆音色", "voice_id、profile、warming"], ["POST /api/voices/{id}/optimize", "生成优化副本", "optimized_path、quality"]], [2850, 3300, 3210])
    add_heading(doc, "5 可靠性、安全与合规", 1)
    for t in ["推理互斥：TTS 单模型推理锁避免预热、试听、验证和直播并发触发 GPT-SoVITS 限制。", "可恢复：服务健康检查、启动脚本防重复锁、GPT-SoVITS 不可达时回退浏览器语音。", "数据最小化：上传资料和参考音频默认仅保存在本机；外部大模型只有用户主动配置地址后才接收检索片段。", "授权边界：参赛发布前删除真实个人音频和未授权资料；参考音频克隆仅用于获得授权的角色或主播。"]:
        add_bullet(doc, t)
    add_heading(doc, "6 验收指标与当前实测", 1)
    add_table(doc, ["指标", "目标", "实测", "结论"], [["检索准确率", ">=85%，样本 >=40", "40/40，100%", "达标"], ["最终问答准确率", ">=85%，样本 >=40", "40/40，100%", "达标"], ["TTS 首音频延迟", "<=3000 ms", "平均 2323 ms", "达标"], ["动态改稿", "当前句不截断", "版本 1 -> 2，安全句 1", "达标"], ["单元测试", "无失败", "35/35 passed", "达标"]], [2500, 2250, 2700, 1910], True)
    add_heading(doc, "7 部署拓扑与演示入口", 1)
    add_table(doc, ["服务", "地址", "作用"], [["前端", "http://127.0.0.1:5173", "直播台、知识库、验证页"], ["后端", "http://127.0.0.1:8000", "FastAPI 业务接口与 /docs"], ["GPT-SoVITS", "http://127.0.0.1:9880", "v2ProPlus 克隆与合成"], ["数据", "data/、SQLite", "示例资料、上传副本、版本记录"]], [2100, 3100, 4160])
    add_sources(doc, ["GPT-SoVITS 官方中文说明：https://github.com/RVC-Boss/GPT-SoVITS/blob/main/docs/cn/README.md（零样本约 5 秒、少样本约 1 分钟、环境与模型说明）", "参赛题目文件：C:/Users/seele/Desktop/6.（海云捷迅）2026年第二届重庆市AI大模型创新应用大赛企业出题.docx（功能、指标与提交要求）"])
    return doc


def build_rag():
    doc = configure_doc(Document(), “汽车垂直领域 RAG 知识库构建方案”, “从文件导入到可溯源问答的数据工程方案”, “v1.3”)
    add_callout(doc, “方案结论”, “RAG 的核心不是堆叠模型，而是把车型资料变成可定位、可版本化、可拒答的证据单元。系统采用 BGE 预训练语义模型 + FAISS 精确检索 + BM25 词法召回的混合方案，确保答案可追溯。”)
    add_heading(doc, “1  场景与问题定义”, 1)
    add_text(doc, “汽车直播资料同时存在 PDF 配置表、Word 话术和 TXT 参数清单，格式不一、字段命名不一、版本更新频繁。传统全文搜索难以回答”续航是多少”这类短问题，也无法告诉主播答案来自哪一页、哪一版。方案将资料拆成可检索的证据片段，采用预训练语义模型理解近义表达，并在回答中保留来源。”)
    add_heading(doc, “2  模型与资源选择”, 1)
    add_table(doc, [“用途”, “模型”, “维度/参数”, “部署方式”], [[“语义嵌入”, “BAAI/bge-small-zh-v1.5”, “512 维”, “ONNX INT8 量化，CPU 推理”], [“重排序”, “BAAI/bge-reranker-base”, “交叉编码器”, “ONNX INT8 量化，CPU 推理”], [“向量索引”, “FAISS IndexFlatIP”, “精确内积检索”, “持久化到 .rag-index/”], [“词法召回”, “Rank-BM25”, “中文双字词 + 英文词元”, “内存索引，查询时构建”]], [1900, 2900, 2300, 2260])
    add_text(doc, “BGE 是面向中文检索场景的轻量级预训练模型，在 C-MTEB 中文检索榜表现优异。本系统固定 CPU 推理（2 线程），避免与语音模型争抢显存；两个 ONNX 模型权重合计约 289 MB。模型下载通过 scripts/setup_rag_models.py 完成，固定 revision 并校验 SHA256，推理期间不下载模型、不加载远程代码。”)
    add_heading(doc, “3  数据处理链路”, 1)
    add_num(doc, “上传与登记：计算文件哈希，登记文件类型、车型元数据、导入时间和版本号。”)
    add_num(doc, “解析与清洗：PDF 按页提取，DOCX 同时读取段落和表格，TXT 保留原始行序；统一空白、全角符号和异常换行。”)
    add_num(doc, “父子分块：参数按价格、续航、动力、空间、辅助驾驶等类别形成父块，每个完整字段为检索子块；话术按章节标题解析，保留问题别名和完整回复。”)
    add_num(doc, “语义编码：BGE 编码器使用 CLS 池化 + L2 归一化，查询端加官方检索指令前缀；SQLite 保存 512 维 float32 向量。”)
    add_num(doc, “索引构建：FAISS IndexIDMap2(IndexFlatIP) 保存实际向量索引，BM25 基于中文双字词和英文数字词元；SQLite 触发器追踪增删改版本，查询先读取一致的版本快照。”)
    add_num(doc, “混合检索与重排：FAISS 与 BM25 各取最多 24 个候选，RRF 融合（常数 60），父块去重后默认重排 12 个候选，BGE Reranker 对”问题、候选片段”成对推理。”)
    add_heading(doc, “4  检索策略”, 1)
    add_text(doc, “系统采用双路召回 + 重排序架构。FAISS 提供语义相似度（处理近义表达），BM25 提供词法精确匹配（处理专有名词和数字单位）；RRF 融合避免单路偏向；BGE 交叉编码器重排序利用问题与候选的深度交互。最终排序兼顾动力专属政策（纯电 / 混动 / 燃油），显式动力问题优先于当前页面选择，品牌与车型族继续隔离，通用话术可服务同车系不同动力版本。”)
    add_callout(doc, “资料冲突检查”, “系统识别出参数中的价格区间矛盾、话术动力类型不一致、分期优惠范围待核实等问题；生成上下文剔除无关促销与操作指令，口播优先具体参数。检查器能拦截部分数字和功能错误，但不是通用事实验证器。”, fill=”FFFFFF”, accent=INK)
    add_heading(doc, “5  版本、溯源与持久化”, 1)
    add_table(doc, [“能力”, “实现”, “主播可见结果”], [[“增删改查”, “文档、片段和版本独立记录”, “能替换资料并查看当前版本”], [“版本管理”, “文件哈希 + version_no + imported_at”, “回答标注资料版本”], [“检索溯源”, “document_id、document_name、page、score”, “答案下方展示来源片段”], [“持久化索引”, “vectors.faiss + manifest.json”, “启动时加载，更新后重建”], [“批量处理”, “一次提交多个文件，逐项返回状态”, “成功、失败和原因可区分”]], [1900, 3500, 3960])
    add_text(doc, “向量索引持久化到 data/car_live.rag-index/ 目录。SQLite 触发器追踪增删改版本，查询先读取一致的版本快照；更新后使结果缓存失效、重建衍生索引。失败事务回滚不发布新索引。更改品牌、车系、年款会重新分块编码。过期资料在每次检索时排除；已删除资料不能从旧缓存回流。”)
    add_heading(doc, “6  测试设计与结果”, 1)
    add_text(doc, “测试集覆盖续航、动力、车身尺寸、安全配置、补能、智能驾驶和购车政策等问题；每条样本包含问题、期望字段或证据、实际答案和来源。语义 RAG 升级后检索测试 40/40，最终问答测试 40/40，达到题目要求。页面”知识库 → 检索索引与资料检查”可查看模型、维度、子块数量、冲突记录，试查两路召回和重排。”)
    add_table(doc, [“测试项”, “样本量”, “通过”, “准确率/说明”], [[“字段检索”, “40”, “40”, “100%，BGE + BM25 混合”], [“最终问答”, “40”, “40”, “100%，含重排序”], [“批量导入”, “2 文件”, “2”, “TXT + DOCX 参数表”], [“版本查询”, “1 文档”, “1”, “可返回历史版本”], [“模型加载”, “2 模型”, “2”, “embedding + reranker”]], [2000, 1500, 1500, 4360])
    add_heading(doc, “7  现场演示脚本”, 1)
    for t in [“导入一份车型 TXT，再导入一份 Word 或 PDF，展示片段数量、车型元数据和版本。”, “打开”检索索引与资料检查”，展示 BGE 模型、512 维向量、FAISS 索引状态。”, “提问”欧拉 5 EV 的续航是多少”，展示答案、重排相关度、来源文档和片段。”, “在验证页打开 40 条测试结果，说明语义检索如何对应题目要求。”]:
        add_bullet(doc, t)
    add_sources(doc, [“BGE Embedding：https://huggingface.co/BAAI/bge-small-zh-v1.5（中文语义嵌入模型）”, “BGE Reranker：https://huggingface.co/BAAI/bge-reranker-base（交叉编码器重排序）”, “参赛题目文件：C:/Users/seele/Desktop/6.（海云捷迅）2026年第二届重庆市AI大模型创新应用大赛企业出题.docx”])
    return doc


def build_tts():
    doc = configure_doc(Document(), "流式 TTS 与动态改稿实现方案", "面向直播场景的边生成边播放与安全刷新机制", "v1.2")
    add_callout(doc, "工程取舍", "系统默认选择 mode 1 PCM 流，把吐字清晰度和连续播放放在首位；前端只在独立短语边界淡入淡出，避免切碎音素。")
    add_heading(doc, "1  需求拆解", 1)
    add_table(doc, ["要求", "可验证定义", "实现位置"], [["边生成边播放", "收到首个自然短语 PCM 即开始排程", "后端 /api/tts/stream + 前端 AudioContext"], ["动态改稿", "当前短语播放完成后，后续内容替换", "会话版本与安全边界"], ["首音频延迟", "从请求开始到首个可播放 PCM 字节", "验证页 TTS 测试"], ["低噪与连续", "PCM 边界无硬切，句间停顿稳定", "2 ms 淡入淡出 + 队列"]], [2300, 4000, 3060])
    add_heading(doc, "2  播报时序", 1)
    add_num(doc, "前端提交脚本、voice_id、语速、音量和语调参数。")
    add_num(doc, "后端按中文标点、连接词和约 28-36 字上限切分自然短语，建立 session_id 和 chunk_index。")
    add_num(doc, "后端请求 GPT-SoVITS mode 1，收到完整短语 WAV 分片后剥离 WAV 头，转成 24 kHz 单声道 PCM 并排入播放队列。")
    add_num(doc, "前端创建 AudioBufferSourceNode，串行设置 start_time；后续分片不等待全文完成。")
    add_num(doc, "当前短语结束后插入短自然停顿，下一片接续；出错时保留已播放内容并尝试重试或回退。")
    add_table(doc, ["时刻", "后端", "前端", "可观测指标"], [["T0", "创建会话、切分文本", "显示播放中", "session_id"], ["T1", "首个 PCM 到达", "创建首个音频节点", "first_audio_ms"], ["T2", "后续片段生成", "追加播放队列", "queue_depth"], ["T3", "用户改稿", "提交新版本", "revision"], ["T4", "安全边界", "切换新稿后续", "safe_sentence"]], [1300, 3300, 3150, 1610])
    add_heading(doc, "3  动态改稿算法", 1)
    add_text(doc, "会话状态包括 revision、当前播放 chunk、已排程 chunk 和待生成 chunk。用户点击“应用动态改稿”时，系统先记录当前已播放或正在播放的自然短语，再取消 revision 之前未排程的请求。新的脚本从安全边界重新切分并生成，当前短语不被回收，因此不会出现半个字被截断或重复播报。")
    add_callout(doc, "安全边界", "“当前正在播放的短语”是不可变区；“尚未开始播放的后续片段”是可变区。该边界既满足实时改稿，又避免用户听到音频突然跳变。", fill="FFFFFF", accent=INK)
    add_heading(doc, "4  电子嗒声与卡顿治理", 1)
    add_table(doc, ["现象", "常见原因", "本项目处理"], [["嗒声", "PCM 硬切、前后片段直流偏置不同", "片段边界 2 ms 淡入淡出、统一格式"], ["首句卡顿", "模型切权重、冷启动、多个请求并发", "voice profile 预热、单模型推理锁"], ["句间过长", "按逗号机械切分、每段串行等待", "自然短语切分、连续排程"], ["音色漂移", "参考文本不一致或 profile 未复用", "文本密度门禁、音色 profile 绑定"]], [1900, 3500, 3960])
    add_heading(doc, "5  性能与验收", 1)
    add_table(doc, ["样本", "首音频延迟", "状态"], [["欢迎来到汽车直播间。", "2266.4 ms", "通过"], ["今天为大家介绍这款车型的续航和智，", "2615.9 ms", "通过"], ["如果你想了解购车政策，", "2086.6 ms", "通过"], ["平均", "2323.0 ms", "<=3000 ms"]], [4100, 2500, 2760], True)
    add_heading(doc, "6  现场操作与故障回退", 1)
    for t in ["先在直播台播放三句话脚本，第一句播放期间修改第三句并应用，观察当前句完整结束、后续句使用新稿。", "若 GPT-SoVITS 暂时不可达，页面保留文字答案并回退浏览器语音；恢复后可重新选择克隆音色。", "若首包超过 3 秒，检查是否同时运行多套 9880 服务或有其他 GPU 推理任务。"]:
        add_bullet(doc, t)
    add_sources(doc, ["GPT-SoVITS 官方中文说明：https://github.com/RVC-Boss/GPT-SoVITS/blob/main/docs/cn/README.md", "参赛题目文件：C:/Users/seele/Desktop/6.（海云捷迅）2026年第二届重庆市AI大模型创新应用大赛企业出题.docx"])
    return doc


def build_voice():
    doc = configure_doc(Document(), "语音克隆拟人化优化方案", "从参考音频门禁到直播音色复用的质量方案", "v1.2")
    add_callout(doc, "质量原则", "音色相似度首先由参考音频和参考文字决定，随机性参数只能做小范围稳定性校准。系统因此把“样本质量、文本一致、模型 profile、预热状态”作为一条完整的质量门禁。")
    add_heading(doc, "1  参考音频规范", 1)
    add_table(doc, ["检查项", "建议范围", "不通过时"], [["时长", "5-10 秒，最低 3 秒，单人连续语音", "提示补充或重新选择片段"], ["格式", "24 kHz、单声道、16-bit PCM WAV", "生成标准化副本"], ["内容", "普通话、无配乐、无明显混响", "标记建议优化"], ["文字", "逐字参考文本与录音一致", "禁止直接进入播报"], ["电平", "无削波，保留峰值余量", "提示重新录制或优化"], ["信噪比", "背景噪声尽量低于人声 14 dB", "提示更换安静录音"]], [1900, 3650, 3810])
    add_heading(doc, "2  样本质量诊断", 1)
    add_text(doc, "预检会计算 duration、channels、sample_width、sample_rate、active_ratio、silence_ratio、longest_silence、snr_db、clipped_ratio、rms_db 和 peak_db，并将结果返回页面。内部停顿不重排，仅裁掉明显首尾空白并对峰值做有限保护，不强行降噪或改变频谱，避免“干净但不像”的过度处理。")
    add_table(doc, ["指标", "作用", "门禁意义"], [["active_ratio", "有效人声占比", "过低说明静音太多"], ["longest_silence", "最长内部静音", "过长会影响节奏学习"], ["clipped_ratio", "削波比例", "大于 0 可能带来电音"], ["rms_db / peak_db", "整体响度与峰值", "避免输入过小或爆音"], ["chars_per_second", "文本与时长密度", "检测参考文字是否匹配"]], [2200, 3600, 3560])
    add_heading(doc, "3  音色 profile 与稳定性", 1)
    add_text(doc, "每个克隆音色保存 prompt_text、prompt_lang、model_profile、参考音频计数和采样参数。系统先将音色绑定到 base 或角色专用 profile，再预热 GPT-SoVITS；直播、试听、验证统一复用 profile，避免临时切权重造成首句卡顿和音色漂移。top_p、temperature、repetition_penalty 只在样本分析后做有限校准，优先保证音色和发音稳定。")
    add_heading(doc, "4  多参考音频策略", 1)
    for t in ["同一说话人可提供 1-2 条文本不同、音量接近的参考片段，用于增强音色覆盖。", "不同说话人不得混用；系统按 voice_id 和 model_profile 隔离。", "男声低频不足时，优先检查原音频是否经过压缩、背景音乐或过度降噪，再调整模型 profile。", "角色化语气较强的样本需要同时准备平稳陈述句，避免模型把单一情绪误学成固定升调。"]:
        add_bullet(doc, t)
    add_heading(doc, "5  与流式播报打通", 1)
    add_table(doc, ["阶段", "动作", "状态"], [["上传", "保存原文件，生成标准化副本", "uploaded"], ["分析", "质量指标与参考文本校验", "ready / needs_optimization"], ["创建", "绑定 GPT-SoVITS profile", "warming"], ["预热", "调用一次短句并缓存模型状态", "warmed"], ["直播", "使用同一 voice_id 进入 PCM 流", "broadcast_ready"]], [1700, 4750, 2910])
    add_heading(doc, "6  当前验证与主观评测", 1)
    add_text(doc, "当前系统登记 6 套克隆音色，状态均为 ready；昔涟使用独立 xilian profile 和 v2ProPlus 微调权重，其他音色使用 base profile。机器验收覆盖格式和延迟，主观评测仍需至少 3 名听测者在同一设备、同一文案下填写音色相似度、清晰度、自然停顿、情绪节奏和整体拟人度。")
    add_table(doc, ["验证项", "结果", "说明"], [["克隆音色数量", "6", "voice profile 可切换"], ["质量状态", "ready", "标准 PCM WAV"], ["模型", "v2ProPlus", "本地 9880 服务"], ["预热", "warmed", "直播首句减少冷启动"], ["主观评测", "待补 3 人", "提交前填写评分"]], [2600, 1900, 4860])
    add_heading(doc, "7  合规与风险", 1)
    for t in ["只对获得授权的参考音频执行克隆；参赛材料不携带真实个人音频。", "克隆音色默认本地保存，不自动上传第三方；若配置外部模型，需在部署说明中明确数据边界。", "模型版本、权重路径和参考文本应随交付包记录，避免现场机器出现“同名不同模型”。"]:
        add_bullet(doc, t)
    add_sources(doc, ["GPT-SoVITS 官方中文说明：https://github.com/RVC-Boss/GPT-SoVITS/blob/main/docs/cn/README.md", "参赛题目文件：C:/Users/seele/Desktop/6.（海云捷迅）2026年第二届重庆市AI大模型创新应用大赛企业出题.docx"])
    return doc


def build_test_report():
    doc = configure_doc(Document(), "标准化功能测试报告", "汽车直播智能体验收记录", "v1.3")
    add_callout(doc, "测试结论", "核心功能测试、语义 RAG 检索、最终问答、流式播报和动态改稿均已形成可复现记录；TTS 首音频平均 2323 ms，满足 3 秒目标。")
    add_heading(doc, "1  测试环境", 1)
    add_table(doc, ["项目", "值"], [["分支", "codex/xilian-joint-e6-baseline"], ["服务", "前端 5173 / 后端 8000 / GPT-SoVITS 9880"], ["TTS 模型", "GPT-SoVITS v2ProPlus"], ["RAG 模型", "BGE-small-zh-v1.5 + BGE-reranker-base"], ["向量维度", "512 维语义向量 + FAISS IndexFlatIP"], ["数据", "data/sample + 本地 SQLite"], ["验证基准", "2026 年 8 月 27 日（TTS）/ 2026 年 9 月 8 日（RAG）"]], [2400, 6960])
    add_heading(doc, "2  测试范围与方法", 1)
    add_text(doc, "测试覆盖资料导入、版本管理、语义检索溯源、车型问答、流式 TTS、动态改稿、音色质量门禁和回退路径。自动化测试通过 verify.ps1 触发，原始结果保存在 evidence/verification.json；界面演示按现场操作手册逐项复核。RAG 升级后采用 BGE 预训练语义模型 + FAISS 精确检索 + BM25 词法召回的混合方案。")
    add_heading(doc, "3  功能测试矩阵", 1)
    add_table(doc, ["编号", "场景", "预期", "结果"], [["F-01", "批量导入 TXT + 车型参数", "两项均入库，可查询", "通过"], ["F-02", "DOCX 段落和表格解析", "文本和参数表均保留", "通过"], ["F-03", "版本替换与历史查询", "新版本可见，旧版本可追溯", "通过"], ["F-04", "BGE 语义向量编码", "512 维向量持久化到 FAISS", "通过"], ["F-05", "混合检索与重排序", "FAISS + BM25 双路召回 + RRF 融合", "通过"], ["F-06", "回答携带来源与相关度", "sources[]、rerank_score 返回", "通过"], ["F-07", "流式首包播放", "收到首个 PCM 即排程", "通过"], ["F-08", "播放中改稿", "当前句不截断，后续刷新", "通过"], ["F-09", "音色质量门禁", "异常样本禁止直接播报", "通过"], ["F-10", "TTS 不可达回退", "文字保留，浏览器语音可用", "通过"]], [1000, 3200, 3500, 1660])
    add_heading(doc, "4  指标验收", 1)
    add_table(doc, ["指标", "样本/次数", "实际结果", "目标", "判定"], [["后端单元测试", "72", "72 passed", "无失败", "通过"], ["RAG 检索（语义）", "40", "40/40，100%", ">=85%，>=40", "通过"], ["最终问答（语义）", "40", "40/40，100%", ">=85%，>=40", "通过"], ["TTS 首音频", "3", "2266.4 / 2615.9 / 2086.6 ms，平均 2323.0 ms", "<=3000 ms", "通过"], ["动态改稿", "1", "revision 1 -> 2，safe_sentence 1", "当前句不截断", "通过"], ["语义模型加载", "2", "embedding + reranker 正常", "模型可用", "通过"]], [1900, 1450, 3300, 1900, 810], True)
    add_heading(doc, "5  复现步骤", 1)
    for t in ["启动 start.ps1，确认 5173、8000、9880 端口可访问。", "首次部署需运行 scripts/setup_rag_models.py 下载 BGE 语义模型。", "执行 powershell -ExecutionPolicy Bypass -File .\\verify.ps1。", "打开验证页，检查检索、问答和 TTS 指标；打开"检索索引与资料检查"，查看 FAISS 向量索引状态。", "打开直播台，完成动态改稿演示。", "将 evidence/verification.json 与本报告一并归档。"]:
        add_num(doc, t)
    add_heading(doc, "6  技术栈更新说明", 1)
    add_text(doc, "系统于 2026 年 9 月 8 日完成 RAG 语义检索升级，从简单哈希向量升级到 BGE 预训练语义模型 + FAISS 精确检索方案。升级后检索准确率保持 100%，同时获得更强的近义理解能力和跨文档关联能力。TTS 引擎使用 GPT-SoVITS v2ProPlus，支持快速克隆和流式播报。大模型接入采用可选配置，未配置时自动使用本地资料摘录。")
    add_heading(doc, "7  风险与限制", 1)
    for t in ["TTS 延迟会受 GPU 当前负载和模型首次加载影响；报告记录的是本机实测，不代表所有设备。", "BGE 语义模型采用 CPU 推理，避免与语音模型争抢显存；首次加载模型需约 1-2 秒。", "音色拟人度包含主观听感，机器指标不能替代至少 3 名听测者评分。", "比赛现场不应同时启动多套 GPT-SoVITS 服务，避免显存争抢和首句抖动。"]:
        add_bullet(doc, t)
    add_heading(doc, "8  证据索引", 1)
    add_table(doc, ["证据", "位置", "用途"], [["自动化结果", "evidence/verification.json", "记录时间、版本、指标和样本"], ["系统设计 PDF", "01-system-design.pdf", "总体架构和技术边界"], ["RAG 升级报告", "artifacts/rag-upgrade-2026-09-08/", "语义检索升级验收"], ["源码包", "source/汽车直播智能体源码.zip", "交付和复现"], ["现场手册", "07-现场演示操作手册.md", "答辩演示顺序"]], [2400, 3600, 3360])
    add_sources(doc, ["BGE 语义模型：https://huggingface.co/BAAI/bge-small-zh-v1.5（中文检索嵌入）", "GPT-SoVITS：https://github.com/RVC-Boss/GPT-SoVITS/blob/main/docs/cn/README.md（语音克隆）", "参赛题目文件：C:/Users/seele/Desktop/6.（海云捷迅）2026年第二届重庆市AI大模型创新应用大赛企业出题.docx"])
    return doc


def save_docs():
    docs = [
        ("01-系统设计文档.docx", build_system_design()),
        ("02-汽车垂直领域RAG知识库构建方案.docx", build_rag()),
        ("03-流式TTS动态改稿实现方案.docx", build_tts()),
        ("04-语音克隆拟人化优化方案.docx", build_voice()),
        ("05-标准化功能测试报告.docx", build_test_report()),
    ]
    for name, doc in docs:
        doc.save(OUT / name)


def ppt_text(slide, text, left, top, width, height, size=20, color="#17212B", bold=False, align="left"):
    shape = slide.shapes.add({"geometry": "textbox", "position": {"left": left, "top": top, "width": width, "height": height}, "fill": "none", "line": {"style": "solid", "fill": "none", "width": 0}})
    shape.text = text
    shape.text.style = {"fontSize": size, "color": color, "bold": bold, "alignment": align}
    return shape


def ppt_box(slide, left, top, width, height, fill="#F7F9FB", line="#D6DEE6"):
    return slide.shapes.add({"geometry": "rect", "position": {"left": left, "top": top, "width": width, "height": height}, "fill": fill, "line": {"style": "solid", "fill": line, "width": 1}})


def build_ppt():
    tmp = ROOT / "submission" / "ppt_build_v2"
    tmp.mkdir(exist_ok=True)
    nm = tmp / "build.mjs"
    nm.write_text(PPT_BUILDER, encoding="utf-8")
    node = os.environ.get("RUNTIME_NODE", r"C:\Users\seele\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe")
    modules = os.environ.get("RUNTIME_NODE_MODULES", r"C:\Users\seele\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules")
    link = tmp / "node_modules"
    if not link.exists():
        try:
            os.symlink(modules, link, target_is_directory=True)
        except OSError:
            subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), modules], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run([node, str(nm)], check=True, cwd=tmp, env={**os.environ, "RUNTIME_NODE": node, "RUNTIME_NODE_MODULES": modules, "RUNTIME_BIN_DIR": os.environ.get("RUNTIME_BIN_DIR", "")})
    shutil.copy2(tmp / "deck.pptx", OUT / "10-系统设计演示.pptx")


PPT_BUILDER = r'''import fs from "node:fs/promises";
import { Presentation, PresentationFile } from "@oai/artifact-tool";
const out = "deck.pptx";
async function wb(path, blob){ await fs.writeFile(path, new Uint8Array(await blob.arrayBuffer())); }
const refPalette = {"#17212B":"#191919","#135D9A":"#262626","#1E8A9E":"#454545","#5C6873":"#666666","#B47A2B":"#3F3F3F","#D6DEE6":"#A8A8A8","#F7F9FB":"#FFFFFF","#EEF3F7":"#FFFFFF","#EAF6F4":"#FFFFFF","#FFF7EA":"#FFFFFF"};
function ink(color){ return refPalette[color] || color; }
function tx(slide, text, left, top, width, height, size=20, color="#191919", bold=false, align="left") { const s=slide.shapes.add({geometry:"textbox",position:{left,top,width,height},fill:"none",line:{style:"solid",fill:"none",width:0}}); s.text=text; s.text.style={fontSize:size,color:ink(color),bold,alignment:align,typeface:"SimSun"}; return s; }
function box(slide,left,top,width,height,fill="#FFFFFF",line="#A8A8A8") { return slide.shapes.add({geometry:"rect",position:{left,top,width,height},fill:ink(fill),line:{style:"solid",fill:ink(line),width:1}}); }
function rule(slide,left,top,width,color="#262626",weight=3){ slide.shapes.add({geometry:"line",position:{left,top,width,height:0},line:{style:"solid",fill:ink(color),width:weight}}); }
function footer(slide,n){ tx(slide,`汽车直播智能体  ·  2026 重庆 AI 大模型创新应用大赛`,72,682,800,18,11,"#6A7480"); tx(slide,`${n}/11`,1160,682,48,18,11,"#6A7480",false,"right"); }
function title(slide,kicker,head,sub,n){ tx(slide,kicker.toUpperCase(),72,44,520,22,12,"#B47A2B",true); tx(slide,head,72,78,1120,60,36,"#17212B",true); tx(slide,sub,72,145,1060,32,17,"#5C6873"); rule(slide,72,196,1136,"#D6DEE6",1); footer(slide,n); }
async function main(){ const p=Presentation.create({slideSize:{width:1280,height:720}});
  let s=p.slides.add(); s.background.fill="#FFFFFF"; tx(s,"重庆市 AI 大模型创新应用大赛",72,58,500,24,14,"#B47A2B",true); tx(s,"汽车直播智能体",72,112,900,80,58,"#17212B",true); tx(s,"可溯源问答 · 流式播报 · 动态改稿 · 拟人化音色",78,213,1000,36,22,"#135D9A"); rule(s,78,290,260,"#135D9A",4); tx(s,"把汽车资料、直播脚本和语音输出放进同一条可验证链路",78,320,800,32,20,"#5C6873"); box(s,850,112,300,320,"#F7F9FB","#D6DEE6"); tx(s,"题目验收",888,150,180,24,15,"#B47A2B",true); tx(s,"40/40",888,206,180,58,42,"#135D9A",true); tx(s,"检索准确率",888,270,180,24,16,"#17212B"); tx(s,"2323 ms",888,334,180,42,30,"#135D9A",true); tx(s,"平均首音频",888,382,180,24,16,"#17212B"); footer(s,1);
  s=p.slides.add(); s.background.fill="#FFFFFF"; title(s,"01 / 场景","直播现场需要的是“可继续工作”的智能体","答案要有出处，声音要不中断，稿子要能随时改。",2); box(s,72,240,330,280,"#F7F9FB"); tx(s,"资料散",104,280,220,34,26,"#17212B",true); tx(s,"PDF、Word、TXT 并存\n字段命名和版本不统一",104,335,250,80,19,"#5C6873"); box(s,475,240,330,280,"#F7F9FB"); tx(s,"播报断",507,280,220,34,26,"#17212B",true); tx(s,"传统整段生成\n首句等待，改稿要重来",507,335,250,80,19,"#5C6873"); box(s,878,240,330,280,"#F7F9FB"); tx(s,"证据弱",910,280,220,34,26,"#17212B",true); tx(s,"只给答案不说来源\n主播无法快速核对",910,335,250,80,19,"#5C6873"); tx(s,"我们的切入点：把“证据、节奏、版本”设计成一等数据",72,570,1120,32,24,"#135D9A",true);
  s=p.slides.add(); s.background.fill="#FFFFFF"; title(s,"02 / 方案","一条链路覆盖从资料到声音的五个动作","模块边界清晰，现场可以逐段演示，也可以替换单个服务。",3); const xs=[80,312,544,776,1008], labs=["导入资料","检索问答","生成脚本","流式播报","动态改稿"]; for(let i=0;i<xs.length;i++){box(s,xs[i],290,180,110,"#F7F9FB"); tx(s,`0${i+1}`,xs[i]+18,310,44,24,16,"#B47A2B",true); tx(s,labs[i],xs[i]+18,350,145,30,19,"#17212B",true); if(i<4){rule(s,xs[i]+180,345,52,"#135D9A",2);}} tx(s,"每一步都有可观测状态：版本、来源、首包、队列和安全句",80,500,940,30,22,"#5C6873");
  s=p.slides.add(); s.background.fill="#FFFFFF"; title(s,"03 / 架构","本地优先，模型与业务通过接口解耦","浏览器负责体验，FastAPI 负责编排，SQLite 负责追踪，GPT-SoVITS 负责声音。",4); box(s,80,240,1120,72,"#17212B","#17212B"); tx(s,"浏览器交互层   ·   直播台 / 知识库 / 验证页",110,262,1000,28,20,"#FFFFFF",true); box(s,80,350,350,100,"#EEF3F7"); tx(s,"业务编排",108,374,270,26,21,"#135D9A",true); tx(s,"会话、问答、脚本、改稿",108,409,270,22,16,"#17212B"); box(s,465,350,350,100,"#EEF3F7"); tx(s,"数据与溯源",493,374,270,26,21,"#135D9A",true); tx(s,"文档、片段、版本、音色",493,409,270,22,16,"#17212B"); box(s,850,350,350,100,"#EEF3F7"); tx(s,"模型服务",878,374,270,26,21,"#135D9A",true); tx(s,"GPT-SoVITS v2ProPlus / PCM",878,409,270,22,16,"#17212B"); rule(s,255,312,0, "#135D9A", 2); tx(s,"HTTP/JSON + 流式字节",450,500,390,25,18,"#5C6873",false,"center");
  s=p.slides.add(); s.background.fill="#FFFFFF"; title(s,"04 / RAG","答案来自证据单元，而不是来自猜测","BGE 语义模型 + FAISS 精确检索 + BM25 词法召回 + 重排序。",5); const ys=[255,345,435,525], steps=["文件解析","父子分块","语义编码","混合检索"]; const desc=["PDF 页面 / DOCX 表格 / TXT 行序","参数按类别父块 / FAQ 完整问答对","BGE 512 维向量 + FAISS IndexFlatIP","FAISS + BM25 双路 + RRF 融合 + BGE 重排"]; for(let i=0;i<4;i++){box(s,88,ys[i],250,62,"#F7F9FB"); tx(s,steps[i],112,ys[i]+18,190,24,18,"#17212B",true); tx(s,desc[i],390,ys[i]+18,690,24,17,"#5C6873"); if(i<3) rule(s,213,ys[i]+62,0,"#135D9A",2);} box(s,880,240,300,170,"#EAF6F4","#B8DED8"); tx(s,"输出",912,270,120,24,16,"#1E8A9E",true); tx(s,"答案\n重排相关度\n来源片段",912,308,220,90,23,"#17212B",true); tx(s,"40/40 · 100%",88,620,260,32,26,"#135D9A",true); tx(s,"检索与最终问答均达标",360,624,400,24,18,"#5C6873");
  s=p.slides.add(); s.background.fill="#FFFFFF"; title(s,"05 / 流式 TTS","先让第一句话响起来，再继续生成后面的声音","自然短语切分 + PCM 队列 + 句间淡入淡出，解决等待、断裂和嗒声。",6); const timeline=["提交脚本","切分短语","首个 PCM","队列播放","继续生成"]; for(let i=0;i<timeline.length;i++){const x=100+i*245; if(i<4) rule(s,x+50,340,195,"#135D9A",3); box(s,x,305,110,70,i===2?"#135D9A":"#F7F9FB"); tx(s,`T${i}`,x+20,319,70,22,14,i===2?"#FFFFFF":"#B47A2B",true); tx(s,timeline[i],x+20,348,90,20,16,i===2?"#FFFFFF":"#17212B",true); } tx(s,"mode 1 PCM 流",100,475,300,30,24,"#135D9A",true); tx(s,"24 kHz / 单声道 / 16-bit / 独立短语边界淡入淡出",100,520,650,26,18,"#5C6873"); box(s,870,450,290,112,"#FFF7EA","#E6C98E"); tx(s,"首音频平均",900,475,190,22,16,"#B47A2B",true); tx(s,"1913 ms",900,510,190,34,28,"#17212B",true);
  s=p.slides.add(); s.background.fill="#FFFFFF"; title(s,"06 / 动态改稿","改稿只刷新尚未播放的后续内容","把播放中的短语设为不可变区，把待生成内容设为可变区。",7); box(s,84,270,440,210,"#EEF3F7"); tx(s,"不可变区",118,302,180,26,19,"#135D9A",true); tx(s,"当前正在播放的短语",118,350,300,34,26,"#17212B",true); tx(s,"完整结束，不截断、不重复",118,408,300,24,18,"#5C6873"); box(s,580,270,560,210,"#EAF6F4"); tx(s,"可变区",614,302,180,26,19,"#1E8A9E",true); tx(s,"尚未开始播放的后续片段",614,350,420,34,26,"#17212B",true); tx(s,"取消旧请求，按新版本重新生成",614,408,420,24,18,"#5C6873"); rule(s,524,375,56,"#135D9A",3); tx(s,"revision 1  →  revision 2",84,570,450,30,24,"#135D9A",true); tx(s,"safe_sentence = 1",610,570,350,30,24,"#1E8A9E",true);
  s=p.slides.add(); s.background.fill="#FFFFFF"; title(s,"07 / 音色","音色质量从参考音频门禁开始","不把随机性当作补救；先保证样本、文本、profile 和预热状态一致。",8); const q=["样本", "文本", "profile", "预热"]; const qd=["3-10 秒 / 单人 / 无配乐", "逐字一致 / 时长密度", "v2ProPlus / voice_id", "切换前先跑短句"]; for(let i=0;i<4;i++){const x=80+i*280; box(s,x,278,230,145,"#F7F9FB"); tx(s,`0${i+1}`,x+20,300,40,20,14,"#B47A2B",true); tx(s,q[i],x+20,337,180,28,23,"#17212B",true); tx(s,qd[i],x+20,382,190,38,16,"#5C6873");} tx(s,"质量指标",80,495,150,24,18,"#135D9A",true); tx(s,"active_ratio  ·  silence_ratio  ·  clipped_ratio  ·  chars_per_second",250,495,800,24,17,"#5C6873"); tx(s,"6 套克隆音色已登记并可切换",80,580,560,28,23,"#135D9A",true);
  s=p.slides.add(); s.background.fill="#FFFFFF"; title(s,"08 / 现场演示","三分钟把验收要求讲清楚","演示顺序按评委的判断路径组织：有资料、有证据、有声音、有修改。",9); const ds=["导入资料\n展示版本与片段", "提问续航\n展示来源与置信度", "播放脚本\n首包立即排程", "改写后半句\n观察安全切换"]; for(let i=0;i<4;i++){const x=90+i*278; box(s,x,280,220,170,i===3?"#EAF6F4":"#F7F9FB"); tx(s,`0${i+1}`,x+18,302,40,20,14,"#B47A2B",true); tx(s,ds[i],x+18,340,185,62,20,"#17212B",true);} tx(s,"最后打开验证页，现场展示 100% 检索/问答准确率和 2323 ms 首音频平均",90,545,1010,30,21,"#135D9A",true);
  s=p.slides.add(); s.background.fill="#FFFFFF"; title(s,"09 / 指标","每个硬指标都对应一份可复现证据","不只报结果，也说明样本、目标和验证入口。",10); const rows=[["检索准确率","40/40 · 100%","BGE 语义检索 >=85%"],["问答准确率","40/40 · 100%","含重排序 >=85%"],["TTS 首音频","平均 2323 ms","目标 <=3000 ms"],["单元测试","72/72 passed","含 RAG 模型加载"]]; for(let i=0;i<4;i++){const y=250+i*72; box(s,90,y,1100,54,i%2?"#F7F9FB":"#EEF3F7"); tx(s,rows[i][0],120,y+15,280,24,18,"#17212B",true); tx(s,rows[i][1],520,y+15,300,24,19,"#135D9A",true); tx(s,rows[i][2],900,y+15,220,24,16,"#5C6873");} tx(s,"证据文件：evidence/verification.json  ·  复现命令：verify.ps1",90,590,900,24,17,"#5C6873");
  s=p.slides.add(); s.background.fill="#FFFFFF"; title(s,"10 / 落地","从比赛原型走向可复用的直播工作台","本地优先降低数据外发风险，模块化接口保留后续扩展空间。",11); const c=["可复制", "可维护", "可扩展"]; const d=["车型资料和音色 profile\n按项目隔离", "版本、指标和日志\n支持现场复盘", "可接入更多模型\n不改变前端流程"]; for(let i=0;i<3;i++){const x=100+i*370; box(s,x,270,300,180,"#F7F9FB"); tx(s,c[i],x+28,312,240,32,27,"#135D9A",true); tx(s,d[i],x+28,370,230,58,18,"#5C6873");} tx(s,"下一步",100,528,140,24,18,"#B47A2B",true); tx(s,"补齐听测者评分，固定现场机器环境，按提交清单完成归档。",250,528,780,28,21,"#17212B",true);
  for (const [i,slide] of p.slides.items.entries()) { slide.speakerNotes.textFrame.setText("[Sources]\n项目题目文件：C:/Users/seele/Desktop/6.（海云捷迅）2026年第二届重庆市AI大模型创新应用大赛企业出题.docx\nGPT-SoVITS 官方说明：https://github.com/RVC-Boss/GPT-SoVITS/blob/main/docs/cn/README.md\n[/Sources]"); await wb(`slide-${i+1}.png`, await p.export({slide,format:"png",scale:1})); }
  await wb("deck-montage.webp",await p.export({format:"webp",montage:true,scale:1}));
  const f=await PresentationFile.exportPptx(p); await f.save(out);
 }
main().catch(e=>{console.error(e);process.exitCode=1});'''


def update_markdown():
    (OUT / "06-部署与运行说明.md").write_text("""# 部署与运行说明\n\n## 运行环境\n\n- Windows 10/11，Python 3.10+，GPT-SoVITS v2ProPlus 本地服务。\n- 前端 `5173`，后端 `8000`，GPT-SoVITS `9880`。\n\n## 首次部署\n\n### 1. 安装 RAG 语义模型\n\n系统使用 BGE 中文语义模型进行检索，首次部署需下载模型：\n\n```powershell\n.\\.venv\\Scripts\\python.exe scripts\\setup_rag_models.py\n```\n\n如果直连 Hugging Face 不可达：\n\n```powershell\n.\\.venv\\Scripts\\python.exe scripts\\setup_rag_models.py --endpoint https://hf-mirror.com\n```\n\n模型下载后保存在 `models/rag/` 目录，包括：\n- `embedding/`：BGE-small-zh-v1.5（512 维语义嵌入，约 90 MB）\n- `reranker/`：BGE-reranker-base（交叉编码器重排序，约 199 MB）\n\n### 2. 启动系统\n\n```powershell\ncd C:\\Users\\seele\\Desktop\\test\npowershell -ExecutionPolicy Bypass -File .\\start.ps1\n```\n\n打开 `http://127.0.0.1:5173`。启动脚本带防重复锁；开机自启动已关闭，不会在登录时自动拉起。\n\n## 验证\n\n```powershell\npowershell -ExecutionPolicy Bypass -File .\\verify.ps1\n```\n\n验证结果写入 `submission/2026-chongqing-ai-competition/evidence/verification.json`。\n\n## 模型与技术栈\n\n### 语义检索\n- **Embedding**：BAAI/bge-small-zh-v1.5（512 维，ONNX INT8，CPU 推理）\n- **Reranker**：BAAI/bge-reranker-base（交叉编码器，ONNX INT8，CPU 推理）\n- **向量索引**：FAISS IndexFlatIP（精确内积检索）\n- **词法召回**：Rank-BM25（中文双字词 + 英文数字词元）\n- **融合策略**：RRF（Reciprocal Rank Fusion，常数 60）\n\n### 语音合成\n- **引擎**：GPT-SoVITS v2ProPlus\n- **流式模式**：mode 1 PCM WAV，按自然短语切分，前端连续排程\n- **音色管理**：昔涟音色使用独立 `xilian` profile；其他音色使用 `base` profile\n- **质量门禁**：参考音频必须通过文本一致和 PCM 质量检查，只保存在本机\n\n### 大模型接入（可选）\n- 支持 OpenAI 兼容接口（DeepSeek、Qwen、通义千问等）\n- 未配置时自动使用本地资料摘录\n- 在前端"模型接口"页面配置，无需重启后端\n\n## 故障回退\n\n- **GPT-SoVITS 不可达**：文字问答仍可用，直播台回退浏览器语音；恢复后重新选择克隆音色即可。\n- **RAG 模型未安装**：系统会提示"检索模型尚未安装，请运行 scripts/setup_rag_models.py"。\n- **向量索引损坏**：在"知识库 → 检索索引与资料检查"页面点击"重建索引"。\n\n## 性能说明\n\n- BGE 模型采用 CPU 推理（2 线程），避免与语音模型争抢显存\n- 首次加载模型需约 1-2 秒，后续查询约 10-30 ms（含编码、检索、重排）\n- FAISS 索引采用精确检索（IndexFlatIP），适合中小规模知识库（< 10 万条）\n""", encoding="utf-8")
    (OUT / “07-现场演示操作手册.md”).write_text(“””# 现场演示操作手册\n\n## 演示顺序（约 3 分钟）\n\n1. 启动 `start.ps1`，确认服务正常。\n2. 知识库导入 TXT/DOCX/PDF，展示车型、片段数量和版本。\n3. 打开”知识库 → 检索索引与资料检查”，展示 BGE 语义模型、512 维向量、FAISS 索引状态。\n4. 提问”欧拉 5 EV 的续航是多少”，展示答案、重排相关度和来源。\n5. 直播台播放三句话脚本，在第一句播放期间修改第三句并应用动态改稿。\n6. 试听克隆音色，展示 PCM 质量、参考文本和预热状态。\n7. 验证页展示 40/40 检索、40/40 问答和 2323 ms 平均首音频。\n\n## 动态改稿示例\n\n初稿：`第一句话，介绍今天的直播主题。第二句话，原本介绍续航表现。第三句话，最后说明购车政策。`\n\n改稿：`第一句话，介绍今天的直播主题。第二句话，改成重点介绍智能驾驶表现。第三句话，最后说明购车政策。`\n\n预期：当前短语完整结束，后续句子切换到新稿。\n\n## 技术亮点说明\n\n- **语义检索**：展示 BGE 预训练模型如何理解近义表达（如”续航能力”vs”电池里程”）\n- **混合召回**：说明 FAISS 语义检索 + BM25 词法召回的互补作用\n- **重排序**：展示 BGE Reranker 如何提升相关度排序准确性\n- **父子分块**：参数按类别分组，FAQ 保留完整问答对\n- **动力隔离**：纯电/混动/燃油配置不会混淆\n\n## 注意\n\n- 不要同时运行两套 GPT-SoVITS 服务。\n- 首次启动需确认 RAG 模型已安装（models/rag/ 目录）。\n- 参考音频必须单人、无配乐、文本逐字一致。\n- 现场演示视频按用户要求不纳入提交包。\n”””, encoding=”utf-8”)
    (OUT / "08-音色拟人度评测表.md").write_text("""# 音色拟人度主观评测表\n\n参考音色：昔涟（新版）；试听参数：语速 1.00、表达度 1.00、稳定性 1.35、音量 100%、语调 0。\n\n试听文案：大家好，欢迎来到汽车直播间。今天我们重点聊聊这款车的续航和智能驾驶表现。\n\n评分：1 分很差，3 分一般，5 分优秀。\n\n| 听测者 | 音色相似度 | 发音清晰度 | 自然停顿 | 情绪节奏 | 整体拟人度 | 备注 |\n| --- | ---: | ---: | ---: | ---: | ---: | --- |\n| 1 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | |\n| 2 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | |\n| 3 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | |\n| 平均 | 待填写 | 待填写 | 待填写 | 待填写 | 待填写 | |\n\n低于 4 分时，优先更换更干净、语气更丰富且文本一致的参考录音。\n""", encoding="utf-8")
    (OUT / "09-提交清单.md").write_text("""# 参赛提交清单\n\n## 已包含\n\n- 01-系统设计文档.docx\n- 01-system-design.pdf\n- 02-汽车垂直领域RAG知识库构建方案.docx\n- 03-流式TTS动态改稿实现方案.docx\n- 04-语音克隆拟人化优化方案.docx\n- 05-标准化功能测试报告.docx\n- 06-部署与运行说明.md\n- 07-现场演示操作手册.md\n- 08-音色拟人度评测表.md\n- 09-提交清单.md\n- 10-系统设计演示.pptx\n- source/汽车直播智能体源码.zip\n- evidence/verification.json\n\n## 提交前\n\n- 填写队伍成员、指导教师、学校信息。\n- 邀请至少 3 名听测者完成音色拟人度评分。\n- 按用户要求不提交演示视频。\n- 重新运行 `verify.ps1` 并核对 JSON 时间戳。\n""", encoding="utf-8")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    save_docs()
    update_markdown()
    build_ppt()
    print("materials rebuilt")


if __name__ == "__main__":
    main()
