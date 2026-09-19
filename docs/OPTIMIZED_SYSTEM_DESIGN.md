# 汽车直播智能体系统设计说明书

## 1. 引言

### 1.1 编写目的
本系统设计说明书是对汽车直播智能体系统的详细设计文档，旨在：
- 明确系统的技术架构和实现方案
- 为开发人员提供实现依据
- 为测试人员提供验收标准
- 为评审专家提供技术评估材料

预期读者：项目开发团队、技术评审专家、系统运维人员。

### 1.2 背景
- **系统名称**：汽车直播智能体系统（Automotive Live Streaming AI Agent）
- **任务来源**：2026年第二届重庆市AI大模型创新应用大赛
- **开发单位**：[参赛队伍名称]
- **应用场景**：汽车销售直播场景，为主播提供智能问答、脚本播报和拟人化语音服务
- **实现环境**：本地计算机网络，支持GPU加速的工作站

### 1.3 定义
| 术语 | 定义 |
|------|------|
| RAG | Retrieval-Augmented Generation，检索增强生成 |
| TTS | Text-to-Speech，文本转语音 |
| LLM | Large Language Model，大语言模型 |
| BGE | BAAI General Embedding，智源通用嵌入模型 |
| FAISS | Facebook AI Similarity Search，向量相似度检索库 |
| BM25 | Best Matching 25，经典词法检索算法 |
| RRF | Reciprocal Rank Fusion，倒数排名融合 |
| GPT-SoVITS | 基于GPT和SoVITS的少样本语音克隆模型 |
| Live2D | 2D动态立绘技术 |

### 1.4 参考资料
- GB8567-88《计算机软件产品开发文件编制指南》
- 2026年第二届重庆市AI大模型创新应用大赛赛题文件
- BAAI/bge-small-zh-v1.5 技术文档
- GPT-SoVITS v2 技术文档
- FastAPI 官方文档
- Vue.js 3 官方文档

---

## 2. 总体设计

### 2.1 需求规定

#### 2.1.1 功能需求
1. **知识库管理**
   - 支持PDF、Word、TXT格式批量上传
   - 自动提取和结构化存储
   - 支持资料编辑、删除和版本管理
   - 支持来源溯源和许可维护

2. **智能检索与问答**
   - 向量化和结构化混合检索
   - 检索准确率≥85%，测试样本≥40条
   - 支持文字和语音问答
   - 展示来源、相关度和置信度

3. **流式语音播报**
   - 流式音频生成和播放
   - 首音频延迟≤3秒
   - 支持语速、音量、语调调节
   - 支持多套预置音色

4. **动态改稿**
   - 实时修改未播放内容
   - 保持当前短语播放连续性
   - 取消过期请求并应用新稿

5. **语音克隆**
   - 真人音色少样本克隆
   - 支持参考音频上传和质量检测
   - 支持麦克风实时录制
   - 音色质量评估和优化建议

6. **数字主播**
   - Live2D模型加载和渲染
   - 播报时口型同步
   - 与直播脚本和RAG问答联动

7. **统计与评测**
   - 讲解时长统计
   - 车型和问题热点分析
   - 延迟和改稿统计
   - 真人听测评分

#### 2.1.2 性能需求
- **检索准确率**：≥85%（40条标准测试集）
- **TTS首音频延迟**：≤3秒（浏览器端实测）
- **系统响应时间**：API接口平均响应<500ms
- **并发支持**：支持至少10路并发问答
- **音频质量**：采样率24kHz，16-bit PCM
- **向量检索延迟**：<100ms（千级文档库）

#### 2.1.3 约束条件
- 运行环境：Windows 11，需GPU支持
- 内存要求：≥16GB
- 显存要求：≥8GB（RTX 4060或同等性能）
- 网络要求：需外网访问（大模型API调用）
- 数据合规：本地存储，不自动上传第三方

### 2.2 运行环境

#### 2.2.1 硬件环境
- CPU：Intel Core i5或同等性能，≥4核心
- 内存：16GB DDR4
- 显卡：NVIDIA RTX 4060 Laptop（8GB显存）或更高
- 存储：≥100GB可用空间（SSD推荐）

#### 2.2.2 软件环境
- 操作系统：Windows 11 Home China 10.0.26200
- Python：3.10+
- Node.js：16.0+（前端开发）
- 数据库：SQLite 3
- 浏览器：Chrome 90+, Edge 90+, Firefox 88+

#### 2.2.3 依赖服务
- GPT-SoVITS：本地9881端口
- 大模型API：用户配置的OpenAI兼容接口（可选）

### 2.3 基本设计概念和处理流程

#### 2.3.1 系统架构
```
┌─────────────────────────────────────────────────────────┐
│                      前端层（Vue.js）                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │ 知识库   │  │ 直播台   │  │ 数字主播 │  │ 统计    │ │
│  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP/WebSocket
┌────────────────────┴────────────────────────────────────┐
│                   后端层（FastAPI）                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │ 文档管理 │  │ RAG引擎  │  │ TTS适配  │  │ 统计    │ │
│  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────┴────────────────────────────────────┐
│                      数据层                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ SQLite   │  │ FAISS    │  │ 文件存储 │              │
│  │ (元数据) │  │ (向量)   │  │ (资料)   │              │
│  └──────────┘  └──────────┘  └──────────┘              │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────┴────────────────────────────────────┐
│                    AI服务层                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ BGE模型  │  │ TTS引擎  │  │ 大模型   │              │
│  │ (检索)   │  │ (语音)   │  │ (生成)   │              │
│  └──────────┘  └──────────┘  └──────────┘              │
└─────────────────────────────────────────────────────────┘
```

#### 2.3.2 核心处理流程

**RAG问答流程**：
```
用户提问 → 查询解析 → 双路召回（FAISS+BM25）→ RRF融合 
→ BGE重排 → 父块展开 → 大模型生成 → 答案检查 → 返回结果
```

**流式TTS播报流程**：
```
输入文本 → 自然停顿切分 → 按序TTS合成 → PCM流推送 
→ Web Audio排程 → 连续播放 → 进度回馈
```

**动态改稿流程**：
```
修改检测 → 取消未生成任务 → 保留当前短语 → 新稿切分 
→ 从下一停顿应用 → 无缝切换
```

### 2.4 结构

#### 2.4.1 系统模块组成
1. **前端模块**（frontend/）
   - app.js：主应用逻辑
   - index.html：页面结构
   - style.css：样式定义
   - lip-sync.js：口型同步引擎
   - live2d/：Live2D渲染库

2. **后端模块**（backend/app/）
   - main.py：主入口和路由
   - db.py：数据库操作
   - rag.py：RAG检索引擎
   - llm_gateway.py：大模型适配
   - tts_gpt_sovits.py：GPT-SoVITS适配
   - voice_similarity.py：音色评估
   - business.py：业务逻辑

3. **数据模块**（data/）
   - sample/：示例资料
   - uploads/：用户上传
   - car_live.db：SQLite数据库
   - car_live.rag-index/：FAISS索引

4. **模型模块**（models/）
   - rag/：BGE Embedding和Reranker
   - tts/：语音模型权重

5. **脚本模块**（scripts/）
   - setup_rag_models.py：模型下载
   - evaluate_rag.py：性能评估

### 2.5 功能需求与程序的关系

| 功能需求 | 实现模块 | 主要文件 | 接口端点 |
|---------|---------|----------|---------|
| 知识库上传 | 文档管理 | backend/app/main.py | POST /api/documents/upload |
| 知识库检索 | RAG引擎 | backend/app/rag.py | POST /api/rag/search |
| 智能问答 | RAG+LLM | backend/app/main.py | POST /api/query |
| 流式播报 | TTS适配 | backend/app/tts_gpt_sovits.py | POST /api/tts/stream |
| 动态改稿 | 前端控制 | frontend/app.js | cancelPendingPhrases() |
| 音色克隆 | 语音管理 | backend/app/voice_similarity.py | POST /api/voices/clone |
| 数字主播 | Live2D | frontend/app.js | updateLive2DExpression() |
| 统计分析 | 业务逻辑 | backend/app/business.py | GET /api/stats/* |

### 2.6 人工处理过程

#### 2.6.1 资料准备
- 人工收集和整理汽车资料文档
- 核对资料的公开来源和授权范围
- 标识需要脱敏的敏感信息

#### 2.6.2 音色样本录制
- 主播录制参考音频（建议10秒以上）
- 提供准确的参考文本
- 人工审听克隆质量

#### 2.6.3 直播脚本编写
- 人工撰写直播讲解脚本
- 标记重点卖点和话术
- 设置语速和情感参数

#### 2.6.4 质量评估
- 真人听测评分（自然度、相似度、流畅度）
- 检索准确率人工标注
- 问答质量人工审核

### 2.7 尚未解决的问题

#### 2.7.1 已知限制
1. **大模型依赖**：完整问答功能需用户自行接入外部大模型API
2. **GPU内存限制**：当前硬件无法同时加载大型Embedding模型和TTS模型
3. **多语言支持**：当前仅优化中文，其他语言效果有限
4. **实时流媒体**：尚未集成RTMP推流到直播平台

#### 2.7.2 待优化项
1. 检索重排模型可升级到更大规模版本
2. 音色克隆可引入声纹微调训练
3. 数字主播可增加姿态和表情动画
4. 统计分析可增加更多维度和可视化

---

## 3. 接口设计

### 3.1 用户接口

#### 3.1.1 前端页面组成
1. **知识库页面**
   - 文档上传区（支持拖拽）
   - 文档列表（显示车型、片段数、版本）
   - 版本历史查看
   - 检索测试区

2. **直播台页面**
   - 车型选择下拉框
   - 脚本输入/导入区
   - 播放控制按钮（播放、暂停、停止、改稿）
   - 音色选择器
   - 语速/音量/语调滑块
   - 问答区（输入框、回答展示、来源展示）

3. **数字主播页面**
   - Live2D模型渲染区
   - 播报控制（复用直播台脚本和问答）
   - 口型同步状态显示

4. **语音克隆页面**
   - 上传参考音频
   - 麦克风录制按钮
   - 参考文本输入框
   - 音色质量诊断
   - 试听和应用按钮

5. **验证页面**
   - 检索准确率测试
   - 问答准确率测试
   - TTS延迟测试
   - 测试结果展示

6. **统计页面**
   - 讲解时长统计
   - 车型热点排行
   - 问题热点排行
   - 改稿次数统计
   - 延迟分布图

7. **模型接口页面**
   - 大模型服务地址配置
   - API Key输入
   - 连接测试按钮
   - 配置状态显示

#### 3.1.2 交互流程
**知识库导入流程**：
```
选择文件 → 填写元数据 → 点击上传 → 显示进度 → 上传成功 
→ 自动分块 → 生成向量 → 显示片段数
```

**问答交互流程**：
```
输入问题 → 点击提问 → 显示加载状态 → 展示回答文字 
→ 展示来源片段 → 自动开始语音播报
```

### 3.2 外部接口

#### 3.2.1 大模型API接口
**请求格式**（OpenAI兼容）：
```json
POST {LLM_BASE_URL}/v1/chat/completions
Content-Type: application/json
Authorization: Bearer {LLM_API_KEY}

{
  "model": "模型名称",
  "messages": [
    {"role": "system", "content": "系统提示词"},
    {"role": "user", "content": "用户问题"}
  ],
  "temperature": 0.7,
  "max_tokens": 500
}
```

**响应格式**：
```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "回答内容"
      }
    }
  ]
}
```

#### 3.2.2 TTS服务接口

**GPT-SoVITS HTTP接口**：
```json
POST http://127.0.0.1:9881/tts
Content-Type: application/json

{
  "text": "要合成的文本",
  "text_language": "zh",
  "ref_audio_path": "参考音频路径",
  "prompt_text": "参考音频对应文本",
  "prompt_language": "zh"
}
```

**响应**：
- Content-Type: audio/wav
- Body: PCM WAV音频数据

**GPT-SoVITS接口**：
```json
POST http://127.0.0.1:9880
Content-Type: application/json

{
  "text": "要合成的文本",
  "text_language": "zh",
  "ref_audio_path": "参考音频路径",
  "prompt_text": "参考文本",
  "prompt_language": "zh",
  "top_k": 5,
  "top_p": 1.0,
  "temperature": 1.0,
  "speed": 1.0
}
```

### 3.3 内部接口

#### 3.3.1 后端API接口

**1. 文档管理接口**

`POST /api/documents/upload`
- 功能：上传文档到知识库
- 请求：multipart/form-data，包含file、brand、series、year
- 响应：文档ID、片段数量、版本号

`GET /api/documents`
- 功能：获取文档列表
- 响应：文档列表（ID、名称、车型、片段数、上传时间）

`GET /api/documents/{id}/versions`
- 功能：获取文档版本历史
- 响应：版本列表（版本号、时间、变更说明）

`DELETE /api/documents/{id}`
- 功能：删除文档
- 响应：成功/失败状态

**2. RAG检索接口**

`POST /api/rag/search`
- 功能：检索相关片段（不调用大模型）
- 请求：
```json
{
  "question": "用户问题",
  "brand": "品牌",
  "series": "车系",
  "year": "年款",
  "top_k": 5
}
```
- 响应：
```json
{
  "results": [
    {
      "content": "片段内容",
      "source": "来源文档",
      "score": 0.95,
      "page": 3
    }
  ]
}
```

`GET /api/rag/status`
- 功能：获取RAG引擎状态
- 响应：模型版本、向量维度、索引版本、文档数量

`POST /api/rag/reindex`
- 功能：重建FAISS索引
- 响应：索引重建状态

**3. 问答接口**

`POST /api/query`
- 功能：RAG问答（检索+大模型生成）
- 请求：同/api/rag/search
- 响应：
```json
{
  "answer": "回答内容",
  "sources": [{"content": "...", "score": 0.95}],
  "method": "llm",
  "confidence": 0.9
}
```

**4. TTS接口**

`POST /api/tts/stream`
- 功能：流式TTS合成
- 请求：
```json
{
  "text": "播报文本",
  "voice_id": "音色ID",
  "speed": 1.0,
  "volume": 1.0,
  "pitch": 1.0
}
```
- 响应：Server-Sent Events流，逐段推送PCM数据

`GET /api/tts/status`
- 功能：获取TTS引擎状态
- 响应：提供商、模型版本、可用音色列表

**5. 音色管理接口**

`POST /api/voices/clone`
- 功能：克隆新音色
- 请求：multipart/form-data，包含audio_file、ref_text、name
- 响应：音色ID、质量评分、优化建议

`GET /api/voices`
- 功能：获取音色列表
- 响应：音色列表（ID、名称、类型、质量状态）

`POST /api/voices/{voice_id}/optimize`
- 功能：优化音色样本
- 响应：优化后的音色信息

`DELETE /api/voices/{voice_id}`
- 功能：删除音色
- 响应：成功/失败状态

**6. 统计接口**

`GET /api/stats/session`
- 功能：获取当前会话统计
- 响应：讲解时长、问答次数、改稿次数

`GET /api/stats/热点`
- 功能：获取热点统计
- 响应：车型热点、问题热点

#### 3.3.2 模块间接口

**RAG模块 → LLM模块**：
```python
def generate(question: str, sources: List[dict], task: str) -> str:
    """
    调用大模型生成回答
    
    Args:
        question: 用户问题
        sources: 检索到的相关片段列表
        task: 任务类型（"qa"或"script"）
    
    Returns:
        生成的回答文本
    """
```

**TTS模块 → Voice模块**：
```python
def get_voice_config(voice_id: str) -> dict:
    """
    获取音色配置
    
    Args:
        voice_id: 音色ID
    
    Returns:
        {
            "ref_audio": "参考音频路径",
            "ref_text": "参考文本",
            "model_path": "模型路径"
        }
    """
```

**DB模块 → RAG模块**：
```python
def get_active_documents(brand: str, series: str, year: str) -> List[dict]:
    """
    获取有效文档列表
    
    Args:
        brand, series, year: 筛选条件
    
    Returns:
        文档列表，包含ID、内容、元数据
    """
```

---

## 4. 运行设计

### 4.1 运行模块组合

#### 4.1.1 开发模式
```
前端开发服务器（Vite, 5173端口）
    ↓
后端开发服务器（Uvicorn reload, 8000端口）
    ↓
GPT-SoVITS服务（单独进程, 9881端口）
```

#### 4.1.2 生产模式
```
前端静态文件（Nginx/Apache服务）
    ↓
后端生产服务器（Uvicorn多worker, 8000端口）
    ↓
TTS服务（常驻后台进程）
    ↓
数据库（SQLite文件）
```

### 4.2 运行控制

#### 4.2.1 启动流程
```powershell
# 一键启动脚本
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

执行步骤：
1. 检查Python虚拟环境
2. 检查Node.js依赖
3. 启动后端服务（8000端口）
4. 启动前端服务（5173端口）
5. 启动GPT-SoVITS服务（9881端口）
6. 自动打开浏览器

#### 4.2.2 停止流程
- Ctrl+C终止所有服务
- 或关闭PowerShell窗口
- 或使用任务管理器结束进程

#### 4.2.3 监控机制
- 健康检查端点：GET /api/health
- 日志输出：控制台和文件（logs/app.log）
- 错误捕获：全局异常处理器

### 4.3 运行时间

#### 4.3.1 启动时间
- 后端服务启动：2-5秒
- 前端服务启动：3-8秒
- GPT-SoVITS模型加载：30-60秒
- 总启动时间：约1-2分钟

#### 4.3.2 响应时间要求
- 文档上传：<5秒（取决于文件大小）
- 检索查询：<100ms
- 问答生成：<3秒（不含TTS）
- TTS首音频：<3秒
- 音色克隆：<10秒

#### 4.3.3 运行时性能
- CPU占用率：平均30-50%，峰值70%
- 内存占用：约8-10GB
- 显存占用：约6-7GB
- 磁盘I/O：主要在文档上传和索引重建时

---

## 5. 系统数据结构设计

### 5.1 逻辑结构设计要点

#### 5.1.1 实体关系模型（ER图）
```
[文档Document] 1───N [片段Fragment]
      │
      │ 1
      │
      N
[版本Version]

[音色Voice] 1───N [参考音频ReferenceAudio]

[会话Session] 1───N [问答QA]
                │
                N
            [播报Playback]
```

#### 5.1.2 数据流图
```
原始文档 → 文档解析器 → 结构化片段 → 向量编码器 → FAISS索引
                                        ↓
用户问题 → 查询解析 → 双路召回 → RRF融合 → 重排序 → 大模型 → 回答
```

### 5.2 物理结构设计要点

#### 5.2.1 SQLite数据库表结构

**1. documents表（文档）**
```sql
CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    brand TEXT NOT NULL,
    series TEXT NOT NULL,
    year TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    upload_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    version INTEGER DEFAULT 1,
    status TEXT DEFAULT 'active',
    license_info TEXT
);
```

**2. fragments表（片段）**
```sql
CREATE TABLE fragments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL,
    content TEXT NOT NULL,
    parent_content TEXT,
    category TEXT,
    page_number INTEGER,
    version INTEGER DEFAULT 1,
    embedding BLOB,  -- 存储512维float32向量
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (document_id) REFERENCES documents(id)
);
```

**3. voices表（音色）**
```sql
CREATE TABLE voices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL,  -- 'preset', 'cloned', 'system'
    ref_audio_path TEXT,
    ref_text TEXT,
    quality_score REAL,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**4. qa_logs表（问答日志）**
```sql
CREATE TABLE qa_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    brand TEXT,
    series TEXT,
    year TEXT,
    method TEXT,  -- 'llm' or 'local'
    confidence REAL,
    latency_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**5. playback_logs表（播报日志）**
```sql
CREATE TABLE playback_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    voice_id INTEGER,
    duration_ms INTEGER,
    tts_latency_ms INTEGER,
    was_revised BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (voice_id) REFERENCES voices(id)
);
```

#### 5.2.2 FAISS向量索引结构
```python
# 索引类型
index = faiss.IndexIDMap2(faiss.IndexFlatIP(512))
# ID映射：fragment_id → vector_position
# 持久化文件：data/car_live.rag-index/vectors.faiss
```

#### 5.2.3 文件存储结构
```
data/
├── sample/              # 示例资料（只读）
│   ├── 欧拉5-EV-参数.xlsx
│   └── 欧拉5-EV-话术.docx
├── uploads/             # 用户上传资料
│   ├── documents/       # 原始文档
│   └── voices/          # 参考音频
├── car_live.db          # SQLite数据库
└── car_live.rag-index/  # FAISS索引
    ├── vectors.faiss    # 向量索引
    └── manifest.json    # 索引元数据
```

### 5.3 数据结构与程序的关系

| 数据表/结构 | 访问模块 | 主要操作 |
|------------|----------|----------|
| documents | backend/app/db.py | 文档增删改查、版本管理 |
| fragments | backend/app/rag.py | 片段检索、向量查询 |
| FAISS索引 | backend/app/rag.py | 向量相似度检索 |
| voices | backend/app/voice_similarity.py | 音色管理、质量评估 |
| qa_logs | backend/app/business.py | 统计分析、热点计算 |
| playback_logs | backend/app/business.py | 播报统计、延迟分析 |

---

## 6. 系统出错处理设计

### 6.1 出错信息

#### 6.1.1 错误分类
1. **客户端错误（4xx）**
   - 400 Bad Request：请求参数错误
   - 401 Unauthorized：未授权访问
   - 404 Not Found：资源不存在
   - 413 Payload Too Large：文件过大

2. **服务器错误（5xx）**
   - 500 Internal Server Error：服务器内部错误
   - 503 Service Unavailable：服务不可用（TTS服务未就绪）

3. **业务错误**
   - DOCUMENT_PARSE_ERROR：文档解析失败
   - RETRIEVAL_FAILED：检索失败
   - TTS_GENERATION_FAILED：语音合成失败
   - VOICE_QUALITY_LOW：音色质量不合格
   - LLM_API_ERROR：大模型API调用失败

#### 6.1.2 错误码定义
```python
ERROR_CODES = {
    "DOC001": "不支持的文档格式",
    "DOC002": "文档大小超过限制（最大50MB）",
    "DOC003": "文档解析失败",
    "RAG001": "检索索引未就绪",
    "RAG002": "未找到相关资料",
    "RAG003": "向量编码失败",
    "TTS001": "TTS服务未就绪",
    "TTS002": "音频生成失败",
    "TTS003": "音色加载失败",
    "VOICE001": "参考音频格式不支持",
    "VOICE002": "参考文本缺失",
    "VOICE003": "音色质量不合格",
    "LLM001": "大模型未配置",
    "LLM002": "大模型API调用失败",
    "LLM003": "大模型响应超时"
}
```

### 6.2 补救措施

#### 6.2.1 容错机制

**1. LLM降级**
- 大模型调用失败时自动降级到本地摘录式回答
- 保证基本问答功能可用

**2. TTS重试**
- 音频生成失败时自动重试（最多3次）
- 重试间隔：1秒、2秒、5秒
- 所有重试失败后返回错误提示

**3. 向量检索容错**
- FAISS索引损坏时尝试重建
- 重建失败时使用BM25词法检索

**4. 音色回退**
- 克隆音色不可用时回退到系统默认音色
- 保证播报功能连续性

#### 6.2.2 数据保护
- 文档上传前验证文件完整性
- 数据库操作使用事务保证原子性
- 定期备份数据库和索引文件
- 音频文件上传后验证可读性

#### 6.2.3 降级策略
```
完整功能：RAG检索 + 大模型生成 + 高质量TTS
    ↓ 大模型不可用
基础功能：RAG检索 + 本地摘录 + 高质量TTS
    ↓ TTS不可用
最小功能：RAG检索 + 本地摘录 + 文字展示
```

### 6.3 系统维护设计

#### 6.3.1 日志记录

**日志级别**：
- DEBUG：调试信息（开发环境）
- INFO：正常操作日志
- WARNING：警告信息（不影响功能）
- ERROR：错误信息（功能受影响）
- CRITICAL：严重错误（服务不可用）

**日志内容**：
```python
{
    "timestamp": "2026-09-15T10:30:00.123Z",
    "level": "ERROR",
    "module": "rag",
    "function": "search",
    "message": "FAISS索引查询失败",
    "error": "IndexError: index out of range",
    "context": {
        "question": "续航是多少",
        "brand": "欧拉",
        "series": "欧拉5 EV"
    }
}
```

**日志存储**：
- 控制台输出：实时查看
- 文件存储：logs/app-{date}.log
- 日志轮转：每天一个文件，保留30天

#### 6.3.2 监控告警

**健康检查**：
```python
GET /api/health
响应：
{
    "status": "healthy",
    "services": {
        "database": "ok",
        "rag": "ok",
        "tts": "degraded",  # 降级但可用
        "llm": "unavailable"  # 不可用
    },
    "uptime_seconds": 3600
}
```

**性能监控**：
- API响应时间统计
- TTS延迟监控
- 内存和CPU占用率
- 并发请求数

**告警规则**：
- TTS延迟连续3次超过5秒
- API错误率超过10%
- 内存占用超过90%
- 磁盘空间不足10GB

#### 6.3.3 定期维护任务

**每日任务**：
- 清理过期日志文件（保留30天）
- 清理临时音频文件
- 数据库VACUUM优化

**每周任务**：
- 数据库和索引备份
- 统计数据汇总
- 性能报告生成

**按需任务**：
- 向量索引重建（资料大量更新后）
- 数据库迁移（结构变更时）
- 模型升级（新版本发布时）

---

## 7. 附录

### 7.1 详细算法说明

#### 7.1.1 RRF融合算法
```python
def rrf_fusion(vector_results, bm25_results, k=60):
    """
    Reciprocal Rank Fusion算法
    
    score(doc) = sum(1 / (k + rank_i))
    其中rank_i是文档在第i个排序列表中的排名
    """
    scores = {}
    for rank, item in enumerate(vector_results):
        scores[item['id']] = scores.get(item['id'], 0) + 1 / (k + rank + 1)
    for rank, item in enumerate(bm25_results):
        scores[item['id']] = scores.get(item['id'], 0) + 1 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

#### 7.1.2 自然停顿切分算法
```python
def split_by_natural_pauses(text):
    """
    按中文自然停顿切分文本
    优先级：。！？ > ， > 、 > 分句
    """
    sentences = []
    current = ""
    for char in text:
        current += char
        if char in "。！？" or (char in "，、" and len(current) > 20):
            sentences.append(current.strip())
            current = ""
    if current:
        sentences.append(current.strip())
    return sentences
```

#### 7.1.3 口型同步算法
```python
def calculate_mouth_openness(audio_energy):
    """
    根据音频能量计算嘴型开度
    
    Args:
        audio_energy: 20ms音频包络能量（0-1）
    
    Returns:
        mouth_openness: 嘴型开度（0-1）
    """
    # 能量阈值
    threshold = 0.02
    # 非线性映射
    if audio_energy < threshold:
        return 0.0
    else:
        return min(1.0, (audio_energy - threshold) * 5)
```

### 7.2 配置文件示例

#### 7.2.1 后端配置（backend/.env）
```dotenv
# TTS提供商（当前唯一实现）
TTS_PROVIDER=gpt-sovits

# GPT-SoVITS配置
GPT_SOVITS_URL=http://127.0.0.1:9881
GPT_SOVITS_PYTHON=C:\\path\\to\\GPT-SoVITS\\.venv\\Scripts\\python.exe
GPT_SOVITS_ROOT=C:\\path\\to\\GPT-SoVITS

# 大模型配置（可选）
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_API_KEY=your_api_key_here
LLM_TIMEOUT_SECONDS=12

# Live2D模型配置
LIVE2D_MODEL_ROOT=C:\\Users\\seele\\Desktop\\原神
LIVE2D_MODEL_FILE=Hu Tao.model3.json

# 数据目录
DATA_DIR=./data
UPLOADS_DIR=./data/uploads
SAMPLE_DIR=./data/sample
```

#### 7.2.2 启动脚本（start.ps1）
```powershell
# 检查虚拟环境
if (-Not (Test-Path ".venv")) {
    Write-Host "创建Python虚拟环境..."
    python -m venv .venv
}

# 激活虚拟环境
.\.venv\Scripts\Activate.ps1

# 安装依赖
Write-Host "安装后端依赖..."
pip install -r backend\requirements.txt

# 启动后端
Write-Host "启动后端服务..."
Start-Process -NoNewWindow -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"

# GPT-SoVITS 服务由项目启动脚本按本机安装路径启动

# 启动前端
Write-Host "启动前端服务..."
Set-Location frontend
npm install
npm run dev

# 打开浏览器
Start-Process "http://127.0.0.1:5173"
```

### 7.3 测试数据

#### 7.3.1 检索测试集（data/testset/retrieval_questions.json）
```json
[
  {
    "id": 1,
    "question": "欧拉5 EV的续航是多少？",
    "brand": "欧拉",
    "series": "欧拉5 EV",
    "year": "2026",
    "expected_keywords": ["续航", "公里", "CLTC"]
  },
  {
    "id": 2,
    "question": "这款车的快充时间是多久？",
    "brand": "欧拉",
    "series": "欧拉5 EV",
    "year": "2026",
    "expected_keywords": ["快充", "分钟", "30%-80%"]
  }
  // ... 共40条
]
```

### 7.4 部署检查清单

- [ ] Python 3.10+已安装
- [ ] Node.js 16.0+已安装
- [ ] NVIDIA驱动和CUDA已安装
- [ ] 虚拟环境已创建（.venv/）
- [ ] 后端依赖已安装（requirements.txt）
- [ ] 前端依赖已安装（node_modules/）
- [ ] RAG模型已下载（models/rag/）
- [ ] TTS服务已配置（.env文件）
- [ ] 数据库已初始化（car_live.db）
- [ ] 示例资料已导入（data/sample/）
- [ ] 健康检查接口响应正常（/api/health）
- [ ] 前端页面可访问（http://127.0.0.1:5173）
- [ ] TTS服务可用（试听功能正常）
- [ ] 检索功能正常（验证页面测试通过）
- [ ] 问答功能正常（有/无大模型均测试）
- [ ] 数字主播模型加载成功

---

## 版本历史

| 版本 | 日期 | 修订内容 | 修订人 |
|------|------|----------|--------|
| 1.0 | 2026-09-15 | 初版完成 | [姓名] |

---

## 审批记录

| 角色 | 姓名 | 日期 | 签名 |
|------|------|------|------|
| 编写 | | | |
| 审核 | | | |
| 批准 | | | |
