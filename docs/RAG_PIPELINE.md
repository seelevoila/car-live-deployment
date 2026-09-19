# 语义检索方案（2026-09-08）

当前运行链路：资料脱敏 → 结构分块 → BGE 语义向量 → FAISS 与 BM25 双路召回 → RRF 融合 → BGE 交叉编码器重排 → 完整父块与动力范围检查 → 已配置的大模型生成 → 数值及部分功能承诺检查。失败原因随接口返回；没有用哈希向量冒充语义模型。

## 模型与资源

| 用途 | 当前模型 | 部署 |
|---|---|---|
| Embedding | BAAI/bge-small-zh-v1.5，Xenova ONNX 导出 | INT8，512维，CPU，2线程 |
| Reranker | BAAI/bge-reranker-base，Xenova ONNX 导出 | INT8交叉编码器，CPU，逐对推理 |
| 回答和口播 | 页面配置的大模型 | 独立于本地检索模型；本次实测使用现有 DeepSeek 配置 |
| 播报 | GPT-SoVITS | 延用已有独立语音服务 |

此电脑为 8GB 显存的 RTX 4060 Laptop，总内存约16GB；开始工作时空闲内存约3GB。Qwen3-Embedding-8B 的 FP16 权重约16GB，无法与语音模型直接在此显卡共驻。本次选择适合中文小型车型库的 BGE，并固定 CPU 推理，不分配 CUDA 显存。两个 ONNX 模型权重合计约289MiB，另有约17MiB tokenizer。

模型安装：

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe scripts\setup_rag_models.py
# 直连 Hugging Face 不可达时：
.\.venv\Scripts\python.exe scripts\setup_rag_models.py --endpoint https://hf-mirror.com
```

下载脚本固定仓库 revision，并校验大文件的 LFS SHA256。下载记录在 `models/rag/*/manifest.json`。推理期间不下载模型、不加载远程代码。缺失模型会报错，不自动退回旧哈希实现。更换模型需修改 `rag_models.embed()` 的模型适配（包括 tokenizer、池化和查询前缀），并重建全部向量；Qwen 的池化与 BGE 不同，不能只替换文件名。

## 分块、索引、召回与重排

分块参考 [Chonkie 的 RecursiveChunker / SentenceChunker](https://github.com/chonkie-inc/chonkie#-chunkers) 的层次边界思路。本次采用项目内结构解析器，**没有宣称安装或调用 Chonkie 的 SemanticChunker**。对这两份格式稳定的资料，字段行、章节标题和问答对比固定字数更可靠。

- 参数：按价格、充电续航、动力、空间、辅助驾驶等类别形成父块；每个完整字段为检索子块。小块用于精确召回，同类字段一起给生成模型。
- 话术：按中文章节标题解析，保留问题别名和完整回复；长回复产生多个子块，命中后返回完整问答。没有“回复”字段的天幕段也可读取。
- 每块保存资料类型、动力范围、车型族、原文、父块、版本、页码和自动核对提示。资料库原始文件保持可追溯。
- BGE 用 CLS 池化、L2 归一化，查询端加官方检索指令；SQLite 保存512维 float32 向量。
- FAISS `IndexIDMap2(IndexFlatIP)` 保存实际向量索引。当前库很小，采用精确内积检索；未声称已实现海量库 ANN 性能。
- BM25 基于中文双字词和英文数字词元；与向量路各取最多24个候选。RRF 使用常数60融合，父块去重后默认重排12个候选。
- 独立 BGE Reranker 对“问题、候选片段”成对推理。最终排序兼顾动力专属政策；接口分别暴露原始神经分数和融合分数，相关度不是答案正确概率。
- 显式动力问题优先于当前页面选择，品牌与车型族继续隔离。通用话术可服务同车系 EV；其他配置的参数不会无条件混入。

`data/car_live.rag-index/vectors.faiss` 与 `manifest.json` 是持久化索引。SQLite触发器追踪增删改版本，查询先读取一致的版本快照；更新后使结果缓存失效、重建衍生索引。失败事务回滚不发布新索引。更改品牌、车系、年款还会重新分块编码。过期资料在每次检索时排除；已删除资料不能从旧缓存回流。

## 生成与资料冲突

- 原参数中的45.48万、50.80万区间与13.38万配置价格不一致；区间字段保留在原文检查中，隔离出生成依据。13.38万保留“资料记载、单位有疑点、需要核实”的限定。
- 话术燃油价格段标题／问题与回复动力类型矛盾，隔离报价；不会将误写的7.98万套给纯电版。
- 7000／10000置换及24期6万／36期8万分期保留不同范围与待核实提示；不自行取最大优惠。
- 生成上下文剔除无关促销与“小风车”等操作指令。门店实时库存未接入时直接说明资料边界。
- 口播按用户卖点检索，优先具体参数；如发现无依据数值或部分功能承诺，允许一次收紧条件的重写，再失败则返回带原因的资料提纲。
- DeepSeek适配对其官方域名明确关闭默认推理模式，避免短输出额度全部消耗在推理内容而造成空正文；其他服务不发送此供应商专用字段。

检查器能拦截部分数字和功能错误，**不是通用事实验证器**。资料质量与生成模型能力仍决定最终质量；“70条命中”仅指本地测试集的证据召回，不能解释为所有直播回答100%正确。政策仍需补充正式来源、日期及适用条件。

## 使用与复现

页面：知识库 → **检索索引与资料检查**，可查看模型、维度、子块数量、冲突记录，试查两路召回和重排，也可重建索引。直播台／数字主播中的问答显示生成方式、重排相关度和资料提醒。

| 接口 | 用途 |
|---|---|
| GET `/api/rag/status` | 模型、维度、索引版本与完整性 |
| GET `/api/rag/quality` | 冲突原文与核对提示 |
| POST `/api/rag/search` | 不调用大模型的检索调试，参数同 `/api/query` |
| POST `/api/rag/reindex` | 从当前文档重建语义索引 |
| POST `/api/query` | 返回答案、来源、检索追踪和生成状态 |
| POST `/api/script/generate` | 卖点生成口播，支持delivery与duration_seconds |

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -q
.\.venv\Scripts\python.exe scripts\evaluate_rag.py
# 同时调用已配置的大模型，记录真实答案和口播：
.\.venv\Scripts\python.exe scripts\evaluate_rag.py --llm
```

模型依据：[BGE Embedding](https://huggingface.co/BAAI/bge-small-zh-v1.5)、[BGE Reranker](https://huggingface.co/BAAI/bge-reranker-base)。本轮证据保存在 `artifacts/rag-upgrade-2026-09-08/`；未重新打包提交源码ZIP。
