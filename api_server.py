import os
import sys
import json
import time
import signal
import logging
import hashlib
import asyncio
from typing import List, Optional, Dict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Header, Query, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, validator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src.rag_engine import RAGEngine
from src.review_agent import ReviewAgent, ReviewResult
from src.database import Database
from src.clause_relation_extractor import ClauseRelationExtractor, populate_predefined_relations
from src.security import security_middleware
from src.resilience import llm_circuit_breaker, embedding_circuit_breaker, review_cache
from src.async_engine import task_queue, review_semaphore
from src.observability import (
    trace_operation, alert_manager, health_checker, setup_default_alerts,
    get_metrics_text, get_metrics_content_type, PROMETHEUS_AVAILABLE,
    REVIEW_TOTAL, REVIEW_DURATION, REVIEW_IN_PROGRESS, SECURITY_BLOCKED,
    TASK_QUEUE_SIZE,
)

logger = logging.getLogger(__name__)

rag_engine: Optional[RAGEngine] = None
review_agent: Optional[ReviewAgent] = None
db: Optional[Database] = None
_shutdown_event = asyncio.Event()


class ReviewRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000, description="待审核的营销文本")
    image_descriptions: Optional[List[str]] = Field(None, max_length=5, description="图片描述列表")

    @validator("content")
    def content_must_not_be_empty(cls, v):
        if not v.strip():
            raise ValueError("内容不能为空")
        return v.strip()

    @validator("image_descriptions")
    def image_descriptions_length(cls, v):
        if v:
            for desc in v:
                if len(desc) > 2000:
                    raise ValueError("单条图片描述不能超过2000字符")
        return v


class MultiModalReviewRequest(BaseModel):
    text: Optional[str] = Field(None, max_length=10000, description="文本内容")
    image_paths: Optional[List[str]] = Field(None, max_length=5, description="图片文件路径")
    file_paths: Optional[List[str]] = Field(None, max_length=3, description="文件路径(PDF/Word/TXT)")

    @validator("text")
    def text_must_not_all_empty(cls, v):
        if v is not None:
            return v.strip()
        return v


class BatchReviewRequest(BaseModel):
    items: List[ReviewRequest] = Field(..., min_length=1, max_length=50)

    @validator("items")
    def items_length(cls, v):
        if len(v) > 50:
            raise ValueError("批量审核最多50条")
        return v


class FeedbackRequest(BaseModel):
    review_id: int = Field(..., gt=0)
    is_correct: bool
    comment: str = Field("", max_length=1000)


class ReviewResponse(BaseModel):
    review_id: int
    compliant: str
    violation_type: str
    violated_articles: list
    confidence: float
    reasoning: str
    suggestions: str
    latency_ms: float
    risk_score: float = 0.0
    risk_level: str = "low"
    decision: str = "auto_pass"
    review_mode: str = ""
    model_used: str = ""
    prompt_version: str = ""
    workflow_steps: list = []
    regulation_snapshot: dict = {}
    crosscheck_passed: bool = True
    expanded_relations: list = []


class BatchReviewResponse(BaseModel):
    total: int
    results: List[ReviewResponse]
    total_latency_ms: float


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float
    components: dict


_start_time = time.time()


def _ensure_db():
    global db
    if db is None:
        db = Database()
    return db


async def get_current_user(api_key: Optional[str] = Header(None, alias="X-API-Key")):
    database = _ensure_db()
    if api_key:
        user = database.authenticate_api_key(api_key)
        if user:
            return user
    demo_row = database._get_conn().execute(
        "SELECT id, username, role FROM users WHERE username = 'demo' AND is_active = 1"
    ).fetchone()
    if demo_row:
        return {"id": demo_row["id"], "username": demo_row["username"], "role": demo_row["role"], "api_key": ""}
    raise HTTPException(status_code=401, detail="缺少API Key，请在X-API-Key头中提供")


async def get_optional_user(api_key: Optional[str] = Header(None, alias="X-API-Key")):
    if not api_key:
        return None
    database = _ensure_db()
    return database.authenticate_api_key(api_key)


def _ensure_agent():
    global rag_engine, review_agent
    if review_agent is None:
        rag_engine = RAGEngine()
        rag_engine.build_index()
        review_agent = ReviewAgent(rag_engine)
    return review_agent


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rag_engine, review_agent, db
    logger.info("正在初始化系统...")

    db = Database()
    rag_engine = RAGEngine()
    rag_engine.build_index()
    review_agent = ReviewAgent(rag_engine)

    db._ensure_regulation_versions()
    db._sync_clause_mappings()

    populate_predefined_relations(db)
    extractor = ClauseRelationExtractor()
    docs = rag_engine.get_all_chunks() if hasattr(rag_engine, 'get_all_chunks') else []
    if docs:
        extracted = extractor.extract_from_documents(docs)
        for rel in extracted:
            db.save_clause_relation(
                from_doc=rel['from_doc'], from_article=rel['from_article'],
                to_doc=rel['to_doc'], to_article=rel['to_article'],
                relation_type=rel['relation_type'], confidence=rel['confidence'],
                evidence_text=rel['evidence_text'], source=rel['source']
            )
        logger.info(f"正则提取了 {len(extracted)} 条条款关系")

    setup_default_alerts()
    health_checker.register("database", lambda: db.health_check()["status"] == "healthy")
    health_checker.register("rag_engine", lambda: len(rag_engine.chunks) > 0)
    health_checker.register("llm_circuit", lambda: llm_circuit_breaker.state.value != "open")
    health_checker.register("task_queue", lambda: task_queue.get_stats()["queue_size"] < task_queue.max_queue_size * 0.9)

    if PROMETHEUS_AVAILABLE and TASK_QUEUE_SIZE:
        TASK_QUEUE_SIZE.set(0)

    loop = asyncio.get_event_loop()

    def _signal_handler(signum, frame):
        logger.info(f"收到信号 {signum}，开始优雅关闭...")
        _shutdown_event.set()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    logger.info("系统初始化完成")

    yield

    logger.info("正在关闭系统...")
    task_queue.shutdown(wait=False)
    database = _ensure_db()
    database.backup()
    database.close()
    logger.info("系统已关闭")


app = FastAPI(
    title="保险营销内容智能审核系统",
    version="2.0.0",
    lifespan=lifespan,
)

_cors_origins = os.getenv("CORS_ORIGINS", config.CORS_ORIGINS + ",http://localhost:8080")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PUT"],
    allow_headers=["X-API-Key", "X-Model", "Content-Type"],
)

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")


@app.get("/", tags=["前端"])
async def serve_frontend():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"), media_type="text/html")


@app.get("/health", response_model=HealthResponse, tags=["系统"])
async def health_check():
    components = {}

    db_health = _ensure_db().health_check()
    components["database"] = db_health

    components["rag_engine"] = {
        "status": "healthy" if rag_engine is not None and rag_engine.chunks else "not_initialized",
        "chunks_count": len(rag_engine.chunks) if rag_engine is not None else 0,
        "use_vector": rag_engine.use_vector if rag_engine is not None else False,
    }

    components["llm_circuit_breaker"] = llm_circuit_breaker.get_state()
    components["embedding_circuit_breaker"] = embedding_circuit_breaker.get_state()
    components["cache"] = review_cache.stats()

    overall = "healthy"
    for comp in components.values():
        if isinstance(comp, dict) and comp.get("status") in ("unhealthy", "open", "not_initialized"):
            overall = "degraded"
            break

    if _shutdown_event.is_set():
        overall = "shutting_down"

    return HealthResponse(
        status=overall,
        version="2.0.0",
        uptime_seconds=round(time.time() - _start_time, 1),
        components=components,
    )


@app.get("/ready", tags=["系统"])
async def readiness_check():
    if rag_engine is None or not rag_engine.chunks:
        raise HTTPException(status_code=503, detail="服务未就绪")
    if _shutdown_event.is_set():
        raise HTTPException(status_code=503, detail="服务正在关闭")
    return {"status": "ready"}


@app.post("/api/v1/test-connection", tags=["系统"])
async def test_dashscope_connection(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    api_key = x_api_key or config.DASHSCOPE_API_KEY
    if not api_key or api_key == "demo-key-insurance-review-2024":
        return {"success": False, "message": "未配置DashScope API Key，请输入有效的API Key后重试"}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=config.LLM_BASE_URL)
        resp = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "user", "content": "Hi"}],
            max_tokens=5,
        )
        if rag_engine and not rag_engine.use_vector:
            try:
                rag_engine.enable_vector_search()
            except Exception:
                pass
        return {"success": True, "message": f"连接成功，模型: {config.LLM_MODEL}"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)[:200]}"}


@app.get("/metrics", tags=["监控"])
async def metrics_endpoint():
    if PROMETHEUS_AVAILABLE and TASK_QUEUE_SIZE:
        TASK_QUEUE_SIZE.set(task_queue.get_stats()["queue_size"])
    return Response(
        content=get_metrics_text(),
        media_type=get_metrics_content_type(),
    )


@app.get("/api/v1/alerts", tags=["监控"])
async def get_alerts(user: dict = Depends(get_current_user)):
    if not _ensure_db().check_permission(user.get("id"), "reviewer"):
        raise HTTPException(status_code=403, detail="权限不足")
    active = alert_manager.get_active_alerts()
    new_fired = alert_manager.check_alerts()
    return {"active_alerts": active, "new_fired": new_fired}


@app.get("/api/v1/health/detail", tags=["监控"])
async def detailed_health(user: dict = Depends(get_optional_user)):
    return health_checker.run_all()


@app.post("/api/v1/review", response_model=ReviewResponse, tags=["审核"])
async def review_content(
    request: ReviewRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
    x_model: Optional[str] = Header(None, alias="X-Model"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
):
    start_time = time.time()

    validation = security_middleware.validate_and_sanitize(
        request.content, client_id=user.get("username", "anonymous")
    )
    if not validation.is_valid:
        if PROMETHEUS_AVAILABLE and SECURITY_BLOCKED:
            for threat in validation.threats:
                SECURITY_BLOCKED.labels(reason=threat[:50]).inc()
        raise HTTPException(
            status_code=400,
            detail={"message": "输入校验失败", "threats": validation.threats},
        )

    if not review_semaphore.acquire(timeout=10.0):
        raise HTTPException(
            status_code=429,
            detail="系统繁忙，并发审核数已达上限，请稍后重试",
        )

    try:
        if PROMETHEUS_AVAILABLE and REVIEW_IN_PROGRESS:
            REVIEW_IN_PROGRESS.inc()

        with trace_operation("review", {"user": user.get("username", "anonymous"), "mode": "llm" if not config.DEMO_MODE else "rule"}):
            result = _ensure_agent().review(
                content=validation.sanitized_input,
                image_descriptions=request.image_descriptions,
                client_id=user.get("username", "anonymous"),
                model_name=x_model,
                api_key=x_api_key,
            )
    finally:
        if PROMETHEUS_AVAILABLE and REVIEW_IN_PROGRESS:
            REVIEW_IN_PROGRESS.dec()
        review_semaphore.release()

    latency_ms = (time.time() - start_time) * 1000

    if PROMETHEUS_AVAILABLE and REVIEW_TOTAL:
        REVIEW_TOTAL.labels(
            status=result.compliant,
            violation_type=result.violation_type[:50],
            review_mode="llm" if not config.DEMO_MODE else "rule",
        ).inc()
    if PROMETHEUS_AVAILABLE and REVIEW_DURATION:
        REVIEW_DURATION.labels(review_mode="llm" if not config.DEMO_MODE else "rule").observe(
            latency_ms / 1000
        )

    review_data = {
        "user_id": user.get("id"),
        "input_content": validation.sanitized_input,
        "input_hash": hashlib.sha256(validation.sanitized_input.encode()).hexdigest()[:16],
        "input_length": len(validation.sanitized_input),
        "compliant": result.compliant,
        "violation_type": result.violation_type,
        "violated_articles": result.violated_articles,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
        "suggestions": result.suggestions,
        "review_mode": result.review_mode or ("llm" if not config.DEMO_MODE else "rule"),
        "latency_ms": latency_ms,
        "client_id": user.get("username", "anonymous"),
        "threats": validation.threats,
        "decision": result.decision,
        "risk_score": result.risk_score,
        "risk_level": result.risk_level,
        "model_used": result.model_used,
        "prompt_version": result.prompt_version,
        "violation_types": result.violation_types,
    }

    review_id = _ensure_db().save_review(review_data)

    return ReviewResponse(
        review_id=review_id,
        compliant=result.compliant,
        violation_type=result.violation_type,
        violated_articles=result.violated_articles,
        confidence=result.confidence,
        reasoning=result.reasoning,
        suggestions=result.suggestions,
        latency_ms=round(latency_ms, 2),
        risk_score=result.risk_score,
        risk_level=result.risk_level,
        decision=result.decision,
        review_mode=result.review_mode,
        model_used=result.model_used,
        prompt_version=result.prompt_version,
        workflow_steps=result.workflow_steps or [],
        regulation_snapshot=result.regulation_snapshot or {},
        crosscheck_passed=result.crosscheck_passed,
        expanded_relations=result.expanded_relations or [],
    )


@app.post("/api/v1/review/batch", response_model=BatchReviewResponse, tags=["审核"])
async def batch_review(
    request: BatchReviewRequest,
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "reviewer"):
        raise HTTPException(status_code=403, detail="权限不足，需要reviewer角色")

    start_time = time.time()
    results = []

    for item in request.items:
        validation = security_middleware.validate_and_sanitize(
            item.content, client_id=user.get("username", "anonymous")
        )
        if not validation.is_valid:
            if PROMETHEUS_AVAILABLE and SECURITY_BLOCKED:
                for threat in validation.threats:
                    SECURITY_BLOCKED.labels(reason=threat[:50]).inc()
            results.append(ReviewResponse(
                review_id=0,
                compliant="unknown",
                violation_type="输入校验失败",
                violated_articles=[],
                confidence=0.0,
                reasoning=f"校验失败: {'; '.join(validation.threats)}",
                suggestions="请修改输入内容",
                latency_ms=0,
            ))
            continue

        item_start = time.time()
        if not review_semaphore.acquire(timeout=10.0):
            results.append(ReviewResponse(
                review_id=0,
                compliant="unknown",
                violation_type="并发超限",
                violated_articles=[],
                confidence=0.0,
                reasoning="系统繁忙，并发审核数已达上限",
                suggestions="请稍后重试",
                latency_ms=0,
            ))
            continue

        try:
            with trace_operation("review_batch_item", {"user": user.get("username", "anonymous")}):
                result = _ensure_agent().review(
                    content=validation.sanitized_input,
                    image_descriptions=item.image_descriptions,
                    client_id=user.get("username", "anonymous"),
                )
        finally:
            review_semaphore.release()

        item_latency = (time.time() - item_start) * 1000

        if PROMETHEUS_AVAILABLE and REVIEW_TOTAL:
            REVIEW_TOTAL.labels(
                status=result.compliant,
                violation_type=result.violation_type[:50],
                review_mode="llm" if not config.DEMO_MODE else "rule",
            ).inc()

        review_data = {
            "user_id": user.get("id"),
            "input_content": validation.sanitized_input,
            "input_hash": hashlib.sha256(validation.sanitized_input.encode()).hexdigest()[:16],
            "input_length": len(validation.sanitized_input),
            "compliant": result.compliant,
            "violation_type": result.violation_type,
            "violated_articles": result.violated_articles,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "suggestions": result.suggestions,
            "review_mode": "llm" if not config.DEMO_MODE else "rule",
            "latency_ms": item_latency,
            "client_id": user.get("username", "anonymous"),
            "threats": validation.threats,
            "violation_types": result.violation_types,
        }
        item_review_id = _ensure_db().save_review(review_data)

        results.append(ReviewResponse(
            review_id=item_review_id,
            compliant=result.compliant,
            violation_type=result.violation_type,
            violated_articles=result.violated_articles,
            confidence=result.confidence,
            reasoning=result.reasoning,
            suggestions=result.suggestions,
            latency_ms=round(item_latency, 2),
            risk_score=result.risk_score,
            risk_level=result.risk_level,
            decision=result.decision,
            review_mode=result.review_mode,
            model_used=result.model_used,
            prompt_version=result.prompt_version,
            workflow_steps=result.workflow_steps or [],
            regulation_snapshot=result.regulation_snapshot or {},
            crosscheck_passed=result.crosscheck_passed,
        ))

    total_latency = (time.time() - start_time) * 1000

    return BatchReviewResponse(
        total=len(results),
        results=results,
        total_latency_ms=round(total_latency, 2),
    )


class AsyncReviewResponse(BaseModel):
    task_id: str
    status: str
    message: str


@app.post("/api/v1/review/async", response_model=AsyncReviewResponse, tags=["审核"])
async def async_review_content(
    request: ReviewRequest,
    user: dict = Depends(get_current_user),
):
    validation = security_middleware.validate_and_sanitize(
        request.content, client_id=user.get("username", "anonymous")
    )
    if not validation.is_valid:
        if PROMETHEUS_AVAILABLE and SECURITY_BLOCKED:
            for threat in validation.threats:
                SECURITY_BLOCKED.labels(reason=threat[:50]).inc()
        raise HTTPException(
            status_code=400,
            detail={"message": "输入校验失败", "threats": validation.threats},
        )

    sanitized = validation.sanitized_input
    input_length = len(sanitized)
    input_hash = hashlib.sha256(sanitized.encode()).hexdigest()[:16]
    client_id = user.get("username", "anonymous")
    user_id = user.get("id")

    def _do_review():
        if not review_semaphore.acquire(timeout=30.0):
            raise RuntimeError("并发审核数已达上限")
        try:
            return _ensure_agent().review(
                content=sanitized,
                image_descriptions=request.image_descriptions,
                client_id=client_id,
            )
        finally:
            review_semaphore.release()

    def _on_complete(review_result: ReviewResult):
        review_data = {
            "user_id": user_id,
            "input_content": sanitized,
            "input_hash": input_hash,
            "input_length": input_length,
            "compliant": review_result.compliant,
            "violation_type": review_result.violation_type,
            "violated_articles": review_result.violated_articles,
            "confidence": review_result.confidence,
            "reasoning": review_result.reasoning,
            "suggestions": review_result.suggestions,
            "review_mode": "llm" if not config.DEMO_MODE else "rule",
            "latency_ms": 0,
            "client_id": client_id,
            "threats": [],
            "violation_types": review_result.violation_types,
        }
        _ensure_db().save_review(review_data)

    try:
        task_id = task_queue.submit(_do_review)
    except RuntimeError as e:
        raise HTTPException(status_code=429, detail=str(e))

    return AsyncReviewResponse(
        task_id=task_id,
        status="pending",
        message=f"审核任务已提交，请通过 /api/v1/task/{task_id} 查询结果",
    )


@app.get("/api/v1/task/stats", tags=["审核"])
async def get_task_queue_stats(user: dict = Depends(get_current_user)):
    if not _ensure_db().check_permission(user.get("id"), "reviewer"):
        raise HTTPException(status_code=403, detail="权限不足")
    return {
        "task_queue": task_queue.get_stats(),
        "semaphore": review_semaphore.get_stats(),
    }


@app.get("/api/v1/task/{task_id}", tags=["审核"])
async def get_task_status(
    task_id: str,
    user: dict = Depends(get_current_user),
):
    task = task_queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    result = task.to_dict()

    if task.status == "completed" and task.result:
        if isinstance(task.result, ReviewResult):
            result["result"] = task.result.to_dict()

    return result


@app.post("/api/v1/feedback", tags=["审核"])
async def submit_feedback(
    request: FeedbackRequest,
    user: dict = Depends(get_current_user),
):
    review = _ensure_db().get_review(request.review_id)
    if not review:
        raise HTTPException(status_code=404, detail="审核记录不存在")

    feedback_id = _ensure_db().save_feedback(
        review_id=request.review_id,
        is_correct=request.is_correct,
        comment=request.comment,
        user_id=user.get("id"),
    )

    if not request.is_correct and request.comment:
        try:
            from src.prompt_manager import prompt_manager
            correct_result = {
                "compliant": "yes" if "合规" in request.comment else "no",
                "violation_type": request.comment[:100],
                "violated_articles": [],
                "confidence": 1.0,
            }
            input_text = review.get("input_content", "")[:500]
            if input_text:
                prompt_manager.add_few_shot_from_feedback(
                    input_text=input_text,
                    correct_result=correct_result,
                    source=f"human_feedback_user_{user.get('id')}",
                )
        except Exception as e:
            logger.warning(f"Few-Shot回流失败: {e}")

    return {"feedback_id": feedback_id, "message": "反馈已提交，Few-Shot样本已回流"}


@app.get("/api/v1/review/pending", tags=["人工复核"])
async def get_pending_reviews(
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "reviewer"):
        raise HTTPException(status_code=403, detail="权限不足")

    conn = _ensure_db()._get_conn()
    rows = conn.execute(
        "SELECT * FROM review_records WHERE decision = 'human_review' AND is_deleted = 0 ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return {"pending": [dict(r) for r in rows], "total": len(rows)}


class OverrideRequest(BaseModel):
    decision: str = Field(..., pattern="^(yes|no|unknown)$")
    reason: str = Field("")
    violations: list = Field(default_factory=list)
    removed_types: list = Field(default_factory=list)


@app.post("/api/v1/review/{review_id}/override", tags=["人工复核"])
async def override_review(
    review_id: int,
    body: OverrideRequest,
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "reviewer"):
        raise HTTPException(status_code=403, detail="权限不足")

    review = _ensure_db().get_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="审核记录不存在")

    conn = _ensure_db()._get_conn()
    violation_type_str = ",".join(v.get("violation_type", "") for v in body.violations if v.get("violation_type"))
    conn.execute(
        "UPDATE review_records SET compliant = ?, violation_type = ?, decision = 'human_override', reviewer_id = ?, review_comment = ? WHERE id = ?",
        (body.decision, violation_type_str, user.get("id"), body.reason, review_id),
    )

    for v in body.violations:
        vtype = v.get("violation_type", "")
        articles = v.get("violated_articles", [])
        reasoning = v.get("reasoning", "")
        source = v.get("source", "system")
        conn.execute(
            "INSERT INTO review_violations (review_id, violation_type_id, violation_type_name, violated_articles, reasoning, source) VALUES (?, ?, ?, ?, ?, ?)",
            (review_id, vtype, vtype, json.dumps(articles, ensure_ascii=False), reasoning, source),
        )

    for rt in body.removed_types:
        conn.execute(
            "UPDATE review_violations SET is_deprecated = 1 WHERE review_id = ? AND violation_type_id = ?",
            (review_id, rt),
        )

    if body.reason:
        conn.execute(
            "INSERT INTO review_modifications (review_id, modification_type, after_value, modification_reason, user_id) VALUES (?, ?, ?, ?, ?)",
            (review_id, "override_decision", body.decision, body.reason, user.get("id")),
        )

    conn.commit()

    try:
        from src.prompt_manager import prompt_manager
        input_text = review.get("input_content", "")[:500]
        if input_text:
            prompt_manager.add_few_shot_from_feedback(
                input_text=input_text,
                correct_result={
                    "compliant": body.decision,
                    "violation_type": violation_type_str,
                    "violated_articles": [],
                    "confidence": 1.0,
                },
                source=f"human_override_user_{user.get('id')}",
            )
    except Exception as e:
        logger.warning(f"Few-Shot回流失败: {e}")

    return {"review_id": review_id, "message": "人工覆写完成，Few-Shot样本已回流"}


@app.post("/api/v1/review/{review_id}/request-human-review", tags=["人工复核"])
async def request_human_review(
    review_id: int,
    user: dict = Depends(get_optional_user),
):
    review = _ensure_db().get_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="审核记录不存在")
    conn = _ensure_db()._get_conn()
    conn.execute(
        "UPDATE review_records SET decision = 'human_review' WHERE id = ?",
        (review_id,),
    )
    conn.commit()
    return {"review_id": review_id, "message": "已提交人工复核"}


@app.get("/api/v1/prompts/versions", tags=["Prompt管理"])
async def list_prompt_versions(user: dict = Depends(get_current_user)):
    if not _ensure_db().check_permission(user.get("id"), "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可查看Prompt版本")
    from src.prompt_manager import prompt_manager
    return {"versions": prompt_manager.list_versions(), "stats": prompt_manager.get_stats()}


@app.post("/api/v1/prompts/activate", tags=["Prompt管理"])
async def activate_prompt_version(
    version: str = Query(...),
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可切换Prompt版本")
    from src.prompt_manager import prompt_manager
    try:
        prompt_manager.activate_version(version)
        return {"message": f"Prompt版本已切换到 {version}"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/v1/llm/status", tags=["模型管理"])
async def get_llm_status(user: dict = Depends(get_current_user)):
    if not _ensure_db().check_permission(user.get("id"), "reviewer"):
        raise HTTPException(status_code=403, detail="权限不足")
    from src.llm_gateway import llm_gateway
    return llm_gateway.get_model_status()


@app.get("/api/v1/violation-types", tags=["违规类型"])
async def list_violation_types(
    level: Optional[int] = Query(None, ge=1, le=2),
    parent_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    from src.violation_registry import violation_registry
    types = violation_registry.list_types(level=level, parent_id=parent_id)
    return {
        "types": [vt.to_dict() for vt in types],
        "stats": violation_registry.get_stats(),
    }


@app.get("/api/v1/violation-types/{type_id}", tags=["违规类型"])
async def get_violation_type(
    type_id: str,
    user: dict = Depends(get_current_user),
):
    from src.violation_registry import violation_registry
    vt = violation_registry.get_type(type_id)
    if not vt:
        raise HTTPException(status_code=404, detail="违规类型不存在")
    result = vt.to_dict()
    result["articles"] = violation_registry.get_articles_for_type(type_id)
    return result


@app.post("/api/v1/violation-types", tags=["违规类型"])
async def create_violation_type(
    name: str = Query(..., min_length=1, max_length=50),
    level: int = Query(2, ge=1, le=2),
    parent_id: Optional[str] = Query(None),
    severity: float = Query(0.5, ge=0.0, le=1.0),
    description: str = Query(""),
    keywords: str = Query(""),
    suggestions: str = Query(""),
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可创建违规类型")
    from src.violation_registry import violation_registry
    try:
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else []
        vt = violation_registry.add_type(
            name=name,
            level=level,
            parent_id=parent_id,
            severity=severity,
            description=description,
            keywords=kw_list,
            suggestions=suggestions,
        )
        return {"message": "违规类型已创建", "type": vt.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/v1/violation-types/{type_id}", tags=["违规类型"])
async def update_violation_type(
    type_id: str,
    name: Optional[str] = Query(None),
    severity: Optional[float] = Query(None, ge=0.0, le=1.0),
    description: Optional[str] = Query(None),
    keywords: Optional[str] = Query(None),
    suggestions: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可修改违规类型")
    from src.violation_registry import violation_registry
    kwargs = {}
    if name is not None:
        kwargs["name"] = name
    if severity is not None:
        kwargs["severity"] = severity
    if description is not None:
        kwargs["description"] = description
    if keywords is not None:
        kwargs["keywords"] = [k.strip() for k in keywords.split(",") if k.strip()]
    if suggestions is not None:
        kwargs["suggestions"] = suggestions
    vt = violation_registry.update_type(type_id, **kwargs)
    if not vt:
        raise HTTPException(status_code=404, detail="违规类型不存在")
    return {"message": "违规类型已更新", "type": vt.to_dict()}


@app.delete("/api/v1/violation-types/{type_id}", tags=["违规类型"])
async def deprecate_violation_type(
    type_id: str,
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可废弃违规类型")
    from src.violation_registry import violation_registry
    success = violation_registry.deprecate_type(type_id)
    if not success:
        raise HTTPException(status_code=404, detail="违规类型不存在")
    return {"message": "违规类型已废弃", "type_id": type_id}


@app.post("/api/v1/violation-types/{type_id}/keywords", tags=["违规类型"])
async def add_keyword_to_type(
    type_id: str,
    keyword: str = Query(..., min_length=1),
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可添加关键词")
    from src.violation_registry import violation_registry
    success = violation_registry.add_keyword(type_id, keyword)
    if not success:
        raise HTTPException(status_code=404, detail="违规类型不存在")
    return {"message": f"关键词已添加: {keyword}"}


@app.delete("/api/v1/violation-types/{type_id}/keywords", tags=["违规类型"])
async def remove_keyword_from_type(
    type_id: str,
    keyword: str = Query(..., min_length=1),
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可删除关键词")
    from src.violation_registry import violation_registry
    success = violation_registry.remove_keyword(type_id, keyword)
    if not success:
        raise HTTPException(status_code=404, detail="违规类型不存在或关键词不存在")
    return {"message": f"关键词已删除: {keyword}"}


@app.get("/api/v1/violation-types/annotations/pending", tags=["违规类型"])
async def get_pending_annotations(
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可查看待审批标注")
    from src.violation_registry import violation_registry
    pending = violation_registry.get_pending_annotations()
    return {"annotations": [pa.to_dict() for pa in pending], "total": len(pending)}


@app.post("/api/v1/violation-types/annotations/{annotation_id}/approve", tags=["违规类型"])
async def approve_annotation(
    annotation_id: str,
    type_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可审批标注")
    from src.violation_registry import violation_registry
    pa = violation_registry.approve_annotation(annotation_id, type_id=type_id)
    if not pa:
        raise HTTPException(status_code=404, detail="标注不存在或已处理")
    return {"message": "标注已审批", "annotation": pa.to_dict()}


@app.post("/api/v1/violation-types/annotations/{annotation_id}/reject", tags=["违规类型"])
async def reject_annotation(
    annotation_id: str,
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可拒绝标注")
    from src.violation_registry import violation_registry
    pa = violation_registry.reject_annotation(annotation_id)
    if not pa:
        raise HTTPException(status_code=404, detail="标注不存在或已处理")
    return {"message": "标注已拒绝", "annotation_id": annotation_id}


@app.get("/api/v1/reviews", tags=["审核"])
async def list_reviews(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    compliant: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "reviewer"):
        raise HTTPException(status_code=403, detail="权限不足")

    reviews, total = _ensure_db().list_reviews(
        user_id=user.get("id") if user.get("role") != "admin" else None,
        compliant=compliant,
        limit=limit,
        offset=offset,
    )
    return {"total": total, "items": reviews, "limit": limit, "offset": offset}


@app.get("/api/v1/reviews/{review_id}", tags=["审核"])
async def get_review_detail(
    review_id: int,
    user: dict = Depends(get_current_user),
):
    review = _ensure_db().get_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="审核记录不存在")
    if user.get("role") != "admin" and review.get("user_id") and review["user_id"] != user.get("id"):
        raise HTTPException(status_code=403, detail="无权查看此记录")
    violations = _ensure_db().get_review_violations(review_id)
    modifications = _ensure_db().get_review_modifications(review_id)
    review["violations"] = violations
    review["modifications"] = modifications
    review["review_id"] = review.get("id", review_id)
    return review


@app.delete("/api/v1/reviews/{review_id}", tags=["审核"])
async def delete_review(
    review_id: int,
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可删除审核记录")

    success = _ensure_db().hard_delete_review(review_id, user.get("id"))
    if not success:
        raise HTTPException(status_code=404, detail="审核记录不存在")
    return {"message": "审核记录已删除"}


@app.get("/api/v1/clause-relations", tags=["条款关系"])
async def get_clause_relations(
    doc_name: str = Query(None),
    article_number: str = Query(None),
    relation_type: str = Query(None),
    user: dict = Depends(get_optional_user),
):
    relations = _ensure_db().get_clause_relations(doc_name, article_number, relation_type)
    return {"relations": relations, "total": len(relations)}


@app.get("/api/v1/clause-relations/expand", tags=["条款关系"])
async def expand_related_clauses(
    doc_name: str = Query(...),
    article_number: str = Query(...),
    max_depth: int = Query(1),
    max_related: int = Query(10),
    user: dict = Depends(get_optional_user),
):
    database = _ensure_db()
    visited = {(doc_name, article_number)}
    queue = [(doc_name, article_number, 0)]
    results = []
    while queue:
        current_doc, current_article, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        rels = database.get_clause_relations(doc_name=current_doc, article_number=current_article)
        for rel in rels:
            target_key = (rel['to_doc'], rel['to_article'])
            if target_key in visited or not rel['to_article']:
                continue
            if len(results) >= max_related:
                break
            visited.add(target_key)
            results.append(rel)
            queue.append((rel['to_doc'], rel['to_article'], depth + 1))
    return {"related_clauses": results, "total": len(results)}


@app.get("/api/v1/clause-mappings", tags=["条款映射"])
async def list_clause_mappings(
    violation_type_id: Optional[str] = Query(None),
    doc_name: Optional[str] = Query(None),
):
    from src.violation_registry import violation_registry
    mappings = []
    for cm in violation_registry._mappings.values():
        if cm.expiration_date:
            continue
        if violation_type_id and cm.violation_type_id != violation_type_id:
            continue
        if doc_name and cm.doc_name != doc_name:
            continue
        d = cm.to_dict()
        vt = violation_registry.get_type(cm.violation_type_id)
        d["violation_type_name"] = vt.name if vt else cm.violation_type_id
        mappings.append(d)
    return {"mappings": mappings, "total": len(mappings)}


@app.get("/api/v1/llm-audit-logs", tags=["系统"])
async def get_llm_audit_logs(
    date: Optional[str] = Query(None),
    limit: int = Query(50),
):
    import os
    import json
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "llm_audit")
    if not os.path.exists(log_dir):
        return {"logs": [], "total": 0}
    if date:
        log_file = os.path.join(log_dir, f"llm_audit_{date}.jsonl")
        files = [log_file] if os.path.exists(log_file) else []
    else:
        files = sorted([os.path.join(log_dir, f) for f in os.listdir(log_dir) if f.endswith(".jsonl")], reverse=True)
    logs = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        logs.append(json.loads(line.strip()))
                    except Exception:
                        pass
        except Exception:
            pass
    logs = logs[-limit:]
    return {"logs": logs, "total": len(logs), "log_dir": log_dir}


@app.get("/api/v1/stats", tags=["统计"])
async def get_stats(user: dict = Depends(get_current_user)):
    if not _ensure_db().check_permission(user.get("id"), "reviewer"):
        raise HTTPException(status_code=403, detail="权限不足")
    return _ensure_db().get_stats()


class GenerateReasonRequest(BaseModel):
    review_id: int
    decision: str = Field("")


@app.post("/api/v1/generate-modification-reason", tags=["人工复核"])
async def generate_modification_reason(
    body: GenerateReasonRequest,
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "reviewer"):
        raise HTTPException(status_code=403, detail="权限不足")

    review = _ensure_db().get_review(body.review_id)
    if not review:
        raise HTTPException(status_code=404, detail="审核记录不存在")

    original_decision = review.get("compliant", "unknown")
    original_violations = review.get("violation_type", "")
    input_preview = review.get("input_content", "")[:300]

    reason_parts = []
    if body.decision == "yes" and original_decision != "yes":
        reason_parts.append(f"原审核结果为'{original_decision}'，经人工复核确认内容合规")
        if original_violations:
            reason_parts.append(f"原标记违规类型'{original_violations}'经核实不成立")
    elif body.decision == "no" and original_decision != "no":
        reason_parts.append(f"原审核结果为'{original_decision}'，经人工复核确认存在违规")
    elif body.decision == "unknown":
        reason_parts.append("经人工复核，无法明确判定合规性，需进一步审查")

    if not reason_parts:
        reason_parts.append("人工复核确认审核结果")

    return {"reason": "；".join(reason_parts)}


@app.get("/api/v1/feedback/stats", tags=["统计"])
async def get_feedback_stats(user: dict = Depends(get_current_user)):
    return _ensure_db().get_feedback_stats()


@app.get("/api/v1/regulations", tags=["法规"])
async def list_regulations(user: dict = Depends(get_optional_user)):
    versions = _ensure_db().list_regulation_versions()
    return {"regulations": versions}


@app.get("/api/v1/regulations/chunks", tags=["法规"])
async def get_regulation_chunks(
    doc_name: Optional[str] = Query(None),
):
    if rag_engine is None:
        return {"chunks": []}
    chunks = rag_engine.chunks
    if doc_name:
        chunks = [c for c in chunks if c.doc_name == doc_name]
    result = []
    for c in chunks:
        result.append({
            "doc_name": c.doc_name,
            "article_number": c.article_number,
            "content": c.article_text,
            "content_hash": c.content_hash,
        })
    return {"chunks": result, "total": len(result)}


@app.post("/api/v1/regulations/reindex", tags=["法规"])
async def reindex_regulations(
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可重建索引")

    def _do_reindex():
        _ensure_agent()
        rag_engine.rebuild_vector_index()
        logger.info("法规索引重建完成")

    background_tasks.add_task(_do_reindex)
    return {"message": "索引重建已启动"}


@app.get("/api/v1/regulations/vectorization-status", tags=["法规"])
async def get_vectorization_status():
    if rag_engine is None:
        return {"status": "not_initialized", "use_vector": False}
    return rag_engine.get_vectorization_status()


@app.post("/api/v1/regulations/upload", tags=["法规"])
async def upload_regulation(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可上传法规文档")

    from src.document_parsers import parser_registry
    supported = parser_registry.supported_formats()
    ext = os.path.splitext(file.filename)[1].lstrip(".")
    if ext not in supported:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: .{ext}，支持: {', '.join('.' + f for f in supported)}",
        )

    save_dir = config.REGULATIONS_DIR
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, file.filename)

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件大小不能超过50MB")

    with open(save_path, "wb") as f:
        f.write(content)

    try:
        parsed = parser_registry.parse(save_path)
        chunk_count = len(parsed.sections) if parsed.sections else 0
    except Exception as e:
        os.remove(save_path)
        raise HTTPException(status_code=400, detail=f"文档解析失败: {str(e)}")

    annotation_count = 0
    try:
        from src.violation_registry import violation_registry
        if rag_engine and rag_engine.chunks:
            annotations = violation_registry.annotate_chunks(rag_engine.chunks)
            annotation_count = len(annotations)
    except Exception as e:
        logger.warning(f"法规条文标注失败: {e}")

    return {
        "message": f"法规文档已上传: {file.filename}",
        "filename": file.filename,
        "format": ext,
        "title": parsed.title,
        "sections": chunk_count,
        "tables": len(parsed.tables),
        "images": len(parsed.images),
        "pending_annotations": annotation_count,
        "hint": "请调用 POST /api/v1/regulations/reindex 重建索引以生效，"
                "并通过 GET /api/v1/violation-types/annotations/pending 审批条文标注",
    }


@app.get("/api/v1/regulations/formats", tags=["法规"])
async def get_supported_formats():
    from src.document_parsers import parser_registry
    formats = parser_registry.supported_formats()
    return {"supported_formats": formats}


@app.post("/api/v1/review/multimodal", response_model=ReviewResponse, tags=["审核"])
async def multimodal_review(
    request: MultiModalReviewRequest,
    user: dict = Depends(get_current_user),
):
    from src.input_processors import input_processor_chain, InputType, UserInput

    user_input = input_processor_chain.auto_detect(
        text=request.text or "",
        images=[{"path": p} for p in (request.image_paths or [])],
        files=[{"path": p} for p in (request.file_paths or [])],
    )

    if not user_input.combined_text.strip():
        raise HTTPException(status_code=400, detail="至少需要提供一种输入内容(文本/图片/文件)")

    processed = input_processor_chain.process(user_input)
    combined = processed.combined_text

    validation = security_middleware.validate_and_sanitize(
        combined, client_id=user.get("username", "anonymous")
    )
    if not validation.is_valid:
        if PROMETHEUS_AVAILABLE and SECURITY_BLOCKED:
            for threat in validation.threats:
                SECURITY_BLOCKED.labels(reason=threat[:50]).inc()
        raise HTTPException(
            status_code=400,
            detail={"message": "输入校验失败", "threats": validation.threats},
        )

    start_time = time.time()

    if not review_semaphore.acquire(timeout=10.0):
        raise HTTPException(status_code=429, detail="系统繁忙，并发审核数已达上限")

    try:
        if PROMETHEUS_AVAILABLE and REVIEW_IN_PROGRESS:
            REVIEW_IN_PROGRESS.inc()

        with trace_operation("review_multimodal", {"user": user.get("username", "anonymous"), "input_type": user_input.input_type.value}):
            result = _ensure_agent().review(
                content=validation.sanitized_input,
                image_descriptions=[img.get("description", "") or img.get("ocr_text", "") for img in processed.images if img.get("description") or img.get("ocr_text")],
                client_id=user.get("username", "anonymous"),
            )
    finally:
        if PROMETHEUS_AVAILABLE and REVIEW_IN_PROGRESS:
            REVIEW_IN_PROGRESS.dec()
        review_semaphore.release()

    latency_ms = (time.time() - start_time) * 1000

    review_data = {
        "user_id": user.get("id"),
        "input_content": validation.sanitized_input[:500],
        "input_hash": hashlib.sha256(validation.sanitized_input.encode()).hexdigest()[:16],
        "input_length": len(validation.sanitized_input),
        "compliant": result.compliant,
        "violation_type": result.violation_type,
        "violated_articles": result.violated_articles,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
        "suggestions": result.suggestions,
        "review_mode": "llm" if not config.DEMO_MODE else "rule",
        "latency_ms": latency_ms,
        "client_id": user.get("username", "anonymous"),
        "threats": validation.threats,
        "violation_types": result.violation_types,
    }

    review_id = _ensure_db().save_review(review_data)

    return ReviewResponse(
        review_id=review_id,
        compliant=result.compliant,
        violation_type=result.violation_type,
        violated_articles=result.violated_articles,
        confidence=result.confidence,
        reasoning=result.reasoning,
        suggestions=result.suggestions,
        latency_ms=round(latency_ms, 2),
        risk_score=result.risk_score,
        risk_level=result.risk_level,
        decision=result.decision,
        review_mode=result.review_mode,
        model_used=result.model_used,
        prompt_version=result.prompt_version,
        workflow_steps=result.workflow_steps or [],
    )


@app.post("/api/v1/review/upload", response_model=ReviewResponse, tags=["审核"])
async def upload_and_review(
    text: str = "",
    files: List[UploadFile] = File(default=[]),
    user: dict = Depends(get_current_user),
):
    from src.input_processors import input_processor_chain, UserInput, InputType

    uploaded_files = []
    upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    for f in files:
        content = await f.read()
        if len(content) > 50 * 1024 * 1024:
            raise HTTPException(status_code=400, detail=f"文件 {f.filename} 超过50MB限制")
        save_path = os.path.join(upload_dir, f"{int(time.time())}_{f.filename}")
        with open(save_path, "wb") as out:
            out.write(content)
        uploaded_files.append({"path": save_path, "filename": f.filename})

    user_input = input_processor_chain.auto_detect(
        text=text,
        files=uploaded_files,
    )

    if not user_input.combined_text.strip():
        raise HTTPException(status_code=400, detail="至少需要提供文本或上传文件")

    processed = input_processor_chain.process(user_input)
    combined = processed.combined_text

    validation = security_middleware.validate_and_sanitize(
        combined, client_id=user.get("username", "anonymous")
    )
    if not validation.is_valid:
        raise HTTPException(status_code=400, detail={"message": "输入校验失败", "threats": validation.threats})

    start_time = time.time()

    if not review_semaphore.acquire(timeout=10.0):
        raise HTTPException(status_code=429, detail="系统繁忙，并发审核数已达上限")

    try:
        result = _ensure_agent().review(
            content=validation.sanitized_input,
            client_id=user.get("username", "anonymous"),
        )
    finally:
        review_semaphore.release()

    latency_ms = (time.time() - start_time) * 1000

    review_data = {
        "user_id": user.get("id"),
        "input_content": validation.sanitized_input[:500],
        "input_hash": hashlib.sha256(validation.sanitized_input.encode()).hexdigest()[:16],
        "input_length": len(validation.sanitized_input),
        "compliant": result.compliant,
        "violation_type": result.violation_type,
        "violated_articles": result.violated_articles,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
        "suggestions": result.suggestions,
        "review_mode": "llm" if not config.DEMO_MODE else "rule",
        "latency_ms": latency_ms,
        "client_id": user.get("username", "anonymous"),
        "threats": validation.threats,
        "violation_types": result.violation_types,
    }

    review_id = _ensure_db().save_review(review_data)

    return ReviewResponse(
        review_id=review_id,
        compliant=result.compliant,
        violation_type=result.violation_type,
        violated_articles=result.violated_articles,
        confidence=result.confidence,
        reasoning=result.reasoning,
        suggestions=result.suggestions,
        latency_ms=round(latency_ms, 2),
        risk_score=result.risk_score,
        risk_level=result.risk_level,
        decision=result.decision,
        review_mode=result.review_mode,
        model_used=result.model_used,
        prompt_version=result.prompt_version,
        workflow_steps=result.workflow_steps or [],
    )


@app.post("/api/v1/backup", tags=["系统"])
async def trigger_backup(user: dict = Depends(get_current_user)):
    if not _ensure_db().check_permission(user.get("id"), "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可触发备份")
    backup_path = _ensure_db().backup()
    return {"message": "备份完成", "path": backup_path}


@app.post("/api/v1/cleanup", tags=["系统"])
async def trigger_cleanup(
    days: int = Query(365, ge=30),
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可触发清理")
    stats = _ensure_db().cleanup_expired_data(days)
    return {"message": "数据清理完成", "stats": stats}


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"未处理异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，请稍后重试"},
    )


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    uvicorn.run(
        "api_server:app",
        host=config.SERVER_HOST,
        port=int(os.getenv("API_PORT", config.SERVER_PORT + 1)),
        workers=1,
        log_level="info",
        access_log=True,
    )
