"""
使用Python生成Mermaid图表的PNG图片
需要安装: pip install playwright pymermaid
"""
import os
from pathlib import Path
import base64

# 创建图片输出目录
output_dir = Path(__file__).parent / "diagrams"
output_dir.mkdir(exist_ok=True)

# Mermaid图表定义
diagrams = {
    "01-系统架构图": """
graph TB
    subgraph "交互层"
        A[Web前端<br/>Vue.js 5173]
        B[音频排程<br/>AudioContext]
    end

    subgraph "业务层"
        C[FastAPI服务<br/>8000端口]
        D[会话管理]
        E[动态改稿引擎]
        F[问答编排]
    end

    subgraph "数据层"
        G[SQLite数据库<br/>文档/片段/版本/音色]
        H[FAISS向量索引<br/>512维语义向量]
        I[BM25词法索引<br/>中文双字词]
    end

    subgraph "模型层"
        J[GPT-SoVITS<br/>9880端口]
        K[BGE Embedding<br/>ONNX INT8]
        L[BGE Reranker<br/>交叉编码器]
    end

    A --> C
    B --> C
    C --> D
    C --> E
    C --> F
    D --> G
    E --> J
    F --> H
    F --> I
    F --> L
    G --> H
    J --> B
    K --> H

    style A fill:#E3F2FD
    style B fill:#E3F2FD
    style C fill:#BBDEFB
    style J fill:#90CAF9
    style K fill:#90CAF9
    style L fill:#90CAF9
    style G fill:#FFF9C4
    style H fill:#FFF9C4
    style I fill:#FFF9C4
""",

    "02-RAG检索Pipeline": """
flowchart TD
    Start([用户提问]) --> A[问题预处理]
    A --> B[BGE Embedding<br/>生成512维查询向量]

    B --> C1[FAISS语义检索]
    B --> C2[BM25词法检索]

    C1 --> D1[Top 24候选]
    C2 --> D2[Top 24候选]

    D1 --> E[RRF融合<br/>k=60]
    D2 --> E

    E --> F[父块去重]
    F --> G[BGE Reranker<br/>重排序]
    G --> H[动力范围检查]
    H --> I[Top 5结果]

    I --> J{配置LLM?}
    J -->|是| K[大模型生成]
    J -->|否| L[本地摘录]

    K --> M[冲突检查]
    L --> M
    M --> End([返回答案])

    style Start fill:#4CAF50
    style End fill:#4CAF50
    style B fill:#2196F3
    style G fill:#2196F3
""",

    "03-TTS时序图": """
sequenceDiagram
    participant U as 前端
    participant F as FastAPI
    participant T as GPT-SoVITS
    participant A as Audio

    U->>F: 提交脚本
    F->>F: 自然停顿切分
    F->>T: 请求合成短语1
    T-->>F: 返回WAV
    F->>F: 转PCM
    F-->>A: 推送首包
    Note over A: 2300ms<br/>开始播放

    loop 后续短语
        F->>T: 合成短语N
        T-->>F: 返回WAV
        F-->>A: 持续推送
    end
""",

    "04-改稿状态机": """
stateDiagram-v2
    [*] --> Idle
    Idle --> Loading: 提交脚本
    Loading --> Playing: 首包到达
    Playing --> Playing: 继续播放
    Playing --> Paused: 暂停
    Paused --> Playing: 继续
    Playing --> EditRequested: 改稿
    EditRequested --> ComputeBoundary: 计算边界
    ComputeBoundary --> CancelPending: 取消待生成
    CancelPending --> Playing: 新稿
    Playing --> [*]: 完成
""",

    "05-质量门禁": """
flowchart TD
    Start([上传音频]) --> A[格式检查]
    A --> B{时长5-10s?}
    B -->|否| Fail1[拒绝]
    B -->|是| C{采样率≥16k?}
    C -->|否| Fail2[拒绝]
    C -->|是| D[标准化处理]
    D --> E[质量分析]
    E --> F{人声>80%?}
    F -->|否| Fail3[拒绝]
    F -->|是| G{静音<20%?}
    G -->|否| Fail4[拒绝]
    G -->|是| H{削波<1%?}
    H -->|否| Fail5[拒绝]
    H -->|是| I[文本检查]
    I --> J{匹配>90%?}
    J -->|否| Fail6[拒绝]
    J -->|是| K[声纹检查]
    K --> L{相似度>85%?}
    L -->|是| M[创建Profile]
    L -->|否| M
    M --> End([可用])

    style Start fill:#4CAF50
    style End fill:#4CAF50
    Fail1 --> Failed([拒绝])
    Fail2 --> Failed
    Fail3 --> Failed
    Fail4 --> Failed
    Fail5 --> Failed
    Fail6 --> Failed
    style Failed fill:#F44336
""",

    "06-数据流向": """
flowchart LR
    A1[PDF] --> B1[解析]
    A2[DOCX] --> B1
    A3[TXT] --> B1

    B1 --> B2[清洗]
    B2 --> B3[分块]
    B3 --> C1[(SQLite)]
    B3 --> D1[BGE编码]
    D1 --> C2[(FAISS)]

    C1 --> E1[BM25]
    C2 --> E2[FAISS检索]

    E1 --> F1[RRF融合]
    E2 --> F1
    F1 --> F2[重排序]
    F2 --> G1[大模型]
    F2 --> G2[本地摘录]

    G1 --> H1[答案]
    G2 --> H1
    H1 --> I1[TTS]
    I1 --> J1[音频]

    style A1 fill:#E1F5FE
    style A2 fill:#E1F5FE
    style A3 fill:#E1F5FE
    style J1 fill:#F8BBD0
"""
}

# 生成说明文档
instructions = """
# 架构图生成说明

由于Python直接生成PNG需要额外的依赖（playwright等），更简单的方法是：

## 方法1：使用在线工具（推荐）

1. 访问 https://mermaid.live
2. 将下面每个Mermaid代码复制到编辑器
3. 点击右上角 "Actions" → "Download PNG"
4. 选择 2x 或 3x 分辨率
5. 保存为对应文件名

## 方法2：使用VS Code插件

1. 安装 "Markdown Preview Mermaid Support" 插件
2. 打开 架构图和流程图.md
3. 右键点击图表 → Export as PNG

## 方法3：使用命令行工具

```bash
npm install -g @mermaid-js/mermaid-cli
mmdc -i diagram.mmd -o diagram.png -w 1920 -H 1080 -b white
```

---

下面是所有图表的Mermaid代码，已保存到单独的.mmd文件：
"""

print(instructions)
print("\n正在生成Mermaid源文件...")

# 保存每个图表为.mmd文件
for name, code in diagrams.items():
    mmd_file = output_dir / f"{name}.mmd"
    with open(mmd_file, 'w', encoding='utf-8') as f:
        f.write(code.strip())
    print(f"  ✓ {mmd_file.name}")

print(f"\n✅ 已生成 {len(diagrams)} 个 .mmd 文件")
print(f"📁 位置: {output_dir}")
print("\n🔗 快速生成PNG:")
print("   访问 https://mermaid.live")
print("   复制 .mmd 文件内容")
print("   下载PNG图片")

# 创建HTML预览文件
html_content = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>架构图预览</title>
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({ startOnLoad: true, theme: 'default' });
    </script>
    <style>
        body { font-family: Arial; padding: 20px; background: #f5f5f5; }
        .diagram { background: white; padding: 20px; margin: 20px 0; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        h2 { color: #1976D2; }
    </style>
</head>
<body>
    <h1>🎨 汽车直播智能体 - 架构图预览</h1>
"""

for name, code in diagrams.items():
    html_content += f"""
    <div class="diagram">
        <h2>{name}</h2>
        <pre class="mermaid">
{code}
        </pre>
    </div>
"""

html_content += """
</body>
</html>
"""

html_file = output_dir.parent / "架构图预览.html"
with open(html_file, 'w', encoding='utf-8') as f:
    f.write(html_content)

print(f"\n🌐 HTML预览文件: {html_file.name}")
print("   用浏览器打开可预览所有图表")
