# -*- coding: utf-8 -*-
"""
Variety Type Service - 阀门型号解析

支撑 POST /valve/parse 接口。
"""

from __future__ import annotations
from typing import Optional, Dict, Tuple
import re
import logging

logger = logging.getLogger(__name__)

# ======= 映射表 =======

TYPE_SPECIAL = {
    "XZ": "闸阀(带信号装置)",
    "XD": "蝶阀(带信号装置)",
    "DH": "蝶式止回阀",
    "IP": "指示器系列",
    "WP": "指示器系列",
}

TYPE_SINGLE = {
    "Z": "闸阀", "J": "截止阀", "L": "节流阀", "Q": "球阀",
    "D": "蝶阀", "A": "弹簧式安全阀", "R": "杠杆式安全阀",
    "Y": "减压阀", "S": "疏水阀", "H": "止回阀/底阀",
    "P": "排污阀", "G": "隔膜阀", "U": "柱塞阀",
    "X": "旋塞阀", "V": "过滤器",
}

ACTUATION = {
    "0": "电磁", "1": "电磁液动", "2": "电液动", "3": "蜗轮",
    "4": "正齿轮", "5": "伞齿轮", "6": "气动", "7": "液动",
    "8": "气液联动", "9": "电动",
}

CONNECTION = {
    "1": "内螺纹", "2": "外螺纹", "3": "机械接头", "4": "法兰",
    "5": "法兰+卡箍", "6": "焊接", "7": "对夹式", "8": "卡箍",
    "9": "卡套", "0": "法兰+机械",
}

STRUCT_Z = {
    "0": "弹性闸板", "1": "明杆楔式单闸板", "2": "明杆楔式双闸板",
    "3": "明杆平行单闸板", "4": "明杆平行双闸板", "5": "暗杆楔式单闸板",
    "6": "暗杆楔式双闸板", "7": "暗杆平行单闸板", "8": "暗杆平行双闸板",
}

STRUCT_D = {
    "0": "单偏心(密闭型)", "1": "中心垂直板(密闭型)", "2": "双偏心(密闭型)",
    "3": "三偏心(密闭型)", "4": "连杆机构(密闭型)", "5": "单偏心(非密闭型)",
    "6": "中心垂直板(非密闭型)", "7": "双偏心(非密闭型)", "8": "三偏心(非密闭型)",
    "9": "连杆机构(非密闭型)",
}

STRUCT_H = {
    "1": "升降式-直通流", "2": "升降式-立式", "3": "升降式-角式流",
    "4": "旋启式-单瓣", "5": "旋启式-多瓣", "6": "旋启式-双瓣",
    "7": "旋启式-蝶形止回",
}

MATERIAL = {
    "B": "巴氏合金", "N": "尼龙", "F": "氟塑料/PTFE衬里",
    "H": "Cr13系不锈钢", "J": "衬胶", "M": "蒙乃尔合金",
    "P": "渗硼钢", "R": "奥氏体不锈钢", "S": "塑料",
    "T": "铜合金", "X": "橡胶", "Y": "硬质合金",
    "C": "搪瓷", "D": "渗氮钢", "G": "陶瓷", "Q": "衬铅",
}

SEAL_BY_MATERIAL = {"J": "橡胶(衬胶常见)", "X": "橡胶", "F": "PTFE", "S": "塑料", "N": "尼龙"}
MATERIAL_SET = set(MATERIAL.keys())
_SANITIZE_RE = re.compile(r"[^A-Za-z0-9]+")


class VarietyTypeService:
    """阀门型号解析服务，支撑 POST /valve/parse。"""

    def parse_with_normalized(self, model: str) -> Dict[str, Optional[str]]:
        """解析阀门型号，返回品种、驱动、连接、结构、密封材质及标准化品种。

        Args:
            model: 原始品种字符串，如 "D371X4"。

        Returns:
            解析结果字典。

        Raises:
            ValueError: 输入为空或无法识别。
        """
        # Step 1: 标准化（清洗 + 截断到材质位）
        norm = self._normalize(model)
        # Step 2: 解析
        parsed = self._parse_from_normalized(norm)
        parsed["standardizedProduct"] = norm
        return parsed

    # ==================== 内部方法 ====================

    def _normalize(self, raw: str) -> str:
        """清洗后截断到 Pos6 主体材质码。"""
        if not raw or not raw.strip():
            raise ValueError("输入为空")
        s = _SANITIZE_RE.sub("", raw.strip().upper())

        try:
            type_code, _, rest = self._pick_type_and_rest(s)
            prefix_len = len(type_code)
            candidate = s[prefix_len:]
            base = s
        except ValueError:
            if len(s) < 2:
                raise
            type_code, _, rest = self._pick_type_and_rest(s[1:])
            base = s[1:]
            prefix_len = len(type_code)
            candidate = base[prefix_len:]

        # 找第一个材质字母（紧跟数字之后）
        for i, ch in enumerate(candidate):
            if ch in MATERIAL_SET:
                if i > 0 and candidate[i - 1].isdigit():
                    return base[:prefix_len] + candidate[: i + 1]

        # 兜底：最后一个材质字母
        last_pos = -1
        for i, ch in enumerate(candidate):
            if ch in MATERIAL_SET:
                last_pos = i
        if last_pos >= 0:
            return base[:prefix_len] + candidate[: last_pos + 1]

        raise ValueError(f"未找到主体材质码(Pos6)，无法标准化: {raw!r}")

    def _parse_from_normalized(self, norm: str) -> Dict[str, Optional[str]]:
        """解析标准化品种编码。"""
        s = norm.strip().upper()
        type_code, type_name, rest = self._pick_type_and_rest(s)
        if not rest or not rest[-1].isalpha():
            raise ValueError(f"标准化串不以材质字母结尾: {norm!r}")

        material_code = rest[-1]
        if material_code not in MATERIAL_SET:
            raise ValueError(f"未知主体材质码(Pos6): {material_code}")

        core = rest[:-1]
        actuation: Optional[str] = None

        if type_code not in ("A", "R", "Y", "S"):
            looks_like_conn_struct = (
                len(core) >= 2 and core[0] in CONNECTION and core[1].isdigit()
            )
            looks_like_actuation = (
                len(core) >= 3
                and core[0] in ACTUATION
                and core[1] in CONNECTION
                and core[2].isdigit()
            )
            if looks_like_actuation:
                actuation = ACTUATION[core[0]]
                core = core[1:]
            elif looks_like_conn_struct:
                actuation = "手动驱动"

        connection = CONNECTION.get(core[0]) if len(core) >= 1 and core[0] in CONNECTION else None
        struct_digit = core[1] if len(core) >= 2 and core[1].isdigit() else ""
        structure = self._structure_name(type_code, struct_digit)
        seal = SEAL_BY_MATERIAL.get(material_code)

        return {
            "type": type_name,
            "driveMode": actuation,
            "connectMode": connection,
            "form": structure,
            "material": seal,
        }

    def _pick_type_and_rest(self, code: str) -> Tuple[str, str, str]:
        """返回 (type_code, type_name, rest_after_type)。"""
        for k, v in TYPE_SPECIAL.items():
            if code.startswith(k):
                return k, v, code[len(k):]
        if code and code[0] in TYPE_SINGLE:
            k = code[0]
            return k, TYPE_SINGLE[k], code[1:]
        raise ValueError(f"无法识别阀门类型(Pos2): {code!r}")

    def _structure_name(self, type_code: str, struct_digit: str) -> Optional[str]:
        """获取结构名称。"""
        if not struct_digit:
            return None
        if type_code in ("Z", "XZ"):
            return STRUCT_Z.get(struct_digit)
        if type_code in ("D", "XD"):
            return STRUCT_D.get(struct_digit)
        if type_code in ("H", "DH"):
            return STRUCT_H.get(struct_digit)
        return None
