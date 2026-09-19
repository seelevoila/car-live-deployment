"""Repeatable local corpus evaluation; --llm additionally calls the configured LLM."""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.rag import retrieve_with_trace, index_status
from app.main import Query, ScriptRequest, query, generate_script

EXTRA = [
    ('纯电版多少钱', '9.98万到13.39万'), ('纯电多少米', '9.98万到13.39万'),
    ('电车什么价', '9.98万到13.39万'), ('混动版多少钱', '8.98万和9.98万'),
    ('油混多少钱', '8.98万和9.98万'), ('纯电可以分多少期免息', '36期 8万免息'),
    ('电车贷款有免息吗', '36期 8万免息'), ('混动能办免息吗', '24期 6万免息'),
    ('置换补贴最高多少', '7000'), ('天窗能打开吗', '不能打开'),
    ('纯电有没有天幕', '标配有天幕'), ('充满一次能跑多远', 'CLTC纯电续航里程(km)是：580'),
    ('这台车一箱电能跑多远', 'CLTC纯电续航里程(km)是：580'),
    ('新手停车方便吗', '泊车'), ('能帮我自动停进车位吗', '泊车'),
    ('露营能给电器供电吗', '对外放电'), ('外放电多少千瓦', '对外交流放电功率(kW)是：6'),
    ('后备箱放得下多少东西', '后备厢容积(L)是：377'), ('后排空间怎么样', '空间'),
    ('想看深色内饰选什么外观', '灰色'), ('纯电和燃油动力有什么区别', '1.5T'),
    ('这个车的电池有多少度电', '电池能量(kWh)是：58.3'),
    ('快充到八成要多久', '电池快充时间(小时)是：0.33'),
    ('油车和混动油耗分别多少', '6.4L'), ('运动版上市了没', '公开亮相'),
    ('想去试驾怎么预约', '试驾'), ('有热泵空调吗', '热泵空调是：标配'),
    ('前排座椅可以电动调吗', '主/副驾驶座电动调节是：主标配/副标配'),
    ('方向盘冬天能加热吗', '方向盘加热是：标配'), ('混动免息额度多少', '24期 6万免息'),
]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/rag-upgrade-2026-09-08/evaluation.json')
    parser.add_argument('--llm', action='store_true')
    args=parser.parse_args()
    fixed=json.loads((ROOT/'data/testset/retrieval_questions.json').read_text(encoding='utf-8'))
    cases=[{**x,'suite':'parameters'} for x in fixed]
    cases += [{'question':q,'evidence':e,'brand':'欧拉','series':'欧拉5 EV','year':'2026','suite':'conversational'} for q,e in EXTRA]
    results=[]
    for case in cases:
        sources,trace=retrieve_with_trace(case['question'],case['brand'],case['series'],case['year'],5)
        compact=lambda text: ''.join(text.split()).lower()
        rank=next((i for i,s in enumerate(sources,1) if compact(case['evidence']) in compact(s['content'])),None)
        results.append({'question':case['question'],'suite':case['suite'],'expected_evidence':case['evidence'],
                        'evidence_rank':rank,'passed':rank is not None,'sources':sources,'trace':trace})
        print(f"{len(results)}/{len(cases)} {'PASS' if rank else 'FAIL'} {case['question']}",flush=True)
    latency=[r['trace'].get('latency_ms',0) for r in results]
    report={'status':index_status(),'cases':results,'summary':{'total':len(results),'passed':sum(r['passed'] for r in results),
             'recall_at_5':sum(r['passed'] for r in results)/len(results),
             'mean_reciprocal_rank':sum(1/r['evidence_rank'] if r['evidence_rank'] else 0 for r in results)/len(results),
             'median_ms':statistics.median(latency),'p95_ms':sorted(latency)[int(.95*(len(latency)-1))]}}
    if args.llm:
        report['answers']=[]
        questions=['纯电版多少钱','纯电多少米','混动版多少钱','燃油版多少钱','纯电可以分多少期免息',
                   '置换补贴最高多少','充满一次能跑多远','天窗能打开吗','新手停车方便吗','后备箱放得下多少东西',
                   '我露营想接电磁炉可以吗','这款580激光雷达版指导价是多少','质保有哪些条件','北京门店今天有现车吗']
        for question in questions:
            answer=query(Query(question=question,brand='欧拉',series='欧拉5 EV',year='2026'))
            report['answers'].append({'question':question,**answer})
            print('LLM',question,answer['provider'],flush=True)
        report['scripts']=[]
        for points in ['续航、智能泊车、家用空间','露营外放电、后备箱、热泵空调']:
            started=time.perf_counter()
            report['scripts'].append({'request':points,**generate_script(ScriptRequest(selling_points=points,delivery='warm')),
                                      'latency_ms':round((time.perf_counter()-started)*1000)})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report['summary']),flush=True)


if __name__=='__main__': main()
