# -*- coding: utf-8 -*-
"""
完整的文档生成脚本 - 包含架构图占位符
"""
from pathlib import Path
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

SUBMISSION_DIR = Path(__file__).parent
MATERIALS_DIR = SUBMISSION_DIR / "2026-chongqing-ai-competition"
DIAGRAMS_DIR = SUBMISSION_DIR / "diagrams"

# 架构图映射关系
DIAGRAM_MAPPING = {
    "01-系统设计文档": [
        ("2 总体架构", "01-系统架构图"),
        ("3.6 部署架构与扩展性", "06-数据流向")
    ],
    "02-汽车垂直领域RAG知识库构建方案": [
        ("2 模型与资源选择", "02-RAG检索Pipeline"),
        ("3 数据处理链路", "02-RAG检索Pipeline")
    ],
    "03-流式TTS动态改稿实现方案": [
        ("2.6 延迟优化深度分析", "03-TTS时序图"),
        ("2.7 动态改稿算法详解", "04-改稿状态机")
    ],
    "04-语音克隆拟人化优化方案": [
        ("2.6 质量评估完整Pipeline", "05-质量门禁")
    ],
    "05-标准化功能测试报告": []
}

def add_diagram_placeholder(doc, diagram_name, section_title):
    """添加架构图占位符"""
    # 添加段落说明
    p = doc.add_paragraph()
    p.add_run(f"【架构图占位符：{diagram_name}】").bold = True
    p.add_run("\n")
    p.add_run(f"请在此处插入图片: diagrams/{diagram_name}.png").italic = True

    # 添加空白占位空间
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(12)

    # 添加边框（模拟图片位置）
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    pPr = p._element.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    for border_name in ['top', 'left', 'bottom', 'right']:
        border = OxmlElement(f'w:{border_name}')
        border.set(qn('w:val'), 'single')
        border.set(qn('w:sz'), '12')
        border.set(qn('w:space'), '1')
        border.set(qn('w:color'), 'CCCCCC')
        pBdr.append(border)
    pPr.append(pBdr)

    # 占位文本
    run = p.add_run(f"\n\n\n    图片位置: {diagram_name}\n    建议尺寸: 宽14cm\n\n\n")
    run.font.color.rgb = RGBColor(150, 150, 150)
    run.font.size = Pt(10)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

def enhance_document(doc_name):
    """增强单个文档 - 添加图片占位符和格式优化"""
    print(f"\n增强文档: {doc_name}")

    doc_file = MATERIALS_DIR / f"{doc_name}-扩充版.docx"
    if not doc_file.exists():
        print(f"  ⚠️  文件不存在: {doc_file}")
        return False

    doc = Document(doc_file)

    # 获取该文档需要的架构图
    diagrams = DIAGRAM_MAPPING.get(doc_name, [])

    if diagrams:
        # 在文档末尾添加"架构图插入说明"章节
        doc.add_page_break()
        heading = doc.add_heading('📌 架构图插入指南', level=1)

        p = doc.add_paragraph()
        p.add_run("以下位置需要插入架构图。图片文件位于 ").font.size = Pt(11)
        p.add_run("submission/diagrams/").bold = True
        p.add_run(" 目录。").font.size = Pt(11)

        doc.add_paragraph()

        for section, diagram in diagrams:
            doc.add_heading(f'在 "{section}" 章节插入', level=2)
            add_diagram_placeholder(doc, diagram, section)

    # 保存增强版
    output_file = MATERIALS_DIR / f"{doc_name}-完整版.docx"
    doc.save(output_file)

    print(f"  ✓ 已保存: {output_file.name}")
    return True

def create_quick_guide():
    """创建快速操作指南"""
    guide_content = """# 🚀 快速完成指南

## 当前状态

✅ 扩充内容已整合到DOCX
✅ 架构图源文件已生成 (diagrams/*.mmd)
✅ HTML预览文件已生成

## 立即执行（1小时完成）

### 步骤1：生成架构图PNG（15分钟）

**方法A - 在线工具（最简单）**：
1. 打开浏览器访问 https://mermaid.live
2. 打开 `submission/diagrams/01-系统架构图.mmd`
3. 复制全部内容，粘贴到网站
4. 点击右上角 Actions → Download PNG (选择2x)
5. 保存为 `01-系统架构图.png`
6. 重复步骤2-5，完成全部6张图

**方法B - 浏览器预览（可选）**：
1. 双击打开 `submission/架构图预览.html`
2. 在浏览器中查看所有图表
3. 右键每个图 → 另存为图像

### 步骤2：插入图片到文档（20分钟）

打开每个 `-完整版.docx` 文档，你会看到：
```
【架构图占位符：01-系统架构图】
请在此处插入图片: diagrams/01-系统架构图.png

┌─────────────────────────────┐
│                             │
│    图片位置: 01-系统架构图     │
│    建议尺寸: 宽14cm           │
│                             │
└─────────────────────────────┘
```

操作：
1. 删除占位符框
2. 插入 → 图片 → 选择对应PNG文件
3. 调整宽度为14cm
4. 添加图注 "图X 系统架构图"

### 步骤3：最终调整（15分钟）

1. 统一字体：
   - 标题：黑体
   - 正文：宋体 11pt
   - 表格：微软雅黑 10pt

2. 检查页边距：上下2.54cm，左右3.18cm

3. 行距：1.5倍

### 步骤4：生成PDF（10分钟）

每个文档：
1. 文件 → 另存为
2. 文件类型选择 "PDF"
3. 点击保存

---

## 🎯 预期成果

完成后你将拥有：

✅ 5份完整PDF文档（每份12-15页，含架构图）
✅ 专业的视觉呈现
✅ 详实的技术内容
✅ 准备好的答辩材料

**总耗时：约1小时**

---

## 📁 文件清单

```
submission/
├── diagrams/               # 架构图源文件
│   ├── 01-系统架构图.mmd
│   ├── 02-RAG检索Pipeline.mmd
│   ├── 03-TTS时序图.mmd
│   ├── 04-改稿状态机.mmd
│   ├── 05-质量门禁.mmd
│   └── 06-数据流向.mmd
│
├── 架构图预览.html         # 浏览器预览
│
└── 2026-chongqing-ai-competition/
    ├── 01-系统设计文档-完整版.docx       ✅
    ├── 02-汽车垂直领域RAG知识库构建方案-完整版.docx  ✅
    ├── 03-流式TTS动态改稿实现方案-完整版.docx  ✅
    ├── 04-语音克隆拟人化优化方案-完整版.docx  ✅
    └── 05-标准化功能测试报告-完整版.docx  ✅
```

---

## 💡 小技巧

1. **批量处理**：用Word宏批量生成PDF
2. **快捷键**：Ctrl+Enter 插入分页符
3. **格式刷**：统一标题格式更快
4. **样式**：使用内置"标题1/2/3"样式

---

**现在就开始！打开浏览器访问 https://mermaid.live** 🚀
"""

    guide_file = SUBMISSION_DIR / "快速完成指南.md"
    with open(guide_file, 'w', encoding='utf-8') as f:
        f.write(guide_content)

    print(f"\n✅ 快速指南: {guide_file.name}")

def main():
    print("="*60)
    print("生成完整版文档（含架构图占位符）")
    print("="*60)

    # 增强所有文档
    for doc_name in DIAGRAM_MAPPING.keys():
        enhance_document(doc_name)

    # 创建快速指南
    create_quick_guide()

    print("\n" + "="*60)
    print("✅ 完成！")
    print("="*60)

    print("\n📋 下一步:")
    print("  1. 打开 '快速完成指南.md'")
    print("  2. 按照步骤生成PNG图片")
    print("  3. 插入图片到'-完整版.docx'文档")
    print("  4. 生成PDF")

    print("\n⏱️  预计耗时: 1小时")

if __name__ == '__main__':
    main()
