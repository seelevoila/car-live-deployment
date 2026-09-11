# 汽车直播智能体

本仓库是可在新电脑部署的精简版汽车直播智能体，包含知识库、车型问答、流式语音播报、音色管理和 Live2D 数字主播界面。

## 快速部署（Windows）

要求：Windows 10/11、Python 3.10+，建议 8 GB 以上内存和 10 GB 可用磁盘空间。

```powershell
git clone https://github.com/seelevoila/car-live-deployment.git
cd car-live-deployment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
Copy-Item backend\.env.example backend\.env
python scripts\setup_rag_models.py
powershell -ExecutionPolicy Bypass -File .\start.ps1 -OpenBrowser
```

然后访问 `http://127.0.0.1:5173`。首次启动会自动创建 `data/car_live.db` 并导入 `data/sample` 中的示例资料。

## 语音服务

界面和知识库不依赖本仓库之外的模型即可启动；要使用服务端语音，需要单独部署 IndexTTS-2.5 HTTP 服务或 GPT-SoVITS，并在 `backend/.env` 中配置对应地址。详细步骤见 [DEPLOYMENT.md](DEPLOYMENT.md)。未配置服务时，页面仍可使用浏览器语音回退。

预置主播音频保存在 `data/preset_voices`，因此克隆仓库后可以直接试听内置音色。

## 可选配置

- `LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY`：接入 OpenAI 兼容大模型；不配置时使用本地抽取式问答。
- `LIVE2D_MODEL_ROOT`、`LIVE2D_MODEL_FILE`：配置本机 Live2D 模型；未配置时数字主播页面仍可打开。
- `INDEX_TTS2_URL`：配置独立 IndexTTS-2.5 服务。

## 常用命令

```powershell
# 检查服务和功能
powershell -ExecutionPolicy Bypass -File .\verify.ps1

# 安装或移除 Windows 登录后自动启动
powershell -ExecutionPolicy Bypass -File .\install-startup.ps1
powershell -ExecutionPolicy Bypass -File .\install-startup.ps1 -Remove
```

运行数据、上传文件、数据库、模型缓存、日志和本地模型源码均不会提交到仓库。
