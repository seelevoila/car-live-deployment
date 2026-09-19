"""Knowledge management, analytics and real human voice evaluations."""
from datetime import datetime,timezone,timedelta
import json
import logging
from uuid import uuid4
from typing import Literal
from fastapi import APIRouter,HTTPException,Body
from fastapi.responses import Response
from pydantic import BaseModel,Field
from .db import conn,now
from .compliance import redact
from . import llm_gateway

router=APIRouter(prefix='/api')


def log_event(kind,vehicle='',question='',seconds=0,latency_ms=0,details=None,event_id=None):
    with conn() as c:
        c.execute('INSERT OR IGNORE INTO analytics_events(id,kind,created_at,vehicle,question,seconds,latency_ms,details) VALUES(?,?,?,?,?,?,?,?)',
                  (event_id or uuid4().hex,kind,now(),vehicle,redact(question),seconds,latency_ms,json.dumps(details or {},ensure_ascii=False)))


class Batch(BaseModel):
    ids:list[int]=Field(min_length=1,max_length=200)
    brand:str|None=Field(default=None,max_length=100)
    series:str|None=Field(default=None,max_length=100)
    year:str|None=Field(default=None,max_length=20)
    source_url:str|None=Field(default=None,max_length=2000)
    license:str|None=Field(default=None,max_length=200)
    valid_until:str|None=Field(default=None,max_length=30)


@router.patch('/knowledge/batch')
def batch_update(req:Batch):
    changes=req.model_dump(exclude_none=True,exclude={'ids'})
    if not changes: raise HTTPException(422,'请填写需要更新的字段')
    if req.source_url and not req.source_url.startswith(('https://','http://')):
        raise HTTPException(422,'来源地址应以 http:// 或 https:// 开头')
    if req.valid_until:
        try: datetime.fromisoformat(req.valid_until)
        except ValueError: raise HTTPException(422,'有效期请填写 YYYY-MM-DD')
    ids=sorted(set(req.ids))
    marks=','.join('?' for _ in ids)
    with conn() as c:
        rows=c.execute(f'SELECT * FROM documents WHERE id IN ({marks})',ids).fetchall()
        if len(rows)!=len(ids): raise HTTPException(404,'部分资料已不存在，请刷新后重试')
        for row in rows:
            version=row['version']+1
            c.execute(f"UPDATE documents SET {','.join(key+'=?' for key in changes)},version=?,updated_at=? WHERE id=?",[*changes.values(),version,now(),row['id']])
            total = row['chunks']
            if {'brand','series','year'}.intersection(changes):
                from pathlib import Path
                from .main import _write_chunks
                c.execute('DELETE FROM chunks WHERE document_id=?', (row['id'],))
                total = _write_chunks(c, row['id'], Path(row['path']))
                c.execute('UPDATE documents SET chunks=? WHERE id=?', (total,row['id']))
            metadata={key:changes.get(key,row[key]) for key in ['brand','series','year','source_url','license','valid_until']}
            c.execute('INSERT INTO document_versions(document_id,version,name,path,size,chunks,created_at,metadata) VALUES(?,?,?,?,?,?,?,?)',
                      (row['id'],version,row['name'],row['path'],row['size'],total,now(),json.dumps(metadata,ensure_ascii=False)))
    return {'updated':len(ids),'ids':ids}


@router.post('/knowledge/batch-delete')
def batch_delete(req:Batch):
    from .main import _unlink_owned_upload
    ids=sorted(set(req.ids))
    marks=','.join('?' for _ in ids)
    with conn() as c:
        found=c.execute(f'SELECT id FROM documents WHERE id IN ({marks})',ids).fetchall()
        if len(found)!=len(ids): raise HTTPException(404,'部分资料已不存在，请刷新后重试')
        paths=c.execute(f'SELECT path FROM document_versions WHERE document_id IN ({marks}) UNION SELECT path FROM documents WHERE id IN ({marks})',ids+ids).fetchall()
        c.execute(f'DELETE FROM documents WHERE id IN ({marks})',ids)
    for row in paths: _unlink_owned_upload(row['path'])
    return {'deleted':len(ids),'ids':ids}


@router.get('/knowledge/{did}/content')
def content(did:int):
    with conn() as c:
        document=c.execute('SELECT * FROM documents WHERE id=?',(did,)).fetchone()
        if not document: raise HTTPException(404,'资料不存在')
        chunks=[dict(x) for x in c.execute('SELECT id,content,page FROM chunks WHERE document_id=? ORDER BY id',(did,))]
    return {'document':{k:document[k] for k in ['id','name','version','brand','series','year','source_url','license','valid_until']},'chunks':chunks}


class PlaybackEvent(BaseModel):
    id:str=Field(min_length=1,max_length=100)
    kind:str=Field(pattern='^(playback|first_audio|revision)$')
    vehicle:str=Field(default='',max_length=200)
    seconds:float=Field(default=0,ge=0,le=30)
    latency_ms:float=Field(default=0,ge=0,le=300000)


@router.post('/analytics/events')
def event(req:PlaybackEvent):
    log_event(req.kind,vehicle=req.vehicle,seconds=req.seconds,latency_ms=req.latency_ms,event_id=req.id)
    if req.kind == 'first_audio':
        logging.getLogger('uvicorn.error').info('first_audio event: %s', json.dumps(req.model_dump(), ensure_ascii=False))
    return {'saved':True}


@router.get('/analytics')
def analytics(days:int=7):
    start=(datetime.now(timezone.utc)-timedelta(days=min(365,max(1,days)))).isoformat()
    with conn() as c:
        events=[dict(x) for x in c.execute('SELECT * FROM analytics_events WHERE created_at>=?',(start,))]
    questions=[e for e in events if e['kind']=='question']
    vehicles={};hotspots={};questions_count={}
    for e in questions:
        vehicles[e['vehicle'] or '未绑定车型']=vehicles.get(e['vehicle'] or '未绑定车型',0)+1
        questions_count[e['question']]=questions_count.get(e['question'],0)+1
        for item in json.loads(e['details']).get('sources',[]):
            label=f"{item['document_name']} · v{item.get('version',1)}"
            hotspots[label]=hotspots.get(label,0)+1
    rank=lambda values:[{'name':key,'count':value} for key,value in sorted(values.items(),key=lambda pair:pair[1],reverse=True)[:10]]
    first=[e['latency_ms'] for e in events if e['kind']=='first_audio']
    return {'days':days,'playback_seconds':round(sum(e['seconds'] for e in events if e['kind']=='playback'),2),
            'question_count':len(questions),'revision_count':sum(e['kind']=='revision' for e in events),
            'popular_vehicles':rank(vehicles),'retrieval_hotspots':rank(hotspots),'frequent_questions':rank(questions_count),
            'first_audio':{'count':len(first),'average_ms':round(sum(first)/len(first),1) if first else None,'max_ms':max(first) if first else None}}


class AnalyticsClear(BaseModel):
    # Omitted filters mean all historical analytics events, including questions.
    days: int | None = Field(default=None, ge=1, le=36500)
    scopes: list[Literal['playback', 'first_audio', 'revision', 'question']] | None = Field(default=None, min_length=1)


@router.post('/analytics/clear')
def clear_analytics(req: AnalyticsClear = Body(default_factory=AnalyticsClear)):
    clauses, values = [], []
    if req.days is not None:
        clauses.append('created_at>=?')
        values.append((datetime.now(timezone.utc)-timedelta(days=req.days)).isoformat())
    if req.scopes is not None:
        clauses.append('kind IN (' + ','.join('?' for _ in req.scopes) + ')')
        values.extend(req.scopes)
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    with conn() as c:
        deleted = c.execute('DELETE FROM analytics_events' + where, values).rowcount
    return {'deleted': deleted, 'days': req.days, 'scopes': req.scopes, 'all_history': req.days is None}


@router.get('/llm/status')
def model_status(): return llm_gateway.status()


@router.get('/voice-presets')
def voice_presets():
    from .main import voices
    return [voice for voice in voices() if voice['builtin']]


class PresetBinding(BaseModel):
    steady:str=Field(min_length=1,max_length=100)
    energetic:str=Field(min_length=1,max_length=100)
    friendly:str=Field(min_length=1,max_length=100)


@router.put('/voice-presets')
def bind_presets(req:PresetBinding):
    raise HTTPException(409, '内置主播已固定声音，无需绑定克隆音色；请在音色库直接选择要使用的声音')


@router.post('/llm/test')
def model_test(): return llm_gateway.probe()


class Evaluation(BaseModel):
    voice_id:str=Field(min_length=1,max_length=100)
    reviewer:str=Field(min_length=1,max_length=50)
    text:str=Field(min_length=10,max_length=2000)
    similarity:int=Field(ge=1,le=5)
    clarity:int=Field(ge=1,le=5)
    pause:int=Field(ge=1,le=5)
    emotion:int=Field(ge=1,le=5)
    overall:int=Field(ge=1,le=5)
    notes:str=Field(default='',max_length=1000)


@router.post('/voice-evaluations')
def save_evaluation(req:Evaluation):
    with conn() as c:
        if not c.execute('SELECT id FROM voices WHERE id=?',(req.voice_id,)).fetchone(): raise HTTPException(404,'音色不存在')
        c.execute('INSERT INTO voice_evaluations VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                  (uuid4().hex,now(),req.voice_id,redact(req.reviewer),redact(req.text),req.similarity,req.clarity,req.pause,req.emotion,req.overall,redact(req.notes)))
    return {'saved':True}


@router.get('/voice-evaluations')
def evaluations():
    with conn() as c:
        rows=[dict(x) for x in c.execute('SELECT * FROM voice_evaluations ORDER BY created_at DESC')]
    groups={}
    for row in rows: groups.setdefault(row['voice_id'],[]).append(row)
    scores=['similarity','clarity','pause','emotion','overall']
    return {'records':rows,'voices':[{'voice_id':voice,'samples':len(items),'reviewers':len({r['reviewer'] for r in items}),
            'averages':{key:round(sum(r[key] for r in items)/len(items),2) for key in scores}} for voice,items in groups.items()],
            'message':'尚无真实听测记录' if not rows else '分数来自已提交听测记录；同一听测者可重复评分，样本数与人数分别统计'}


@router.get('/reports/export')
def export_report():
    result={'generated_at':now(),'analytics':analytics(),'human_voice_evaluations':evaluations(),'llm':llm_gateway.status(),
            'scope':'实际运行统计与人工评分。未提交评分时不生成拟人度分数；是否满足赛题需结合独立性能测试。'}
    return Response(json.dumps(result,ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':'attachment; filename="car-live-report.json"'})
