"""Structure-first parent/child chunks inspired by recursive chunking.

Parameter rows and FAQ pairs are semantic boundaries. The original text remains
in SQLite; unsafe or inconsistent fields are excluded only from model evidence.
"""
import re
from collections import defaultdict

POWER_PATTERNS = {'ev': r'纯电|\bEV\b|电车', 'hybrid': r'混动|油混|\bHEV\b', 'ice': r'燃油|油车'}


def powers(text):
    return [key for key, pattern in POWER_PATTERNS.items() if re.search(pattern, text, re.I)]


def family(series):
    return re.sub(r'多动力版|纯电动?版?|混动版?|燃油版?|\bEV\b|\bHEV\b|\s+', '', series, flags=re.I).strip()


def split_text(text, size=200, overlap=0):
    """Recursive sentence/line splitting with a hard bound, without cutting decimals."""
    parts = [x.strip() for x in re.split(r'\n+|(?<=[。！？；!?;])', text) if x.strip()]
    output, current = [], ''
    for part in parts:
        # A pathological long line is split at commas first, then a hard bound.
        units = [part] if len(part) <= size else re.split(r'(?<=[，,、])', part)
        for unit in units:
            for start in range(0, len(unit), size):
                small = unit[start:start + size]
                if current and len(current) + len(small) + 1 > size:
                    output.append(current)
                    current = ''
                current += ('\n' if current else '') + small
    if current:
        output.append(current)
    return output


CATEGORIES = [
    ('价格与车型', r'指导价|车型名称|年款|上市|销售状态|级别|能源类型|^厂商$|^品牌$|^车系$'),
    ('露营与放电', r'放电'),
    ('充电与续航', r'续航|电池|快充|慢充|充电|预加热|热泵'),
    ('动力与能耗', r'电动?机|功率|扭矩|马力|驱动|车速|能耗|消耗|加速|变速|挡位|简称|能量回收'),
    ('空间与车身', r'长度|宽度|高度\(mm|轴距|轮距|长\*宽|质量|后备厢容积|级别|结构|角\(|车门|风阻'),
    ('驾驶辅助与泊车', r'泊车|倒车|雷达|车道|并线|变道|匝道|标识|碰撞|预警|巡航|底盘/|信号灯|起步提醒|驾驶灯'),
    ('安全防护', r'气囊|气帘|ABS|EBD|CBC|刹车|牵引力|稳定|ISOFIX|疲劳|驻车|上坡|陡坡|备胎|低速'),
    ('座舱与舒适', r'座椅|驾驶座|空调|扶手|杯架|车窗|车顶|后备厢|无钥匙|车锁|中控锁|方向盘|净化|PM2.5'),
    ('车机与互联', r'语音|导航|蓝牙|电话|车联网|OTA|仪表|应用|ETC|Wi-Fi|KTV|声纹|哨兵|行车记录|可见即|扬声器'),
    ('灯光与外部配置', r'灯|雨刷|格栅'),
    ('露营与放电', r'放电'),
]


def build_chunks(text, brand='', series='', year=''):
    text = re.sub(r'[ \t]+', ' ', text).strip()
    identity_match = re.search(r'车型名称是[：:]\s*(.+)', text)
    identity = identity_match.group(1) if identity_match else ' '.join(x for x in [series, year] if x)
    base = {'family': family(series), 'identity': identity}
    records = []

    def add(title, raw, context, kind, scope, warnings=(), blocked=False, aliases=''):
        parent_key = str(len(records))
        prefix = f'{identity} / {title}\n'
        children = context.splitlines() if kind == 'parameter' else split_text(context, 230)
        children = [x for x in children if x.strip()] or [context]
        for child in children:
            records.append({'content': raw,
                            'parent_content': prefix + context,
                            'search_text': (f'{family(series)} / {title}\n' if kind != 'parameter' else '')
                                           + (f'观众问：{aliases[:180]}\n' if aliases and aliases not in child else '') + child,
                            'metadata': {**base, 'kind': kind, 'title': title, 'powers': scope,
                                         'aliases': aliases[:250],
                                         'parent_key': parent_key, 'warnings': list(warnings),
                                         'blocked': blocked}})

    headers = list(re.finditer(r'(?m)^[一二三四五六七八九十百]+[、．.]\s*[^\n]+', text))
    if headers and '客户问' in text:
        policy_values = set(re.findall(r'(?:至高|最高)\s*(\d+)\s*元?\s*置换', text))
        finance_values = set(re.findall(r'(\d+)\s*期\s*(\d+)\s*万免息', text))
        for index, header in enumerate(headers):
            title = header.group().strip()
            body = text[header.end():headers[index + 1].start() if index + 1 < len(headers) else len(text)].strip()
            qa = re.split(r'回复[：:]', body, maxsplit=1)
            questions = qa[0].removeprefix('客户问：').removeprefix('客户问:').strip()
            response = qa[1].strip() if len(qa) > 1 else body
            scope = powers(title + ' ' + questions)
            if not scope:
                scope = powers(response) or ['all']
            warnings = []
            blocked = False
            answer_head = re.split(r'[，,。]', response)[0]
            answer_scope = powers(answer_head)
            if len(scope) == 1 and answer_scope and scope[0] not in answer_scope:
                warnings.append('标题和观众问题的动力类型与回答正文矛盾；本节禁止用于报价，需人工核对。')
                blocked = True
            if re.search(r'价格|优惠|福利|活动|置换|贷款|金融|现车|质保|费用|保值|新车型', title):
                warnings.append('销售话术没有明确政策日期、门店及适用条件；只能作为待核实资料，不能承诺当前有效。')
            if '置换' in response and len(policy_values) > 1:
                warnings.append('同一话术文件存在不同置换补贴金额，适用条件不明；不得选取最大值作为承诺。')
            if '免息' in response and len(finance_values) > 1:
                warnings.append('文件有不同分期方案，通用段落与动力专属段落口径不同；须保留动力范围并核实政策。')
            raw = title + '\n' + body
            add(title, raw, body, 'faq' if len(qa) > 1 else 'note', scope, warnings, blocked, questions)
        return records

    rows = [line.strip() for line in text.splitlines() if line.strip() and not re.search(r'_id是[：:]', line)]
    if sum('是：' in line or '是:' in line for line in rows) >= max(1, len(rows) // 2):
        scope = powers(identity + ' ' + series) or powers(text[:500]) or ['all']
        grouped = defaultdict(list)
        for line in rows:
            category = next((name for name, pattern in CATEGORIES if re.search(pattern, line.split('是')[0])), '其他参数')
            grouped[category].append(line)
        price_warnings, blocked_prices = [], []
        price_values = {}
        for label in ['最低指导价', '最高指导价', '厂商指导价']:
            match = re.search(label + r'[^\n]*?[：:]\s*(\d+(?:\.\d+)?)(万)?', text)
            if match:
                value = float(match.group(1))
                price_values[label] = value if match.group(2) or '(万)' in match.group() else value / 10000
        low, high, trim = [price_values.get(x) for x in ['最低指导价', '最高指导价', '厂商指导价']]
        if low is not None and high is not None and trim is not None and not low <= trim <= high:
            blocked_prices = ['最低指导价', '最高指导价']
            price_warnings.append('指导价区间与本车型厂商指导价冲突；范围字段已隔离，不作为报价依据。')
        if re.search(r'厂商指导价\(元\).*?[：:].*?万', text):
            price_warnings.append('厂商指导价字段标注“元”但原值使用“万”，单位不一致；仅可引用为资料记载，需核实。')
        for title, lines in grouped.items():
            # Group neighbouring complete fields; never overlap unrelated prices.
            for raw in split_text('\n'.join(lines), 160):
                warnings = price_warnings if title == '价格与车型' else []
                context = '\n'.join(line for line in raw.splitlines() if not any(x in line for x in blocked_prices))
                if context.strip():
                    add(title, raw, context, 'parameter', scope, warnings)
        return records

    for index, child in enumerate(split_text(text, 240)):
        add(f'正文 {index + 1}', child, child, 'text', powers(series) or ['all'])
    return records
