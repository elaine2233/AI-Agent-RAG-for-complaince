import os
import json
import uuid
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime

import config

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "violation_types")
TYPES_FILE = os.path.join(DATA_DIR, "violation_types.json")
MAPPINGS_FILE = os.path.join(DATA_DIR, "clause_mappings.json")
ANNOTATIONS_FILE = os.path.join(DATA_DIR, "pending_annotations.json")


@dataclass
class ViolationType:
    id: str
    name: str
    level: int
    parent_id: Optional[str]
    severity: float
    description: str
    keywords: List[str]
    suggestions: str
    is_system: bool
    status: str
    source: str = "regulation"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ClauseTypeMapping:
    id: str
    violation_type_id: str
    doc_name: str
    article_number: str
    mapping_logic: str
    effective_date: str
    expiration_date: Optional[str]
    created_at: str

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class PendingAnnotation:
    id: str
    doc_name: str
    article_number: str
    article_text: str
    behavior_pattern: Dict
    suggested_type_id: Optional[str]
    suggested_type_name: Optional[str]
    is_new_type: bool
    status: str
    created_at: str

    def to_dict(self) -> Dict:
        return asdict(self)


_DEFAULT_L1_TYPES = [
    {
        "id": "false_publicity",
        "name": "虚假宣传",
        "level": 1,
        "parent_id": None,
        "severity": 1.0,
        "description": "使用虚假、误导性信息进行保险营销宣传",
        "keywords": [],
        "suggestions": "删除虚假或误导性表述，确保宣传内容真实准确",
        "is_system": True,
        "status": "active",
        "source": "regulation",
    },
    {
        "id": "qualification_violation",
        "name": "资质违规",
        "level": 1,
        "parent_id": None,
        "severity": 1.0,
        "description": "涉及销售资质、代言资质等方面的违规",
        "keywords": [],
        "suggestions": "确保销售和代言人员具备相应资质",
        "is_system": True,
        "status": "active",
        "source": "regulation",
    },
    {
        "id": "sales_misconduct",
        "name": "销售行为违规",
        "level": 1,
        "parent_id": None,
        "severity": 1.0,
        "description": "销售过程中的违规行为，如诱导、强制等",
        "keywords": [],
        "suggestions": "规范销售行为，不得诱导或强制购买",
        "is_system": True,
        "status": "active",
        "source": "regulation",
    },
    {
        "id": "info_disclosure",
        "name": "信息披露违规",
        "level": 1,
        "parent_id": None,
        "severity": 1.0,
        "description": "未按规定披露产品信息、风险提示等",
        "keywords": [],
        "suggestions": "完整披露产品信息和风险提示",
        "is_system": True,
        "status": "active",
        "source": "regulation",
    },
    {
        "id": "info_protection",
        "name": "信息保护违规",
        "level": 1,
        "parent_id": None,
        "severity": 1.0,
        "description": "涉及客户个人信息保护的违规",
        "keywords": [],
        "suggestions": "遵守个人信息保护相关规定",
        "is_system": True,
        "status": "active",
        "source": "regulation",
    },
]

_DEFAULT_L2_TYPES = [
    {
        "id": "absolute_language",
        "name": "绝对化用语",
        "level": 2,
        "parent_id": "false_publicity",
        "severity": 1.0,
        "description": "使用绝对化、确定性用语进行保险营销宣传",
        "keywords": ["稳赚不赔", "保本保息", "无风险", "零风险", "绝对安全", "100%保本", "100%安全"],
        "suggestions": "删除绝对化用语，替换为合规表述",
        "is_system": True,
        "status": "active",
        "source": "regulation",
    },
    {
        "id": "return_promise",
        "name": "收益承诺",
        "level": 2,
        "parent_id": "false_publicity",
        "severity": 1.0,
        "description": "对不确定利益作保证性承诺",
        "keywords": ["保证收益", "保证赚钱", "承诺收益", "收益确定", "确定收益", "保证利率", "保证回报"],
        "suggestions": "不得对不确定利益作保证性承诺",
        "is_system": True,
        "status": "active",
        "source": "regulation",
    },
    {
        "id": "exaggerated_return",
        "name": "夸大收益",
        "level": 2,
        "parent_id": "false_publicity",
        "severity": 1.0,
        "description": "夸大保险产品收益或回报",
        "keywords": ["年化收益", "收益率高达", "收益高达", "回报率"],
        "suggestions": "不得夸大产品收益",
        "is_system": True,
        "status": "active",
        "source": "regulation",
    },
    {
        "id": "product_confusion",
        "name": "产品混淆",
        "level": 2,
        "parent_id": "false_publicity",
        "severity": 1.0,
        "description": "将保险产品与其他金融产品混淆",
        "keywords": ["存款", "存钱", "理财", "基金", "比银行", "比存款"],
        "suggestions": "明确标注为保险产品，不得与存款/理财混淆",
        "is_system": True,
        "status": "active",
        "source": "regulation",
    },
    {
        "id": "unauthorized_endorsement",
        "name": "无资质代言",
        "level": 2,
        "parent_id": "qualification_violation",
        "severity": 1.0,
        "description": "利用无资质公众人物或专业人士代言推荐",
        "keywords": ["明星", "影星", "网红", "主播", "代言", "倾情推荐"],
        "suggestions": "不得利用无资质公众人物代言",
        "is_system": True,
        "status": "active",
        "source": "regulation",
    },
    {
        "id": "inducement_sales",
        "name": "诱导销售",
        "level": 2,
        "parent_id": "sales_misconduct",
        "severity": 1.0,
        "description": "以额外利益诱导购买保险产品",
        "keywords": ["赠送", "送礼", "大礼包", "返现", "返利", "红包", "额外赠送", "旅游基金", "限时", "仅剩", "名额", "涨价", "最后机会", "错过", "抢购", "秒杀", "立减"],
        "suggestions": "不得以额外利益诱导购买",
        "is_system": True,
        "status": "active",
        "source": "regulation",
    },
    {
        "id": "concealment",
        "name": "隐瞒信息",
        "level": 2,
        "parent_id": "info_disclosure",
        "severity": 1.0,
        "description": "隐瞒免责条款、退保损失等重要信息",
        "keywords": [],
        "suggestions": "完整披露产品条款和风险信息",
        "is_system": True,
        "status": "active",
        "source": "regulation",
    },
    {
        "id": "insufficient_risk_disclosure",
        "name": "风险提示不足",
        "level": 2,
        "parent_id": "info_disclosure",
        "severity": 1.0,
        "description": "未充分提示保险产品风险",
        "keywords": [],
        "suggestions": "充分提示产品风险和不确定性",
        "is_system": True,
        "status": "active",
        "source": "regulation",
    },
    {
        "id": "privacy_violation",
        "name": "信息保护",
        "level": 2,
        "parent_id": "info_protection",
        "severity": 1.0,
        "description": "未经授权收集、使用客户个人信息",
        "keywords": [],
        "suggestions": "遵守个人信息保护相关规定",
        "is_system": True,
        "status": "active",
        "source": "regulation",
    },
    {
        "id": "procedural",
        "name": "程序性条款",
        "level": 2,
        "parent_id": "info_disclosure",
        "severity": 0.1,
        "description": "法规中的程序性、管理性条款，与营销内容审核无直接关系",
        "keywords": [],
        "suggestions": "此条款为程序性规定，不涉及营销内容合规判定",
        "is_system": True,
        "status": "active",
        "source": "regulation",
    },
    {
        "id": "other_violation",
        "name": "其他违规",
        "level": 2,
        "parent_id": "false_publicity",
        "severity": 1.0,
        "description": "其他未分类的违规行为",
        "keywords": [],
        "suggestions": "请根据违规类型修改",
        "is_system": True,
        "status": "active",
        "source": "regulation",
    },
]

_DEFAULT_MAPPINGS = [
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "一", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "二", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "sales_misconduct", "doc_name": "保险销售行为管理办法", "article_number": "六", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "sales_misconduct", "doc_name": "保险销售行为管理办法", "article_number": "七", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "保险销售行为管理办法", "article_number": "八", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "insufficient_risk_disclosure", "doc_name": "保险销售行为管理办法", "article_number": "八", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "保险销售行为管理办法", "article_number": "九", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "insufficient_risk_disclosure", "doc_name": "保险销售行为管理办法", "article_number": "九", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "保险销售行为管理办法", "article_number": "十", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "insufficient_risk_disclosure", "doc_name": "保险销售行为管理办法", "article_number": "十", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "return_promise", "doc_name": "保险销售行为管理办法", "article_number": "十一", "mapping_logic": "secondary", "effective_date": "2026-01-01"},
    {"violation_type_id": "return_promise", "doc_name": "保险销售行为管理办法", "article_number": "十二", "mapping_logic": "secondary", "effective_date": "2026-01-01"},
    {"violation_type_id": "return_promise", "doc_name": "保险销售行为管理办法", "article_number": "十三", "mapping_logic": "secondary", "effective_date": "2026-01-01"},
    {"violation_type_id": "return_promise", "doc_name": "保险销售行为管理办法", "article_number": "十四", "mapping_logic": "secondary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "保险销售行为管理办法", "article_number": "十五", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "保险销售行为管理办法", "article_number": "十六", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "保险销售行为管理办法", "article_number": "十七", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "concealment", "doc_name": "保险销售行为管理办法", "article_number": "十七", "mapping_logic": "secondary", "effective_date": "2026-01-01"},
    {"violation_type_id": "absolute_language", "doc_name": "保险销售行为管理办法", "article_number": "十八", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "return_promise", "doc_name": "保险销售行为管理办法", "article_number": "十九", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "exaggerated_return", "doc_name": "保险销售行为管理办法", "article_number": "二十", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "concealment", "doc_name": "保险销售行为管理办法", "article_number": "二十一", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "二十二", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "二十三", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "二十四", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "inducement_sales", "doc_name": "保险销售行为管理办法", "article_number": "二十五", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "inducement_sales", "doc_name": "保险销售行为管理办法", "article_number": "二十六", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "inducement_sales", "doc_name": "保险销售行为管理办法", "article_number": "二十七", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "concealment", "doc_name": "保险销售行为管理办法", "article_number": "二十七", "mapping_logic": "secondary", "effective_date": "2026-01-01"},
    {"violation_type_id": "inducement_sales", "doc_name": "保险销售行为管理办法", "article_number": "二十八", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "concealment", "doc_name": "保险销售行为管理办法", "article_number": "二十八", "mapping_logic": "secondary", "effective_date": "2026-01-01"},
    {"violation_type_id": "insufficient_risk_disclosure", "doc_name": "保险销售行为管理办法", "article_number": "二十九", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "insufficient_risk_disclosure", "doc_name": "保险销售行为管理办法", "article_number": "三十", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "inducement_sales", "doc_name": "保险销售行为管理办法", "article_number": "三十一", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "三十二", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "三十三", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "三十四", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "三十五", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "三十六", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "三十七", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "三十八", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "三十九", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "四十", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "四十一", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "四十二", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "四十三", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "四十四", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "四十五", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "四十六", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "四十七", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "四十八", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "四十九", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "保险销售行为管理办法", "article_number": "五十", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "一", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "二", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "三", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "qualification_violation", "doc_name": "互联网保险业务监管办法", "article_number": "四", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "qualification_violation", "doc_name": "互联网保险业务监管办法", "article_number": "五", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "qualification_violation", "doc_name": "互联网保险业务监管办法", "article_number": "六", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "qualification_violation", "doc_name": "互联网保险业务监管办法", "article_number": "七", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "qualification_violation", "doc_name": "互联网保险业务监管办法", "article_number": "八", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "互联网保险业务监管办法", "article_number": "九", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "insufficient_risk_disclosure", "doc_name": "互联网保险业务监管办法", "article_number": "九", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "互联网保险业务监管办法", "article_number": "十", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "insufficient_risk_disclosure", "doc_name": "互联网保险业务监管办法", "article_number": "十", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "互联网保险业务监管办法", "article_number": "十一", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "insufficient_risk_disclosure", "doc_name": "互联网保险业务监管办法", "article_number": "十一", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "互联网保险业务监管办法", "article_number": "十二", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "insufficient_risk_disclosure", "doc_name": "互联网保险业务监管办法", "article_number": "十二", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "互联网保险业务监管办法", "article_number": "十三", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "insufficient_risk_disclosure", "doc_name": "互联网保险业务监管办法", "article_number": "十三", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "sales_misconduct", "doc_name": "互联网保险业务监管办法", "article_number": "十四", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "sales_misconduct", "doc_name": "互联网保险业务监管办法", "article_number": "十五", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "sales_misconduct", "doc_name": "互联网保险业务监管办法", "article_number": "十六", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "sales_misconduct", "doc_name": "互联网保险业务监管办法", "article_number": "十七", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "sales_misconduct", "doc_name": "互联网保险业务监管办法", "article_number": "十八", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "qualification_violation", "doc_name": "互联网保险业务监管办法", "article_number": "十九", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "product_confusion", "doc_name": "互联网保险业务监管办法", "article_number": "十九", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "qualification_violation", "doc_name": "互联网保险业务监管办法", "article_number": "二十", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "product_confusion", "doc_name": "互联网保险业务监管办法", "article_number": "二十", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "qualification_violation", "doc_name": "互联网保险业务监管办法", "article_number": "二十一", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "product_confusion", "doc_name": "互联网保险业务监管办法", "article_number": "二十一", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "qualification_violation", "doc_name": "互联网保险业务监管办法", "article_number": "二十二", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "product_confusion", "doc_name": "互联网保险业务监管办法", "article_number": "二十二", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "qualification_violation", "doc_name": "互联网保险业务监管办法", "article_number": "二十三", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "product_confusion", "doc_name": "互联网保险业务监管办法", "article_number": "二十三", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_protection", "doc_name": "互联网保险业务监管办法", "article_number": "二十四", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "互联网保险业务监管办法", "article_number": "二十四", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_protection", "doc_name": "互联网保险业务监管办法", "article_number": "二十五", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "互联网保险业务监管办法", "article_number": "二十五", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_protection", "doc_name": "互联网保险业务监管办法", "article_number": "二十六", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "互联网保险业务监管办法", "article_number": "二十六", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_protection", "doc_name": "互联网保险业务监管办法", "article_number": "二十七", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "互联网保险业务监管办法", "article_number": "二十七", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_protection", "doc_name": "互联网保险业务监管办法", "article_number": "二十八", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "互联网保险业务监管办法", "article_number": "二十八", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_protection", "doc_name": "互联网保险业务监管办法", "article_number": "二十九", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "互联网保险业务监管办法", "article_number": "二十九", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_protection", "doc_name": "互联网保险业务监管办法", "article_number": "三十", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "互联网保险业务监管办法", "article_number": "三十", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "三十一", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "三十二", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "三十三", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "三十四", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "三十五", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "三十六", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "三十七", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "三十八", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "三十九", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "四十", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "四十一", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "四十二", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "四十三", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "四十四", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "四十五", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "四十六", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "四十七", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "四十八", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "四十九", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "五十", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "五十一", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "五十二", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "五十三", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "五十四", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "五十五", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "五十六", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "五十七", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "五十八", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "五十九", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "六十", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "六十一", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "六十二", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "六十三", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "六十四", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "六十五", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "六十六", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "六十七", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "六十八", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "六十九", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "七十", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "七十一", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "七十二", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "七十三", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "七十四", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "七十五", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "七十六", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "七十七", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "七十八", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "七十九", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "八十", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "八十一", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "八十二", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "互联网保险业务监管办法", "article_number": "八十三", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "一", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "二", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "三", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "absolute_language", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "四", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "absolute_language", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "五", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "absolute_language", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "六", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "absolute_language", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "七", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "八", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "insufficient_risk_disclosure", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "八", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "九", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "insufficient_risk_disclosure", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "九", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "insufficient_risk_disclosure", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十一", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "insufficient_risk_disclosure", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十一", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_disclosure", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十二", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "insufficient_risk_disclosure", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十二", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "return_promise", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十三", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "exaggerated_return", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十三", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "inducement_sales", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十三", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "unauthorized_endorsement", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十三", "mapping_logic": "secondary", "effective_date": "2026-01-01"},
    {"violation_type_id": "return_promise", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十四", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "exaggerated_return", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十四", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "inducement_sales", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十四", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "return_promise", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十五", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "exaggerated_return", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十五", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "inducement_sales", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十五", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "return_promise", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十六", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "exaggerated_return", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十六", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "inducement_sales", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十六", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_protection", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十七", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "concealment", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十七", "mapping_logic": "secondary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_protection", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十八", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "concealment", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十八", "mapping_logic": "secondary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_protection", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十九", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "concealment", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "十九", "mapping_logic": "secondary", "effective_date": "2026-01-01"},
    {"violation_type_id": "info_protection", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "二十", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "concealment", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "二十", "mapping_logic": "secondary", "effective_date": "2026-01-01"},
    {"violation_type_id": "unauthorized_endorsement", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "二十", "mapping_logic": "primary", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "二十一", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "二十二", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "二十三", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "二十四", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "二十五", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "二十六", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "二十七", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "二十八", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "二十九", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "三十", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "三十一", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "三十二", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "三十三", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "三十四", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "三十五", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "三十六", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
    {"violation_type_id": "procedural", "doc_name": "金融产品网络营销管理办法（征求意见稿）", "article_number": "三十七", "mapping_logic": "not_applicable", "effective_date": "2026-01-01"},
]

ANNOTATION_SYSTEM_PROMPT = """你是一位保险合规法规分析专家。你的任务是分析法规条文，判断其是否属于"营销内容审核"范畴，并提取行为模式。

请按以下JSON格式输出：
{
  "is_content_audit": true/false,
  "reason": "判断理由",
  "behavior_pattern": {
    "subject": "行为主体",
    "action": "行为动作",
    "object": "行为对象",
    "condition": "条件/场景"
  },
  "suggested_violation_type": "建议的违规类型名称，如果无法归入现有类型则建议新类型",
  "is_new_type": true/false,
  "new_type_description": "如果是新类型，描述其业务定义"
}

注意：
1. 程序性条款（如"应建立审核制度""内容保存期限"等）不属于营销内容审核范畴，is_content_audit=false
2. 只约束营销内容本身的合规性的条款才属于内容审核范畴
3. 行为模式提取要结构化，便于后续匹配"""

ANNOTATION_USER_TEMPLATE = """## 现有违规类型列表
{existing_types}

## 待标注的法规条文
法规名称：{doc_name}
条文编号：{article_number}
条文内容：
{article_text}

请分析该条文并输出JSON。"""


class ViolationRegistry:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._types: Dict[str, ViolationType] = {}
        self._mappings: Dict[str, ClauseTypeMapping] = {}
        self._pending_annotations: Dict[str, PendingAnnotation] = {}
        self._load()
        self._initialized = True
        logger.info(f"违规类型注册表初始化完成: {len(self._types)}个类型, {len(self._mappings)}条映射")

    def _load(self):
        os.makedirs(DATA_DIR, exist_ok=True)

        if os.path.exists(TYPES_FILE):
            try:
                with open(TYPES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data:
                    vt = ViolationType(**item)
                    self._types[vt.id] = vt
            except Exception as e:
                logger.error(f"加载违规类型失败: {e}")
                self._types = {}

        if os.path.exists(MAPPINGS_FILE):
            try:
                with open(MAPPINGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data:
                    cm = ClauseTypeMapping(**item)
                    self._mappings[cm.id] = cm
            except Exception as e:
                logger.error(f"加载条款映射失败: {e}")
                self._mappings = {}

        if os.path.exists(ANNOTATIONS_FILE):
            try:
                with open(ANNOTATIONS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for item in data:
                    pa = PendingAnnotation(**item)
                    self._pending_annotations[pa.id] = pa
            except Exception as e:
                logger.error(f"加载待审批标注失败: {e}")
                self._pending_annotations = {}

        if not self._types:
            self._init_defaults()
        else:
            self._sync_default_types()
            if len(self._mappings) < len(_DEFAULT_MAPPINGS):
                self._sync_default_mappings()

    def load_mappings_from_db(self):
        try:
            from src.database import Database
            db = Database()
            conn = db._get_conn()
            rows = conn.execute("SELECT id, violation_type_id, doc_name, article_number, mapping_logic, effective_date, expiration_date, created_at FROM clause_type_mappings").fetchall()
            if rows:
                self._mappings.clear()
                for row in rows:
                    cm = ClauseTypeMapping(
                        id=row[0],
                        violation_type_id=row[1],
                        doc_name=row[2],
                        article_number=row[3],
                        mapping_logic=row[4],
                        effective_date=row[5],
                        expiration_date=row[6],
                        created_at=row[7],
                    )
                    self._mappings[cm.id] = cm
                logger.info(f"从数据库加载条款映射: {len(self._mappings)}条")
        except Exception as e:
            logger.warning(f"从数据库加载条款映射失败: {e}")

    def _sync_default_types(self):
        now = datetime.now().isoformat()
        added = 0
        for type_data in _DEFAULT_L1_TYPES + _DEFAULT_L2_TYPES:
            if type_data["id"] not in self._types:
                vt = ViolationType(
                    id=type_data["id"],
                    name=type_data["name"],
                    level=type_data["level"],
                    parent_id=type_data["parent_id"],
                    severity=type_data["severity"],
                    description=type_data["description"],
                    keywords=type_data["keywords"],
                    suggestions=type_data["suggestions"],
                    is_system=type_data["is_system"],
                    status=type_data["status"],
                    source=type_data.get("source", "regulation"),
                    created_at=now,
                    updated_at=now,
                )
                self._types[vt.id] = vt
                added += 1
        if added > 0:
            self._save()
            logger.info(f"同步默认违规类型: 新增 {added} 个，总计 {len(self._types)} 个")

    def _sync_default_mappings(self):
        now = datetime.now().isoformat()
        existing_keys = set()
        for cm in self._mappings.values():
            key = (cm.violation_type_id, cm.doc_name, cm.article_number)
            existing_keys.add(key)

        added = 0
        for mapping_data in _DEFAULT_MAPPINGS:
            key = (mapping_data["violation_type_id"], mapping_data["doc_name"], mapping_data["article_number"])
            if key not in existing_keys:
                cm = ClauseTypeMapping(
                    id=str(uuid.uuid4())[:8],
                    violation_type_id=mapping_data["violation_type_id"],
                    doc_name=mapping_data["doc_name"],
                    article_number=mapping_data["article_number"],
                    mapping_logic=mapping_data["mapping_logic"],
                    effective_date=mapping_data.get("effective_date", now),
                    expiration_date=None,
                    created_at=now,
                )
                self._mappings[cm.id] = cm
                added += 1

        if added > 0:
            self._save()
            logger.info(f"同步默认条款映射: 新增 {added} 条，总计 {len(self._mappings)} 条")

    def _init_defaults(self):
        now = datetime.now().isoformat()
        for type_data in _DEFAULT_L1_TYPES + _DEFAULT_L2_TYPES:
            vt = ViolationType(
                id=type_data["id"],
                name=type_data["name"],
                level=type_data["level"],
                parent_id=type_data["parent_id"],
                severity=type_data["severity"],
                description=type_data["description"],
                keywords=type_data["keywords"],
                suggestions=type_data["suggestions"],
                is_system=type_data["is_system"],
                status=type_data["status"],
                source=type_data.get("source", "regulation"),
                created_at=now,
                updated_at=now,
            )
            self._types[vt.id] = vt

        for mapping_data in _DEFAULT_MAPPINGS:
            cm = ClauseTypeMapping(
                id=str(uuid.uuid4())[:8],
                violation_type_id=mapping_data["violation_type_id"],
                doc_name=mapping_data["doc_name"],
                article_number=mapping_data["article_number"],
                mapping_logic=mapping_data["mapping_logic"],
                effective_date=mapping_data.get("effective_date", now),
                expiration_date=None,
                created_at=now,
            )
            self._mappings[cm.id] = cm

        self._save()
        logger.info("已初始化默认违规类型和条款映射")

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        try:
            with open(TYPES_FILE, "w", encoding="utf-8") as f:
                json.dump([vt.to_dict() for vt in self._types.values()], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存违规类型失败: {e}")

        try:
            with open(MAPPINGS_FILE, "w", encoding="utf-8") as f:
                json.dump([cm.to_dict() for cm in self._mappings.values()], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存条款映射失败: {e}")

        try:
            with open(ANNOTATIONS_FILE, "w", encoding="utf-8") as f:
                json.dump([pa.to_dict() for pa in self._pending_annotations.values()], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存待审批标注失败: {e}")

    def get_type(self, type_id: str) -> Optional[ViolationType]:
        return self._types.get(type_id)

    def get_type_by_name(self, name: str) -> Optional[ViolationType]:
        for vt in self._types.values():
            if vt.name == name and vt.status == "active":
                return vt
        return None

    def list_types(self, level: int = None, parent_id: str = None, status: str = "active") -> List[ViolationType]:
        result = []
        for vt in self._types.values():
            if status and vt.status != status:
                continue
            if level is not None and vt.level != level:
                continue
            if parent_id is not None and vt.parent_id != parent_id:
                continue
            result.append(vt)
        return result

    def get_active_rules(self) -> List[Dict]:
        rules = []
        for vt in self._types.values():
            if vt.status != "active" or not vt.keywords:
                continue
            articles = self.get_articles_for_type(vt.id)
            rules.append({
                "type_id": vt.id,
                "keywords": vt.keywords,
                "violation_type": vt.name,
                "severity": vt.severity,
                "articles": articles,
                "suggestions": vt.suggestions,
            })
        return rules

    def get_articles_for_type(self, type_id: str) -> List[Dict]:
        articles = []
        for cm in self._mappings.values():
            if cm.violation_type_id == type_id and cm.expiration_date is None:
                articles.append({
                    "doc_name": cm.doc_name,
                    "article_number": cm.article_number,
                    "mapping_logic": cm.mapping_logic,
                })
        return articles

    def get_mappings_for_article(self, doc_name: str, article_number: str) -> List[ClauseTypeMapping]:
        result = []
        for cm in self._mappings.values():
            if cm.doc_name == doc_name and cm.article_number == article_number and cm.expiration_date is None:
                result.append(cm)
        return result

    def get_severity(self, violation_type_name: str) -> float:
        vt = self.get_type_by_name(violation_type_name)
        if vt:
            return vt.severity
        return 0.5

    def get_suggestion(self, violation_type_name: str) -> str:
        vt = self.get_type_by_name(violation_type_name)
        if vt:
            return vt.suggestions
        return "请根据违规类型修改"

    def add_type(
        self,
        name: str,
        level: int,
        parent_id: Optional[str],
        severity: float,
        description: str,
        keywords: List[str],
        suggestions: str,
        is_system: bool = False,
    ) -> ViolationType:
        if not config.has_api_key():
            raise ValueError("无API Key，不支持创建自定义违规类型")

        type_id = name.lower().replace(" ", "_")
        if any(c in type_id for c in "/\\、，"):
            type_id = str(uuid.uuid4())[:8]

        if type_id in self._types:
            existing = self._types[type_id]
            if existing.status == "deprecated":
                existing.status = "active"
                existing.name = name
                existing.severity = severity
                existing.description = description
                existing.keywords = keywords
                existing.suggestions = suggestions
                existing.updated_at = datetime.now().isoformat()
                self._save()
                return existing
            raise ValueError(f"违规类型已存在: {type_id}")

        now = datetime.now().isoformat()
        vt = ViolationType(
            id=type_id,
            name=name,
            level=level,
            parent_id=parent_id,
            severity=severity,
            description=description,
            keywords=keywords,
            suggestions=suggestions,
            is_system=is_system,
            status="active",
            created_at=now,
            updated_at=now,
        )
        self._types[vt.id] = vt
        self._save()
        logger.info(f"新增违规类型: {name}({type_id}), level={level}, severity={severity}")
        return vt

    def update_type(self, type_id: str, **kwargs) -> Optional[ViolationType]:
        vt = self._types.get(type_id)
        if not vt:
            return None
        if vt.is_system and "severity" in kwargs:
            logger.warning(f"系统预定义类型 {type_id} 的severity不建议修改")
        for key, value in kwargs.items():
            if hasattr(vt, key) and key not in ("id", "is_system", "created_at"):
                setattr(vt, key, value)
        vt.updated_at = datetime.now().isoformat()
        self._save()
        return vt

    def deprecate_type(self, type_id: str) -> bool:
        vt = self._types.get(type_id)
        if not vt:
            return False
        if vt.is_system:
            logger.warning(f"系统预定义类型 {type_id} 不建议废弃")
        vt.status = "deprecated"
        vt.updated_at = datetime.now().isoformat()
        for cm in self._mappings.values():
            if cm.violation_type_id == type_id and cm.expiration_date is None:
                cm.expiration_date = datetime.now().isoformat()
        if vt.level == 1:
            deprecated_children = []
            for child_id, child_vt in self._types.items():
                if child_vt.parent_id == type_id and child_vt.status != "deprecated":
                    child_vt.status = "deprecated"
                    child_vt.updated_at = datetime.now().isoformat()
                    for cm in self._mappings.values():
                        if cm.violation_type_id == child_id and cm.expiration_date is None:
                            cm.expiration_date = datetime.now().isoformat()
                    deprecated_children.append(child_vt.name)
            if deprecated_children:
                logger.info(f"L1类型 {type_id} 废弃，级联废弃子类型: {deprecated_children}")
        self._save()
        logger.info(f"违规类型已废弃: {type_id}")
        return True

    def add_mapping(
        self,
        violation_type_id: str,
        doc_name: str,
        article_number: str,
        mapping_logic: str = "primary",
        effective_date: str = None,
    ) -> ClauseTypeMapping:
        for cm in self._mappings.values():
            if (cm.violation_type_id == violation_type_id and
                    cm.doc_name == doc_name and
                    cm.article_number == article_number and
                    cm.expiration_date is None):
                logger.info(f"映射已存在: {violation_type_id} -> {doc_name}/{article_number}")
                return cm

        now = datetime.now().isoformat()
        cm = ClauseTypeMapping(
            id=str(uuid.uuid4())[:8],
            violation_type_id=violation_type_id,
            doc_name=doc_name,
            article_number=article_number,
            mapping_logic=mapping_logic,
            effective_date=effective_date or now,
            expiration_date=None,
            created_at=now,
        )
        self._mappings[cm.id] = cm
        self._save()
        logger.info(f"新增条款映射: {violation_type_id} -> {doc_name}/{article_number}")
        return cm

    def expire_mapping(self, doc_name: str, article_number: str, violation_type_id: str = None):
        for cm in self._mappings.values():
            if cm.doc_name == doc_name and cm.article_number == article_number and cm.expiration_date is None:
                if violation_type_id is None or cm.violation_type_id == violation_type_id:
                    cm.expiration_date = datetime.now().isoformat()
        self._save()

    def add_keyword(self, type_id: str, keyword: str) -> bool:
        vt = self._types.get(type_id)
        if not vt:
            return False
        if keyword not in vt.keywords:
            vt.keywords.append(keyword)
            vt.updated_at = datetime.now().isoformat()
            self._save()
            logger.info(f"违规类型 {type_id} 新增关键词: {keyword}")
        return True

    def remove_keyword(self, type_id: str, keyword: str, force: bool = False) -> bool:
        vt = self._types.get(type_id)
        if not vt:
            return False
        if keyword in vt.keywords:
            if len(vt.keywords) == 1 and not force:
                raise ValueError(
                    f"该关键词是类型 {type_id} 的最后一个关键词，删除后规则引擎将无法匹配该类型。如确认删除请使用 force=True"
                )
            if vt.is_system:
                logger.warning(f"系统预定义类型 {type_id} 正在移除关键词: {keyword}")
            vt.keywords.remove(keyword)
            vt.updated_at = datetime.now().isoformat()
            self._save()
            logger.info(f"违规类型 {type_id} 移除关键词: {keyword}, operator=...")
        return True

    def annotate_chunks(self, chunks: List) -> List[PendingAnnotation]:
        if not config.has_api_key():
            return self._annotate_chunks_rule_based(chunks)

        try:
            return self._annotate_chunks_llm(chunks)
        except Exception as e:
            logger.warning(f"LLM标注失败，降级为规则标注: {e}")
            return self._annotate_chunks_rule_based(chunks)

    def _annotate_chunks_rule_based(self, chunks: List) -> List[PendingAnnotation]:
        annotations = []
        now = datetime.now().isoformat()

        for chunk in chunks:
            existing = self.get_mappings_for_article(chunk.doc_name, chunk.article_number)
            if existing:
                continue

            suggested_type_id = None
            suggested_type_name = None
            is_new_type = False

            for vt in self._types.values():
                if vt.status != "active" or not vt.keywords:
                    continue
                for kw in vt.keywords:
                    if kw in chunk.article_text:
                        suggested_type_id = vt.id
                        suggested_type_name = vt.name
                        break
                if suggested_type_id:
                    break

            if not suggested_type_id:
                suggested_type_name = "待分类"
                is_new_type = True

            pa = PendingAnnotation(
                id=str(uuid.uuid4())[:8],
                doc_name=chunk.doc_name,
                article_number=chunk.article_number,
                article_text=chunk.article_text[:500],
                behavior_pattern={},
                suggested_type_id=suggested_type_id,
                suggested_type_name=suggested_type_name,
                is_new_type=is_new_type,
                status="pending",
                created_at=now,
            )
            self._pending_annotations[pa.id] = pa
            annotations.append(pa)

        if annotations:
            self._save()
        return annotations

    def _annotate_chunks_llm(self, chunks: List) -> List[PendingAnnotation]:
        from src.llm_gateway import llm_gateway, ModelRole

        annotations = []
        now = datetime.now().isoformat()

        existing_types_text = "\n".join(
            f"- {vt.name}(id={vt.id}, level=L{vt.level}): {vt.description}"
            for vt in sorted(self._types.values(), key=lambda x: (x.level, x.name))
            if vt.status == "active"
        )

        for chunk in chunks:
            existing = self.get_mappings_for_article(chunk.doc_name, chunk.article_number)
            if existing:
                continue

            user_prompt = ANNOTATION_USER_TEMPLATE.format(
                existing_types=existing_types_text,
                doc_name=chunk.doc_name,
                article_number=chunk.article_number,
                article_text=chunk.article_text[:1000],
            )

            try:
                resp = llm_gateway.generate(
                    system_prompt=ANNOTATION_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    role=ModelRole.LIGHTWEIGHT,
                )
                parsed = self._parse_annotation_json(resp.content)
            except Exception as e:
                logger.warning(f"条文 {chunk.doc_name}/{chunk.article_number} LLM标注失败: {e}")
                parsed = None

            if parsed and not parsed.get("is_content_audit", True):
                logger.info(f"条文 {chunk.doc_name}/{chunk.article_number} 为程序性条款，跳过")
                continue

            suggested_type_id = None
            suggested_type_name = None
            is_new_type = False

            if parsed:
                suggested_name = parsed.get("suggested_violation_type", "")
                is_new_type = parsed.get("is_new_type", False)
                if not is_new_type and suggested_name:
                    matched = self.get_type_by_name(suggested_name)
                    if matched:
                        suggested_type_id = matched.id
                        suggested_type_name = matched.name
                    else:
                        is_new_type = True
                        suggested_type_name = suggested_name
                elif is_new_type:
                    suggested_type_name = suggested_name
            else:
                suggested_type_name = "待分类"
                is_new_type = True

            pa = PendingAnnotation(
                id=str(uuid.uuid4())[:8],
                doc_name=chunk.doc_name,
                article_number=chunk.article_number,
                article_text=chunk.article_text[:500],
                behavior_pattern=parsed.get("behavior_pattern", {}) if parsed else {},
                suggested_type_id=suggested_type_id,
                suggested_type_name=suggested_type_name,
                is_new_type=is_new_type,
                status="pending",
                created_at=now,
            )
            self._pending_annotations[pa.id] = pa
            annotations.append(pa)

        if annotations:
            self._save()
        return annotations

    def _parse_annotation_json(self, text: str) -> Optional[Dict]:
        import json as _json
        try:
            json_str = text
            if "```json" in text:
                json_str = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                json_str = text.split("```")[1].split("```")[0].strip()
            return _json.loads(json_str)
        except Exception:
            return None

    def get_pending_annotations(self, status: str = "pending") -> List[PendingAnnotation]:
        return [pa for pa in self._pending_annotations.values() if pa.status == status]

    def approve_annotation(self, annotation_id: str, type_id: str = None) -> Optional[PendingAnnotation]:
        pa = self._pending_annotations.get(annotation_id)
        if not pa or pa.status != "pending":
            return None

        if type_id:
            pa.suggested_type_id = type_id
            vt = self._types.get(type_id)
            if vt:
                pa.suggested_type_name = vt.name
                pa.is_new_type = False

        if pa.is_new_type and pa.suggested_type_name:
            new_vt = self.add_type(
                name=pa.suggested_type_name,
                level=2,
                parent_id=pa.suggested_type_id or "false_publicity",
                severity=0.5,
                description=pa.behavior_pattern.get("action", pa.suggested_type_name),
                keywords=[],
                suggestions="请根据违规类型修改",
            )
            pa.suggested_type_id = new_vt.id
            pa.is_new_type = False

        if pa.suggested_type_id:
            self.add_mapping(
                violation_type_id=pa.suggested_type_id,
                doc_name=pa.doc_name,
                article_number=pa.article_number,
            )

        pa.status = "approved"
        self._save()
        logger.info(f"标注已审批: {pa.doc_name}/{pa.article_number} -> {pa.suggested_type_name}")
        return pa

    def reject_annotation(self, annotation_id: str) -> Optional[PendingAnnotation]:
        pa = self._pending_annotations.get(annotation_id)
        if not pa or pa.status != "pending":
            return None
        pa.status = "rejected"
        self._save()
        return pa

    def is_type_deprecated(self, type_id: str) -> bool:
        vt = self._types.get(type_id)
        return vt is not None and vt.status == "deprecated"

    def get_deprecated_names(self, type_ids: List[str]) -> List[str]:
        result = []
        for tid in type_ids:
            vt = self._types.get(tid)
            if vt and vt.status == "deprecated":
                result.append(vt.name)
        return result

    def get_stats(self) -> Dict:
        l1_count = sum(1 for vt in self._types.values() if vt.level == 1 and vt.status == "active")
        l2_count = sum(1 for vt in self._types.values() if vt.level == 2 and vt.status == "active")
        system_count = sum(1 for vt in self._types.values() if vt.is_system and vt.status == "active")
        custom_count = sum(1 for vt in self._types.values() if not vt.is_system and vt.status == "active")
        active_mappings = sum(1 for cm in self._mappings.values() if cm.expiration_date is None)
        pending_count = sum(1 for pa in self._pending_annotations.values() if pa.status == "pending")
        return {
            "total_types": len(self._types),
            "l1_types": l1_count,
            "l2_types": l2_count,
            "system_types": system_count,
            "custom_types": custom_count,
            "active_mappings": active_mappings,
            "pending_annotations": pending_count,
        }


violation_registry = ViolationRegistry()
