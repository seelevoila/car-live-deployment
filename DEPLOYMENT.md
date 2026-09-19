# 部署说明

本文按全新机器编写。项目本身包含前端、FastAPI 后端、本地 RAG 模型和三套内置音色；GPT-SoVITS 整合包、GPU 权重、Live2D 模型和用户自己的克隆音色需要另行准备。

## 1. 运行架构

- 前端静态文件：127.0.0.1:5173
- FastAPI：127.0.0.1:8000
- GPT-SoVITS 包装服务：127.0.0.1:9881
- 数据库：data/car_live.db
- RAG 模型：models/rag
- 可选 Live2D：LIVE2D_MODEL_ROOT 指向的目录

浏览器请求先进入 5173，接口请求进入 8000，语音请求由 8000 转发到 9881。9880 是外部应用端口，启动脚本不会占用或修改它。

## 2. 系统要求

推荐：

- Python 3.12（项目约束 >=3.12,<3.13）
- Windows 10/11、Linux 或 macOS
- NVIDIA GPU 和 CUDA（用于可接受的 GPT-SoVITS 延迟）
- 内存至少 8 GB，磁盘至少 5 GB（不含外部 GPT-SoVITS 整合包）
- Git LFS
- ffmpeg

没有 NVIDIA GPU 时可以把 GPT-SoVITS 配置为 CPU，但推理和短时适配会明显变慢。文档中的首音频时间不适用于 CPU。

## 3. 克隆与 RAG 模型

克隆前安装 Git LFS，否则 279 MB 的 reranker ONNX 只会得到一个指针文件：

~~~bash
git lfs install
git clone https://github.com/seelevoila/car-live-deployment.git
cd car-live-deployment
git lfs pull
~~~

验证 RAG 文件：

~~~bash
python scripts/setup_rag_models.py
~~~

预期输出：

~~~text
All bundled RAG models passed local manifest checks; no download needed.
~~~

如果 LFS 文件未下载或 manifest 校验失败，脚本会从 Hugging Face 固定 revision 下载。国内网络：

~~~bash
python scripts/setup_rag_models.py --endpoint https://hf-mirror.com
~~~

模型来自 Xenova/bge-small-zh-v1.5 和 Xenova/bge-reranker-base，revision 和 SHA256 在 models/rag/embedding/manifest.json、models/rag/reranker/manifest.json。脚本只在本地校验通过后才跳过网络。

## 4. 外部 GPT-SoVITS

从 [GPT-SoVITS 上游仓库](https://github.com/RVC-Boss/GPT-SoVITS) 的 Releases 获取 v2ProPlus 官方整合包。国内机器可以使用团队已有的合规镜像或本地备份，但必须保留原始目录结构。

推荐放置：

~~~text
项目目录/
├─ car-live-deployment/
└─ GPT-SoVITS-v2pro-20250604/
~~~

也可以设置 GPT_SOVITS_ROOT。以下文件必须存在：

~~~text
GPT_SoVITS/pretrained_models/s1v3.ckpt
GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth
GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt
runtime/python.exe       # Windows
runtime/python            # Linux/macOS
~~~

项目用 scripts/gpt_sovits_api.py 启动包装服务，而不是直接把上游服务暴露给前端。服务监听 9881，运行时状态可查：

~~~text
http://127.0.0.1:9881/runtime/status
~~~

缺少上述整合包或权重时，前端和知识库仍可启动，但 GPT-SoVITS 播报、音色克隆和音色评分不可用；启动脚本会打印缺失路径。

## 5. ffmpeg 和 Live2D

参考音频解码、格式转换和质量检查需要 ffmpeg。检测顺序：

1. FFMPEG_BIN 环境变量；
2. PATH 中的 ffmpeg；
3. GPT-SoVITS runtime/ffmpeg.exe 或 runtime/ffmpeg。

缺失时页面会提示需要安装 ffmpeg，不会把问题伪装成“参考音频无效”。

数字主播模型是可选外部资产：

~~~dotenv
LIVE2D_MODEL_ROOT=/path/to/live2d
LIVE2D_MODEL_FILE=Hu Tao.model3.json
~~~

缺失时数字主播页显示“未找到模型”，直播台、RAG 和 TTS 不受影响。

## 6. 配置

复制模板：

Windows PowerShell：

~~~powershell
Copy-Item backend/.env.example backend/.env
~~~

Linux/macOS：

~~~bash
cp backend/.env.example backend/.env
~~~

最小配置：

~~~dotenv
TTS_PROVIDER=gpt-sovits
GPT_SOVITS_URL=http://127.0.0.1:9881
GPT_SOVITS_ADAPTATION_ENABLED=true
~~~

关键变量：

- GPT_SOVITS_ROOT：外部整合包根目录；不设置时探测项目同级目录。
- GPT_SOVITS_PYTHON：外部 runtime 的 Python；不设置时自动探测。
- GPT_SOVITS_URL：包装服务地址，默认 9881。
- GPT_SOVITS_ADAPTATION_SECONDS、GPT_SOVITS_ADAPTATION_MAX_STEPS：新克隆短时适配的软预算。
- LLM_BASE_URL、LLM_MODEL、LLM_API_KEY：可选 OpenAI 兼容问答服务。也可以从“模型接口”页面保存。
- LIVE2D_MODEL_ROOT、LIVE2D_MODEL_FILE：可选数字主播资源。

## 7. 安装依赖

### uv

~~~bash
uv sync
uv run python scripts/setup_rag_models.py
~~~

### venv + pip

Windows：

~~~powershell
py -3.12 -m venv .venv
.\\.venv\\Scripts\\python.exe -m pip install -e .
~~~

Linux/macOS：

~~~bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
~~~

不要在 backend 目录单独建立第二个环境；启动脚本会优先使用项目根目录的 .venv。

## 8. 启动方式

### Windows

~~~powershell
powershell -ExecutionPolicy Bypass -File .\\start.ps1
~~~

### Linux/macOS

~~~bash
chmod +x start.sh
./start.sh
~~~

### 跨平台 Python / uv

~~~bash
uv run python start.py
~~~

三个脚本都会检测 8000、5173、9881。只有命令行明确属于本项目的旧进程才会被停止；如果端口由其他程序占用，会显示 PID 并退出。9880 永远不会被脚本清理。

手动启动（排查脚本问题时）：

~~~bash
# 终端 1，项目根目录
python -m http.server 5173 --directory frontend

# 终端 2，backend 工作目录
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 终端 3，GPT-SoVITS 根目录
runtime/python scripts/gpt_sovits_api.py --gpt-root . -a 127.0.0.1 -p 9881 -c GPT_SoVITS/configs/tts_infer.yaml
~~~

## 9. 功能自检

启动后依次检查：

1. 打开 http://127.0.0.1:5173，能看到直播台、音色管理、知识库和数字主播入口。
2. 打开 http://127.0.0.1:8000/api/tts/status，确认 provider 为 gpt-sovits、ready 为 true；9881 未就绪时 ready 会是 false。
3. 音色管理中能看到沉稳阿川、活力小桃、亲切阿诚，并能试听。
4. 知识库导入一份 PDF、DOCX 或 TXT，建立索引并执行检索。
5. 直播台创建会话，生成话术、播报和改稿；数字主播在模型存在时能加载 Live2D。
6. 上传一段录音并填写逐字原文，确认新克隆进入“训练 → 验收 → 可播报”流程。
7. 未配置 LLM 时执行一个问答，确认页面显示本地回答回退而不是静默失败。

测试命令：

~~~bash
python -m pytest backend/tests -q
node --test frontend/tests/*.test.cjs
python scripts/setup_rag_models.py
~~~

## 10. 常见问题

### 9881 未启动

检查 GPT_SOVITS_ROOT、GPT_SOVITS_PYTHON 和三个必需权重路径。先直接访问 /runtime/status；后端日志会记录连接错误。安装 GPT-SoVITS 后重新运行启动脚本。

### 页面一直显示正在预热

第一次加载会读入 GPT 和 SoVITS 权重，GPU 机器通常比后续请求慢。等待 /api/tts/status 的 warming_up 变为 false。冷启动耗时不能用缓存命中时间替代。

### 首次播报比后续慢

首次请求包含模型加载、参考音频处理和语义检查；后续请求可使用运行时缓存。清空缓存后测得的时间才是未缓存证据。

### 没有 GPU

可以改用 CPU，但速度会明显下降。若 CPU 机器无法在直播节奏下播报，应使用预先生成音频或准备 NVIDIA GPU。

### 端口冲突

查看启动脚本打印的 PID。若 PID 属于其他软件，修改 .env 和前端配置前先确认所有端口引用；不要停止 9880 上的第三方服务。

### RAG 校验失败

先运行 git lfs pull，再运行 setup_rag_models.py。仍失败时使用 hf-mirror endpoint；不要手动改 manifest 的 SHA256。

## 11. 已知限制和分发边界

已经实现并在本地 Windows 环境验证：GPT-SoVITS 默认配置、流式接口、通用新建音色适配、profile 隔离、训练失败回退、旧权重回退、RAG 本地校验和三套内置音色。

随仓库分发：RAG 模型（Git LFS）、RAG manifest、源码、测试、三套内置参考音频。

需要用户自备：GPT-SoVITS v2ProPlus 整合包及权重、ffmpeg、可选 Live2D 模型、可选 LLM API Key、用户自己的克隆录音。

尚未在所有硬件上保证：音色相似度、独立情绪控制、冷启动首音频延迟和 CPU 性能。当前工作区是 Windows 环境；Linux/macOS 启动脚本已按 POSIX 路径实现，但发布前仍应在目标系统执行一次完整自检，不应把未实测环境写成已验证。
