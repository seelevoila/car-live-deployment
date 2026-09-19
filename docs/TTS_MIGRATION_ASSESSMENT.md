# TTS 迁移评估：AstraTTS V1 与 C# + ONNX Runtime

评估日期：2026-09-09

> 历史评估文档。当前项目不包含 AstraTTS 或其他替代 TTS provider，生产和克隆功能统一使用 GPT-SoVITS；下文的迁移方案不属于当前部署步骤。

## 结论

当前项目**不适合立即把默认推理链路切换为 C# + ONNX Runtime**。AstraTTS V1 适合作为隔离的灰度 provider，待资源、GPU provider、音频一致性和现有功能验收全部通过后再切换默认值。

本文评估时的默认值：

```text
TTS_PROVIDER=gpt-sovits
```

本次没有把默认推理迁移到 C# + ONNX；直播链路做了兼容性优化，仍通过现有 GPT-SoVITS HTTP 服务输出 WAV/PCM。

## 已落地的低风险优化

- 前端将最多三个自然短语合并为一个有界 `stream_batch`，后端只对该批次建立一次 GPT-SoVITS 流式请求，保留模型内部的语义连续性。
- 服务端只做一次文本归一化，`30%`、单位和引用标记在进入模型前统一处理；批次请求不会再次按短语切分。
- 克隆音色直播在没有显式覆盖时使用有界表达力下限（`top_k=18`、`top_p=0.72`、`temperature=0.66`），避免校准得到的保守参数把语气完全压平；试听仍使用音色校准结果。
- 改稿时，尚未出声的批次可以取消并从编辑位置重新生成；已经进入播放设备的批次保持完整，在自然批次边界应用新稿。
- `GPT_SOVITS_LIVE_*` 与 `GPT_SOVITS_CLONE_LIVE_*` 已加入配置示例，直播语言默认固定为 `zh`；具备完整多语种前端资源时可显式改为 `auto`。

## 已验证的可行部分

- 本机安装 .NET SDK 8.0.405，Windows x64；机器有 RTX 4060 Laptop GPU。
- AstraTTS 官方 V1 转换器可以读取当前 `s1v3.ckpt` 和 `s2Gv2ProPlus.pth`。
- 当前基础模型的权重覆盖检查通过：GPT 语义模型 295/295，SoVITS/VITS 650/650，提示编码器 23/23。
- 转换器生成的五个 ONNX 分片均通过 `onnx.checker`，并可由 CPU Execution Provider 建立会话。
- AstraTTS V1 的 `PredictStreamAsync`、KV cache 和 `AudioPipeline` 能提供单次长文本流式推理、跨块 CrossFade、PCM 输出和取消令牌，这些方向可以解决当前每个短语重复请求造成的连续性问题。

## 不能据此直接切换的原因

### 1. ONNX 模型还没有完成等价性验收

模板的 `ssl_proj` 输入形状是 `[768, 768, 2]`，当前 V2ProPlus 权重是 `[192, 768, 1]`。AstraTTS 转换器对该层使用自适应填充/复制才能生成文件。文件能够加载不代表输出与 PyTorch 等价，必须用同一参考音频、同一文本逐句比较音频有效率、时长、ASR 文本和音色相似度。

### 2. C# 运行时需要额外的共享模型资源

AstraTTS V1 不只需要五个 TTS ONNX 分片，还需要 HuBERT、RoBERTa、speaker encoder、中文/英文 G2P 词典和 tokenizer。当前项目已有的主要是 PyTorch 模型；`g2pw.onnx` 不能替代全部资源。官方 `resources-minimal` 资源包约 1.2 GB，尚未纳入本项目，也没有完成资源许可、路径和发布流程。

### 3. 当前 GPU 加速条件未满足

当前 GPT-SoVITS 的 PyTorch CUDA 可用，但本机 ONNX Runtime CUDA provider 因缺少 `cublasLt64_13.dll` 无法加载。C# 使用 CUDA 或 DirectML 仍需要单独验证和打包 provider。若退回 CPU，T2S、VITS 和参考音频特征提取可能无法达到题目要求的首包延迟 ≤3 秒。

### 4. 现有音色功能存在行为差异

- 当前项目使用官方 `base` GPT-SoVITS profile，并按已安装的通用克隆 profile 动态切换。
- AstraTTS V1 的配置模型是 Avatar/Reference；需要为数据库中的每个克隆音色建立动态映射和参考特征缓存。
- 当前克隆验收、辅助参考音频筛选和后台采样校准依赖 GPT-SoVITS 的推理接口。
- AstraTTS V1 是确定性生成，不能保留当前 `top_k`、`top_p`、`temperature` 校准行为。直接切换会改变克隆音色的语气、韵律和可重复性。

### 5. 现有接口和播放器需要适配

当前 `/api/tts/stream` 发送的是 GPT-SoVITS 的 WAV 流，前端按 WAV 头和 PCM 块播放，并在请求之间做短语队列。AstraTTS 的核心接口输出裸 PCM 并由 `AudioPipeline` 维护跨块状态。若不增加兼容适配器，会影响试听下载、直播播放、断句取消和 Live2D 嘴型时间轴。

## 对其他功能的影响

| 功能 | 直接切换风险 | 说明 |
| --- | --- | --- |
| 直播播报 | 高 | 需要把多次短语请求改为单会话流，并保持取消和顺序语义 |
| 首包延迟 | 未知 | CPU ONNX 未测；GPU provider 当前未就绪 |
| 快速克隆 | 高 | 需要 C# 侧参考音频特征缓存、G2P、BERT/Hubert 和真实合成验收 |
| 音色采样校准 | 高 | V1 不支持现有 TopK/TopP/Temperature 采样契约 |
| 试听/下载 | 中 | PCM/WAV 格式和结束标记需要兼容层 |
| Live2D 嘴型 | 中 | 需要确保块时长、采样率和结束事件与现有时间轴一致 |
| RAG、问答、直播间接口 | 低 | 只要 provider 保持后端 API 契约，业务逻辑无需变化 |

## 允许进入灰度的验收门槛

1. 在 .NET 8 或 .NET 10 环境中编译 C# 服务，并锁定 ONNX Runtime provider；启动时报告实际使用的 CPU、CUDA 或 DirectML provider。
2. 补齐并固定 AstraTTS `resources` 目录，包含 HuBERT、RoBERTa、speaker encoder、tokenizer 和 G2P 资源。
3. 对基础音色和至少一个克隆音色各运行 30 条中英混合句：无吞字、漏读、异常静音；ASR 文本与输入一致率达到 95% 以上。
4. 测量冷启动、预热后和连续播报的首个可播放 PCM 块；预热后 P95 必须 ≤3 秒。
5. 验证参考音频上传、辅助参考音频、音色删除/编辑、取消请求、试听和 Live2D 嘴型时间轴。
6. 通过以上门槛后，仅将 `TTS_PROVIDER` 切换为新的 native provider，并保留 GPT-SoVITS 回退开关。

## 当前处理

- 当前唯一生产语音引擎为 `TTS_PROVIDER=gpt-sovits`；本评估中的其他 provider 没有接入启动链路。
- 不启动未完成的 C# 服务，AstraTTS 配置字段保持为独立实验入口。
- 本次生成的 ONNX 文件只用于转换和结构验证，不作为已验收的生产模型。
