# RAG Models

This directory contains the exact ONNX INT8 models used by the application:

| Role | Source | Pinned revision | Model size |
| --- | --- | --- | ---: |
| Embedding | [Xenova/bge-small-zh-v1.5](https://huggingface.co/Xenova/bge-small-zh-v1.5) | `75c43b069aac4d136ba6bc1122f995fedcfd2781` | 24,010,842 bytes |
| Reranker | [Xenova/bge-reranker-base](https://huggingface.co/Xenova/bge-reranker-base) | `280bcc27a84e0b898c251e06fddb25171bd9b101` | 279,301,077 bytes |

The Embedding model is stored directly. GitHub's 100 MB file limit means the
Reranker model is stored as three repository parts under 100 MB each. After
cloning, run this from the repository root to join and verify it:

```powershell
python scripts\setup_rag_models.py
```

The script joins the bundled parts and checks the local manifests first, so a
complete checkout needs no network access. It downloads from the pinned public
model source only when a bundled file is missing or invalid.
The generated `model_quantized.onnx` is ignored locally and is never committed
as a fourth copy. `manifest.json` records SHA256 checksums for every model file.
Git attributes preserve model and tokenizer bytes on Windows and Linux.
