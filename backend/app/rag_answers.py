"""Evidence selection and concise fallbacks for commercial questions."""
import re
from copy import deepcopy
from .rag_chunking import powers


def price_question(question):
    return bool(re.search(r'价格|多少钱|多少米|售价|指导价|报价|落地', question)) and not re.search(r'保险|保养|油耗|电费|贷款|免息|分期|置换|补贴', question)


def prepare_context(question, sources, series=''):
    """Remove unrelated powertrain facts from multi-power sales paragraphs.

    Full parent text and the matching child are still available in the source
    inspector; the generator sees only applicable evidence and quality notices.
    """
    scope = powers(question) or powers(series)
    output = deepcopy(sources)
    commercial = bool(re.search(r'价格|多少钱|多少米|指导价|优惠|补贴|免息|分期|贷款|置换|政策|福利', question))
    for source in output:
        content = source['content']
        meta = source.get('metadata', {})
        selected = []
        for line in content.splitlines():
            if line.startswith(('客户问', '观众问')):
                continue
            # Split power-labelled lists, keeping complete values and decimals.
            units = re.split(r'(?<=[；。！？])|(?=混动[：:]|燃油[：:]|纯电[：:])', line)
            for unit in units:
                lead = re.match(r'\s*(纯电|混动|燃油)[：:]', unit)
                if len(scope) == 1 and lead and scope[0] not in powers(lead.group()):
                    continue
                if meta.get('kind') in ['faq','note']:
                    # CTA text is an operator action, not vehicle evidence.
                    unit = re.split(r'点(?:击|下方|小风车|小发)|下方小风车|赶紧点|私信主播', unit)[0]
                    if re.search(r'官方直播中心|优惠全国通用|现车充足|均有现车|最快\s*\d.*天提车', unit):
                        continue
                    if not commercial and re.search(r'指导价|免息|补贴|置换|优惠|政策力度|专属福利', unit):
                        continue
                    if price_question(question):
                        unit = re.split(r'直播间专属福利|直播中心专属福利|至高|最高.*置换|免息|并且', unit)[0]
                elif not commercial and '指导价' in unit:
                    continue
                selected.append(unit)
        source['evidence_content'] = '\n'.join(selected)
        meta['warnings'] = applicable_warnings(question, meta.get('warnings', []))
        if price_question(question) and len(scope) == 1 and meta.get('kind') == 'faq' and meta.get('powers') != scope:
            # The family's entry price does not establish a specific power price.
            source['evidence_content'] = re.sub(r'[^\n。！？]*指导价[^\n。！？]*', '', source['evidence_content'])
    return output


def applicable_warnings(question, warnings):
    result=[]
    for warning in warnings:
        if re.search(r'指导价|报价|单位', warning) and not price_question(question):
            continue
        if '置换补贴' in warning and not re.search(r'置换|补贴|优惠|福利', question):
            continue
        if '分期方案' in warning and not re.search(r'免息|分期|贷款|金融|优惠|福利', question):
            continue
        if '没有明确政策日期' in warning and not re.search(r'价格|多少钱|多少米|优惠|补贴|免息|分期|贷款|置换|政策|福利|现车|提车|质保|保险|上市', question):
            continue
        result.append(warning)
    return result


def live_data_answer(question):
    if re.search(r'现车|库存', question):
        return '目前没有接入门店实时库存，不能确认今天是否有现车或提车时间。需要由意向门店核实具体配置和颜色。'
    return None


def appliance_answer(question, sources):
    if not re.search(r'电磁炉|烧水壶|电烤炉|电器.*(?:同时|一起)|(?:同时|一起).*电器', question):
        return None
    for index, source in enumerate(sources, 1):
        match = re.search(r'对外交流放电功率\(([^)]+)\)是[：:]\s*([\d.]+)',source['content'])
        if match:
            unit,value=match.groups()
            return f'参数表记载这款车支持对外放电，额定对外交流放电功率为{value}{unit}。[{index}] 能否使用您这台电器，还需核对电器额定及启动功率、连接设备和车辆使用说明，不能仅凭车型判断。您的电器额定功率是多少？'
    return '当前检索依据不足以确认该电器能否使用，需要补充车辆外放电参数和电器功率。'


def commercial_answer(question, sources, series=''):
    """Return None for non-commercial questions, a bounded grounded answer otherwise."""
    scope = powers(question) or powers(series)
    if price_question(question):
        trim_requested = bool(re.search(r'这款|这个配置|激光雷达|580|厂商指导价', question))
        order = sorted(enumerate(sources, 1), key=lambda pair: pair[1].get('metadata',{}).get('kind') != ('parameter' if trim_requested else 'faq'))
        for index, source in order:
            meta = source.get('metadata', {})
            if len(scope) == 1 and meta.get('powers') != scope:
                continue
            content = source.get('evidence_content', source['content'])
            if meta.get('kind') == 'parameter':
                match = re.search(r'厂商指导价[^\n]*[：:]\s*([^\n]+)', content)
                if match:
                    return f"该配置的参数表记载厂商指导价为{match.group(1)}，但原表价格范围和单位标注存在疑点，需核实后确认；这不是落地报价。[{index}]"
            elif meta.get('kind') == 'faq':
                match = re.search(r'指导价\s*([\d.]+\s*万[^，。\n]*)', content)
                if match:
                    return f"销售资料记载的该动力版本指导价为{match.group(1).strip()}。[{index}] 资料未注明价格有效日期，当前价格及落地费用还需向门店核实。"
        return '当前资料不足以确认该动力版本的价格，请补充对应配置与有效报价；不能用全车系起售价代替。'
    if re.search(r'免息|分期|贷款', question):
        found = []
        for index, source in enumerate(sources, 1):
            for match in re.finditer(r'(\d+)\s*期\s*(\d+)\s*万免息', source.get('evidence_content',source['content'])):
                value = f'{match.group(1)}期{match.group(2)}万免息'
                if any(value in item for item in found):
                    continue
                label = '动力专属段落' if len(scope)==1 and source.get('metadata',{}).get('powers')==scope else '通用段落'
                found.append(f'{label}记载{value}[{index}]')
        if found:
            return '；'.join(found[:3]) + ('。资料口径不同，不能默认同时适用' if len(found)>1 else '') + '。政策日期和适用条件未明确，当前方案需核实。'
    if re.search(r'置换|补贴', question):
        found = {}
        for index, source in enumerate(sources, 1):
            for amount in re.findall(r'(?:至高|最高)\s*(\d+)\s*元?\s*置换', source.get('evidence_content',source['content'])):
                found.setdefault(amount, index)
        if found:
            items = '、'.join(f'{amount}元[{index}]' for amount,index in found.items())
            return ('资料中的置换补贴金额存在冲突，分别记载' if len(found)>1 else '资料记载置换补贴最高') + items + '，政策日期和条件未明确，当前可享金额需要核实。'
    return None
