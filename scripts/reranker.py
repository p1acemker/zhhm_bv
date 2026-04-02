# -*- coding: utf-8 -*-
"""
by1 精排器 (Reranker)

对召回的候选 by1 进行逐维度特征匹配评分, 输出精排结果。

架构:
    召回 (Recall)  →  精排 (Rerank)  →  Top-K
    向量库 Top-20      逐维度评分        排序输出
    规则引擎 Top-10    融合向量分

使用:
    reranker = By1Reranker()

    # 单条精排
    results = reranker.rerank(
        edesc="2 1/2\" WAFER BFV, DI+EPDM DISC, LEVER, EPDM SEAT",
        candidates=['D71X4', 'D71XK', 'D371X4', 'XD371X'],
        top_k=10,
        vec_scores={'D71X4': 0.95, 'D371X4': 0.88},
    )
    # results[0] → {'by1': 'D71X4', 'score': 128.5, 'breakdown': {...}}

评分维度 (满分 ~120):
    prefix_match  (10)  XD 前缀是否与信号特征匹配
    pos3_match    (15)  连接方式码 (7/8/4/1) 是否匹配
    pos4_match    (10)  结构形式码 (1/2/3) 是否匹配
    seat_match    (15)  密封材料码 (X/F/H) 是否匹配
    suffix_lug    ( 8)  凸耳 L 后缀
    suffix_disc   ( 8)  阀板材料后缀 (4/-BL/K)
    suffix_lock   ( 4)  可锁定 E 后缀
    suffix_lever  ( 4)  高位手柄 V 后缀
    suffix_300psi ( 6)  300PSI G 后缀
    known_bonus   (20)  是否在已知 by1 集合中
    freq_bonus    (10)  训练集频率加分
"""

import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.by1_rule_engine import (
    preprocess, extract_features,
    KNOWN_BY1, _BY1_FREQ
)


# ============================================================
# by1 编码解析
# ============================================================

_BY1_RE = re.compile(r'^([X]?)(D)(\d{2,3})([XFH])(.*)$')


def parse_by1_code(by1: str) -> dict:
    """解析 by1 编码字符串为结构化特征字典。

    XD371XLV4 → {prefix:'X', pos2:'3', pos3:'7', pos4:'1', seat:'X',
                 suffix:'LV4', base:'XD371X'}
    D71X4     → {prefix:'',  pos2:'',  pos3:'7', pos4:'1', seat:'X',
                 suffix:'4', base:'D71X'}
    """
    m = _BY1_RE.match(by1)
    if not m:
        return {'raw': by1, 'valid': False}

    prefix = m.group(1)
    nums = m.group(3)
    seat = m.group(4)
    suffix = m.group(5)

    if len(nums) == 3:
        pos2, pos3, pos4 = nums[0], nums[1], nums[2]
    elif len(nums) == 2:
        pos2, pos3, pos4 = '', nums[0], nums[1]
    else:
        return {'raw': by1, 'valid': False}

    return {
        'valid': True,
        'prefix': prefix,
        'pos2': pos2,
        'pos3': pos3,
        'pos4': pos4,
        'seat': seat,
        'suffix': suffix,
        'base': f"{prefix}D{nums}{seat}",
    }


# ============================================================
# 精排器
# ============================================================

class By1Reranker:
    """by1 精排器: 对召回的候选 by1 进行逐维度特征匹配评分。"""

    # 连接方式 → pos3 编码映射
    CONN_POS3 = {
        'WAFER': '7', 'LUG': '7', 'LUG_WAFER': '7',
        'GROOVED': '8', 'FLANGED': '4', 'THREADED': '1',
    }

    def __init__(self):
        self.freq = _BY1_FREQ
        self.known = KNOWN_BY1

    def rerank(self, edesc: str, candidates: list, top_k: int = 10,
               vec_scores: dict = None, alpha: float = 0.3) -> list:
        """
        精排主入口。

        Args:
            edesc: 原始英文描述
            candidates: 召回的候选 by1 列表
            top_k: 返回数量 (默认 10)
            vec_scores: 可选的 {by1: cosine_score} 向量召回分
            alpha: 向量分融合权重 (默认 0.3)

        Returns:
            精排结果列表, 按分数降序:
            [{
                'by1': 'D71X4',
                'score': 128.5,
                'rule_score': 98.5,
                'base_match_bonus': 30.0,
                'vec_score': 0.95,
                'vec_contribution': 28.5,
                'breakdown': { 'prefix_match': 10, ... },
                'rank': 1,
            }, ...]
        """
        # Step 1: 从 EDesc 提取特征 (一次)
        clean = preprocess(edesc)
        features = extract_features(clean)

        # Step 2: 归一化向量分到 [0, 1]
        vec_norm = self._normalize_vec_scores(vec_scores)

        # Step 3: 逐候选精排
        results = []
        for by1 in candidates:
            # 规则精排分 (含 breakdown)
            rule_total, breakdown = self._score_detail(features, by1)

            # 基础码完全匹配加分
            base_bonus = self._base_code_match_bonus(features, by1)

            # 向量融合
            raw_vec = vec_scores.get(by1, 0.0) if vec_scores else 0.0
            norm_vec = vec_norm.get(by1, 0.0)
            vec_contrib = alpha * norm_vec * 100

            final = rule_total + base_bonus + vec_contrib

            results.append({
                'by1': by1,
                'score': round(final, 1),
                'rule_score': round(rule_total, 1),
                'base_match_bonus': round(base_bonus, 1),
                'vec_score': round(raw_vec, 4),
                'vec_contribution': round(vec_contrib, 1),
                'breakdown': {k: round(v, 1) for k, v in breakdown.items()},
            })

        # Step 4: 排序
        results.sort(key=lambda x: -x['score'])

        # Step 5: 添加排名, 截取 top_k
        output = []
        for i, r in enumerate(results[:top_k]):
            r['rank'] = i + 1
            output.append(r)

        return output

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------

    def _normalize_vec_scores(self, vec_scores: dict) -> dict:
        """min-max 归一化向量分到 [0, 1]"""
        if not vec_scores:
            return {}
        scores = list(vec_scores.values())
        s_min, s_max = min(scores), max(scores)
        if s_max <= s_min:
            return {k: 0.5 if v > 0 else 0.0 for k, v in vec_scores.items()}
        return {k: (v - s_min) / (s_max - s_min) for k, v in vec_scores.items()}

    def _score_detail(self, f: dict, by1: str) -> tuple:
        """逐维度规则评分。

        Returns:
            (total_score, breakdown_dict)
        """
        parsed = parse_by1_code(by1)
        if not parsed.get('valid'):
            return 0.0, {'invalid': True}

        bd = {}

        # ==== 基础码匹配 (50 分) ====

        # 1. 信号前缀 (10 分)
        has_signal = f.get('has_signal', False)
        has_x_prefix = parsed['prefix'] == 'X'
        if has_signal == has_x_prefix:
            bd['prefix_match'] = 10
        elif f.get('has_signal_weak') and has_x_prefix:
            bd['prefix_match'] = 5
        else:
            bd['prefix_match'] = 0

        # 2. 连接方式 pos3 (15 分)
        conn = f.get('connection', 'UNKNOWN')
        expected_pos3 = self.CONN_POS3.get(conn, '')
        if expected_pos3 and parsed['pos3'] == expected_pos3:
            bd['pos3_match'] = 15
        elif conn == 'UNKNOWN':
            bd['pos3_match'] = 3
        else:
            bd['pos3_match'] = 0

        # 3. 结构形式 pos4 (10 分)
        struct = f.get('valve_structure', '1')
        if parsed['pos4'] == struct:
            bd['pos4_match'] = 10
        else:
            bd['pos4_match'] = 0

        # 4. 密封材料 seat (15 分)
        seat = f.get('seat_material', 'X')
        if parsed['seat'] == seat:
            bd['seat_match'] = 15
        else:
            bd['seat_match'] = 0

        # ==== 后缀特征匹配 (30 分) ====
        suffix = parsed['suffix']

        # 5. 凸耳 L (8 分)
        has_lug = f.get('has_lug', False)
        suffix_has_lug = 'L' in suffix
        if has_lug == suffix_has_lug:
            bd['suffix_lug'] = 8
        elif not has_lug and not suffix_has_lug:
            bd['suffix_lug'] = 4
        else:
            bd['suffix_lug'] = 0

        # 6. 阀板材料 (8 分)
        bd['suffix_disc'] = self._score_disc(f.get('disc_material', 'UNKNOWN'), suffix)

        # 7. 可锁定 E (4 分)
        is_lock = f.get('is_lockable', False)
        has_e = 'E' in suffix
        if is_lock and has_e:
            bd['suffix_lock'] = 4
        elif not is_lock and not has_e:
            bd['suffix_lock'] = 0
        else:
            bd['suffix_lock'] = 0



        # 8. 高位手柄 V (4 分)
        is_hl = f.get('is_higher_lever', False)
        has_v = 'V' in suffix
        if is_hl == has_v:
            bd['suffix_lever'] = 4
        elif not is_hl and not has_v:
            bd['suffix_lever'] = 2
        else:
            bd['suffix_lever'] = 0

        # 9. 300PSI → G (6 分)
        has_300psi = f.get('has_300psi', False)
        has_g = 'G' in suffix
        if has_300psi and has_g:
            bd['suffix_300psi'] = 6
        elif not has_300psi and not has_g:
            bd['suffix_300psi'] = 3
        else:
            bd['suffix_300psi'] = 0

        # ==== 加分项 (30 分) ====

        # 10. 已知编码 (20 分)
        bd['known_bonus'] = 20 if by1 in self.known else 0

        # 11. 频率加分 (最多 10 分)
        bd['freq_bonus'] = min(self.freq.get(by1, 0), 20) * 0.5

        return sum(bd.values()), bd

    def _score_disc(self, disc: str, suffix: str) -> float:
        """阀板材料后缀评分"""
        if disc in ('SS316', 'SS304'):
            return 8 if ('4' in suffix or 'V4' in suffix) else 0
        if disc == 'DI_EPDM':
            return 5 if ('4' in suffix or suffix == '') else 0
        if disc == 'DI_NBR':
            return 8 if 'BL' in suffix else (4 if '4' in suffix else 0)
        if disc == 'DI':
            return 5 if ('K' in suffix or suffix == '') else 0
        if disc == 'UNKNOWN':
            return 2
        return 0

    def _base_code_match_bonus(self, f: dict, by1: str) -> float:
        """基础码完全匹配加分 (0 或 30)。

        EDesc 特征推导出的基础码与候选 by1 基础码一致时,
        说明该候选与查询高度吻合。
        """
        parsed = parse_by1_code(by1)
        if not parsed.get('valid'):
            return 0.0

        expected_pos3 = self.CONN_POS3.get(f.get('connection', ''), '')
        if not expected_pos3:
            return 0.0

        expected_prefix = 'X' if f.get('has_signal', False) else ''
        if (parsed['prefix'] == expected_prefix and
                parsed['pos3'] == expected_pos3 and
                parsed['pos4'] == f.get('valve_structure', '1') and
                parsed['seat'] == f.get('seat_material', 'X')):
            return 15.0

        return 0.0


# ============================================================
# 便捷函数
# ============================================================

def rerank(edesc: str, candidates: list, top_k: int = 10,
           vec_scores: dict = None, alpha: float = 0.3) -> list:
    """精排便捷函数 (无状态)"""
    return By1Reranker().rerank(edesc, candidates, top_k, vec_scores, alpha)
