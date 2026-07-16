# -*- coding: utf-8 -*-
"""Service module - 业务逻辑层"""

from .edesc_service import EDescService
from .recommendation import RecommendationService
from .spec_inference import SpecInferenceService
from .variety_type import VarietyTypeService

__all__ = [
    "EDescService",
    "RecommendationService",
    "SpecInferenceService",
    "VarietyTypeService",
]
