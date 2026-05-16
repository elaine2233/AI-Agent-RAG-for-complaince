import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

import config

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Decision(Enum):
    AUTO_PASS = "auto_pass"
    AUTO_BLOCK = "auto_block"
    HUMAN_REVIEW = "human_review"


@dataclass
class RiskAssessment:
    risk_score: float
    risk_level: RiskLevel
    decision: Decision
    risk_factors: List[Dict]
    explanation: str

    def to_dict(self):
        return {
            "risk_score": self.risk_score,
            "risk_level": self.risk_level.value,
            "decision": self.decision.value,
            "risk_factors": self.risk_factors,
            "explanation": self.explanation,
        }


VIOLATION_SEVERITY = {
    "绝对化用语": 0.9,
    "收益承诺": 0.9,
    "夸大收益": 0.8,
    "产品混淆": 0.8,
    "无资质代言": 0.7,
    "诱导销售": 0.7,
    "隐瞒信息": 0.6,
    "夸大宣传": 0.6,
    "风险提示不足": 0.5,
    "资质合规": 0.5,
    "信息保护": 0.4,
    "其他违规": 0.3,
}


class RiskEngine:
    def __init__(self):
        self._thresholds = {
            "auto_pass_max": getattr(config, "RISK_AUTO_PASS_MAX", 0.3),
            "human_review_max": getattr(config, "RISK_HUMAN_REVIEW_MAX", 0.7),
        }

    def assess(
        self,
        compliant: str,
        violation_type: str,
        violated_articles: List[Dict],
        confidence: float,
        rule_hit: bool = False,
    ) -> RiskAssessment:
        risk_score = self._calculate_risk_score(
            compliant, violation_type, violated_articles, confidence, rule_hit
        )
        risk_level = self._determine_risk_level(risk_score)
        decision = self._make_decision(risk_level, risk_score)
        risk_factors = self._identify_risk_factors(
            violation_type, violated_articles, confidence, rule_hit
        )
        explanation = self._generate_explanation(risk_level, decision, risk_factors)

        return RiskAssessment(
            risk_score=round(risk_score, 4),
            risk_level=risk_level,
            decision=decision,
            risk_factors=risk_factors,
            explanation=explanation,
        )

    def _calculate_risk_score(
        self,
        compliant: str,
        violation_type: str,
        violated_articles: List[Dict],
        confidence: float,
        rule_hit: bool,
    ) -> float:
        if compliant == "yes":
            base_score = 0.1
            if confidence < 0.7:
                base_score += (1.0 - confidence) * 0.3
            return min(base_score, 1.0)

        if compliant == "unknown":
            return 0.5

        score = 0.0

        violation_types = [v.strip() for v in violation_type.split("、") if v.strip() and v.strip() != "无"]
        if violation_types:
            max_severity = max(VIOLATION_SEVERITY.get(vt, 0.5) for vt in violation_types)
            score += max_severity * 0.5

        score += min(len(violated_articles) * 0.1, 0.3)

        if rule_hit:
            score += 0.15

        if confidence > 0.8:
            score += 0.1
        elif confidence < 0.5:
            score -= 0.1

        return max(0.0, min(1.0, score))

    def _determine_risk_level(self, risk_score: float) -> RiskLevel:
        if risk_score < self._thresholds["auto_pass_max"]:
            return RiskLevel.LOW
        elif risk_score < self._thresholds["human_review_max"]:
            return RiskLevel.MEDIUM
        elif risk_score < 0.9:
            return RiskLevel.HIGH
        else:
            return RiskLevel.CRITICAL

    def _make_decision(self, risk_level: RiskLevel, risk_score: float) -> Decision:
        if risk_level == RiskLevel.LOW:
            return Decision.AUTO_PASS
        elif risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            return Decision.AUTO_BLOCK
        else:
            return Decision.HUMAN_REVIEW

    def _identify_risk_factors(
        self,
        violation_type: str,
        violated_articles: List[Dict],
        confidence: float,
        rule_hit: bool,
    ) -> List[Dict]:
        factors = []

        violation_types = [v.strip() for v in violation_type.split("、") if v.strip() and v.strip() != "无"]
        for vt in violation_types:
            severity = VIOLATION_SEVERITY.get(vt, 0.5)
            factors.append({
                "type": "violation",
                "violation_type": vt,
                "severity": severity,
                "description": f"检测到{vt}违规，严重度{severity:.1f}",
            })

        if len(violated_articles) > 2:
            factors.append({
                "type": "multi_violation",
                "severity": 0.7,
                "description": f"涉及{len(violated_articles)}条法规违规，风险叠加",
            })

        if confidence < 0.6:
            factors.append({
                "type": "low_confidence",
                "severity": 0.4,
                "description": f"置信度较低({confidence:.2f})，建议人工复核",
            })

        if rule_hit:
            factors.append({
                "type": "rule_hit",
                "severity": 0.8,
                "description": "规则引擎命中违规关键词，确定性高",
            })

        return factors

    def _generate_explanation(
        self,
        risk_level: RiskLevel,
        decision: Decision,
        risk_factors: List[Dict],
    ) -> str:
        parts = [f"风险等级: {risk_level.value}"]

        decision_map = {
            Decision.AUTO_PASS: "自动通过",
            Decision.AUTO_BLOCK: "自动拦截",
            Decision.HUMAN_REVIEW: "转人工复核",
        }
        parts.append(f"处置决策: {decision_map[decision]}")

        if risk_factors:
            top_factors = sorted(risk_factors, key=lambda f: f.get("severity", 0), reverse=True)[:3]
            for f in top_factors:
                parts.append(f"- {f['description']}")

        return "\n".join(parts)


risk_engine = RiskEngine()
