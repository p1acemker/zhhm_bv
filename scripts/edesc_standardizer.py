# -*- coding: utf-8 -*-
"""Standardize raw product descriptions for the API search and write workflows."""

import re
from scripts.edesc_features import extract_features, preprocess
from service.template_models import AttributeEvidence, DescriptionViews


# ============================================================
# 口径对照表
# ============================================================

INCH_TO_DN = {
    1.5: 40, 2: 50, 2.5: 65, 3: 80, 4: 100, 5: 125, 6: 150,
    8: 200, 10: 250, 12: 300, 14: 350, 16: 400, 18: 450,
    20: 500, 24: 600, 28: 700, 32: 800, 36: 900, 40: 1000,
    48: 1200,
}

DN_TO_INCH = {v: k for k, v in INCH_TO_DN.items()}

MM_TO_DN = {
    48: 40, 50: 50, 60: 50, 63: 50, 65: 65, 73: 65, 76: 65, 76.1: 65,
    80: 80, 89: 80, 88.9: 80, 100: 100, 108: 100, 114: 100, 114.3: 100,
    125: 125, 133: 125, 140: 125, 139.7: 125, 150: 150, 159: 150,
    165: 150, 168: 150, 165.1: 150, 165.2: 150, 200: 200, 219: 200,
    216: 200, 216.3: 200, 250: 250, 267: 250, 273: 250, 267: 250,
    300: 300, 324: 300, 323.9: 300, 325: 300, 350: 350, 356: 350,
    355.6: 350, 400: 400, 406: 400, 406.4: 400, 450: 450, 457: 450,
    500: 500, 508: 500, 600: 600, 610: 600, 609.6: 600, 700: 700,
    711: 700, 800: 800, 813: 800, 812.8: 800,
}

# ============================================================
# 缩写/同义映射
# ============================================================

ABBREV_MAP = [
    # 长词优先匹配
    ('BUTTERFLY VALVE', 'BFV'),
    ('BUTTERFLY', 'BFV'),
    ('BFLY', 'BFV'),
    ('GROOVED', 'GRVD'),
    ('FLANGED', 'FLGD'),
    ('THREADED', 'THD'),
    ('WORM GEAR', 'GEAR'),
    ('GEARBOX', 'GEAR'),
    ('GEAR BOX', 'GEAR'),
    ('WORM', 'GEAR'),
    ('HANDLE', 'LEVER'),
    ('BUNA-N', 'NBR'),
    ('BUNA', 'NBR'),
    ('NITRILE', 'NBR'),
    ('VTON', 'VITON'),
    ('TEFLON', 'PTFE'),
    ('DUCTILE IRON', 'DI'),
    ('DUCTILE', 'DI'),
    ('COMPLETE WITH', 'W/'),
    ('WITH', 'W/'),
    ('OPERATED', 'OP'),
    # 材料
    ('316 SS', 'SS316'),
    ('SS 316', 'SS316'),
    ('TYPE 316', 'SS316'),
    ('304 SS', 'SS304'),
    ('SS 304', 'SS304'),
    ('TYPE 304', 'SS304'),
]

SPELLING_FIXES = {
    'ENCENTRIC': 'ECCENTRIC',
    'THEREADED': 'THREADED',
    'WAFTER': 'WAFER',
    'WAFERF.V.': 'WAFER BFV',
    'BUTTERF.V.': 'WAFER BFV',
    'BUTTERFLYVALVE': 'BUTTERFLY VALVE',
    'WAFTER': 'WAFER',
    'BFLY': 'BFV',
}

# ============================================================
# 段 7 额外属性提取规则
# ============================================================

EXTRA_ATTR_PATTERNS = [
    # 阀杆/紧固件
    (r'SS316\s*STEM', 'raw'),
    (r'416\s*SS\s*STEM', 'raw'),
    (r'SS304\s*STEM', 'raw'),
    (r'SS316\s*BOLT\s*&\s*NUT', 'raw'),
    (r'SS316\s*BOLT', 'raw'),
    (r'STAINLESS\s*STEM', 'raw'),
    (r'SS316\s*SHAFT', 'raw'),
    # 执行器型号
    (r'\b608[DLF]?E?\b', 'raw'),
    (r'\b808[DLF]?E?\b', 'raw'),
    (r'\b608L\b', 'raw'),
    (r'\bST-700\w*\b', 'raw'),
    # 产品型号
    (r'\bBV[GWL]-[\w-]+\b', 'raw'),
    (r'\bHDM\w+\b', 'raw'),
    (r'\bHD\d{3}\b', 'raw'),
    (r'\bGBV-\d+\b', 'raw'),
    (r'\bBFV-[\w-]+\b', 'raw'),
    (r'\bBVL-\w+\b', 'raw'),
    (r'\bLD\d+\w*\b', 'raw'),
    (r'\bFIG\s*\d+\b', 'raw'),
    # 认证/标准
    (r'\bAWWA\b', 'raw'),
    (r'\bUL\s*LISTED\b', 'raw'),
    (r'\bFM\s*APPROV\w*\b', 'raw'),
    (r'\bJIS\s*\d+\w*\b', 'raw'),
    (r'\bANSI\b', 'raw'),
    (r'\bASME\b', 'raw'),
    # 开关/信号细节
    (r'\bMICROSWITCH\b', 'raw'),
    (r'\bPOSITION\s*INDICATOR\b', 'raw'),
    (r'\bNORMAL\s*CLOSE\b', 'raw'),
    (r'\bFLYING\s*LEAD\b', 'raw'),
    (r'\bSUPERVISORY\b', 'raw'),
    (r'\bNC\b', 'raw'),
    # 密封细节
    (r'\bO-RING\b', 'raw'),
    (r'\bRESILIENT\b', 'raw'),
    (r'\bLIP\s*SEAL\b', 'raw'),
    (r'\bEPDM\s*SEAL\b', 'raw'),
    # 表面处理
    (r'\bRAL\s*\d+\b', 'raw'),
    (r'\bGALVANIZED\b', 'raw'),
    (r'\bEPOXY\s*COAT\w*\b', 'raw'),
    (r'\bBLUE\b', 'raw'),
    (r'\bRED\b', 'raw'),
    # 品牌
    (r'\bB&N\b', 'raw'),
    (r'\bSALZGITTER\b', 'raw'),
    (r'\bSPF\b', 'raw'),
    (r'\bTYCO\b', 'raw'),
    (r'\bAVCON\b', 'raw'),
    (r'\bWATTS\b', 'raw'),
    (r'\bVAG\b', 'raw'),
    # 其他常见额外属性
    (r'\b\d+M\s*CABLE\b', 'raw'),
    (r'\b\d+M\s*FLYING\s*LEAD\b', 'raw'),
    (r'\bEXTERNAL\b', 'raw'),
    (r'\bFIXTURE\b', 'raw'),
    (r'\bACCESSOR\w+\b', 'raw'),
    (r'\bHOLDER\b', 'raw'),
    (r'\bCATALOG\w*\b', 'raw'),
    (r'\bSERIES\s*\d+\b', 'raw'),
    (r'\bCL\s*\d+\b', 'raw'),
    (r'\b\d+OD\b', 'raw'),
]


# ============================================================
# 标准化函数
# ============================================================

def _parse_fraction_inch(s: str) -> float:
    """Standardize raw product descriptions for the API search and write workflows."""
    s = s.strip()
    m = re.match(r'^(\d+)\s+(\d+)/(\d+)$', s)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    m = re.match(r'^(\d+)/(\d+)$', s)
    if m:
        return int(m.group(1)) / int(m.group(2))
    try:
        return float(s)
    except ValueError:
        return 0


def _format_inch(inch: float) -> str:
    """Standardize raw product descriptions for the API search and write workflows."""
    if inch == int(inch):
        return str(int(inch))
    frac = inch - int(inch)
    whole = int(inch)
    fractions = {0.25: '1/4', 0.5: '1/2', 0.75: '3/4',
                 0.333: '1/3', 0.667: '2/3'}
    for fv, fs in sorted(fractions.items(), key=lambda x: -abs(frac - x[0])):
        if abs(frac - fv) < 0.01:
            return f"{whole} {fs}" if whole > 0 else fs
    return f"{inch:.1f}"


def normalize_size(text: str) -> str:
    """Standardize raw product descriptions for the API search and write workflows."""
    t = text.upper()

    # 模式1: N"/DNxxx 或 N"/xxxMM
    m = re.search(r'(\d+(?:\s+\d+/\d+)?)\s*"\s*/\s*(?:DN(\d+)|(\d+(?:\.\d+)?)\s*MM)', t)
    if m:
        inch_str = m.group(1).replace(' ', '')
        dn = int(m.group(2)) if m.group(2) else None
        mm = float(m.group(3)) if m.group(3) else None
        if dn:
            inch = _parse_fraction_inch(inch_str)
            return f'{_format_inch(inch)}"/DN{dn}'
        elif mm:
            inch = _parse_fraction_inch(inch_str)
            return f'{_format_inch(inch)}"/DN{MM_TO_DN.get(int(mm), int(mm))}'

    # 模式2: N" 单独
    m = re.search(r'(\d+(?:\s+\d+/\d+)?)\s*"', t)
    if m:
        inch_str = m.group(1)
        inch = _parse_fraction_inch(inch_str)
        dn = INCH_TO_DN.get(inch)
        if dn:
            return f'{_format_inch(inch)}"/DN{dn}'
        return f'{_format_inch(inch)}"'

    # 模式3: DNxxx 单独
    m = re.search(r'DN(\d+)', t)
    if m:
        dn = int(m.group(1))
        inch = DN_TO_INCH.get(dn)
        if inch:
            return f'{_format_inch(inch)}"/DN{dn}'
        return f'DN{dn}'

    # 模式4: 纯数字开头 (如 "4 300PSI...")
    m = re.match(r'^(\d+(?:\s+\d+/\d+)?)\s', t)
    if m:
        inch_str = m.group(1)
        inch = _parse_fraction_inch(inch_str)
        dn = INCH_TO_DN.get(inch)
        if dn:
            return f'{_format_inch(inch)}"/DN{dn}'
        return f'{_format_inch(inch)}"'

    return ''


def extract_pressure(text: str) -> str:
    """Standardize raw product descriptions for the API search and write workflows."""
    t = text.upper()
    m = re.search(r'(\d+)\s*PSI', t)
    if m:
        return f'{m.group(1)}PSI'
    m = re.search(r'\bPN(\d+)\b', t)
    if m:
        return f'PN{m.group(1)}'
    m = re.search(r'(\d+)\s*BAR', t)
    if m:
        return f'{m.group(1)}BAR'
    return ''


def _build_segment1(f: dict) -> str:
    """Standardize raw product descriptions for the API search and write workflows."""
    parts = []
    # 消防认证
    if f.get('has_signal') or f.get('has_signal_weak'):
        parts.append('UL/FM')
    # 阀体
    parts.append('DI')
    # 连接方式
    conn = f.get('connection', 'UNKNOWN')
    conn_map = {
        'WAFER': 'WAFER', 'LUG_WAFER': 'LUG WAFER', 'LUG': 'LUG',
        'GROOVED': 'GRVD', 'FLANGED': 'FLGD', 'THREADED': 'THD',
    }
    parts.append(conn_map.get(conn, ''))
    # 阀门类型
    parts.append('BFV')
    # 结构形式
    if f.get('valve_structure') == '2':
        parts.append('DOUBLE ECCENTRIC')
    elif f.get('valve_structure') == '3':
        parts.append('TRIPLE ECCENTRIC')
    # 信号开关
    if f.get('has_signal'):
        parts.append('W/TAMPER SWITCH')
    return ' '.join(p for p in parts if p)


def _build_segment2(f: dict) -> str:
    """Standardize raw product descriptions for the API search and write workflows."""
    seat = f.get('seat_name', 'UNKNOWN')
    return f'{seat} SEAT' if seat != 'UNKNOWN' else ''


def _build_segment3(f: dict) -> str:
    """Standardize raw product descriptions for the API search and write workflows."""
    disc_map = {
        'SS316': 'SS316 DISC', 'SS304': 'SS304 DISC',
        'DI_EPDM': 'DI+EPDM DISC', 'DI_NBR': 'DI+NBR DISC',
        'DI': 'DI DISC', 'CS': 'CS DISC',
    }
    return disc_map.get(f.get('disc_material', 'UNKNOWN'), '')


def _build_segment4(f: dict) -> str:
    """Standardize raw product descriptions for the API search and write workflows."""
    parts = []
    act = f.get('actuation', 'UNKNOWN')
    act_map = {
        'GEAR': 'GEAR', 'LEVER': 'LEVER', 'MOTORIZED': 'MOTORIZED',
        'NO_DRIVE': 'BARE SHAFT', 'UNKNOWN': '',
    }
    a = act_map.get(act, '')
    if a:
        parts.append(a)
    if f.get('is_higher_lever'):
        parts.append('HIGHER')
    if f.get('is_lockable'):
        parts.append('LOCKABLE')
    if f.get('is_long_neck'):
        parts.append('LONG NECK')
    return ' '.join(parts)


def _build_segment7(edesc_orig: str, features: dict) -> str:
    """Standardize raw product descriptions for the API search and write workflows."""
    t = edesc_orig.upper()

    # 收集已提取特征对应的原文片段，用于移除
    remove_patterns = [
        # 段1 相关
        r'\bUL\b\s*/?\s*\bFM\b', r'\bUL\b', r'\bFM\b', r'\bUL/FM\b',
        r'\bDI\b', r'\bDUCTILE\s*IRON\b', r'\bDUCTILE\b',
        r'\bWAFER\b', r'\bLUG(?:GED)?\b', r'\bGRVD\b', r'\bGROOVED\b', r'\bGRV\b',
        r'\bFLGD\b', r'\bFLANGED?\b', r'\bFLG\b', r'\bTHD\b', r'\bTHREADED\b',
        r'\bBUTTERFLY\b', r'\bBFV\b', r'\bBV\b', r'\bBFLY\b',
        r'\bVALVE\b', r'\bBF\b',
        r'\bDOUBLE\s*ECCENTRIC\b', r'\bTRIPLE\s*ECCENTRIC\b', r'\bECCENTRIC\b', r'\bENCENTRIC\b',
        r'\bTAMPER\b', r'\bSWITCH(?:ES)?\b', r'\bW/\b', r'\bC/W\b',
        r'\bFIRE\b', r'\bRISER\b',
        r'\bSUPERVISORY\b', r'\bSPF\b',
        # 段2 相关
        r'\bEPDM\b', r'\bNBR\b', r'\bVITON\b', r'\bVTON\b', r'\bPTFE\b', r'\bTEFLON\b',
        r'\bSEAT\b', r'\bBUNA\b', r'\bNITRILE\b',
        # 段3 相关
        r'\bSS\s*316\b', r'\bSS\s*304\b', r'\b316\s*SS\b', r'\b304\s*SS\b',
        r'\bDI\+EPDM\b', r'\bDI\+NBR\b', r'\bDI\s*DISC\b', r'\bCS\s*DISC\b',
        r'\bDISC\b', r'\bDISK\b', r'\bSS316\b', r'\bSS304\b',
        r'\+HOLDER\b', r'\bHOLDER\b',
        # 段4 相关
        r'\bLEVER\b', r'\bGEAR\b', r'\bGEARBOX\b', r'\bWORM\b', r'\bHANDLE\b',
        r'\bMOTORIZED\b', r'\bACTUAT\w*\b', r'\bBARE\b', r'\bBARE\s*SHAFT\b',
        r'\bHIGHER\b', r'\bLOCKABLE\b', r'\bLONG\s*NECK\b',
        r'\bNO\s*DRIVE\b', r'\bWITHOUT\s*GEAR\s*BOX\b', r'\bOP\b', r'\bOPERATED\b',
        r'\bTURBINE\b', r'\bHANDWHEEL\b', r'\bWORM\b',
        # 口径
        r'\d+(?:\s+\d+/\d+)?\s*"[^,)]*(?:DN\d+)?[\d\sMM]*',
        r'\bDN\d+\b', r'\d+(?:\.\d+)?\s*MM\b', r'\b\d+OD\b',
        # 压力
        r'\d+\s*PSI', r'\bPN\d+\b', r'\d+\s*BAR', r'\b\d+PSI\b',
        # 通用
        r'\bWITH\b', r'\bC/W\b', r'\bW/\b', r'\bAND\b', r'\bTYPE\b',
        r'\bINCH\b', r'\bBODY\b', r'\bIRON\b', r'\bTHE\b',
    ]

    cleaned = t
    for pat in remove_patterns:
        cleaned = re.sub(pat, ' ', cleaned)

    # 用额外属性规则从原文中提取
    extras = []
    for pattern, fmt_type in EXTRA_ATTR_PATTERNS:
        matches = list(re.finditer(pattern, t))
        for m in matches:
            token = m.group(0).strip()
            if token and token not in extras:
                extras.append(token)

    # 清理残余 token
    cleaned = re.sub(r'[,.\-/]+\s*', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    remaining = [w for w in cleaned.split() if len(w) > 1]

    # 过滤残余词中已在 extras 中的
    seen_tokens = set(extras)
    for w in remaining:
        if w not in seen_tokens and not re.match(r'^\d+$', w):
            extras.append(w)
            seen_tokens.add(w)

    return ' '.join(extras)


def standardize_edesc(edesc: str) -> dict:
    """Standardize raw product descriptions for the API search and write workflows."""
    # Step 1: 预处理 + 特征提取 (复用 rule_engine)
    clean = preprocess(edesc)
    features = extract_features(clean)

    # Step 2: 构建 7 段
    seg1 = _build_segment1(features)
    seg2 = _build_segment2(features)
    seg3 = _build_segment3(features)
    seg4 = _build_segment4(features)
    seg5 = normalize_size(edesc)
    seg6 = extract_pressure(edesc)
    seg7 = _build_segment7(edesc, features)

    standardized = ','.join(s for s in [seg1, seg2, seg3, seg4, seg5, seg6, seg7] if s)

    return {
        'original': edesc,
        'standardized': standardized,
        'segments': {
            'body': seg1,
            'seat': seg2,
            'disc': seg3,
            'actuation': seg4,
            'size': seg5,
            'pressure': seg6,
            'extra': seg7,
        },
        'features': features,
    }


def standardize_edesc_for_by1(edesc: str) -> str:
    """Return a structure-focused representation without product size."""
    clean = preprocess(edesc)
    if not re.search(r'\b(?:BFV|BV|BUTTERFLY|VALVE|CHECK)\b', clean):
        clean = re.sub(r'\bDN\s*\d+(?:\.\d+)?\b', ' ', clean)
        clean = re.sub(r'\b\d+(?:\.\d+)?\s*MM\b', ' ', clean)
        clean = re.sub(r'\b\d+(?:\s+\d+/\d+)?\s*"', ' ', clean)
        return re.sub(r'[_\W]+', ' ', clean, flags=re.UNICODE).strip()
    result = standardize_edesc(edesc)
    segments = result['segments']
    return ','.join(
        segment
        for segment in [
            segments['body'],
            segments['seat'],
            segments['disc'],
            segments['actuation'],
            segments['pressure'],
            segments['extra'],
        ]
        if segment
    )


def standardize_description_views(edesc: str) -> DescriptionViews:
    """Build lossless structural and full views without inventing attributes."""
    raw = "" if edesc is None else str(edesc)
    normalized = preprocess(raw)
    standardized = standardize_edesc(raw)
    features = standardized["features"]
    segments = standardized["segments"]
    attributes: dict[str, AttributeEvidence] = {}

    def add(field: str, value: object, evidence: object) -> None:
        text = "" if value is None else str(value).strip()
        if not text or text.upper() in {"UNKNOWN", "NONE", "NAN"}:
            return
        attributes[field] = AttributeEvidence(
            value=text.upper(),
            source="query",
            confidence=1.0,
            evidence=str(evidence).strip(),
        )

    body_material = ""
    upper = normalized.upper()
    for marker, value in (
        ("DUCTILE IRON", "DI"),
        ("CAST IRON", "CI"),
        ("CARBON STEEL", "CS"),
        ("SS316", "SS316"),
        ("SS304", "SS304"),
    ):
        if marker in upper:
            body_material = value
            break
    add("body_material", body_material, body_material)

    connection_map = {
        "LUG_WAFER": "LUG WAFER",
        "GROOVED": "GROOVED",
        "FLANGED": "FLANGED",
        "WAFER": "WAFER",
        "LUG": "LUG",
        "THREADED": "THREADED",
    }
    connection = connection_map.get(str(features.get("connection", "")))
    add("connection", connection, connection)
    add("seat_material", features.get("seat_name"), segments.get("seat", ""))
    add("closure_material", features.get("disc_material"), segments.get("disc", ""))
    add("actuation", features.get("actuation"), segments.get("actuation", ""))
    add("pressure", segments.get("pressure"), segments.get("pressure", ""))
    add("size", segments.get("size"), segments.get("size", ""))

    family = ""
    if re.search(r"\b(?:BFV|BUTTERFLY)\b", upper):
        family = "butterfly"
    elif re.search(r"\b(?:CHECK|NRV)\b", upper):
        family = "check"
    elif re.search(r"\b(?:GATE|GV)\b", upper):
        family = "gate"
    add("family", family, family)

    return DescriptionViews(
        raw_description=raw,
        normalized_description=normalized,
        structural_description=standardize_edesc_for_by1(raw),
        full_description=standardized["standardized"] or normalized,
        attributes=attributes,
    )


# ============================================================
# 主流程: 标准化 + 去重
# ============================================================
