from pathlib import Path
p=Path(__file__).resolve().parents[1]/'backend/app/main.py'
s=p.read_text(encoding='utf-8')
start=s.index('def _llm_endpoint():')
end=s.index('@app.post("/api/tts/synthesize")',start)
s=s[:start]+'''def _llm_endpoint():
    return llm_gateway.endpoint()


def _llm_answer(question, sources):
    return llm_gateway.generate(question,sources)


'''+s[end:]
old='''                        acquired = await asyncio.to_thread(_acquire_tts_lock, "foreground", 20)
                        if not acquired:
                            raise RuntimeError("语音引擎正在处理上一条请求，请稍后重试")
                        try:
'''
assert s.count(old)==2
s=s.replace(old,'''                        async with _async_tts_lock():
''')
s=s.replace('''                        finally:
                            _release_tts_lock()
''','')
s=s.replace('''    profile = _voice_model_profile(voice_id)
    VOICE_PROFILE_WARMING.add(voice_id)''','''    profile = _voice_model_profile(voice_id)
    if _ACTIVE_MODEL_PROFILE == profile:
        return
    VOICE_PROFILE_WARMING.add(voice_id)''')
# Bound optional priming; it must never hold the whole UI in a permanent warmup state.
start=s.index('def _prime_voice_profile')
end=s.index('def _voice_calibration_worker',start)
part=s[start:end].replace('with _tts_lock(priority="foreground"):', 'with _tts_lock(priority="foreground", timeout=20):')
s=s[:start]+part+s[end:]
s=s.replace('''"llm": {"mode": "openai-compatible" if llm_ready else "local", "provider": "OpenAI-compatible" if llm_ready else "local-extractive", "ready": True, "enhanced": llm_ready},''','''"llm": llm_gateway.status(),''')
s=s.replace('''    return {"answer": answer, "confidence": confidence, "provider": provider, "latency_ms": int((time.perf_counter() - start) * 1000), "sources": sources}''','''    latency=int((time.perf_counter()-start)*1000)
    log_event('question',vehicle=' / '.join(x for x in [q.brand,q.series,q.year] if x),question=q.question,latency_ms=latency,
              details={'provider':provider,'sources':[{'document_name':x['document_name'],'version':x.get('version',1)} for x in sources]})
    return {"answer": answer, "confidence": confidence, "provider": provider, "latency_ms": latency, "sources": sources,
            "model_configured": llm_gateway.status()['configured']}
''')
start=s.index('def generate_script(req: ScriptRequest):')
end=s.index('@app.get("/api/voices")',start)
s=s[:start]+'''def generate_script(req: ScriptRequest):
    sources = retrieve(req.selling_points, req.brand, req.series, req.year, 5)
    generated=llm_gateway.generate(req.selling_points,sources,task='script')
    if generated:
        return {'script':generated,'sources':sources,'provider':'llm-grounded-rag'}
    facts=[]
    for topic in ['续航','电池容量','最大功率','轴距','辅助泊车入位']:
        relevant=retrieve(topic,req.brand,req.series,req.year,3)
        answer=_short_answer(topic,relevant)
        if answer!=INSUFFICIENT_ANSWER and answer not in facts: facts.append(answer)
    script=f"大家好，欢迎来到直播间！今天一起了解{req.brand}{req.series}。\\n"
    script+='\\n'.join(f'我们来看看{fact}。' for fact in facts[:4])
    script+='\\n大家更关注续航、空间还是配置？欢迎在评论区告诉我，我们根据车型资料逐一解答。'
    if not facts: script=f'欢迎来到直播间！今天介绍{req.brand}{req.series}。当前资料不足，请先补充车型参数后生成讲解内容。'
    return {'script':script,'sources':sources,'provider':'local-grounded-outline',
            'notice':'当前按资料生成讲解提纲；接入大模型后将使用卖点生成完整话术，未核实的卖点不会直接作为事实播报。'}


'''+s[end:]
s=s.replace('''"meets_target": bool(valid and max(valid) <= 3000),''','''"meets_target": bool(len(valid) == len(samples) and max(valid) <= 3000),''')
s+='\n\nfrom .business import router as business_router, log_event\napp.include_router(business_router)\n'
p.write_text(s,encoding='utf-8')
