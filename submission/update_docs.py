# -*- coding: utf-8 -*-
"""Update competition materials to reflect BGE semantic RAG upgrade"""
import re

def update_build_script():
    with open('build_materials_v2.py', 'r', encoding='utf-8') as f:
        content = f.read()

    # Update version numbers from v1.2 to v1.3
    content = re.sub(r'"v1\.2"', '"v1.3"', content)

    # Update system design architecture description
    old_arch = "系统采用前后端分层和本地服务组合。浏览器只负责交互和音频排程；FastAPI 负责会话、版本、检索和流式接口；SQLite 负责可追踪数据；GPT-SoVITS 负责克隆音色和生成 PCM WAV。模块之间以 HTTP/JSON 和流式字节协议连接，便于现场替换单个组件。"
    new_arch = "系统采用前后端分层和本地服务组合。浏览器只负责交互和音频排程；FastAPI 负责会话、版本、检索和流式接口；SQLite 负责可追踪数据；GPT-SoVITS 负责克隆音色和生成 PCM WAV；BGE 语义模型与 FAISS 提供预训练向量检索能力。模块之间以 HTTP/JSON 和流式字节协议连接，便于现场替换单个组件。"
    content = content.replace(old_arch, new_arch)

    # Update RAG description
    old_rag = "检索采用词法命中与稳定哈希向量混合排序，答案生成优先使用字段级抽取，避免模型在关键参数上自行补写。"
    new_rag = "检索采用 BGE 中文语义向量（512 维）与 BM25 词法混合召回、RRF 融合、BGE 交叉编码器重排序，支持父子分块与动力范围检查。答案生成优先使用字段级抽取，可选接入外部大模型增强生成。"
    content = content.replace(old_rag, new_rag)

    # Update data flow description
    old_flow = "资料流：文件上传 -> 类型解析 -> 文本清洗 -> 片段切分 -> 哈希向量 / 词法索引 -> SQLite -> 检索结果带来源。"
    new_flow = "资料流：文件上传 -> 类型解析 -> 文本清洗 -> 父子分块 -> BGE 语义向量 / BM25 索引 -> FAISS / SQLite -> 混合检索带来源。"
    content = content.replace(old_flow, new_flow)

    # Update model layer
    old_model = '[["模型层", "GPT-SoVITS v2ProPlus", "参考音频 + 文本 -> PCM", "回退预置音色或浏览器语音"]]'
    new_model = '[["模型层", "GPT-SoVITS + BGE 语义检索", "参考音频/问题 -> PCM/证据", "回退预置音色或浏览器语音"]]'
    content = content.replace(old_model, new_model)

    # Update business layer fallback
    old_business = '[["业务层", "脚本会话、动态改稿、问答编排", "会话版本、检索结果", "使用本地抽取式问答"]]'
    new_business = '[["业务层", "脚本会话、动态改稿、问答编排", "会话版本、检索结果", "未配置LLM时使用本地摘录"]]'
    content = content.replace(old_business, new_business)

    # Update test report - unit tests
    old_tests = '[["单元测试", "35", "35 passed", "无失败", "通过"]]'
    new_tests = '[["后端单元测试", "72", "72 passed", "无失败", "通过"]]'
    content = content.replace(old_tests, new_tests)

    # Save updated content
    with open('build_materials_v2.py', 'w', encoding='utf-8') as f:
        f.write(content)

    print("Updated build_materials_v2.py successfully")

if __name__ == '__main__':
    update_build_script()
