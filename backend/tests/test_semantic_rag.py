import json
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient
from app import main, rag, rag_models, llm_gateway
from app.config import settings
from app.db import init_db, conn
from app.rag_chunking import build_chunks
from app.rag_answers import prepare_context, commercial_answer, appliance_answer

PARAMS = '''车型名称是：测试5 EV 2026款 580km 激光雷达版
最低指导价(万)是：45.48万
最高指导价(万)是：50.80万
厂商指导价(元)是：13.38万
能源类型是：纯电动
CLTC纯电续航里程(km)是：580
电池能量(kWh)是：58.3
轴距(mm)是：2720
后备厢容积(L)是：377
辅助泊车入位是：标配
对外交流放电功率(kW)是：6
对外放电是：标配
热泵空调是：标配'''
FAQ = '''测试5 多动力版直播知识库
一、纯电价格
客户问：纯电版多少钱/纯电多少米/纯电价格
回复：测试5纯电版指导价9.98万到13.39万。仅纯电36期8万免息，最高10000元置换补贴。点小风车留资。
二、金融贷款
客户问：分期/贷款/按揭
回复：纯电、混动、燃油都可24期6万免息。至高7000元置换补贴。
三、混动价格
客户问：混动多少钱/油混什么价
回复：测试5混动版指导价8.98万和9.98万，24期6万免息。
四、燃油价格
客户问：燃油版多少钱/油车多少钱
回复：测试5纯电版指导价7.98万和8.98万。
五、天幕
客户问：天窗能打开吗
回复：纯电版有天幕，天窗不能打开。
六、现车
客户问：今天有现车吗
回复：现车充足，最快3-7天提车。点小风车查库存。'''


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'database_path', tmp_path/'corpus.sqlite3')
    monkeypatch.setattr(settings, 'upload_dir', tmp_path/'uploads')
    monkeypatch.setattr(settings, 'llm_base_url', '')
    monkeypatch.setattr(settings, 'llm_model', '')
    init_db()
    ids=[]
    for name,text,series in [('parameters.txt',PARAMS,'测试5 EV'),('faq.txt',FAQ,'测试5 多动力版')]:
        source=tmp_path/name;source.write_text(text,encoding='utf-8')
        ids.append(main.ingest(source,name,'测试',series,'2026'))
    return ids,TestClient(main.app)


def search(q, k=5):
    return rag.retrieve_with_trace(q,'测试','测试5 EV','2026',k)


def test_real_models_normalized_vectors_and_semantic_reranking():
    embeddings=rag_models.embed(['纯电车多少钱','电动汽车的售价','电池冷却方式'])
    assert embeddings.shape==(3,512)
    assert np.allclose(np.linalg.norm(embeddings,axis=1),1,atol=1e-5)
    assert float(embeddings[0]@embeddings[1]) > float(embeddings[0]@embeddings[2])
    prices,battery=rag_models.rerank('纯电车多少钱',['纯电版售价9.98万元','电池容量58.3kWh'])
    assert prices>battery+.5


def test_faq_parent_child_keeps_question_and_complete_reply():
    reply='这是一条完整的解释。'*80
    rows=build_chunks('一、空间\n客户问：后排空间怎么样\n回复：'+reply,series='测试5 EV')
    assert len(rows)>1
    assert len({r['metadata']['parent_key'] for r in rows})==1
    assert all(reply in r['parent_content'] for r in rows)
    assert all('后排空间怎么样' in r['search_text'] for r in rows)


def test_parameter_conflicts_are_retained_but_not_in_model_evidence():
    chunks=build_chunks(PARAMS,series='测试5 EV')
    assert any('45.48' in c['content'] for c in chunks)
    assert not any('45.48' in c['parent_content'] or '50.80' in c['search_text'] for c in chunks)
    assert any('13.38' in c['parent_content'] for c in chunks)
    assert any('单位' in w for c in chunks for w in c['metadata']['warnings'])


def test_hybrid_trace_contains_real_dense_sparse_fusion_and_neural_scores(corpus):
    sources,trace=search('纯电多少米')
    assert '9.98万到13.39万' in sources[0]['content']
    assert trace['dense_candidates'] and trace['bm25_candidates'] and trace['reranked']
    assert sources[0]['retrieval_scores']['reranker'] > .5
    assert sources[0]['metadata']['series']=='测试5 多动力版'


@pytest.mark.parametrize('question,power,forbidden',[
    ('纯电版多少钱','ev','混动价格'),('混动版多少钱','hybrid','纯电价格')])
def test_family_faq_recall_is_filtered_by_power(corpus,question,power,forbidden):
    sources,trace=search(question)
    assert trace['query_power']==[power]
    assert all(forbidden not in s['metadata']['title'] for s in sources)
    assert not any('7.98' in s['content'] for s in sources)


def test_fuel_price_contradiction_cannot_be_relabelled_as_ev_price(corpus):
    sources,trace=search('燃油版多少钱')
    assert any('动力类型' in w for w in trace['warnings'])
    assert all('7.98' not in s['content'] for s in sources)
    response=corpus[1].post('/api/query',json={'question':'燃油版多少钱','brand':'测试','series':'测试5 EV','year':'2026'}).json()
    assert response['provider']=='local-data-boundary'
    assert '矛盾' in response['answer'] or '不同动力类型' in response['answer']
    assert '7.98' not in response['answer'] and '6.98' not in response['answer']


def test_finance_retrieves_specific_policy_and_keeps_conflict(corpus):
    sources,_=search('纯电可以分多少期免息')
    answer=commercial_answer('纯电可以分多少期免息',sources,'测试5 EV')
    assert '36期8万' in answer and '24期6万' in answer and '核实' in answer


def test_metadata_update_rebuilds_power_and_invalidates_cache(corpus):
    ids,client=corpus
    before,trace=search('轴距是多少')
    assert before
    response=client.patch('/api/knowledge/batch',json={'ids':[ids[0]],'brand':'其他品牌'})
    assert response.status_code==200
    after,new_trace=search('轴距是多少')
    assert new_trace['index_revision']>trace['index_revision']
    assert all(s['document_id']!=ids[0] for s in after)


def test_replace_delete_expire_and_persistent_reload(corpus,tmp_path):
    ids,client=corpus
    sources,trace=search('轴距是多少')
    assert '2720' in sources[0]['content']
    replacement=tmp_path/'replacement.txt';replacement.write_text(PARAMS.replace('2720','2999'),encoding='utf-8')
    main.replace_document(ids[0],replacement,'replacement.txt','测试','测试5 EV','2026')
    sources,new_trace=search('轴距是多少')
    assert '2999' in sources[0]['content'] and sources[0]['version']==2
    assert new_trace['index_revision']>trace['index_revision']
    path=Path(rag.index_status()['index_file'])
    assert path.is_file()
    rag._CACHE=None
    assert '2999' in search('轴距是多少')[0][0]['content']
    client.patch('/api/knowledge/batch',json={'ids':[ids[0]],'valid_until':'2000-01-01'})
    assert all(s['document_id']!=ids[0] for s in search('轴距是多少')[0])
    client.post('/api/knowledge/batch-delete',json={'ids':ids})
    assert search('轴距是多少')[0]==[]
    assert rag.index_status()['chunks']==0


def test_failed_write_rolls_back_index_revision_and_vectors(corpus):
    ids,_=corpus
    before,trace=search('轴距是多少')
    with pytest.raises(RuntimeError):
        with conn() as c:
            c.execute('DELETE FROM chunks WHERE document_id=?',(ids[0],))
            raise RuntimeError('simulate ingest failure')
    after,new_trace=search('轴距是多少')
    assert new_trace['index_revision']==trace['index_revision']
    assert before==after


def test_explicit_unknown_vehicle_returns_no_fabricated_evidence(corpus):
    assert rag.retrieve('多少钱','未知品牌','未知车型','2026')==[]


def test_missing_model_is_explicit_not_hash_fallback(tmp_path,monkeypatch):
    monkeypatch.setattr(settings,'rag_model_dir',tmp_path)
    with pytest.raises(rag_models.ModelUnavailable): rag_models.embed(['多少钱'])


def test_metadata_and_user_numbers_are_not_evidence(monkeypatch):
    import httpx
    monkeypatch.setattr(settings,'llm_base_url','https://model.example/v1')
    monkeypatch.setattr(settings,'llm_model','configured')
    def respond(_client,url,**kwargs):
        return httpx.Response(200,request=httpx.Request('POST',url),json={'choices':[{'message':{'content':'可以使用99千瓦电器。[1]'}}]})
    monkeypatch.setattr(httpx.Client,'post',respond)
    assert llm_gateway.generate('支持99千瓦吗',[{'content':'外放电6千瓦','version':99,'document_name':'资料99'}]) is None


def test_context_excludes_unrelated_policy_and_call_to_action(corpus):
    sources,_=search('纯电多少钱')
    prepared=prepare_context('纯电多少钱',sources,'测试5 EV')
    assert all('小风车' not in s['evidence_content'] for s in prepared)
    answer=commercial_answer('纯电多少钱',prepared,'测试5 EV')
    assert '9.98' in answer and '免息' not in answer and '7000' not in answer


def test_live_stock_and_appliance_limits_are_honest(corpus):
    client=corpus[1]
    for question in ['北京门店今天有现车吗','我露营想接电磁炉可以吗']:
        data=client.post('/api/query',json={'question':question,'brand':'测试','series':'测试5 EV','year':'2026'}).json()
        assert data['provider']=='local-data-boundary'
        assert '带得动' not in data['answer'] and '现车充足' not in data['answer']
    assert '6kW' in data['answer'] and '启动功率' in data['answer']
