"""
Phase 1 规则引擎: EDesc → by1 编码预测

基于 docs/产品命名规则.md 和 docs/EDesc预测by1技术路线.md 实现
四阶段流水线: 预处理 → 特征抽取 → 编码组装 → 校验
"""

import re
import csv
import json
import os
import sys
from collections import defaultdict

# 加载统计后缀查找表
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.suffix_lookup_generated import SUFFIX_LOOKUP, SUFFIX_LOOKUP_BASE


# ============================================================
# Stage 1: 文本预处理
# ============================================================

SPELLING_FIXES = {
    'ENCENTRIC': 'ECCENTRIC',
    'THEREADED': 'THREADED',
    'WAFER BUTTERF.V.': 'WAFER BFV',
}

def preprocess(edesc: str) -> str:
    text = edesc.upper()
    for wrong, right in SPELLING_FIXES.items():
        text = text.replace(wrong, right)
    text = text.replace('BUNA-N', 'NBR')
    # 处理无空格连写: DIWAFERFIRERISERBV → DI WAFER FIRE RISER BV
    # 在大小写边界、数字/字母边界不加空格，但在 "FIRE" 前插入空格
    text = re.sub(r'(\w)(FIRE)', r'\1 \2', text)
    text = re.sub(r'(FIRE)(\w)', r'\1 \2', text)
    text = re.sub(r'(\w)(RISER)', r'\1 \2', text)
    text = re.sub(r'(RISER)(\w)', r'\1 \2', text)
    text = re.sub(r'(\w)(WAFER)', r'\1 \2', text)
    text = re.sub(r'(WAFER)(\w)', r'\1 \2', text)
    text = re.sub(r'(\w)(GROOVED)', r'\1 \2', text)
    text = re.sub(r'(\w)(GRVD)', r'\1 \2', text)
    text = re.sub(r'(\w)(LUG)', r'\1 \2', text)
    text = re.sub(r'(LUG)(\w)', r'\1 \2', text)
    text = re.sub(r'(\w)(FLANGE)', r'\1 \2', text)
    text = re.sub(r'(FLANGE)(\w)', r'\1 \2', text)
    text = re.sub(r'(\w)(THREADED)', r'\1 \2', text)
    text = re.sub(r'(\w)(DISC)', r'\1 \2', text)
    text = re.sub(r'(\w)(SEAT)', r'\1 \2', text)
    text = re.sub(r'(\w)(EPDM)', r'\1 \2', text)
    text = re.sub(r'(EPDM)(\w)', r'\1 \2', text)
    text = re.sub(r'(\w)(LEVER)', r'\1 \2', text)
    text = re.sub(r'(\w)(GEAR)', r'\1 \2', text)
    text = re.sub(r'(GEAR)(\w)', r'\1 \2', text)
    text = re.sub(r'(\w)(SWITCH)', r'\1 \2', text)
    text = re.sub(r'(SWITCH)(\w)', r'\1 \2', text)
    text = re.sub(r'(\w)(TAMPER)', r'\1 \2', text)
    text = re.sub(r'(\w)(BUTTERFLY)', r'\1 \2', text)
    text = re.sub(r'(BUTTERFLY)(\w)', r'\1 \2', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# ============================================================
# Stage 2: 特征抽取
# ============================================================

def extract_features(text: str) -> dict:
    t = text  # already uppercased by preprocess

    features = {}

    # --- 1. 信号接收器 (XD 前缀) ---
    # XD = 带信号接收器的蝶阀 (开关/监控/反馈信号)
    # 关键词分两层:
    #   强信号: 明确提到开关/监控/信号
    #   关联信号: 消防系统配套型号 (高概率带信号但不100%)
    signal_keywords_strong = [
        'FIRE RISER',  # 消防立管 — 大概率带信号(84%),少数产品无信号
        'TAMPER SWITCH', 'W/SWITCHES', 'W/ SWITCHES',
        'FLYING LEAD',        # 信号接线
        'NORMAL CLOSE',       # 常闭(信号控制)
        'BVW-', 'BVT-', 'GBV-', 'BFV-',  # 带信号蝶阀型号
        'D48638',             # GD/WD/LD 信号蝶阀型号系列
        'FIG 215', 'FIG 216', # 信号蝶阀型号
        'SPF',                # 信号蝶阀品牌
        'GEAR-OP',            # 信号蝶阀操作方式
        'NEW TURBINE',        # 新型信号涡轮
    ]
    signal_keywords_weak = [
        'BVG-',        # 部分带信号部分不带
        'UL/FM', 'UL FM', 'FM UL', 'UL ', ' FM ',
    ]

    has_strong = any(kw in t for kw in signal_keywords_strong)
    has_weak = any(kw in t for kw in signal_keywords_weak)
    # EDesc 中直接包含 XD 开头的 by1 编码
    has_xd_code = bool(re.search(r'\bXD\d{3}[XFH]', t))

    features['has_signal'] = has_strong or has_xd_code
    features['has_signal_weak'] = has_weak and not has_strong  # 仅有弱信号

    # --- 2. 连接方式 ---
    has_threaded = any(kw in t for kw in ['THREADED', 'THD', 'BSP', 'NPT'])
    has_flanged = any(kw in t for kw in ['FLGD', 'FLANGE', 'FLANGED'])
    has_grooved = any(kw in t for kw in ['GRVD', 'GROOVED', 'GRV', 'GRV BFV', 'GRV BV',
                                          'GR BFV', 'GR BV', 'GROOVE', 'GRV BFV'])
    has_lug = 'LUG' in t or 'LUGGED' in t
    has_wafer = 'WAFER' in t or 'WAF ' in t or 'WAF.' in t or t.startswith('WAF ')

    if has_threaded:
        features['connection'] = 'THREADED'
    elif has_flanged:
        features['connection'] = 'FLANGED'
    elif has_grooved:
        features['connection'] = 'GROOVED'
    elif has_lug and has_wafer:
        features['connection'] = 'LUG_WAFER'
    elif has_lug:
        features['connection'] = 'LUG'
    elif has_wafer:
        features['connection'] = 'WAFER'
    else:
        features['connection'] = 'UNKNOWN'

    features['has_lug'] = has_lug
    features['has_wafer'] = has_wafer
    features['has_grooved'] = has_grooved
    features['has_flanged'] = has_flanged

    # --- 3. 阀门结构 (偏心类型) ---
    if any(kw in t for kw in ['TRIPLE ECCENTRIC', '3 ECCENTRIC', '3 ENCENTRIC']):
        features['valve_structure'] = '3'
    elif any(kw in t for kw in ['DOUBLE ECCENTRIC', 'HIGH PERFORMANCE']):
        features['valve_structure'] = '2'
    else:
        features['valve_structure'] = '1'  # 默认中线

    # --- 4. 密封材料 ---
    if 'PTFE' in t or 'TEFLON' in t or 'T SEAL' in t:
        features['seat_material'] = 'F'
        features['seat_name'] = 'PTFE'
    elif 'CS SEAT' in t or ('CS DISC' in t and 'CS SEAT' in t):
        features['seat_material'] = 'H'
        features['seat_name'] = 'CS'
    elif 'NBR' in t:
        features['seat_material'] = 'X'
        features['seat_name'] = 'NBR'
    elif 'EPDM' in t:
        features['seat_material'] = 'X'
        features['seat_name'] = 'EPDM'
    elif 'VITON' in t or 'VTON' in t:
        features['seat_material'] = 'X'
        features['seat_name'] = 'VITON'
    elif 'DI+EPDM' in t or 'DI EPDM' in t:
        features['seat_material'] = 'X'
        features['seat_name'] = 'EPDM'
    elif features['connection'] == 'GROOVED' and 'DI+EPDM' not in t:
        # 沟槽阀默认 EPDM
        features['seat_material'] = 'X'
        features['seat_name'] = 'EPDM'
    else:
        features['seat_material'] = 'X'
        features['seat_name'] = 'EPDM'  # 默认

    # --- 5. 操作方式 ---
    has_gear = any(kw in t for kw in ['GEAR', 'GEARBOX', 'TURBINE', 'WORM GEAR',
                                       'W/HWHEEL', 'H/WHEEL', 'HANDWHEEL',
                                       'GEAR-OP', 'WITH GEAR'])
    has_lever = any(kw in t for kw in ['LEVER', 'LEVER OP'])
    has_no_drive = any(kw in t for kw in ['NO DRIVE', 'WITHOUT GEAR BOX', 'BARE SHAFT',
                                           'BARE', 'NO HANDLE', 'WITHOUT DRIVER'])
    has_motorized = 'MOTORIZED' in t or 'ACTUATOR' in t

    if has_no_drive:
        features['actuation'] = 'NO_DRIVE'
    elif has_gear and not has_lever:
        features['actuation'] = 'GEAR'
    elif has_lever and not has_gear:
        features['actuation'] = 'LEVER'
    elif has_lever and has_gear:
        features['actuation'] = 'LEVER'  # 优先 LEVER
    elif has_motorized:
        features['actuation'] = 'MOTORIZED'
    else:
        features['actuation'] = 'UNKNOWN'

    # --- 6. 阀板材料 ---
    has_ss316_disc = bool(re.search(r'(?:SS\s*316|316)\s*DISC', t))
    has_ss304_disc = bool(re.search(r'(?:SS\s*304|304)\s*DISC', t))
    has_di_epdm_disc = 'DI+EPDM DISC' in t or 'DI EPDM DISC' in t
    has_di_nbr_disc = 'DI+NBR DISC' in t
    has_di_disc = bool(re.search(r'DI\s*DISC|DUCTILE\s*DISC', t))
    has_cs_disc = 'CS DISC' in t

    if has_ss316_disc:
        features['disc_material'] = 'SS316'
    elif has_ss304_disc:
        features['disc_material'] = 'SS304'
    elif has_di_epdm_disc:
        features['disc_material'] = 'DI_EPDM'
    elif has_di_nbr_disc:
        features['disc_material'] = 'DI_NBR'
    elif has_cs_disc:
        features['disc_material'] = 'CS'
    elif has_di_disc:
        features['disc_material'] = 'DI'
    else:
        features['disc_material'] = 'UNKNOWN'

    # --- 7. 特殊结构 ---
    features['is_long_neck'] = 'LONG NECK' in t
    features['is_lockable'] = 'LOCKABLE' in t or 'INFINITE' in t
    features['is_higher_lever'] = 'HIGHER LEVER' in t
    features['has_al_handle'] = 'AL HANDLE' in t or 'ALUMINUM' in t
    features['has_cs_lever'] = 'CS LEVER' in t
    features['has_normal_close'] = 'NORMAL CLOSE' in t
    features['has_new_turbine'] = 'NEW TURBINE' in t
    features['has_jis'] = 'JIS' in t or 'JSI' in t  # typo in data
    features['has_300psi'] = '300PSI' in t or '300 PSI' in t or '300PSI' in t.replace(' ', '')
    features['has_awwa'] = 'AWWA' in t
    features['has_70g'] = '70G' in t

    # --- 8. 口径 (仅用于辅助) ---
    m = re.search(r'(\d+(?:\.\d+)?)\s*"/DN(\d+)', t)
    if m:
        features['size_inch'] = float(m.group(1))
        features['size_dn'] = int(m.group(2))
    else:
        m = re.search(r'(\d+(?:\.\d+)?)\s*/(\d+)MM', t)
        if m:
            features['size_inch'] = float(m.group(1))
            features['size_dn'] = None
        else:
            m = re.search(r'DN(\d+)', t)
            if m:
                features['size_dn'] = int(m.group(1))
                features['size_inch'] = None
            else:
                features['size_inch'] = None
                features['size_dn'] = None

    return features


# ============================================================
# Stage 3: 编码组装
# ============================================================

def assemble_by1(features: dict) -> str:
    """
    核心编码逻辑: 将特征映射为 by1 编码

    by1 遵循中国阀门命名标准 (GB/T 3035) 的 5 位编码体系:
    [X] D [Pos2] [Pos3] [Pos4] [Pos5] [后缀]
     │   │    │      │      │      │       │
     │   │    │      │      │      │       └─ L/K/V/E/G 等变体
     │   │    │      │      │      └─ X=橡胶, F=PTFE, H=不锈钢
     │   │    │      │      └─ 1=中线, 2=双偏心, 3=三偏心
     │   │    │      └─ 7=对夹, 8=卡箍/沟槽, 4=法兰, 1=内螺纹
     │   │    └─ 省略(手动) / 3=蜗轮
     │   └─ D=蝶阀
     └─ X=消防认证(FM/UL)

    关键规则:
    - 消防产品(FIRE_RISER) → 固定 Pos2=3(蜗轮), 前缀 X
    - GEAR/GEARBOX → Pos2=3(蜗轮)
    - LEVER/手动 → Pos2 省略
    - D371X vs D71X: D371X 是 D+3(蜗轮)+7(对夹)+1(中线)+X, D71X 省略了 Pos2
    """

    has_signal = features['has_signal']
    conn = features['connection']
    struct = features['valve_structure']
    seat = features['seat_material']
    disc = features['disc_material']
    act = features['actuation']
    has_lug = features['has_lug']
    has_grooved = features['has_grooved']
    has_gear = act in ('GEAR',) or (act == 'UNKNOWN' and has_signal)

    # ---- 确定前缀 ----
    prefix = "X" if has_signal else ""

    # ---- Pos1: 阀门类型 ----
    pos1 = "D"

    # ---- Pos2: 驱动方式 ----
    # 重要: D71X/D81X 系列(对夹/沟槽) Pos2 始终省略, 即使有 GEAR
    # 信号接收器产品(XD前缀): 固定 Pos2=3
    # 法兰双偏心/三偏心: 固定 Pos2=3
    # D371X(非信号): 固定 Pos2=3 (特定产品系列)
    # D41X: Pos2 省略 (中线法兰手动)
    if has_signal:
        pos2 = "3"  # 信号接收器产品默认蜗轮驱动
    elif struct in ('2', '3') and features['has_flanged']:
        pos2 = "3"  # 双偏心/三偏心法兰固定蜗轮
    elif conn in ('WAFER', 'LUG', 'LUG_WAFER', 'UNKNOWN'):
        pos2 = ""   # 对夹系列始终省略
    elif conn == 'GROOVED' or has_grooved:
        pos2 = ""   # 沟槽系列始终省略
    elif conn == 'FLANGED' and struct == '1':
        pos2 = ""   # 中线法兰手动省略
    elif has_gear:
        pos2 = "3"
    elif act == 'NO_DRIVE':
        # NO_DRIVE 比较特殊: 如果连接方式是大口径对夹，也可能走 D371X
        # 但大多数情况下是手动(Pos2省略)
        pos2 = ""
    else:
        pos2 = ""  # 手动省略

    # ---- Pos3: 连接方式 ----
    if conn == 'THREADED':
        pos3 = "1"  # 内螺纹
    elif conn == 'FLANGED':
        pos3 = "4"  # 法兰
    elif conn == 'GROOVED' or has_grooved:
        pos3 = "8"  # 卡箍/沟槽
    else:  # WAFER, LUG, LUG_WAFER, UNKNOWN → 默认对夹
        pos3 = "7"

    # ---- Pos4: 结构形式 ----
    pos4 = struct  # '1'=中线垂直板, '2'=双偏心, '3'=三偏心

    # ---- Pos5: 密封材料 ----
    pos5 = seat    # 'X'=橡胶类, 'F'=PTFE, 'H'=Cr13不锈钢

    base_code = f"{prefix}{pos1}{pos2}{pos3}{pos4}{pos5}"

    # ---- 确定后缀 (使用统计查找表) ----
    suffix = _determine_suffix(base_code, features)

    return base_code + suffix


# 基础码正则: [X]D + 2~3位数字 + Pos5字母(X/F/H)
BASE_CODE_RE = re.compile(r'^([X]?D\d{2,3}[XFH])')


def _determine_suffix(base_code: str, f: dict) -> str:
    """使用统计查找表确定后缀"""
    key = (base_code, f['has_lug'], f['is_higher_lever'],
           f['is_lockable'], f['disc_material'],
           f.get('seat_name', ''), f['actuation'])

    if key in SUFFIX_LOOKUP:
        return SUFFIX_LOOKUP[key]

    # 回退: 仅 base_code 匹配
    if base_code in SUFFIX_LOOKUP_BASE:
        return SUFFIX_LOOKUP_BASE[base_code]

    return ''


# ============================================================
# Top-10 候选预测
# ============================================================

# 频率数据 (从训练集加载)
_BY1_FREQ = {}

def _load_freq():
    _csv = 'F:/zhhm_bge_db/zhhm_orders/edesc_by1_filtered.csv'
    if not os.path.exists(_csv):
        return
    with open(_csv, 'r', encoding='utf-8') as _f:
        for _row in csv.DictReader(_f):
            _BY1_FREQ[_row['by1']] = _BY1_FREQ.get(_row['by1'], 0) + 1

_load_freq()


def _make_base(fire: bool, conn: str, struct: str, seat: str,
               has_gear: bool, has_flanged: bool, has_grooved: bool) -> str:
    """从原始特征构建基础码"""
    if fire:
        pos2 = "3"
    elif struct in ('2', '3') and has_flanged:
        pos2 = "3"
    elif conn in ('WAFER', 'LUG', 'LUG_WAFER', 'UNKNOWN') and not fire:
        pos2 = ""
    elif (conn == 'GROOVED' or has_grooved) and not fire:
        pos2 = ""
    elif conn == 'FLANGED' and struct == '1':
        pos2 = ""
    elif has_gear:
        pos2 = "3"
    else:
        pos2 = ""

    if conn == 'THREADED':
        pos3 = "1"
    elif conn == 'FLANGED':
        pos3 = "4"
    elif conn == 'GROOVED' or has_grooved:
        pos3 = "8"
    else:
        pos3 = "7"

    prefix = "X" if fire else ""
    return f"{prefix}D{pos2}{pos3}{struct}{seat}"


def _companion_bases(base_code: str) -> list:
    """生成基础码的所有变体: fire前缀切换 + Pos2切换

    D71X → [D71X, D371X, XD71X, XD371X]
    D371X → [D371X, D71X, XD371X, XD71X]
    XD381X → [XD381X, XD81X, D381X, D81X]
    """
    m = re.match(r'^([X]?)(D)(\d{2,3})([XFH])$', base_code)
    if not m:
        return [base_code]
    prefix, d, nums, seat = m.groups()

    # 归一化为2位数 (去掉前导3)
    if len(nums) == 3 and nums[0] == '3':
        short = nums[1:]
    else:
        short = nums

    results = []
    for p in ['', 'X']:
        for n in [short, '3' + short]:
            results.append(f"{p}{d}{n}{seat}")
    return results


def _get_base_variants(features: dict) -> list:
    """生成基础码变体及其得分。返回 [(base_code, score), ...]"""
    variants = {}
    f = features
    has_signal = f['has_signal']
    conn = f['connection']
    struct = f['valve_structure']
    seat = f['seat_material']
    act = f['actuation']
    has_gear = act in ('GEAR',) or (act == 'UNKNOWN' and has_signal)
    has_flanged = f['has_flanged']
    has_grooved = f['has_grooved']

    # 主预测
    primary = _make_base(has_signal, conn, struct, seat, has_gear, has_flanged, has_grooved)
    variants[primary] = 50

    # 连接方式不确定 → 尝试替代
    if conn == 'UNKNOWN':
        for alt in ['WAFER', 'GROOVED', 'LUG', 'FLANGED']:
            base = _make_base(has_signal, alt, struct, seat, has_gear,
                              alt == 'FLANGED', alt == 'GROOVED')
            if base not in variants:
                variants[base] = 15

    # 操作方式不确定 → 影响 pos2
    if act == 'UNKNOWN' and not has_signal:
        for alt_gear in [True, False]:
            base = _make_base(has_signal, conn, struct, seat, alt_gear,
                              has_flanged, has_grooved)
            if base not in variants:
                variants[base] = 10

    # 信号前缀切换 (即使 has_signal=False 也生成 XD 变体)
    # 强信号时 XD 权重高; 弱信号(仅FIRE RISER)时 XD 权重适中
    alt_signal = not has_signal
    alt_base = _make_base(alt_signal, conn, struct, seat,
                          has_gear or alt_signal, has_flanged, has_grooved)
    if alt_base not in variants:
        variants[alt_base] = 35  # 非信号伴随 (信号产品也需非信号变体)

    # Pos2 伴随 (D71X ↔ D371X)
    new_variants = {}
    for base, score in list(variants.items()):
        for comp in _companion_bases(base):
            if comp not in variants and comp not in new_variants:
                new_variants[comp] = score * 0.6
    variants.update(new_variants)

    return list(variants.items())


def _match_score(f: dict, k_lug: bool, k_hl: bool, k_lock: bool,
                 k_disc: str, k_seat: str, k_act: str) -> float:
    """计算特征匹配分"""
    score = 0
    if k_lug == f['has_lug']:
        score += 8
    if k_hl == f['is_higher_lever']:
        score += 3
    if k_lock == f['is_lockable']:
        score += 3
    if k_disc == f['disc_material']:
        score += 10
    elif f['disc_material'] == 'UNKNOWN':
        score += 3
    if k_seat == f.get('seat_name', ''):
        score += 4
    if k_act == f['actuation']:
        score += 8
    elif f['actuation'] == 'UNKNOWN':
        score += 2
    return score


def _expand_suffixes(base_code: str, features: dict, base_score: float) -> list:
    """为给定基础码及其伴随码展开所有可能后缀。返回 [(full_code, score), ...]

    关键策略: 将所有伴随码(D71X/D371X/XD71X/XD371X)的后缀互相共享，
    因为 SUFFIX_LOOKUP 可能只在一个基础码下有记录。
    """
    f = features
    results = {}
    all_bases = _companion_bases(base_code)

    # 第1步: 从所有伴随码收集后缀及其最高匹配分
    all_suffix_scores = {}  # suffix -> best match_score
    for bc in all_bases:
        for key, suffix in SUFFIX_LOOKUP.items():
            if key[0] != bc:
                continue
            _, k_lug, k_hl, k_lock, k_disc, k_seat, k_act = key
            ms = _match_score(f, k_lug, k_hl, k_lock, k_disc, k_seat, k_act)
            if suffix not in all_suffix_scores or all_suffix_scores[suffix] < ms:
                all_suffix_scores[suffix] = ms
        if bc in SUFFIX_LOOKUP_BASE:
            s = SUFFIX_LOOKUP_BASE[bc]
            if s and s not in all_suffix_scores:
                all_suffix_scores[s] = 5

    # 第2步: 将所有后缀应用到所有伴随码
    for bc in all_bases:
        mult = 1.0 if bc == base_code else 0.5

        # 无后缀
        total = base_score * mult + min(_BY1_FREQ.get(bc, 0), 20) * 0.5
        if bc not in results or results[bc] < total:
            results[bc] = total

        # 所有收集到的后缀
        for suffix, ms in all_suffix_scores.items():
            code = bc + suffix
            total = base_score * mult + ms + min(_BY1_FREQ.get(code, 0), 20) * 0.5
            if code not in results or results[code] < total:
                results[code] = total

    # 第3步: KNOWN_BY1 中所有以此 base_code 或其伴随码开头的编码
    for bc in all_bases:
        m = 1.0 if bc == base_code else 0.5
        for known in KNOWN_BY1:
            if known.startswith(bc) and known != bc:
                total = base_score * m + 5 + min(_BY1_FREQ.get(known, 0), 20) * 0.5
                if known not in results or results[known] < total:
                    results[known] = total

    # 第4步: 特殊后缀: 300PSI → G
    if f.get('has_300psi'):
        for bc in all_bases:
            m = 1.0 if bc == base_code else 0.5
            code = bc + 'G'
            total = base_score * m + 10 + min(_BY1_FREQ.get(code, 0), 20) * 0.5
            if code not in results or results[code] < total:
                results[code] = total

    return list(results.items())


def predict_top10(edesc: str) -> dict:
    """
    预测 by1，返回前 10 个候选编码，按正确概率排序。

    策略:
    1. 提取特征，生成主预测基础码
    2. 生成变体: 消防前缀切换、Pos2 伴随、连接方式替代
    3. 对每个基础码及其伴随码查找所有可能后缀
    4. 综合特征匹配分 + 频率分排序
    """
    clean = preprocess(edesc)
    features = extract_features(clean)

    candidates = {}
    for base_code, base_score in _get_base_variants(features):
        for code, score in _expand_suffixes(base_code, features, base_score):
            if code not in candidates or candidates[code] < score:
                candidates[code] = score

    ranked = sorted(candidates.items(), key=lambda x: -x[1])[:10]

    return {
        'original': edesc,
        'top': ranked[0][0] if ranked else '',
        'candidates': [code for code, _ in ranked],
        'scores': [round(score, 1) for _, score in ranked],
        'features': features,
    }


def run_test_top10(csv_path: str):
    """评估 top-10 候选准确率"""
    with open(csv_path, 'r', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    total = len(rows)
    top1 = top3 = top5 = top10_count = 0
    misses = []

    print(f"{'序号':<5} {'实际by1':<18} {'Top-1':<18} {'命中':<6} {'位置'}")
    print("-" * 100)

    for i, row in enumerate(rows):
        edesc = row['EDesc']
        actual = row['by1']

        result = predict_top10(edesc)
        cands = result['candidates']
        top = cands[0] if cands else ''

        if top == actual:
            top1 += 1; top3 += 1; top5 += 1; top10_count += 1
            hit = '#1'
        elif actual in cands[:3]:
            top3 += 1; top5 += 1; top10_count += 1
            hit = '#3'
        elif actual in cands[:5]:
            top5 += 1; top10_count += 1
            hit = '#5'
        elif actual in cands:
            top10_count += 1
            hit = '#10'
        else:
            misses.append({'idx': i+1, 'actual': actual, 'top': top,
                           'cands': cands, 'edesc': edesc[:80]})
            hit = 'MISS'

        if hit != '#1' and i < 50:
            pos = f"#{cands.index(actual)+1}" if actual in cands else "未命中"
            print(f"{i+1:<5} {actual:<18} {top:<18} {hit:<6} {pos}")

    print("\n" + "=" * 80)
    print("Top-N 候选准确率报告")
    print("=" * 80)
    print(f"总样本数:     {total}")
    print(f"Top-1 命中:   {top1}/{total} ({top1/total*100:.1f}%)")
    print(f"Top-3 命中:   {top3}/{total} ({top3/total*100:.1f}%)")
    print(f"Top-5 命中:   {top5}/{total} ({top5/total*100:.1f}%)")
    print(f"Top-10 命中:  {top10_count}/{total} ({top10_count/total*100:.1f}%)")
    print(f"完全未命中:   {len(misses)}/{total} ({len(misses)/total*100:.1f}%)")

    if misses:
        print(f"\n未命中案例 ({len(misses)} 条):")
        patterns = defaultdict(int)
        for m in misses:
            patterns[f"{m['actual']} ← {m['top']}"] += 1
        for pat, cnt in sorted(patterns.items(), key=lambda x: -x[1])[:20]:
            print(f"  {pat} (n={cnt})")

    return {'total': total, 'top1': top1, 'top3': top3,
            'top5': top5, 'top10': top10_count}


# ============================================================
# Stage 4: 校验
# ============================================================

# 已知的 60 个 by1 编码集合
KNOWN_BY1 = {
    'D341X4', 'D341X-R4', 'D341X3-16QB1', 'D341X7',
    'D342X', 'D342X4', 'D342X4C', 'D342X4C2-1', 'D342X71', 'D342XC',
    'D343H',
    'D371X', 'D371X4', 'D371XK', 'D371XL', 'D371XLK', 'D371XLV26-AS', 'D371XLV4', 'D371XV4',
    'D373HL',
    'D381X', 'D381X4', 'D381X4-BL', 'D381XE',
    'D41X4',
    'D71X', 'D71X4', 'D71XK', 'D71XKL', 'D71XKL-1', 'D71XKS', 'D71XL4', 'D71XLK',
    'D71XLV-150', 'D71XLV4', 'D71XS4', 'D71XV4',
    'D81X4', 'D81X4-BL', 'D81X700', 'D81X702', 'D81XE', 'D81XS4',
    'XD311X',
    'XD371X', 'XD371X105', 'XD371X243', 'XD371X4', 'XD371XG', 'XD371XL', 'XD371XLV4',
    'XD381X', 'XD381X242', 'XD381X4', 'XD381X4-C', 'XD381X73', 'XD381X76',
    'XD381XE', 'XD381XG',
}

# 只需匹配前缀即可的编码 (后缀含特殊数字/编码)
PREFIX_MATCH = {
    'D341X', 'D342X', 'D343H', 'D373HL',
    'XD371X105', 'XD371X243', 'XD381X242', 'XD381X73', 'XD381X76', 'XD381X4-C',
}


def validate(predicted: str, features: dict) -> dict:
    result = {'predicted': predicted, 'confidence': 'MEDIUM', 'warnings': []}

    # 精确匹配
    if predicted in KNOWN_BY1:
        result['confidence'] = 'HIGH'
        result['match_type'] = 'EXACT'
        return result

    # 前缀匹配 (预测的编码是某个已知编码的前缀)
    for known in KNOWN_BY1:
        if known.startswith(predicted) or predicted.startswith(known):
            result['confidence'] = 'MEDIUM'
            result['match_type'] = 'PREFIX'
            return result

    # 逻辑校验
    if features['connection'] == 'GROOVED' and '8' not in predicted:
        result['warnings'].append('GROOVED连接但Pos3!=8')
    if features['has_signal'] and not predicted.startswith('XD'):
        result['warnings'].append('有信号接收器但无XD前缀')
    if features['valve_structure'] == '2' and features['actuation'] == 'LEVER':
        result['warnings'].append('双偏心通常不配LEVER')

    if result['warnings']:
        result['confidence'] = 'LOW'
    else:
        result['match_type'] = 'NEW'
    return result


# ============================================================
# 主预测函数
# ============================================================

def predict(edesc: str) -> dict:
    """完整预测流水线"""
    clean = preprocess(edesc)
    features = extract_features(clean)
    features['_raw'] = edesc  # 保留原文供后缀判断用

    predicted = assemble_by1(features)
    validation = validate(predicted, features)

    return {
        'original': edesc,
        'predicted': predicted,
        'actual': None,  # 由测试脚本填入
        'confidence': validation['confidence'],
        'warnings': validation.get('warnings', []),
        'features': features,
    }


# ============================================================
# 测试: 使用 CSV 数据评估
# ============================================================

def run_test(csv_path: str):
    with open(csv_path, 'r', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    total = len(rows)
    exact_match = 0
    base_match = 0  # 基础码匹配
    results_by_confidence = defaultdict(int)
    errors = []
    by1_accuracy = defaultdict(lambda: {'total': 0, 'correct': 0})

    print(f"{'序号':<5} {'实际by1':<18} {'预测by1':<18} {'基础码':<10} {'结果':<6} {'置信度':<6} {'EDesc'}")
    print("-" * 120)

    for i, row in enumerate(rows):
        edesc = row['EDesc']
        actual = row['by1']

        result = predict(edesc)
        result['actual'] = actual
        predicted = result['predicted']

        # 提取基础码 (去掉后缀数字和特殊字符)
        actual_base = re.match(r'^[A-Z]*D\d{3}[A-Z]', actual).group(0) if re.match(r'^[A-Z]*D\d{3}[A-Z]', actual) else actual
        pred_base = re.match(r'^[A-Z]*D\d{3}[A-Z]', predicted).group(0) if re.match(r'^[A-Z]*D\d{3}[A-Z]', predicted) else predicted

        is_exact = predicted == actual
        is_base = pred_base == actual_base

        if is_exact:
            exact_match += 1
            status = "OK"
        elif is_base:
            base_match += 1
            status = "BASE"
        else:
            status = "FAIL"

        by1_accuracy[actual]['total'] += 1
        if is_exact:
            by1_accuracy[actual]['correct'] += 1

        results_by_confidence[result['confidence']] += 1

        if not is_exact:
            errors.append({
                'index': i + 1,
                'actual': actual,
                'predicted': predicted,
                'actual_base': actual_base,
                'pred_base': pred_base,
                'edesc': edesc[:80],
                'confidence': result['confidence'],
                'base_ok': is_base,
            })

        # 只打印错误和前20条
        if not is_exact or i < 5:
            print(f"{i+1:<5} {actual:<18} {predicted:<18} {actual_base:<10} {status:<6} {result['confidence']:<6} {edesc[:60]}")

    # 汇总统计
    print("\n" + "=" * 80)
    print("评估报告")
    print("=" * 80)
    print(f"总样本数:        {total}")
    print(f"完全匹配:        {exact_match}/{total} ({exact_match/total*100:.1f}%)")
    print(f"基础码匹配:      {exact_match + base_match}/{total} ({(exact_match + base_match)/total*100:.1f}%)")
    print(f"完全错误:        {total - exact_match - base_match}/{total} ({(total - exact_match - base_match)/total*100:.1f}%)")
    print(f"\n置信度分布:")
    for conf, cnt in sorted(results_by_confidence.items()):
        print(f"  {conf}: {cnt} ({cnt/total*100:.1f}%)")

    # 按 by1 统计准确率
    print(f"\n各 by1 编码准确率 (共 {len(by1_accuracy)} 个编码):")
    print(f"{'by1':<20} {'准确率':<12} {'正确/总数':<12} {'说明'}")
    print("-" * 70)

    perfect = []
    imperfect = []
    for by1, stats in sorted(by1_accuracy.items(), key=lambda x: -x[1]['total']):
        acc = stats['correct'] / stats['total'] * 100 if stats['total'] > 0 else 0
        if acc == 100:
            perfect.append(by1)
        else:
            imperfect.append((by1, stats, acc))

    # 只显示非100%的
    for by1, stats, acc in imperfect:
        mark = "<<<" if acc < 50 else ""
        print(f"{by1:<20} {acc:>5.1f}%       {stats['correct']}/{stats['total']:<8} {mark}")

    print(f"\n100% 准确的编码: {len(perfect)} 个")
    for b in perfect:
        print(f"  {b}")

    # 错误分析
    if errors:
        print(f"\n错误案例统计 (共 {len(errors)} 条):")
        error_patterns = defaultdict(list)
        for e in errors:
            key = f"{e['actual']} → {e['predicted']}"
            error_patterns[key].append(e)

        for key, errs in sorted(error_patterns.items(), key=lambda x: -len(x[1])):
            print(f"  {key} (n={len(errs)})")
            for e in errs[:2]:
                print(f"    {e['edesc']}")
            if len(errs) > 2:
                print(f"    ... 还有 {len(errs) - 2} 条")

    return {
        'total': total,
        'exact_match': exact_match,
        'exact_rate': exact_match / total * 100,
        'base_match_rate': (exact_match + base_match) / total * 100,
        'errors': errors,
    }


if __name__ == '__main__':
    csv_path = 'F:/zhhm_bge_db/zhhm_orders/edesc_by1_filtered.csv'
    result = run_test_top10(csv_path)
