# 汽车直播智能体

这是一个面向汽车销售直播的本地应用：它提供资料检索问答、直播话术生成与改稿、GPT-SoVITS 流式播报、音色克隆、直播统计和可选的 Live2D 数字主播。

默认语音引擎是 GPT-SoVITS v2ProPlus。新建克隆音色会用该音色自己的录音和原文做短时声学适配，并为每个音色安装独立 profile；这不代表所有音色的相似度或首音频延迟都有统一保证。

## 架构

~~~text
浏览器静态前端 :5173
       │ HTTP
FastAPI 后端 :8000 ── SQLite / 本地 RAG 模型
       │ HTTP / PCM WAV
GPT-SoVITS 包装服务 :9881 ── 外部 GPT-SoVITS v2ProPlus 整合包
~~~

RAG 模型和三套内置参考音频随仓库分发。GPT-SoVITS 整合包、其权重、Live2D 模型和用户自己的克隆音频不放进仓库。

## 依赖

- Python >=3.12,<3.13。
- Git LFS：仓库中的 RAG ONNX 文件使用 LFS；克隆前执行 git lfs install。
- GPT-SoVITS v2ProPlus 官方整合包：从 [RVC-Boss/GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) 的 Releases 获取，放到项目同级目录，推荐目录名 GPT-SoVITS-v2pro-20250604。也可以用 GPT_SOVITS_ROOT 指向其他目录。
- ffmpeg：Windows 可用 [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) 或 [BtbN builds](https://github.com/BtbN/FFmpeg-Builds/releases)，Linux/macOS 用系统包管理器。程序先查 FFMPEG_BIN、PATH，再查 GPT-SoVITS runtime。
- Live2D Cubism 模型（可选）：通过 LIVE2D_MODEL_ROOT 指定；缺失时数字主播页显示缺失提示，直播台和语音功能仍可用。

GPT-SoVITS 目录至少需要这些文件：

~~~text
GPT_SoVITS/pretrained_models/s1v3.ckpt
GPT_SoVITS/pretrained_models/v2Pro/s2Gv2ProPlus.pth
GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt
runtime/python.exe                 # Windows 整合包
runtime/python                    # Linux/macOS 整合包
~~~

本项目通过 scripts/gpt_sovits_api.py 启动包装服务，监听 9881。不要把第三方应用的 9880 当成本项目服务。

## 获取与初始化

~~~bash
git lfs install
git clone https://github.com/seelevoila/car-live-deployment.git
cd car-live-deployment
git lfs pull
python scripts/setup_rag_models.py
~~~

正常情况下，脚本会输出 All bundled RAG models passed local manifest checks; no download needed. 如果 LFS 文件缺失或校验失败，脚本会从固定 revision 的 Hugging Face 模型下载；国内网络可使用 --endpoint https://hf-mirror.com。模型来源和 revision 记录在 models/rag/*/manifest.json：

- Xenova/bge-small-zh-v1.5，revision 75c43b069aac4d136ba6bc1122f995fedcfd2781
- Xenova/bge-reranker-base，revision 280bcc27a84e0b898c251e06fddb25171bd9b101

复制配置并按机器修改：

~~~powershell
Copy-Item backend/.env.example backend/.env
~~~

最小 GPT-SoVITS 配置：

~~~dotenv
TTS_PROVIDER=gpt-sovits
GPT_SOVITS_URL=http://127.0.0.1:9881
GPT_SOVITS_ADAPTATION_ENABLED=true
~~~

可选的大模型配置通过页面“模型接口”保存，也可以在 .env 中设置 LLM_BASE_URL、LLM_MODEL 和 LLM_API_KEY。未配置时使用本地抽取式问答回退。不要提交 backend/.env 或 API Key。

## 启动

### Windows 原生

~~~powershell
Copy-Item backend/.env.example backend/.env
powershell -ExecutionPolicy Bypass -File .\start.ps1
~~~

也可以双击 启动汽车直播智能体.cmd。脚本会检查 8000、5173 和 9881 的占用者，只停止带有本项目命令行的旧进程；发现其他程序占用时会报出 PID 并停止启动。

### Linux / macOS

~~~bash
python3.12 -m venv .venv
.venv/bin/pip install -e .
cp backend/.env.example backend/.env
chmod +x start.sh
./start.sh
~~~

start.sh 使用 lsof、ss 或 fuser 检查端口，并在确认进程属于本项目后清理旧进程。缺少端口查询工具时不会静默杀掉未知进程。

### uv

~~~bash
uv sync
uv run python scripts/setup_rag_models.py
uv run python start.py
~~~

pyproject.toml 固定 Python 版本范围和后端依赖。uv 管理的环境与 .venv 方式并存；start.py 会优先使用当前 uv/虚拟环境解释器。

启动后访问：

- [前端](http://127.0.0.1:5173)
- [API 文档](http://127.0.0.1:8000/docs)
- [GPT-SoVITS 状态](http://127.0.0.1:8000/api/tts/status)

页面显示“语音服务未就绪”时，先确认 9881 已启动并检查 backend-runtime.log、gpt-runtime-error.log 或 logs/gpt-sovits.log。

## 使用自定义音色

在音色管理中上传一段清晰的单人录音，并填写与录音逐字一致的原文。辅助录音只有在填写对应原文时才参与短时适配。创建后流程为：素材预检 → 从官方 v2ProPlus 底模训练该音色的独立声学权重 → checked 合成验收 → 恢复常驻模型 → 发布 profile。训练预算默认约 30 秒、最多 24 次有效更新；排队、验收和 GPU 速度会影响总耗时。

data/voice_models/、data/uploads/ 和 data/car_live.db 是本机状态，不会随仓库分发。新环境需要重新创建自定义音色；三套内置音色“沉稳阿川”“活力小桃”“亲切阿诚”可直接使用。

## 自检

~~~bash
python -m pytest backend/tests -q
node --test frontend/tests/*.test.cjs
python scripts/setup_rag_models.py
~~~

打开页面后应能看到三套内置音色；选择音色可试听；知识库页可导入资料并建立索引；直播台可创建会话、生成话术、播报和修改话术；数字主播在有 Live2D 模型时显示模型，缺失时明确提示；未配置 LLM 时问答页显示本地回退状态。

## 已知边界

- GPT-SoVITS 无独立情绪通道，音色相似度和情绪表现仍取决于参考录音、底模和硬件，不能保证每个新克隆都比零样本更像。
- 首音频延迟受 GPU、模型预热、语义检查和参考音频缓存影响；缓存命中时间不能代表冷启动延迟。
- 无 NVIDIA GPU 时可尝试 CPU 配置，但速度会明显变慢，不能按 GPU 的延迟预期使用。
- GPT-SoVITS 整合包、权重、Live2D 模型和 LLM API Key 需要用户自备；仓库只随附 RAG 模型和内置音色参考音频。
- data/preset_voices/*.wav 是随项目发布的第三方角色参考素材，仅用于本项目演示和测试。
