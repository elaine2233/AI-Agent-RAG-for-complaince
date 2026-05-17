import time
import logging
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class WorkflowStep:
    name: str
    status: StepStatus = StepStatus.PENDING
    input_data: Dict = field(default_factory=dict)
    output_data: Dict = field(default_factory=dict)
    latency_ms: float = 0.0
    error: str = ""


@dataclass
class WorkflowState:
    original_text: str = ""
    image_descriptions: List[str] = field(default_factory=list)
    extracted_claims: List[Dict] = field(default_factory=list)
    rule_check_result: Optional[Dict] = None
    retrieved_laws: List[Dict] = field(default_factory=list)
    reranked_laws: List[Dict] = field(default_factory=list)
    expanded_relations: List[Dict] = field(default_factory=list)
    reasoning_result: Optional[Dict] = None
    formatted_result: Optional[Dict] = None
    validation_result: Optional[Dict] = None
    crosscheck_result: Optional[Dict] = None
    risk_score: float = 0.0
    risk_level: str = "low"
    decision: str = "auto_pass"
    few_shot_examples: List[Dict] = field(default_factory=list)
    prompt_version: str = ""
    model_used: str = ""
    steps: List[WorkflowStep] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["steps"] = [
            {**s, "status": s["status"].value if isinstance(s["status"], StepStatus) else s["status"]}
            for s in d["steps"]
        ]
        return d

    def add_step(self, name: str) -> WorkflowStep:
        step = WorkflowStep(name=name)
        self.steps.append(step)
        return step


class WorkflowEngine:
    def __init__(self):
        self._steps: List[Dict] = []
        self._step_registry: Dict[str, Callable] = {}

    def register_step(self, name: str, handler: Callable, condition: Callable = None):
        self._steps.append({"name": name, "handler": handler, "condition": condition})
        self._step_registry[name] = handler

    def run(self, state: WorkflowState) -> WorkflowState:
        for step_config in self._steps:
            name = step_config["name"]
            handler = step_config["handler"]
            condition = step_config["condition"]

            step = state.add_step(name)

            if condition and not condition(state):
                step.status = StepStatus.SKIPPED
                logger.debug(f"Workflow step '{name}' skipped (condition not met)")
                continue

            step.status = StepStatus.RUNNING
            step.input_data = _safe_snapshot(state)
            start = time.time()

            try:
                handler(state)
                step.status = StepStatus.COMPLETED
                step.output_data = _safe_snapshot(state)
            except Exception as e:
                step.status = StepStatus.FAILED
                step.error = str(e)
                logger.error(f"Workflow step '{name}' failed: {e}")
                break

            step.latency_ms = (time.time() - start) * 1000

        return state


def _safe_snapshot(state: WorkflowState) -> Dict:
    try:
        d = state.to_dict()
        if "steps" in d:
            del d["steps"]
        return d
    except Exception:
        return {}
