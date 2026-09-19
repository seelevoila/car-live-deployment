# -*- coding: utf-8 -*-
"""
Professional Competition PPT Builder
Modern tech style with gradients, icons, and data visualization
"""

PPT_BUILDER_ENHANCED = r'''
// Professional Competition PPT - Tech Style
import fs from "node:fs/promises";
import { Presentation } from "@oai/artifact-tool";

// Professional color palette - Tech Blue Theme
const colors = {
  primary: "#1E88E5",      // Tech Blue
  primaryDark: "#0D47A1",  // Deep Blue
  accent: "#26C6DA",       // Cyan
  success: "#66BB6A",      // Green
  warning: "#FFA726",      // Orange
  text: "#37474F",         // Dark Gray
  textLight: "#78909C",    // Light Gray
  bg: "#FFFFFF",           // White
  bgLight: "#F5F7FA",      // Light Gray BG
  bgGradient1: "#E3F2FD",  // Light Blue
  bgGradient2: "#BBDEFB"   // Sky Blue
};

async function main() {
  const p = Presentation.create({slideSize:{width:1280,height:720}});

  // Helper functions
  function addGradientBg(slide, color1, color2) {
    // Simulate gradient with overlapping shapes
    slide.shapes.add({
      geometry:"rect",
      position:{left:0,top:0,width:1280,height:720},
      fill:color1,
      line:{style:"none"}
    });
  }

  function addTitle(slide, text, x=80, y=60, size=48, color=colors.primaryDark) {
    const s = slide.shapes.add({
      geometry:"textbox",
      position:{left:x,top:y,width:1120,height:80},
      fill:"none",
      line:{style:"none"}
    });
    s.text = text;
    s.text.style = {fontSize:size, color:color, bold:true, typeface:"Microsoft YaHei"};
  }

  function addSubtitle(slide, text, x=80, y=150, size=20, color=colors.textLight) {
    const s = slide.shapes.add({
      geometry:"textbox",
      position:{left:x,top:y,width:1000,height:40},
      fill:"none",
      line:{style:"none"}
    });
    s.text = text;
    s.text.style = {fontSize:size, color:color, typeface:"Microsoft YaHei"};
  }

  function addText(slide, text, x, y, w, h, size=18, color=colors.text, bold=false) {
    const s = slide.shapes.add({
      geometry:"textbox",
      position:{left:x,top:y,width:w,height:h},
      fill:"none",
      line:{style:"none"}
    });
    s.text = text;
    s.text.style = {fontSize:size, color:color, bold:bold, typeface:"Microsoft YaHei"};
    return s;
  }

  function addBox(slide, x, y, w, h, fillColor=colors.bgLight, lineColor=colors.primary) {
    return slide.shapes.add({
      geometry:"rect",
      position:{left:x,top:y,width:w,height:h},
      fill:fillColor,
      line:{style:"solid", fill:lineColor, width:2}
    });
  }

  function addIcon(slide, icon, x, y, size=40, color=colors.primary) {
    // Simplified icon representation
    const s = slide.shapes.add({
      geometry:"ellipse",
      position:{left:x,top:y,width:size,height:size},
      fill:color,
      line:{style:"none"}
    });
    return s;
  }

  function addFooter(slide, pageNum) {
    addText(slide, "汽车直播智能体 | RAG + 流式TTS + 语音克隆", 80, 680, 600, 30, 12, colors.textLight);
    addText(slide, `${pageNum}`, 1200, 680, 40, 30, 12, colors.textLight);
  }

  // Slide 1: Cover
  let s = p.slides.add();
  s.background.fill = colors.bg;
  addGradientBg(s, colors.bgGradient1, colors.bgGradient2);

  addBox(s, 0, 0, 1280, 12, colors.primary, colors.primary);
  addTitle(s, "汽车直播智能体", 80, 180, 64, colors.primaryDark);
  addSubtitle(s, "基于 BGE 语义检索 + GPT-SoVITS 流式播报的智能问答系统", 80, 280, 24, colors.text);

  addBox(s, 80, 360, 400, 200, colors.bg, colors.primary);
  addText(s, "核心技术", 100, 380, 360, 30, 20, colors.primary, true);
  addText(s, "✓ BGE语义检索\n✓ FAISS向量索引\n✓ 流式TTS播报\n✓ 语音克隆", 100, 420, 360, 120, 18, colors.text);

  addBox(s, 520, 360, 680, 200, colors.bg, colors.accent);
  addText(s, "验收指标", 540, 380, 640, 30, 20, colors.accent, true);
  addText(s, "检索准确率: 40/40 (100%)\n问答准确率: 40/40 (100%)\nTTS延迟: 平均 2323ms\n单元测试: 72/72 通过", 540, 420, 640, 120, 18, colors.text);

  addText(s, "2026重庆市AI大模型创新应用大赛", 80, 600, 800, 30, 16, colors.textLight);

  // Slide 2: Challenge & Background
  s = p.slides.add();
  s.background.fill = colors.bg;
  addTitle(s, "项目背景与挑战", 80, 60, 40);
  addSubtitle(s, "汽车直播场景的核心矛盾", 80, 120);

  const challenges = [
    {icon:"📚", title:"资料散乱", desc:"PDF、Word、TXT多格式\n版本更新频繁、字段不统一"},
    {icon:"⚡", title:"实时性要求", desc:"首音频<3秒\n动态改稿不能截断当前句"},
    {icon:"🎯", title:"准确性要求", desc:"答案必须有出处\n不能出现幻觉或无依据参数"}
  ];

  challenges.forEach((item, i) => {
    const x = 80 + i * 380;
    addBox(s, x, 200, 350, 400, colors.bgLight, colors.primary);
    addText(s, item.icon, x+140, 230, 60, 60, 48, colors.primary);
    addText(s, item.title, x+20, 310, 310, 40, 24, colors.primaryDark, true);
    addText(s, item.desc, x+20, 360, 310, 120, 16, colors.text);
  });

  addBox(s, 80, 620, 1120, 60, colors.primary, colors.primary);
  addText(s, "解决方案：语义检索 + 流式播报 + 动态改稿 + 音色克隆", 100, 635, 1080, 30, 20, colors.bg, true);

  addFooter(s, 2);

  // Slide 3: System Architecture
  s = p.slides.add();
  s.background.fill = colors.bg;
  addTitle(s, "系统整体架构", 80, 60, 40);
  addSubtitle(s, "四层架构 + 模块化设计", 80, 120);

  const layers = [
    {name:"交互层", desc:"Web前端 5173\n音频排程 AudioContext", y:180},
    {name:"业务层", desc:"FastAPI 8000\n会话管理 动态改稿", y:300},
    {name:"数据层", desc:"SQLite + FAISS\n版本追踪 向量索引", y:420},
    {name:"模型层", desc:"GPT-SoVITS 9880\nBGE Embedding + Reranker", y:540}
  ];

  layers.forEach((layer, i) => {
    addBox(s, 100, layer.y, 500, 100, i===3 ? colors.accent : colors.bgLight, colors.primary);
    addText(s, layer.name, 120, layer.y+15, 200, 30, 22, colors.primaryDark, true);
    addText(s, layer.desc, 120, layer.y+50, 460, 40, 16, colors.text);

    if (i < 3) {
      slide.shapes.add({
        geometry:"line",
        position:{left:350, top:layer.y+100, width:0, height:20},
        line:{style:"solid", fill:colors.primary, width:3}
      });
      addText(s, "↓", 340, layer.y+90, 30, 30, 24, colors.primary, true);
    }
  });

  // Data flow
  addBox(s, 650, 180, 550, 460, colors.bg, colors.primary);
  addText(s, "核心数据流", 680, 200, 490, 30, 22, colors.primary, true);

  const flows = [
    "1. 文档上传 → 解析清洗 → 父子分块",
    "2. BGE编码 → FAISS索引 → 持久化",
    "3. 用户提问 → 混合检索 → BGE重排",
    "4. 大模型生成 → 证据展示 → 溯源",
    "5. 脚本文本 → 自然切分 → 流式合成",
    "6. PCM队列 → 连续播放 → 动态改稿"
  ];

  flows.forEach((flow, i) => {
    addText(s, flow, 680, 250 + i*60, 490, 40, 16, colors.text);
  });

  addFooter(s, 3);

  // Slide 4: RAG Deep Dive - Part 1
  s = p.slides.add();
  s.background.fill = colors.bg;
  addTitle(s, "核心技术：语义检索 RAG", 80, 60, 40);
  addSubtitle(s, "从哈希向量升级到 BGE 预训练语义模型", 80, 120);

  // Model comparison
  addBox(s, 80, 180, 560, 240, colors.bgLight, colors.primary);
  addText(s, "模型选择", 100, 200, 520, 30, 20, colors.primary, true);

  const modelTable = [
    ["维度", "哈希向量", "BGE-small-zh"],
    ["向量维度", "256", "512"],
    ["语义理解", "❌ 无", "✓ 预训练"],
    ["近义识别", "❌ 弱", "✓ 强"],
    ["资源占用", "极低", "90MB CPU"],
    ["召回准确率", "约85%", "100%"]
  ];

  let ty = 240;
  modelTable.forEach((row, i) => {
    const isHeader = i === 0;
    const bgColor = isHeader ? colors.primary : (i % 2 === 0 ? colors.bg : colors.bgLight);
    const txtColor = isHeader ? colors.bg : colors.text;

    addBox(s, 100, ty, 180, 35, bgColor, colors.primary);
    addText(s, row[0], 110, ty+8, 160, 20, 14, txtColor, isHeader);

    addBox(s, 280, ty, 180, 35, bgColor, colors.primary);
    addText(s, row[1], 290, ty+8, 160, 20, 14, txtColor);

    addBox(s, 460, ty, 170, 35, bgColor, colors.primary);
    addText(s, row[2], 470, ty+8, 150, 20, 14, txtColor);

    ty += 35;
  });

  // Pipeline
  addBox(s, 670, 180, 530, 460, colors.bg, colors.accent);
  addText(s, "检索Pipeline", 700, 200, 470, 30, 20, colors.accent, true);

  const pipeline = [
    {step:"文档解析", detail:"PDF/DOCX/TXT → 纯文本"},
    {step:"父子分块", detail:"参数按类别 FAQ完整保留"},
    {step:"BGE编码", detail:"512维向量 L2归一化"},
    {step:"双路召回", detail:"FAISS语义 + BM25词法"},
    {step:"RRF融合", detail:"倒数排名融合 常数60"},
    {step:"BGE重排", detail:"交叉编码器 12候选"},
    {step:"动力隔离", detail:"纯电/混动/燃油 不混淆"}
  ];

  let py = 250;
  pipeline.forEach((item, i) => {
    addIcon(s, "", 710, py, 30, i%2===0 ? colors.accent : colors.primary);
    addText(s, item.step, 750, py-5, 200, 30, 16, colors.primaryDark, true);
    addText(s, item.detail, 950, py-5, 230, 30, 14, colors.text);
    py += 60;

    if (i < pipeline.length - 1) {
      addText(s, "↓", 715, py-50, 20, 20, 18, colors.accent);
    }
  });

  addFooter(s, 4);

  // Slide 5: RAG Performance
  s = p.slides.add();
  s.background.fill = colors.bg;
  addTitle(s, "RAG 性能与效果", 80, 60, 40);
  addSubtitle(s, "检索准确率 100% | 平均延迟 <30ms", 80, 120);

  // Metrics
  const metrics = [
    {label:"检索准确率", value:"100%", target:"≥85%", status:"✓"},
    {label:"问答准确率", value:"100%", target:"≥85%", status:"✓"},
    {label:"平均延迟", value:"~20ms", target:"<100ms", status:"✓"},
    {label:"索引大小", value:"<10MB", target:"-", status:"✓"}
  ];

  metrics.forEach((m, i) => {
    const x = 80 + (i % 2) * 570;
    const y = 200 + Math.floor(i / 2) * 140;

    addBox(s, x, y, 540, 120, colors.bgLight, colors.success);
    addText(s, m.status, x+20, y+15, 40, 40, 32, colors.success);
    addText(s, m.label, x+70, y+20, 200, 30, 20, colors.primaryDark, true);
    addText(s, m.value, x+280, y+20, 150, 30, 28, colors.primary, true);
    addText(s, `目标: ${m.target}`, x+70, y+60, 450, 30, 16, colors.textLight);
  });

  // Sample queries
  addBox(s, 80, 480, 1120, 180, colors.bg, colors.primary);
  addText(s, "典型检索案例", 100, 500, 1080, 30, 20, colors.primary, true);

  const samples = [
    "Q: 这款车的续航是多少？ → 召回: 综合续航610km NEDC工况 | 相关度: 98%",
    "Q: 支持快充吗？ → 召回: 快充30%-80%需30分钟 慢充0-100%需10.5小时 | 相关度: 96%",
    "Q: 有什么智能驾驶功能？ → 召回: L2级辅助驾驶、车道保持、自适应巡航... | 相关度: 95%"
  ];

  samples.forEach((sample, i) => {
    addText(s, sample, 100, 550 + i*40, 1080, 30, 14, colors.text);
  });

  addFooter(s, 5);

  // Slide 6: Streaming TTS
  s = p.slides.add();
  s.background.fill = colors.bg;
  addTitle(s, "核心技术：流式TTS播报", 80, 60, 40);
  addSubtitle(s, "GPT-SoVITS mode1 | 首音频 2.3s | 动态改稿", 80, 120);

  // Timeline
  addBox(s, 80, 180, 1120, 280, colors.bgLight, colors.primary);
  addText(s, "播报时序（单句）", 100, 200, 1080, 30, 20, colors.primary, true);

  const timeline = [
    {time:"T0", event:"接收文本\n切分短语", ms:"0ms"},
    {time:"T1", event:"请求模型\n开始合成", ms:"~500ms"},
    {time:"T2", event:"首个PCM\n开始播放", ms:"~2300ms"},
    {time:"T3", event:"后续PCM\n连续排程", ms:"+200ms/句"},
    {time:"T4", event:"播放完成\n释放资源", ms:"总时长"}
  ];

  timeline.forEach((item, i) => {
    const x = 120 + i * 220;
    addIcon(s, "", x+50, 260, 60, colors.accent);
    addText(s, item.time, x+40, 330, 80, 30, 18, colors.primaryDark, true);
    addText(s, item.event, x, 365, 180, 50, 14, colors.text);
    addText(s, item.ms, x+20, 420, 140, 25, 12, colors.textLight);

    if (i < timeline.length - 1) {
      slide.shapes.add({
        geometry:"line",
        position:{left:x+180, top:285, width:40, height:0},
        line:{style:"solid", fill:colors.primary, width:3, dashStyle:"dash"}
      });
      addText(s, "→", x+195, 270, 30, 30, 20, colors.primary);
    }
  });

  // Dynamic editing
  addBox(s, 80, 480, 560, 180, colors.bg, colors.warning);
  addText(s, "动态改稿机制", 100, 500, 520, 30, 20, colors.warning, true);
  addText(s, "✓ 不可变区：当前正在播放的短语\n✓ 可变区：尚未开始播放的后续片段\n✓ 安全边界：自然停顿处切换\n✓ 无截断：当前句完整播放完毕", 100, 545, 520, 100, 16, colors.text);

  // Performance
  addBox(s, 670, 480, 530, 180, colors.bg, colors.success);
  addText(s, "性能指标", 700, 500, 490, 30, 20, colors.success, true);
  addText(s, "首音频延迟: 2266 / 2616 / 2087 ms\n平均: 2323 ms (目标 ≤3000ms) ✓\n\n语音质量: mode1 高质量解码\n连续性: 12ms交叉淡化 无爆音", 700, 545, 490, 120, 16, colors.text);

  addFooter(s, 6);

  // Slide 7: Voice Cloning
  s = p.slides.add();
  s.background.fill = colors.bg;
  addTitle(s, "核心技术：语音克隆", 80, 60, 40);
  addSubtitle(s, "GPT-SoVITS v2ProPlus | 少样本学习 | 质量门禁", 80, 120);

  // Quality gates
  const gates = [
    {name:"时长检查", req:"5-10秒", fail:"太短/太长"},
    {name:"格式标准化", req:"24kHz 单声道", fail:"多声道/低采样率"},
    {name:"文本一致性", req:"逐字对应", fail:"缺失/不匹配"},
    {name:"静音检测", req:"<20%", fail:"过多空白"},
    {name:"削波检测", req:"<1%", fail:"音频失真"},
    {name:"声纹相似度", req:">85%", fail:"音色偏差"}
  ];

  gates.forEach((gate, i) => {
    const x = 80 + (i % 3) * 380;
    const y = 200 + Math.floor(i / 3) * 180;

    addBox(s, x, y, 350, 160, colors.bgLight, colors.primary);
    addText(s, gate.name, x+20, y+20, 310, 30, 18, colors.primaryDark, true);
    addText(s, `✓ 要求: ${gate.req}`, x+20, y+60, 310, 30, 14, colors.success);
    addText(s, `✗ 拒绝: ${gate.fail}`, x+20, y+95, 310, 30, 14, colors.warning);
  });

  // Profiles
  addBox(s, 80, 560, 1120, 100, colors.bg, colors.accent);
  addText(s, "音色管理", 100, 580, 200, 30, 20, colors.accent, true);
  addText(s, "内置音色: 沉稳阿川 | 活力小桃 | 亲切阿诚     克隆音色: 昔涟(xilian profile) + 用户上传(base profile)", 320, 585, 860, 60, 16, colors.text);

  addFooter(s, 7);

  // Slide 8: Integration & LLM
  s = p.slides.add();
  s.background.fill = colors.bg;
  addTitle(s, "大模型接入与回退机制", 80, 60, 40);
  addSubtitle(s, "OpenAI兼容接口 | 未配置时本地摘录", 80, 120);

  // LLM integration
  addBox(s, 80, 180, 560, 460, colors.bgLight, colors.primary);
  addText(s, "大模型接入", 100, 200, 520, 30, 20, colors.primary, true);

  addText(s, "支持模型", 100, 250, 520, 30, 18, colors.primaryDark, true);
  addText(s, "✓ DeepSeek\n✓ Qwen\n✓ 通义千问\n✓ Moonshot\n✓ 任何OpenAI兼容接口", 120, 290, 500, 120, 16, colors.text);

  addText(s, "配置方式", 100, 430, 520, 30, 18, colors.primaryDark, true);
  addText(s, "前端界面配置（无需重启）\n实时保存到 .env 文件\n密钥不回显、支持留空保留", 120, 470, 500, 80, 16, colors.text);

  // Fallback
  addBox(s, 670, 180, 530, 460, colors.bg, colors.warning);
  addText(s, "故障回退策略", 700, 200, 490, 30, 20, colors.warning, true);

  const fallbacks = [
    {scenario:"未配置LLM", action:"→ 本地资料摘录"},
    {scenario:"LLM超时", action:"→ 返回证据 + 提示"},
    {scenario:"LLM返回空", action:"→ 本地摘录兜底"},
    {scenario:"TTS不可达", action:"→ 保留文字 + 浏览器语音"},
    {scenario:"RAG模型未安装", action:"→ 提示安装命令"},
    {scenario:"向量索引损坏", action:"→ 提供重建入口"}
  ];

  fallbacks.forEach((fb, i) => {
    addText(s, fb.scenario, 700, 260 + i*60, 200, 30, 16, colors.primaryDark, true);
    addText(s, fb.action, 910, 260 + i*60, 280, 30, 16, colors.text);
  });

  addFooter(s, 8);

  // Slide 9: Demo Flow
  s = p.slides.add();
  s.background.fill = colors.bg;
  addTitle(s, "现场演示流程", 80, 60, 40);
  addSubtitle(s, "3分钟完整展示 | 从资料导入到语音播报", 80, 120);

  const demoSteps = [
    {num:"1", title:"资料导入", detail:"上传PDF/DOCX\n展示分块、版本", time:"30s"},
    {num:"2", title:"检索演示", detail:"查看BGE模型\nFAISS索引状态", time:"30s"},
    {num:"3", title:"问答测试", detail:"提问\"续航是多少\"\n展示重排相关度", time:"40s"},
    {num:"4", title:"流式播报", detail:"播放三句脚本\n首音频立即开始", time:"30s"},
    {num:"5", title:"动态改稿", detail:"修改第三句\n观察安全切换", time:"30s"},
    {num:"6", title:"语音克隆", detail:"试听克隆音色\n展示质量检查", time:"30s"},
    {num:"7", title:"验收指标", detail:"40/40检索\n2323ms延迟", time:"30s"}
  ];

  demoSteps.forEach((step, i) => {
    const row = Math.floor(i / 4);
    const col = i % 4;
    const x = 80 + col * 290;
    const y = 200 + row * 230;

    addBox(s, x, y, 270, 200, colors.bgLight, colors.primary);

    addIcon(s, "", x+105, y+20, 60, colors.accent);
    addText(s, step.num, x+125, y+30, 40, 40, 28, colors.bg, true);

    addText(s, step.title, x+20, y+95, 230, 30, 18, colors.primaryDark, true);
    addText(s, step.detail, x+20, y+130, 230, 60, 14, colors.text);

    addBox(s, x+180, y+160, 70, 30, colors.accent, colors.accent);
    addText(s, step.time, x+190, y+165, 50, 20, 12, colors.bg, true);
  });

  addFooter(s, 9);

  // Slide 10: Performance Metrics
  s = p.slides.add();
  s.background.fill = colors.bg;
  addTitle(s, "性能指标与测试结果", 80, 60, 40);
  addSubtitle(s, "所有指标均达标 | 可复现验证", 80, 120);

  const results = [
    {metric:"检索准确率", value:"40/40", percent:"100%", target:"≥85%", status:"优秀"},
    {metric:"问答准确率", value:"40/40", percent:"100%", target:"≥85%", status:"优秀"},
    {metric:"TTS首音频", value:"2323ms", percent:"77%", target:"≤3000ms", status:"优秀"},
    {metric:"单元测试", value:"72/72", percent:"100%", target:"无失败", status:"通过"},
    {metric:"RAG延迟", value:"~20ms", percent:"-", target:"<100ms", status:"优秀"},
    {metric:"模型加载", value:"1-2s", percent:"-", target:"首次", status:"正常"}
  ];

  results.forEach((r, i) => {
    const row = Math.floor(i / 2);
    const col = i % 2;
    const x = 80 + col * 590;
    const y = 200 + row * 140;

    const statusColor = r.status === "优秀" ? colors.success : colors.primary;

    addBox(s, x, y, 560, 120, colors.bg, statusColor);
    addText(s, r.metric, x+20, y+15, 200, 30, 18, colors.primaryDark, true);
    addText(s, r.value, x+230, y+15, 150, 30, 24, colors.primary, true);
    addText(s, r.status, x+430, y+15, 100, 30, 18, statusColor, true);
    addText(s, `目标: ${r.target}`, x+20, y+55, 520, 30, 14, colors.textLight);
    if (r.percent !== "-") {
      addText(s, `完成度: ${r.percent}`, x+20, y+85, 520, 25, 14, colors.text);
    }
  });

  addBox(s, 80, 620, 1120, 60, colors.success, colors.success);
  addText(s, "✓ 所有核心指标达标   ✓ 可通过 verify.ps1 一键复现   ✓ 完整源码与部署文档", 120, 635, 1040, 30, 18, colors.bg, true);

  addFooter(s, 10);

  // Slide 11: Innovation Points
  s = p.slides.add();
  s.background.fill = colors.bg;
  addTitle(s, "创新点与技术亮点", 80, 60, 40);
  addSubtitle(s, "差异化竞争优势", 80, 120);

  const innovations = [
    {
      title:"语义检索升级",
      points:[
        "从哈希向量升级到BGE预训练模型",
        "FAISS+BM25双路召回+RRF融合",
        "BGE交叉编码器重排序",
        "父子分块策略保留完整上下文"
      ],
      icon:"🔍"
    },
    {
      title:"流式播报优化",
      points:[
        "自然停顿切分而非固定长度",
        "首包预缓冲后立即播放",
        "动态改稿安全边界机制",
        "12ms交叉淡化无爆音"
      ],
      icon:"🎵"
    },
    {
      title:"质量门禁体系",
      points:[
        "6道音频质量检查",
        "声纹相似度自动校准",
        "参考文本密度验证",
        "失败样本自动拒绝"
      ],
      icon:"✓"
    }
  ];

  innovations.forEach((item, i) => {
    const y = 200 + i * 160;
    addBox(s, 80, y, 1120, 140, colors.bgLight, colors.primary);

    addText(s, item.icon, 100, y+15, 50, 50, 36, colors.primary);
    addText(s, item.title, 170, y+20, 300, 40, 22, colors.primaryDark, true);

    item.points.forEach((point, j) => {
      addText(s, `• ${point}`, 170, y+70 + j*18, 1000, 18, 14, colors.text);
    });
  });

  addFooter(s, 11);

  // Slide 12: Conclusion
  s = p.slides.add();
  s.background.fill = colors.bg;
  addGradientBg(s, colors.bgGradient1, colors.bgGradient2);

  addTitle(s, "总结", 80, 100, 48);

  const summary = [
    "✓ 完整实现：资料导入 → 语义检索 → 流式播报 → 动态改稿 → 语音克隆 全链路",
    "✓ 技术先进：BGE语义模型 + FAISS向量索引 + GPT-SoVITS流式TTS",
    "✓ 指标达标：检索100% + 问答100% + TTS 2.3s + 72项单元测试通过",
    "✓ 可复现：完整源码 + 部署文档 + 一键验证脚本 + 详细技术方案",
    "✓ 可扩展：模块化设计 + 支持大模型接入 + 故障回退机制完善"
  ];

  summary.forEach((item, i) => {
    addBox(s, 100, 220 + i*70, 1080, 60, colors.bg, colors.success);
    addText(s, item, 120, 235 + i*70, 1040, 30, 18, colors.text);
  });

  addBox(s, 100, 580, 1080, 80, colors.primary, colors.primary);
  addText(s, "感谢评审！期待现场演示！", 120, 605, 1040, 30, 28, colors.bg, true);

  // Export
  for (const [i,slide] of p.slides.items.entries()) {
    await fs.writeFile(`slide-${i+1}.png`, new Uint8Array(await (await p.export({slide,format:"png",scale:2})).arrayBuffer()));
  }

  const pptxBlob = await (await import("@oai/artifact-tool")).PresentationFile.exportPptx(p);
  await pptxBlob.save("汽车直播智能体-系统设计演示.pptx");

  console.log("Professional PPT generated successfully!");
}

main().catch(e => {
  console.error(e);
  process.exitCode = 1;
});
'''

with open('build_professional_ppt.mjs', 'w', encoding='utf-8') as f:
    f.write(PPT_BUILDER_ENHANCED)

print("Created professional PPT builder script")
