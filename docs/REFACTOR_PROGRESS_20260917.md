# 重构任务进度报告 - 2026-09-17

> 历史进度报告。当前运行链路只保留 GPT-SoVITS；现行部署说明以根目录 `README.md` 和 `DEPLOYMENT.md` 为准。

## 已完成任务

### ✅ 任务 D：GPT-SoVITS 真正接通（100%）

**成果**：
- GPT-SoVITS 服务成功运行在 9880 端口
- 后端 TTS 状态：ready=true, reachable=true
- 测试合成：3/3 样本成功，平均延迟 1557.5ms
- CUDA 支持：已启用

**关键修复**：
- backend/.env: 修正 PYTHON 路径（runtime/python.exe）
- start.ps1: 自动探测 v2pro 目录，支持跨平台解释器路径
- start.ps1: 自动验证并修正 tts_infer.yaml 权重配置
- main.py: 移除 CanMV IDE 硬编码，添加 GPT-SoVITS runtime/ffmpeg.exe

**提交**：01fe1bd, 54dbe22

---

### ✅ 任务 A：清理与瘦身（85%）

**回收空间**：~1.93GB

**已完成**：
- ✅ A1：删除零引用文件
  - 12 个根目录日志 (564KB)
  - 3 个散落音频 (398KB)
  - 2 个孤立 HTML
  - 所有 __pycache__ 和 .pytest_cache
- ✅ A2：归位文件
  - 2 个 docx → docs/reference/
  - 3 个脚本 → tools/oneoff/
- ✅ A3：嵌套副本处理
  - test/backend/ → .trash/ (20KB)
- ✅ A4：submission 瘦身
  - 5 个备份目录 (5.1MB)
  - 4 组 QA 截图 (24MB)
  - 中间文件 (~1MB)
  - 瘦身后：36MB（从 64MB）
- ✅ A5：artifacts 治理
  - astra-v1-base/ (1.8GB)
  - 5 个历史验证目录
  - 历史微调权重已在当前清理中移除，不属于现行运行链路

**归档位置**：
```
.trash/logs-20260917/                972KB
.trash/test-backend-20260917/         20KB
.trash/submission-cleanup-20260917/   30MB
.trash/artifacts-archive-20260917/   1.9GB
```

**未完成**（15%）：
- ⏳ A6：合并重复脚本（3 份 create_deployment_package*.ps1）
- ⏳ A6：frontend/app-fixes.js 合并
- ⏳ A7：统一 .gitignore 与 .deployignore

**提交**：大型提交（.trash/ 未纳入 git）

---

### ✅ 任务 C：跨平台移植（30%）

**已完成**：
- ✅ C1：消除 config.py 本机绑定
  - 新增 backend/app/runtime_paths.py
  - 自动探测：GPT-SoVITS、Live2D、ffmpeg
  - 支持环境变量优先级
  - 支持 Windows/Linux venv 布局和 runtime/ 布局
  - 探测结果已验证（6/6 路径正确）

**进行中**：
- ⏳ C2：移除 Windows venv 布局硬编码（config.py 已完成，需处理 verify.ps1）
- ⏳ C3：重写 start.ps1 GPT-SoVITS 启动段（部分完成）
- ⏳ C4：启动器二义性（需决策）
- ⏳ C5：进程探测平台化
- ⏳ C6：新增跨平台启动器（start.sh, start.py）
- ⏳ C7：scripts/package_release.py 替代 PS1
- ⏳ C8：前端去写死后端地址
- ⏳ C9：ffmpeg 依赖扫清（main.py 已完成）
- ⏳ C10：文档修正
- ⏳ C11：数据可移植性

**提交**：490cf2e

---

### ⏳ 任务 B：结构优化（0%）

**未开始**（风险最高，放在最后）：
- B1：拆分 backend/app/main.py（3032 行）
- B2：前端整理
- B3：入口收敛
- B4：目录树文档

---

### ⏳ 任务 E：验收（0%）

**待完成**：
- E1：Windows 验收
- E2：Linux 验收
- E3：结构验收
- E4：产出 docs/MIGRATION_2026.md

---

## 提交历史

```
a0d499f - chore: snapshot before major refactor
01fe1bd - fix(tts): wire GPT-SoVITS v2pro package and fix startup paths
54dbe22 - docs: add Task D evidence and verification results
[cleanup] - refactor: clean up redundant files (1.93GB)
490cf2e - refactor(config): add cross-platform runtime path detection
```

## 下一步行动

1. **继续任务 C**（优先级最高）：
   - C6：创建 start.sh 和 start.py
   - C8：前端 API 地址改为相对路径
   - C10：修正文档中的绝对路径

2. **完成任务 A 遗留**：
   - 合并 3 份打包脚本
   - 合并 app-fixes.js

3. **任务 B**（最后执行）：
   - 拆分 main.py

4. **任务 E**：
   - 双平台验收
   - 输出迁移文档

## 当前状态

- ✅ GPT-SoVITS 服务正常运行
- ✅ 后端可正常启动
- ✅ 路径探测机制工作正常
- ⚠️  前端地址仍硬编码 127.0.0.1:8000
- ⚠️  启动脚本仅 Windows (start.ps1)
- ⚠️  main.py 仍为 3032 行单文件

## 风险评估

**低风险**：
- 路径探测已验证，配置加载正常
- 清理的文件都有归档备份

**中风险**：
- 跨平台启动脚本需要测试
- 文档修正工作量较大

**高风险**：
- main.py 拆分（3032 行）需要充分测试
- 任何路由或响应变更可能破坏前端

## 资源消耗

- Token 使用：~72K / 200K（36%）
- 剩余：128K tokens
- 任务完成度：约 40%
