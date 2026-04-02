# -*- coding: utf-8 -*-
"""
数据处理模块
- CSV 清洗：去除尺寸、删除无用列、去除空值、去重
- EDesc 标准化：缩写展开、大小写统一
"""

import pandas as pd
import re
from pathlib import Path
from typing import List, Dict


class DataCleaner:
    """CSV 数据清洗"""

    # 尺寸模式正则表达式
    SIZE_PATTERNS = [
        r'\s*\d+\.?\d*["/]+DN\d+\s*',           # 4"/DN100
        r'\s*\d+/\d+["/]+[\d.]+MM\s*',          # 21/2"/76MM
        r'\s*/DN\d+\s*',                         # /DN150
        r'\s*/[\d.]+MM\s*',                      # /219MM
        r'\s*DN\d+\s*$',                         # DN150
        r'\s*\d+\.?\d*["]\s*$',                  # 6"
    ]

    def clean_csv(self, input_file: str, output_file: str = None) -> pd.DataFrame:
        """
        清洗 CSV 文件

        Args:
            input_file: 输入文件路径
            output_file: 输出文件路径（默认为 xxx_cleaned.csv）

        Returns:
            清洗后的 DataFrame
        """
        df = pd.read_csv(input_file)

        # 1. 删除 by1 为空的行
        df = df[df['by1'].notna() & (df['by1'] != '')]

        # 2. 删除 by1 非标准编码（中文或特殊字符）
        df = df[df['by1'].str.match(r'^[A-Z0-9\-]+$', na=False)]
        df = df[df['by1'].str.len() >= 3]

        # 3. 清洗 EDesc 中的尺寸描述
        df['EDesc'] = df['EDesc'].apply(self._clean_edesc)

        # 4. 删除指定列
        cols_to_drop = ['Pos1', 'Pos2', 'Pos3', 'Pos4', 'Pos5', 'Pos6',
                        '来源', 'Normalized_Description', 'variety_standardized']
        existing_cols = [c for c in cols_to_drop if c in df.columns]
        df = df.drop(columns=existing_cols)

        # 5. 对 EDesc 去重
        df = df.drop_duplicates(subset=['EDesc'], keep='first')

        # 保存
        if output_file is None:
            output_file = str(Path(input_file).parent / f"{Path(input_file).stem}_cleaned.csv")
        df.to_csv(output_file, index=False, encoding='utf-8-sig')

        return df

    def _clean_edesc(self, text: str) -> str:
        """清洗 EDesc，去除尺寸描述"""
        if pd.isna(text):
            return text

        result = text
        for pattern in self.SIZE_PATTERNS:
            result = re.sub(pattern, ' ', result, flags=re.IGNORECASE)

        # 清理多余空格和逗号
        result = re.sub(r'\s*,\s*', ', ', result)
        result = re.sub(r'\s+', ' ', result)
        result = result.strip(', ')

        return result


class EDescStandardizer:
    """EDesc 标准化"""

    # 缩写映射表
    ABBREVIATION_MAP = {
        'BV': 'Butterfly Valve',
        'BFV': 'Butterfly Valve',
        'GRVD': 'Grooved',
        'DI': 'Ductile Iron',
        'SS': 'Stainless Steel',
        'EPDM': 'EPDM',
        'NBR': 'NBR',
        'DISC': 'Disc',
        'LUG': 'Lug',
        'WAFER': 'Wafer',
        'FLANGE': 'Flange',
        'LEVER': 'Lever',
        'GEAR': 'Gear',
        'OP': 'Operator',
        'SEAT': 'Seat',
        'BODY': 'Body',
        'HOLDER': 'Holder',
        'FIRE': 'Fire',
        'RISER': 'Riser',
        'OPERATED': 'Operated',
        'TAMPER': 'Tamper',
        'SWITCH': 'Switch',
        'HIGHER': 'Higher',
        'LOCKABLE': 'Lockable',
        'INFINITE': 'Infinite',
        'ENCENTRIC': 'Eccentric',
    }

    # 残留尺寸模式
    RESIDUAL_SIZE_PATTERNS = [
        r'^\d+\s+',                    # 开头数字: "2 300PSI"
        r"\d+''\s+",                    # 6'' Grooved
        r'\d+"\s+',                     # 6" Grooved
        r'^\d+\s+1/\d+\s+',             # "2 1/2" 开头
    ]

    def standardize_csv(self, input_file: str, output_file: str = None) -> pd.DataFrame:
        """
        标准化 CSV 中的 EDesc

        Args:
            input_file: 输入文件路径
            output_file: 输出文件路径（默认为 xxx_standardized.csv）

        Returns:
            标准化后的 DataFrame
        """
        df = pd.read_csv(input_file)

        # 执行标准化
        df['EDesc_Standardized'] = df['EDesc'].apply(self.standardize_edesc)

        # 标准化后去重
        df = df.drop_duplicates(subset=['EDesc_Standardized'], keep='first')

        # 保存
        if output_file is None:
            output_file = str(Path(input_file).parent / f"{Path(input_file).stem}_standardized.csv")
        df.to_csv(output_file, index=False, encoding='utf-8-sig')

        return df

    def standardize_edesc(self, text: str) -> str:
        """完整的 EDesc 标准化流程"""
        if pd.isna(text):
            return text

        # 1. 清理残留尺寸
        result = self._clean_residual_sizes(text)

        # 2. 展开缩写
        result = self._expand_abbreviations(result)

        # 3. 标准化大小写（Title Case）
        result = self._title_case_preserve(result)

        # 4. 清理多余空格
        result = re.sub(r'\s+', ' ', result).strip()

        return result

    def _clean_residual_sizes(self, text: str) -> str:
        """去除残留的尺寸描述"""
        result = text
        for pattern in self.RESIDUAL_SIZE_PATTERNS:
            result = re.sub(pattern, '', result, flags=re.IGNORECASE)
        result = re.sub(r'\s*,\s*', ', ', result)
        result = re.sub(r'\s+', ' ', result).strip(', ')
        return result

    def _expand_abbreviations(self, text: str) -> str:
        """展开缩写"""
        result = text
        for abbr, full in sorted(self.ABBREVIATION_MAP.items(), key=lambda x: -len(x[0])):
            pattern = r'\b' + re.escape(abbr) + r'\b'
            result = re.sub(pattern, full, result, flags=re.IGNORECASE)
        return result

    def _title_case_preserve(self, text: str) -> str:
        """转换为 Title Case，保留特定缩写大写"""
        result = text.title()

        # 修正需要保持大写的单词
        preserve_upper = ['SS316', 'EPDM', 'NBR', 'SS', 'DI', 'DN']
        for acro in preserve_upper:
            patterns = [
                r'\b' + acro.lower() + r'\b',
                r'\b' + acro[0].upper() + acro[1:].lower() + r'\b',
            ]
            for pattern in patterns:
                result = re.sub(pattern, acro, result)

        return result
