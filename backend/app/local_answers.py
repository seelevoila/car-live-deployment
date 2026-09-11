"""Grounded local fallback for an installation without a configured chat model."""
import re
from .rag import tokens


def normalize_question(question):
    question=question.replace('能耗','能耗 油耗 电耗')
    if re.search(r'电磁炉|烧水壶|电烤炉|给电器供电|露营.*接电|煮饭', question):
        question += ' 对外放电 对外交流放电功率'
    if re.search(r'停车|停进车位|倒库', question):
        question += ' 辅助泊车入位 遥控泊车 驻车雷达'
    replacements=[
        (r'(?:充满一次|充一次|一箱电).*?(?:能跑|能行驶|跑多远)', 'CLTC纯电续航'),
        (r'(?:纯电|电车).*?(?:多少米|多少钱|什么价|售价)', '纯电版价格'),
        (r'(?:混动|油混).*?(?:多少米|多少钱|什么价|售价)', '混动版价格'),
        (r'(?:燃油|油车).*?(?:多少米|多少钱|什么价|售价)', '燃油版价格'),
        (r'(?:纯电|电车).*?(?:几期|多少期).*免息', '纯电版免息分期'),
        (r'充满电.*(?:跑|行驶).*公里','CLTC纯电续航'),
        (r'最高.*(?:开到|跑到).*','最高车速'),
        (r'快充.*(?:百分|充到|电量范围)','快充电量范围'),
        (r'快充.*(?:多长|多久|小时|时间)','快充时间'),
        (r'慢充.*(?:多长|多久|小时|时间)','慢充时间'),
        (r'(?:能不能|支持|有没有).*快充','快充功能'),
        (r'对外交流放电','对外放电'),
        (r'前电动机.*型号','前电机型号'),
        (r'前电动机.*(?:品牌|生产)','前电机品牌'),
        (r'慢充.*(?:口|接口).*位置','慢充接口位置'),
        (r'电动机总马力','电动机马力'),
        (r'电池.*冷却方式','电池冷却方式'),
        (r'车门.*(?:方式|开启)','车门开启方式'),
        (r'仪表盘.*全液晶','全液晶仪表盘'),
        (r'语音.*连续识别','语音连续识别'),
    ]
    for pattern,value in replacements:
        question=re.sub(pattern,value,question)
    return question


def excerpt_answer(question, sources):
    """Return complete, attributed excerpts for unstructured sales Q&A."""
    question=normalize_question(question)
    query_terms=set(tokens(question))
    comparison=bool(re.search(r'对比|区别|相比|还是|分别',question))
    policy=bool(re.search(r'优惠|补贴|活动|福利|免息|分期|贷款|置换|政策|价格|多少钱|售价|报价',question))
    finance=policy and bool(re.search(r'免息|分期|贷款',question))
    if policy:
        if re.search(r'免息|分期|贷款',question): needles=['免息','分期','贷款','金融']
        elif '置换' in question: needles=['置换','补贴']
        elif re.search(r'价格|多少钱|售价|报价', question): needles=['价格','指导价','售价','报价','纯电版','混动版','燃油版']
        else: needles=['优惠','福利','活动','政策']
    elif comparison:
        needles=[x for x in ['纯电','燃油','混动','动力','能耗','配置','油耗'] if x in question]
    else:
        # Generic structured field lookup handles new labels without a hardcoded answer.
        candidates=[]
        for index,source in enumerate(sources):
            for line in source['content'].splitlines():
                match=re.match(r'^(.{2,45}?)(?:是)?[：:]\s*(.+)$',line.strip())
                if not match: continue
                label,value=match.groups()
                label=re.sub(r'\([^)]*\)|（[^）]*）','',label).rstrip('是')
                terms=set(tokens(label))
                overlap=len(terms&query_terms)/max(1,len(terms))
                if len(terms&query_terms)>=2 and overlap>=.8 and value.strip() and '没有相关配置' not in value:
                    candidates.append((overlap,len(label),f'{label}：{value.strip()}'))
        return max(candidates,default=(0,0,''))[2]
    candidates=[]
    for index,source in enumerate(sources):
        # Text chunks preserve full sentences and document lines.
        for line in re.split(r'(?<=[。！？])|\n',source['content']):
            line=line.strip()
            if len(line)<10 or line.startswith('客户问'): continue
            score=sum(x in line for x in needles)
            numeric=bool(re.search(r'\d',line))
            if comparison:
                technical=bool(re.search(r'kW|kWh|km|油耗|电耗|电机|发动机|变速|离合|智驾|泊车',line,re.I))
                if not technical: continue
                score+=5 if numeric else 1
            if policy:
                if not numeric: continue
                if finance and not re.search(r'\d+\s*期|免息',line): continue
                score+=4
            if score:
                candidates.append((score,line,index+1))
    candidates.sort(key=lambda x:x[0],reverse=True)
    selected=[]
    seen=set()
    for _,line,index in candidates:
        if line in seen: continue
        seen.add(line)
        selected.append(f'{line} [{index}]')
        if len(selected)>= (4 if comparison else 3): break
    if not selected: return ''
    prefix='资料摘录（优惠适用条件和有效期请以来源确认为准）：' if policy else '相关资料对比依据：'
    if policy and not finance and len(set(re.findall(r'(?:至高|最高)\s*(\d+)\s*元?\s*置换',''.join(s['content'] for s in sources))))>1:
        prefix='资料中的置换补贴金额存在冲突，不能确认最终金额。请核对政策有效期和适用条件。相关原文：'
    if finance and len(set(re.findall(r'(\d+)\s*期',''.join(selected))))>1:
        prefix='资料中有不同分期方案，请先确认具体动力版本和政策有效期，不能默认全部适用。相关原文：'
    return prefix+'\n'+'\n'.join(selected)
