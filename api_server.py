import os
import sys
import time
import signal
import logging
import hashlib
import asyncio
from typing import List, Optional, Dict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Header, Query, BackgroundTasks, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, validator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src.rag_engine import RAGEngine
from src.review_agent import ReviewAgent, ReviewResult
from src.database import Database
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
    if not api_key:
        raise HTTPException(status_code=401, detail="缺少API Key，请在X-API-Key头中提供")
    database = _ensure_db()
    user = database.authenticate_api_key(api_key)
    if not user:
        raise HTTPException(status_code=401, detail="无效的API Key")
    return user


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

_cors_origins = os.getenv("CORS_ORIGINS", config.CORS_ORIGINS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["X-API-Key", "Content-Type"],
)


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


@app.post("/api/v1/review/{review_id}/override", tags=["人工复核"])
async def override_review(
    review_id: int,
    compliant: str = Query(..., pattern="^(yes|no|unknown)$"),
    violation_type: str = Query(""),
    comment: str = Query(""),
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "reviewer"):
        raise HTTPException(status_code=403, detail="权限不足")

    review = _ensure_db().get_review(review_id)
    if not review:
        raise HTTPException(status_code=404, detail="审核记录不存在")

    conn = _ensure_db()._get_conn()
    conn.execute(
        "UPDATE review_records SET compliant = ?, violation_type = ?, decision = 'human_override', reviewer_id = ?, review_comment = ? WHERE id = ?",
        (compliant, violation_type, user.get("id"), comment, review_id),
    )
    conn.commit()

    try:
        from src.prompt_manager import prompt_manager
        input_text = review.get("input_content", "")[:500]
        if input_text:
            prompt_manager.add_few_shot_from_feedback(
                input_text=input_text,
                correct_result={
                    "compliant": compliant,
                    "violation_type": violation_type,
                    "violated_articles": [],
                    "confidence": 1.0,
                },
                source=f"human_override_user_{user.get('id')}",
            )
    except Exception as e:
        logger.warning(f"Few-Shot回流失败: {e}")

    return {"review_id": review_id, "message": "人工覆写完成，Few-Shot样本已回流"}


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


@app.get("/api/v1/stats", tags=["统计"])
async def get_stats(user: dict = Depends(get_current_user)):
    if not _ensure_db().check_permission(user.get("id"), "reviewer"):
        raise HTTPException(status_code=403, detail="权限不足")
    return _ensure_db().get_stats()


@app.get("/api/v1/feedback/stats", tags=["统计"])
async def get_feedback_stats(user: dict = Depends(get_current_user)):
    return _ensure_db().get_feedback_stats()


@app.get("/api/v1/regulations", tags=["法规"])
async def list_regulations(user: dict = Depends(get_optional_user)):
    versions = _ensure_db().list_regulation_versions()
    return {"regulations": versions}


@app.post("/api/v1/regulations/reindex", tags=["法规"])
async def reindex_regulations(
    background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
):
    if not _ensure_db().check_permission(user.get("id"), "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可重建索引")

    def _do_reindex():
        _ensure_agent()
        rag_engine.build_index(force_rebuild=True)
        logger.info("法规索引重建完成")

    background_tasks.add_task(_do_reindex)
    return {"message": "索引重建已启动"}


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

    return {
        "message": f"法规文档已上传: {file.filename}",
        "filename": file.filename,
        "format": ext,
        "title": parsed.title,
        "sections": chunk_count,
        "tables": len(parsed.tables),
        "images": len(parsed.images),
        "hint": "请调用 POST /api/v1/regulations/reindex 重建索引以生效",
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
        port=config.SERVER_PORT + 1,
        workers=1,
        log_level="info",
        access_log=True,
    )
