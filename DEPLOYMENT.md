# 部署说明

## 环境要求

- Windows 10/11
- Python 3.10 或更高版本
- 8 GB 以上内存，至少 10 GB 可用磁盘空间
- 服务端语音需要单独运行 IndexTTS-2.5 或 GPT-SoVITS；没有 TTS 服务时页面会回退浏览器语音

## 首次安装

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
Copy-Item backend\.env.example backend\.env
```

运行 `python scripts\setup_rag_models.py` 会自动合并仓库内的 Reranker 分片，并校验 Embedding、Reranker、分词器和配置，共约 306 MiB；完成后可在本地 CPU 上离线运行知识库检索。

在已有仓库中更新模型：

```powershell
git pull --ff-only
python scripts\setup_rag_models.py
```

如果模型分片不完整，脚本会从公开模型源下载相同版本：

```powershell
python scripts\setup_rag_models.py
```

无法访问 Hugging Face 时可使用：

```powershell
python scripts\setup_rag_models.py --endpoint https://hf-mirror.com
```

## 配置语音

### IndexTTS-2.5 HTTP 服务

在独立的 IndexTTS2 官方目录安装依赖并准备 2.5 checkpoints，然后使用本仓库提供的包装服务：

在 IndexTTS2 官方 checkout 根目录执行（把路径替换为本仓库实际位置）：

```powershell
python C:\path\to\car-live-deployment\scripts\index_tts2_server.py --port 8001 --cfg-path checkpoints\config.yaml --model-dir checkpoints
```

在 `backend/.env` 中设置：

```dotenv
TTS_PROVIDER=idextts2
INDEX_TTS2_URL=http://127.0.0.1:8001
```

也可以把 `INDEX_TTS2_URL` 指向另一台电脑上的兼容 HTTP 服务。服务需要提供 `GET /health` 和 `POST /tts`。

### GPT-SoVITS

先单独启动 GPT-SoVITS API，再在 `backend/.env` 中设置：

```dotenv
TTS_PROVIDER=gpt-sovits
GPT_SOVITS_URL=http://127.0.0.1:9880
```

启动脚本会自动使用同级目录中的 GPT-SoVITS（如果存在），也可以只使用外部服务。

## 启动

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 -OpenBrowser
```

或双击 `启动汽车直播智能体.cmd`。访问 `http://127.0.0.1:5173`，API 文档在 `http://127.0.0.1:8000/docs`。

首次启动会创建 `data/car_live.db`，并把 `data/sample` 中的两份示例资料导入知识库。以后上传的资料和音色只保存在本机的 `data` 目录。

## 可选功能

在 `backend/.env` 中配置 `LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY` 可接入 OpenAI 兼容大模型；不配置时使用本地抽取式问答。配置 `LIVE2D_MODEL_ROOT` 和 `LIVE2D_MODEL_FILE` 后，数字主播页面会加载本机 Live2D 模型。

## 检查与停止

```powershell
powershell -ExecutionPolicy Bypass -File .\verify.ps1
```

停止服务可在任务管理器中结束本项目的 Python 进程。日志会写入根目录，仅用于本机排障，不应提交到 Git。
