"""Feature extraction used to normalize product descriptions for API search."""

import re


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
