import json
import os
from typing import List, Dict, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict

from src.review_agent import ReviewAgent, ReviewResult


@dataclass
class EvalResult:
    test_case_id: str
    predicted_compliant: str
    expected_compliant: str
    compliant_correct: bool
    predicted_violation_types: str
    expected_violation_types: List[str]
    violation_type_match: bool
    confidence: float
    reasoning: str

    def to_dict(self):
        return asdict(self)


class Evaluator:
    def __init__(self, review_agent: ReviewAgent):
        self.review_agent = review_agent

    def load_test_cases(self, path: str = None) -> List[Dict]:
        if path is None:
            path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval", "test_cases.json"
            )
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def evaluate_single(self, test_case: Dict) -> EvalResult:
        content = test_case["content"]
        expected_compliant = test_case["expected_compliant"]
        expected_types = test_case["expected_violation_types"]

        result = self.review_agent.review(content)

        predicted_compliant = result.compliant
        compliant_correct = predicted_compliant == expected_compliant

        predicted_types_str = result.violation_type
        predicted_types = [t.strip() for t in predicted_types_str.split("、") if t.strip() and t.strip() != "无"]

        violation_match = self._check_violation_match(predicted_types, expected_types)

        return EvalResult(
            test_case_id=test_case["id"],
            predicted_compliant=predicted_compliant,
            expected_compliant=expected_compliant,
            compliant_correct=compliant_correct,
            predicted_violation_types=predicted_types_str,
            expected_violation_types=expected_types,
            violation_type_match=violation_match,
            confidence=result.confidence,
            reasoning=result.reasoning,
        )

    def _check_violation_match(self, predicted: List[str], expected: List[str]) -> bool:
        if not expected:
            return len(predicted) == 0

        matched = 0
        for exp_type in expected:
            for pred_type in predicted:
                if exp_type in pred_type or pred_type in exp_type:
                    matched += 1
                    break

        return matched >= len(expected) * 0.5

    def evaluate_all(self, test_cases_path: str = None) -> Dict:
        test_cases = self.load_test_cases(test_cases_path)
        eval_results = []

        print(f"\n{'='*60}")
        print(f"开始评估，共 {len(test_cases)} 个测试用例")
        print(f"{'='*60}\n")

        for i, tc in enumerate(test_cases):
            print(f"[{i+1}/{len(test_cases)}] 评估: {tc['id']} - {tc['description']}")
            eval_result = self.evaluate_single(tc)
            eval_results.append(eval_result)
            status = "✓" if eval_result.compliant_correct else "✗"
            print(f"  {status} 合规判断: 预测={eval_result.predicted_compliant}, 期望={eval_result.expected_compliant}")
            print(f"  违规类型: 预测={eval_result.predicted_violation_types}, 期望={eval_result.expected_violation_types}")
            print(f"  置信度: {eval_result.confidence}")
            print()

        total = len(eval_results)
        compliant_correct = sum(1 for r in eval_results if r.compliant_correct)
        violation_correct = sum(1 for r in eval_results if r.violation_type_match)
        avg_confidence = sum(r.confidence for r in eval_results) / total if total > 0 else 0

        compliant_acc = compliant_correct / total if total > 0 else 0
        violation_acc = violation_correct / total if total > 0 else 0

        positive_cases = [r for r in eval_results if r.expected_compliant == "no"]
        negative_cases = [r for r in eval_results if r.expected_compliant == "yes"]

        precision = 0
        recall = 0
        f1 = 0

        if positive_cases:
            tp = sum(1 for r in positive_cases if r.predicted_compliant == "no")
            fn = sum(1 for r in positive_cases if r.predicted_compliant != "no")
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0

        if negative_cases:
            tp_neg = sum(1 for r in positive_cases if r.predicted_compliant == "no")
            fp = sum(1 for r in negative_cases if r.predicted_compliant == "no")
            precision = tp_neg / (tp_neg + fp) if (tp_neg + fp) > 0 else 0

        if precision + recall > 0:
            f1 = 2 * precision * recall / (precision + recall)

        report = {
            "total_cases": total,
            "compliant_accuracy": round(compliant_acc, 4),
            "violation_type_accuracy": round(violation_acc, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1_score": round(f1, 4),
            "avg_confidence": round(avg_confidence, 4),
            "details": [r.to_dict() for r in eval_results],
        }

        print(f"\n{'='*60}")
        print(f"评估报告")
        print(f"{'='*60}")
        print(f"总测试用例: {total}")
        print(f"合规判断准确率: {compliant_acc:.2%} ({compliant_correct}/{total})")
        print(f"违规类型匹配率: {violation_acc:.2%} ({violation_correct}/{total})")
        print(f"精确率 (Precision): {precision:.2%}")
        print(f"召回率 (Recall): {recall:.2%}")
        print(f"F1分数: {f1:.4f}")
        print(f"平均置信度: {avg_confidence:.4f}")
        print(f"{'='*60}\n")

        return report

    def save_report(self, report: Dict, output_path: str):
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"评估报告已保存到: {output_path}")


if __name__ == "__main__":
    from src.rag_engine import RAGEngine

    rag_engine = RAGEngine()
    rag_engine.build_index()

    agent = ReviewAgent(rag_engine)
    evaluator = Evaluator(agent)

    report = evaluator.evaluate_all()
    evaluator.save_report(report, "./data/eval_report.json")
