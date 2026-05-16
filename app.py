import os
import sys
import json
import time
import hashlib
import html
import logging
import gradio as gr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from src.rag_engine import RAGEngine
from src.review_agent import ReviewAgent
from src.database import Database
from src.security import security_middleware

rag_engine = None
review_agent = None
db = None


def init_system():
    global rag_engine, review_agent, db
    if rag_engine is None:
        db = Database()
        rag_engine = RAGEngine()
        rag_engine.build_index()
        review_agent = ReviewAgent(rag_engine)
    return rag_engine, review_agent, db


def _esc(text):
    return html.escape(str(text), quote=True)


def _status_hero(compliant):
    if compliant == "yes":
        return """<div class="status-hero status-hero--success">
  <div class="status-hero__dot"></div>
  <div class="status-hero__label">合规</div>
  <div class="status-hero__sub">内容审核通过，未发现违规</div>
</div>"""
    elif compliant == "no":
        return """<div class="status-hero status-hero--danger">
  <div class="status-hero__dot"></div>
  <div class="status-hero__label">违规</div>
  <div class="status-hero__sub">检测到违规内容，请查看详情</div>
</div>"""
    else:
        return """<div class="status-hero status-hero--warning">
  <div class="status-hero__dot"></div>
  <div class="status-hero__label">待人工确认</div>
  <div class="status-hero__sub">置信度不足，需人工复核</div>
</div>"""


def _pill(text, variant="default"):
    variants = {
        "success": "pill pill--success",
        "danger": "pill pill--danger",
        "warning": "pill pill--warning",
        "info": "pill pill--info",
        "purple": "pill pill--purple",
        "default": "pill pill--default",
    }
    cls = variants.get(variant, "pill pill--default")
    return f'<span class="{cls}">{_esc(text)}</span>'


def _decision_badge(decision):
    mapping = {
        "auto_pass": ("自动通过", "success"),
        "human_review": ("人工复核", "warning"),
        "auto_block": ("自动拦截", "danger"),
    }
    label, variant = mapping.get(decision, (decision, "default"))
    return _pill(label, variant)


def _mode_badge(mode):
    if "rule" in mode and "llm" in mode:
        return _pill("规则+LLM", "info")
    elif "llm" in mode:
        return _pill("LLM", "purple")
    else:
        return _pill("规则", "default")


def _violation_tags(violation_type):
    if not violation_type or violation_type == "无":
        return ""
    types = [t.strip() for t in violation_type.split("、") if t.strip() and t.strip() != "无"]
    if not types:
        return ""
    return "".join(_pill(vt, "danger") for vt in types)


def _confidence_bar(confidence):
    pct = int(confidence * 100)
    if pct >= 80:
        bar_color = "var(--success)"
    elif pct >= 50:
        bar_color = "var(--warning)"
    else:
        bar_color = "var(--danger)"
    return f"""<div class="progress-row">
<div class="progress-track"><div class="progress-fill" style="width:{pct}%;background:{bar_color};"></div></div>
<span class="progress-label" style="color:{bar_color};">{pct}%</span>
</div>"""


def _risk_bar(score):
    pct = int(score * 100)
    if pct < 30:
        bar_color = "var(--success)"
    elif pct < 70:
        bar_color = "var(--warning)"
    else:
        bar_color = "var(--danger)"
    return f"""<div class="progress-row">
<div class="progress-track"><div class="progress-fill" style="width:{pct}%;background:{bar_color};"></div></div>
<span class="progress-label" style="color:{bar_color};">{score:.2f}</span>
</div>"""


def _violation_cards(violated_articles, review_id):
    if not violated_articles:
        return '<div class="empty-state">无违规条文</div>'
    cards = []
    for i, article in enumerate(violated_articles):
        doc_name = _esc(article.get("doc_name", ""))
        article_number = _esc(article.get("article_number", ""))
        article_text = _esc(article.get("article_text", ""))
        violation_reason = _esc(article.get("violation_reason", ""))
        hallucination = article.get("hallucination_detected", False)
        warn_cls = "violation-card violation-card--alert" if hallucination else "violation-card"
        warn_label = ""
        if hallucination:
            warn_label = '<div class="violation-card__warn">引用验证失败</div>'
        cards.append(f"""
<div class="{warn_cls}">
  {warn_label}
  <div class="violation-card__reason">{violation_reason}</div>
  <div class="regulation-quote">
    <div class="regulation-quote__source">《{doc_name}》第{article_number}条</div>
    <div class="regulation-quote__text">{article_text}</div>
  </div>
  <div class="violation-card__actions">
    <button onclick="confirmArticle({review_id},{i},true)" class="btn btn--ghost btn--ghost-success">条款正确</button>
    <button onclick="confirmArticle({review_id},{i},false)" class="btn btn--ghost btn--ghost-danger">条款有误</button>
    <button onclick="toggleViolation({review_id},{i},true)" class="btn btn--ghost btn--ghost-danger">确实违规</button>
    <button onclick="toggleViolation({review_id},{i},false)" class="btn btn--ghost btn--ghost-success">实际合规</button>
  </div>
  <div id="confirm-result-{review_id}-{i}" class="violation-card__result"></div>
</div>""")
    return "".join(cards)


def format_review_result(result_dict, review_id=0):
    result = result_dict["result"]
    compliant = result["compliant"]
    risk_score = result.get("risk_score", 0.0)
    decision = result.get("decision", "auto_pass")
    review_mode = result.get("review_mode", "")
    confidence = result.get("confidence", 0.0)
    violated_articles = result.get("violated_articles", [])
    violation_type = result.get("violation_type", "")
    reasoning = result.get("reasoning", "")
    suggestions = result.get("suggestions", "")

    output = f"""
<div class="review-result">
  <div class="review-result__header">
    {_status_hero(compliant)}
    <div class="review-result__id">审核ID: {review_id}</div>
  </div>

  <div class="info-cards-row">
    <div class="info-card">
      <div class="info-card__label">违规类型</div>
      <div class="info-card__value">{_violation_tags(violation_type) if _violation_tags(violation_type) else '<span class="pill pill--success">无</span>'}</div>
    </div>
    <div class="info-card">
      <div class="info-card__label">风险评分</div>
      <div class="info-card__value">{_risk_bar(risk_score)}</div>
    </div>
    <div class="info-card">
      <div class="info-card__label">处置决策</div>
      <div class="info-card__value">{_decision_badge(decision)}</div>
    </div>
    <div class="info-card">
      <div class="info-card__label">审核模式</div>
      <div class="info-card__value">{_mode_badge(review_mode)}</div>
    </div>
    <div class="info-card">
      <div class="info-card__label">置信度</div>
      <div class="info-card__value">{_confidence_bar(confidence)}</div>
    </div>
  </div>

  <div class="section-block">
    <div class="section-block__title">逐项违规展示</div>
    {_violation_cards(violated_articles, review_id)}
  </div>

  <div class="section-block">
    <div class="section-block__title">修改建议</div>
    <div class="suggestion-card">{_esc(suggestions)}</div>
  </div>
</div>
"""
    return output, reasoning


def format_retrieved_rules(retrieved):
    if not retrieved:
        return "未检索到相关法规条文。"
    output = ""
    for i, rule in enumerate(retrieved, 1):
        output += f"**{i}. 《{_esc(rule['doc_name'])}》第{_esc(rule['article_number'])}条** (相关度: {rule['similarity']})\n\n> {_esc(rule['article_text'])}\n\n"
    return output


def review_text(content):
    if not content or not content.strip():
        return (
            '<div class="empty-state">请输入待审核内容</div>',
            "", "", gr.update(visible=False), 0, {},
        )

    _, agent, database = init_system()
    start_time = time.time()

    validation = security_middleware.validate_and_sanitize(content.strip())
    if not validation.is_valid:
        error_msg = f"⚠️ 输入校验失败：\n" + "\n".join(f"- {t}" for t in validation.threats)
        return (
            f'<div class="alert alert--danger">{error_msg}</div>',
            "", "", gr.update(visible=False), 0, {},
        )

    result = agent.review(validation.sanitized_input, client_id="web_user")
    latency_ms = (time.time() - start_time) * 1000

    review_data = {
        "user_id": None,
        "input_content": validation.sanitized_input,
        "input_hash": hashlib.sha256(validation.sanitized_input.encode()).hexdigest()[:16],
        "input_length": len(validation.sanitized_input),
        "compliant": result.compliant,
        "violation_type": result.violation_type,
        "violated_articles": result.violated_articles,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
        "suggestions": result.suggestions,
        "review_mode": result.review_mode,
        "latency_ms": latency_ms,
        "client_id": "web_user",
        "threats": validation.threats,
        "decision": result.decision,
        "risk_score": result.risk_score,
        "risk_level": result.risk_level,
        "model_used": result.model_used,
        "prompt_version": result.prompt_version,
        "violation_types": result.violation_types,
    }
    review_id = database.save_review(review_data)

    details = {"result": result.to_dict()}
    result_html, reasoning = format_review_result(details, review_id)

    result_json = result.to_dict()
    result_json["review_id"] = review_id

    return (
        result_html,
        reasoning,
        "",
        gr.update(visible=True),
        review_id,
        result_json,
    )


def search_regulations(keyword):
    if not keyword or not keyword.strip():
        return '<div class="empty-state">请输入搜索关键词</div>'
    engine, _, _ = init_system()
    results = []
    kw_lower = keyword.strip().lower()
    for chunk in engine.chunks:
        if kw_lower in chunk.article_text.lower() or kw_lower in chunk.doc_name.lower():
            results.append({
                "doc_name": chunk.doc_name,
                "chapter": chunk.chapter,
                "article_number": chunk.article_number,
                "article_text": chunk.article_text,
            })
    if not results:
        return f'<div class="empty-state">未找到与 "{_esc(keyword)}" 相关的法规条文</div>'
    output = f'<div class="search-summary">共找到 {len(results)} 条相关法规，显示前 {min(len(results), 20)} 条</div>'
    for i, r in enumerate(results[:20], 1):
        output += f"""
<div class="reg-search-item">
  <div class="reg-search-item__source">《{_esc(r['doc_name'])}》第{_esc(r['article_number'])}条</div>
  <div class="reg-search-item__text">{_esc(r['article_text'])}</div>
</div>"""
    return output


def confirm_violation(review_id, violation_idx, is_correct_article, is_actual_violation):
    _, _, database = init_system()
    if not review_id or review_id <= 0:
        return "⚠️ 无有效审核ID"
    review = database.get_review(review_id)
    if not review:
        return "⚠️ 未找到审核记录"
    articles = review.get("violated_articles", [])
    if isinstance(articles, str):
        articles = json.loads(articles)
    if violation_idx < 0 or violation_idx >= len(articles):
        return "⚠️ 违规项索引无效"

    article = articles[violation_idx]
    status_parts = []
    if is_correct_article:
        status_parts.append("条款引用正确 ✅")
    else:
        status_parts.append("条款引用有误 ❌")
    if is_actual_violation:
        status_parts.append("确认为违规 ❌")
    else:
        status_parts.append("标记为合规 ✅")

    try:
        from src.prompt_manager import prompt_manager
        if is_correct_article and not is_actual_violation:
            correct_result = {
                "compliant": "yes",
                "violation_type": "",
                "violated_articles": [],
            }
            prompt_manager.add_few_shot_from_feedback(
                input_text=review["input_content"],
                correct_result=correct_result,
                source="human_review",
            )
        elif is_correct_article and is_actual_violation:
            correct_result = {
                "compliant": "no",
                "violation_type": review.get("violation_type", ""),
                "violated_articles": [article],
            }
            prompt_manager.add_few_shot_from_feedback(
                input_text=review["input_content"],
                correct_result=correct_result,
                source="human_review",
            )

        database.save_feedback(review_id, is_correct_article, f"violation_{violation_idx}: {'; '.join(status_parts)}")
    except Exception as e:
        return f"❌ 操作失败: {str(e)}"

    return f"✅ 已确认（审核ID: {review_id}，违规项 #{violation_idx + 1}）：{'；'.join(status_parts)}"


def load_pending_reviews():
    _, _, database = init_system()
    conn = database._get_conn()
    rows = conn.execute(
        "SELECT id, input_content, violation_type, confidence, risk_score, decision, created_at "
        "FROM review_records WHERE decision IN ('human_review', 'auto_block') AND is_deleted = 0 "
        "ORDER BY created_at DESC LIMIT 50"
    ).fetchall()
    if not rows:
        return '<div class="empty-state">暂无待复核记录</div>'
    output = ""
    for r in rows:
        rid = r["id"]
        content_preview = _esc(r["input_content"][:80]) + ("..." if len(r["input_content"]) > 80 else "")
        vt = _esc(r["violation_type"] or "无")
        conf = r["confidence"]
        risk = r["risk_score"]
        created = r["created_at"][:16] if r["created_at"] else ""
        risk_variant = "danger" if risk >= 0.7 else ("warning" if risk >= 0.3 else "success")
        output += f"""
<div class="pending-card">
  <div class="pending-card__header">
    <span class="pending-card__id">审核 #{rid}</span>
    <span class="pending-card__time">{created}</span>
  </div>
  <div class="pending-card__content">{content_preview}</div>
  <div class="pending-card__meta">
    {_pill(f'违规: {vt}', 'danger')}
    {_pill(f'置信度: {conf:.0%}', 'default')}
    {_pill(f'风险: {risk:.2f}', risk_variant)}
  </div>
</div>"""
    return output


def override_review(review_id, decision, comment, modification_reasons):
    _, _, database = init_system()
    if not review_id or review_id <= 0:
        return "⚠️ 无有效审核ID"
    review = database.get_review(review_id)
    if not review:
        return "⚠️ 未找到审核记录"
    if not modification_reasons or not modification_reasons.strip():
        return "⚠️ 请填写修改原因，每次人工修改必须说明理由"
    try:
        full_comment = f"[修改原因] {modification_reasons.strip()}"
        if comment and comment.strip():
            full_comment += f"\n[补充说明] {comment.strip()}"

        conn = database._get_conn()
        conn.execute(
            "UPDATE review_records SET decision = ?, review_comment = ? WHERE id = ?",
            (decision, full_comment, review_id),
        )
        conn.commit()

        from src.prompt_manager import prompt_manager
        correct_result = {
            "compliant": "yes" if decision == "auto_pass" else "no",
            "violation_type": review.get("violation_type", "") if decision != "auto_pass" else "",
            "violated_articles": json.loads(review.get("violated_articles", "[]")) if decision != "auto_pass" else [],
            "modification_reason": modification_reasons.strip(),
        }
        prompt_manager.add_few_shot_from_feedback(
            input_text=review["input_content"],
            correct_result=correct_result,
            source="human_override",
        )

        label = "通过" if decision == "auto_pass" else "驳回"
        return f"✅ 已{label}（审核ID: {review_id}），修改原因已记录，Few-Shot样本已自动创建"
    except Exception as e:
        return f"❌ 操作失败: {str(e)}"


def get_model_status():
    try:
        from src.llm_gateway import llm_gateway
        status = llm_gateway.get_model_status()
        if not status:
            return '<div class="empty-state">暂无模型信息</div>'
        output = '<div class="model-grid">'
        for name, info in status.items():
            circuit = info.get("circuit_state", "unknown")
            circuit_map = {
                "closed": ("正常", "success"),
                "open": ("熔断", "danger"),
                "half_open": ("半开", "warning"),
            }
            label, variant = circuit_map.get(circuit, (circuit, "default"))
            output += f"""
<div class="model-card">
  <div class="model-card__header">
    <span class="model-card__name">{_esc(name)}</span>
    {_pill(f'熔断: {label}', variant)}
  </div>
  <div class="model-card__meta">
    角色: {info.get('role', '-')} · Provider: {info.get('provider', '-')} · 优先级: {info.get('priority', '-')}
  </div>
</div>"""
        output += "</div>"
        return output
    except Exception as e:
        return f'<div class="alert alert--danger">获取模型状态失败: {_esc(str(e))}</div>'


def _get_violation_type_ids():
    try:
        from src.violation_registry import violation_registry
        return [vt.id for vt in violation_registry.list_types()]
    except Exception:
        return []


def get_violation_types():
    try:
        from src.violation_registry import violation_registry
        types = violation_registry.list_types()
        if not types:
            return '<div class="empty-state">暂无违规类型</div>'
        output = '<div class="vt-grid">'
        for vt in types:
            level_label = "L1" if vt.level == 1 else "L2"
            severity_colors = {0.3: "success", 0.5: "warning", 0.7: "warning", 0.9: "danger"}
            sev_variant = severity_colors.get(vt.severity, "default")
            keywords_str = "、".join(vt.keywords[:5]) if vt.keywords else "无"
            if len(vt.keywords) > 5:
                keywords_str += f" 等{len(vt.keywords)}个"
            output += f"""
<div class="vt-card">
  <div class="vt-card__header">
    <span class="vt-card__name">{_esc(vt.name)}</span>
    <div class="vt-card__badges">
      {_pill(level_label, 'default')}
      {_pill(f'严重度 {vt.severity}', sev_variant)}
    </div>
  </div>
  <div class="vt-card__keywords">关键词: {_esc(keywords_str)}</div>
</div>"""
        output += "</div>"
        return output
    except Exception as e:
        return f'<div class="alert alert--danger">获取违规类型失败: {_esc(str(e))}</div>'


def add_violation_keyword(type_id, keyword):
    try:
        from src.violation_registry import violation_registry
        result = violation_registry.add_keyword(type_id, keyword)
        if result:
            return f"✅ 已为类型 {type_id} 添加关键词: {keyword}"
        return f"❌ 添加失败，类型 {type_id} 不存在"
    except Exception as e:
        return f"❌ 操作失败: {str(e)}"


def deprecate_violation_type(type_id):
    try:
        from src.violation_registry import violation_registry
        result = violation_registry.deprecate_type(type_id)
        if result:
            return f"✅ 违规类型 {type_id} 已废弃，关联映射已自动过期"
        return f"❌ 废弃失败，类型 {type_id} 不存在"
    except Exception as e:
        return f"❌ 操作失败: {str(e)}"


def expire_mapping(doc_name, article_number):
    try:
        from src.violation_registry import violation_registry
        violation_registry.expire_mapping(doc_name, article_number)
        return f"✅ 映射已过期: {doc_name} 第{article_number}条"
    except Exception as e:
        return f"❌ 操作失败: {str(e)}"


def remove_violation_keyword(type_id, keyword):
    try:
        from src.violation_registry import violation_registry
        result = violation_registry.remove_keyword(type_id, keyword)
        if result:
            return f"✅ 已从类型 {type_id} 移除关键词: {keyword}"
        return f"❌ 移除失败，类型 {type_id} 不存在或关键词不存在"
    except ValueError as e:
        return f"⚠️ {str(e)}"
    except Exception as e:
        return f"❌ 操作失败: {str(e)}"


def update_violation_type(type_id, name, severity, description):
    try:
        from src.violation_registry import violation_registry
        kwargs = {}
        if name:
            kwargs["name"] = name
        if severity:
            kwargs["severity"] = float(severity)
        if description:
            kwargs["description"] = description
        result = violation_registry.update_type(type_id, **kwargs)
        if result:
            return f"✅ 违规类型 {type_id} 已更新"
        return f"❌ 更新失败，类型 {type_id} 不存在"
    except Exception as e:
        return f"❌ 操作失败: {str(e)}"


def add_clause_mapping(type_id, doc_name, article_number, mapping_logic):
    try:
        from src.violation_registry import violation_registry
        violation_registry.add_mapping(type_id, doc_name, article_number, mapping_logic or "primary")
        return f"✅ 映射已添加: {type_id} → {doc_name}/{article_number}"
    except Exception as e:
        return f"❌ 操作失败: {str(e)}"


def get_regulation_versions():
    try:
        _, _, database = init_system()
        versions = database.list_regulation_versions()
        if not versions:
            return '<div class="empty-state">暂无法规版本记录</div>'
        output = '<div class="data-table-wrap"><table class="data-table">'
        output += '<thead><tr><th>法规名称</th><th>版本</th><th>条文数</th><th>生效日期</th><th>当前版本</th><th>创建时间</th></tr></thead><tbody>'
        for v in versions:
            current_label = "✅ 是" if v.get("is_current") else ""
            output += f"""<tr>
<td>{_esc(v.get('doc_name', ''))}</td>
<td>{_esc(v.get('version', ''))}</td>
<td>{v.get('article_count', 0)}</td>
<td>{_esc(v.get('effective_date', '') or '-')}</td>
<td>{current_label}</td>
<td class="td-muted">{v.get('created_at', '')[:16]}</td>
</tr>"""
        output += "</tbody></table></div>"
        return output
    except Exception as e:
        return f'<div class="alert alert--danger">获取法规版本失败: {_esc(str(e))}</div>'


def view_regulation_text(doc_name):
    try:
        engine, _, _ = init_system()
        if not doc_name or not doc_name.strip():
            return '<div class="empty-state">请输入法规名称</div>'
        matching = [c for c in engine.chunks if c.doc_name == doc_name.strip()]
        if not matching:
            return f'<div class="empty-state">未找到法规: {_esc(doc_name)}</div>'
        output = f'<div class="section-block"><div class="section-block__title">《{_esc(doc_name)}》法规原文</div>'
        for chunk in sorted(matching, key=lambda c: c.chunk_index):
            output += f"""
<div class="regulation-quote">
  <div class="regulation-quote__source">第{_esc(chunk.article_number)}条</div>
  <div class="regulation-quote__text">{_esc(chunk.article_text)}</div>
</div>"""
        output += "</div>"
        return output
    except Exception as e:
        return f'<div class="alert alert--danger">查看法规原文失败: {_esc(str(e))}</div>'


def load_history(limit=20, offset=0, compliant_filter=None, decision_filter=None):
    _, _, database = init_system()
    kwargs = {"limit": limit, "offset": offset}
    if compliant_filter and compliant_filter != "全部":
        kwargs["compliant"] = compliant_filter
    reviews, total = database.list_reviews(**kwargs)
    if not reviews:
        return '<div class="empty-state">暂无审核记录</div>', total
    output = '<div class="data-table-wrap"><table class="data-table">'
    output += '<thead><tr>'
    output += '<th>ID</th><th>输入摘要</th><th>结论</th><th>违规类型</th><th>置信度</th><th>耗时</th><th>时间</th>'
    output += '</tr></thead><tbody>'
    for r in reviews:
        c = r.get("compliant", "")
        if c == "yes":
            status_html = _pill("合规", "success")
        elif c == "no":
            status_html = _pill("违规", "danger")
        else:
            status_html = _pill("未知", "warning")
        input_hash = r.get("input_hash", "")[:8]
        vt = r.get("violation_type", "")[:15] or "-"
        conf = r.get("confidence", 0)
        latency = r.get("latency_ms", 0)
        created = r.get("created_at", "")[:16]
        output += f"""<tr>
<td class="td-muted">{r.get('id', '')}</td>
<td>{input_hash}...</td>
<td>{status_html}</td>
<td class="td-muted">{_esc(vt)}</td>
<td>{conf:.0%}</td>
<td class="td-muted">{latency:.0f}ms</td>
<td class="td-muted">{created}</td>
</tr>"""
    output += "</tbody></table></div>"
    return output, total


def export_reviews():
    _, _, database = init_system()
    reviews, total = database.list_reviews(limit=1000)
    if not reviews:
        return None
    output_path = os.path.join(config.REGULATIONS_DIR, "..", "export_reviews.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(reviews, f, ensure_ascii=False, indent=2, default=str)
    return output_path


def get_system_stats():
    _, _, database = init_system()
    stats = database.get_stats()
    feedback = database.get_feedback_stats()
    return f"""
<div class="stats-grid">
  <div class="stat-card"><div class="stat-card__value">{stats['total_reviews']}</div><div class="stat-card__label">总审核数</div><div class="stat-card__accent stat-card__accent--neutral"></div></div>
  <div class="stat-card"><div class="stat-card__value">{stats['violation_reviews']}</div><div class="stat-card__label">违规数</div><div class="stat-card__accent stat-card__accent--danger"></div></div>
  <div class="stat-card"><div class="stat-card__value">{stats['compliant_reviews']}</div><div class="stat-card__label">合规数</div><div class="stat-card__accent stat-card__accent--success"></div></div>
  <div class="stat-card"><div class="stat-card__value">{stats['violation_rate']:.1%}</div><div class="stat-card__label">违规率</div><div class="stat-card__accent stat-card__accent--warning"></div></div>
  <div class="stat-card"><div class="stat-card__value">{stats['avg_latency_ms']:.0f}ms</div><div class="stat-card__label">平均延迟</div><div class="stat-card__accent stat-card__accent--neutral"></div></div>
  <div class="stat-card"><div class="stat-card__value">{stats['avg_confidence']:.2%}</div><div class="stat-card__label">平均置信度</div><div class="stat-card__accent stat-card__accent--neutral"></div></div>
  <div class="stat-card"><div class="stat-card__value">{feedback['total_feedback']}</div><div class="stat-card__label">反馈总数</div><div class="stat-card__accent stat-card__accent--neutral"></div></div>
  <div class="stat-card"><div class="stat-card__value">{feedback['accuracy']:.1%}</div><div class="stat-card__label">反馈准确率</div><div class="stat-card__accent stat-card__accent--success"></div></div>
  <div class="stat-card"><div class="stat-card__value">{stats['db_size_mb']:.2f}MB</div><div class="stat-card__label">数据库大小</div><div class="stat-card__accent stat-card__accent--neutral"></div></div>
</div>"""


EXAMPLE_INPUTS = [
    ["这款保险产品稳赚不赔，年化收益率高达8%，保本保息，零风险！现在购买还送价值5000元的黄金大礼包！", "❌ 典型违规"],
    ["本产品由XX保险公司承保，保险责任包括重大疾病保障，责任免除包括投保前已患疾病，犹豫期为15天，退保可能产生损失。请仔细阅读保险条款。", "✅ 合规案例"],
    ["比银行存款利息高多了！存钱不如买保险，这款理财险收益确定，比基金还稳！", "❌ 产品混淆"],
    ["著名影星XXX倾情推荐！这款保险产品保障全面！", "❌ 无资质代言"],
    ["限时特惠！今天购买这款重疾险，还额外赠送体检套餐和旅游基金！", "❌ 诱导销售"],
]

CUSTOM_CSS = """
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,100..1000;1,9..40,100..1000&family=Source+Sans+3:ital,wght@0,200..900;1,200..900&display=swap');

:root {
    --primary: #1a1a2e;
    --accent: #0d9488;
    --accent-light: #f0fdfa;
    --accent-border: #99f6e4;
    --success: #059669;
    --success-light: #ecfdf5;
    --success-border: #a7f3d0;
    --danger: #dc2626;
    --danger-light: #fef2f2;
    --danger-border: #fecaca;
    --warning: #d97706;
    --warning-light: #fffbeb;
    --warning-border: #fde68a;
    --info: #2563eb;
    --info-light: #eff6ff;
    --info-border: #bfdbfe;
    --purple: #7c3aed;
    --purple-light: #f5f3ff;
    --purple-border: #ddd6fe;
    --bg: #fafbfc;
    --bg-card: #ffffff;
    --bg-card-hover: #f8fafc;
    --text-primary: #1e293b;
    --text-muted: #64748b;
    --text-faint: #94a3b8;
    --border: #e2e8f0;
    --border-light: #f1f5f9;
    --radius-sm: 8px;
    --radius-md: 12px;
    --radius-lg: 16px;
    --radius-xl: 24px;
    --shadow-xs: 0 1px 2px rgba(0,0,0,0.04);
    --shadow-sm: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
    --shadow-md: 0 4px 6px -1px rgba(0,0,0,0.06), 0 2px 4px -2px rgba(0,0,0,0.04);
    --shadow-lg: 0 10px 15px -3px rgba(0,0,0,0.06), 0 4px 6px -4px rgba(0,0,0,0.03);
    --shadow-xl: 0 20px 25px -5px rgba(0,0,0,0.08), 0 8px 10px -6px rgba(0,0,0,0.04);
    --font-heading: 'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --font-body: 'Source Sans 3', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --transition-fast: all 0.15s cubic-bezier(0.4, 0, 0.2, 1);
    --transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    --transition-slow: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
}

* {
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

.gradio-container {
    max-width: 1440px !important;
    margin: 0 auto !important;
    padding: 0 !important;
    font-family: var(--font-body) !important;
    background: var(--bg) !important;
    color: var(--text-primary) !important;
}

.gradio-container .main {
    padding: 0 !important;
}

.tabs {
    border: none !important;
    background: transparent !important;
}

.tab-nav {
    background: var(--bg-card) !important;
    border-radius: 0 !important;
    padding: 0 32px !important;
    gap: 0 !important;
    border: none !important;
    border-bottom: 1px solid var(--border) !important;
    position: sticky !important;
    top: 0 !important;
    z-index: 100 !important;
    box-shadow: var(--shadow-xs) !important;
    flex-wrap: nowrap !important;
    overflow-x: auto !important;
}

.tab-nav button {
    color: var(--text-muted) !important;
    border-radius: 0 !important;
    padding: 16px 24px !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    font-family: var(--font-heading) !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
    background: transparent !important;
    transition: var(--transition-fast) !important;
    white-space: nowrap !important;
    letter-spacing: 0.01em !important;
    margin-bottom: -1px !important;
}

.tab-nav button.selected {
    color: var(--accent) !important;
    border-bottom-color: var(--accent) !important;
    font-weight: 600 !important;
    background: transparent !important;
    box-shadow: none !important;
}

.tab-nav button:hover:not(.selected) {
    color: var(--text-primary) !important;
    background: var(--border-light) !important;
}

.tabitem {
    padding: 32px 40px !important;
    border: none !important;
}

button[variant="primary"] {
    background: var(--accent) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: var(--radius-md) !important;
    padding: 12px 32px !important;
    font-size: 14px !important;
    font-weight: 600 !important;
    font-family: var(--font-heading) !important;
    transition: var(--transition) !important;
    letter-spacing: 0.02em !important;
    box-shadow: 0 1px 3px rgba(13,148,136,0.25) !important;
}

button[variant="primary"]:hover {
    background: #0f766e !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 12px rgba(13,148,136,0.3) !important;
}

button[variant="primary"]:active {
    transform: translateY(0) !important;
    box-shadow: 0 1px 2px rgba(13,148,136,0.2) !important;
}

button[variant="secondary"] {
    background: var(--bg-card) !important;
    color: var(--text-primary) !important;
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-md) !important;
    padding: 10px 24px !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    font-family: var(--font-heading) !important;
    transition: var(--transition) !important;
}

button[variant="secondary"]:hover {
    background: var(--border-light) !important;
    border-color: var(--text-faint) !important;
    transform: translateY(-1px) !important;
    box-shadow: var(--shadow-sm) !important;
}

textarea, input[type="text"] {
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-md) !important;
    font-size: 15px !important;
    line-height: 1.7 !important;
    padding: 14px 18px !important;
    transition: var(--transition-fast) !important;
    font-family: var(--font-body) !important;
    background: var(--bg-card) !important;
    color: var(--text-primary) !important;
}

textarea:focus, input[type="text"]:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(13,148,136,0.1) !important;
    outline: none !important;
}

textarea::placeholder, input::placeholder {
    color: var(--text-faint) !important;
}

.accordion {
    border: none !important;
    border-radius: var(--radius-lg) !important;
    margin-bottom: 12px !important;
    background: var(--bg-card) !important;
    box-shadow: var(--shadow-sm) !important;
    overflow: hidden !important;
    transition: var(--transition) !important;
}

.accordion:hover {
    box-shadow: var(--shadow-md) !important;
}

.accordion > .label-wrap {
    padding: 16px 24px !important;
    font-weight: 600 !important;
    font-family: var(--font-heading) !important;
    font-size: 14px !important;
    color: var(--text-primary) !important;
    background: var(--bg-card) !important;
    border-bottom: 1px solid transparent !important;
    transition: var(--transition-fast) !important;
}

.accordion > .label-wrap:hover {
    background: var(--border-light) !important;
}

select, .dropdown {
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-md) !important;
    padding: 10px 14px !important;
    font-size: 14px !important;
    font-family: var(--font-body) !important;
    transition: var(--transition-fast) !important;
    background: var(--bg-card) !important;
    color: var(--text-primary) !important;
}

input[type="number"] {
    border: 1px solid var(--border) !important;
    border-radius: var(--radius-md) !important;
    padding: 10px 14px !important;
    font-size: 14px !important;
    font-family: var(--font-body) !important;
    transition: var(--transition-fast) !important;
    background: var(--bg-card) !important;
    color: var(--text-primary) !important;
}

input[type="number"]:focus, select:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(13,148,136,0.1) !important;
    outline: none !important;
}

.status-hero {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 36px 24px;
    border-radius: var(--radius-xl);
    text-align: center;
    margin-bottom: 24px;
    transition: var(--transition);
}

.status-hero--success {
    background: var(--success-light);
    border: none;
    box-shadow: inset 0 0 0 1px rgba(5,150,105,0.1);
}

.status-hero--danger {
    background: var(--danger-light);
    border: none;
    box-shadow: inset 0 0 0 1px rgba(220,38,38,0.1);
}

.status-hero--warning {
    background: var(--warning-light);
    border: none;
    box-shadow: inset 0 0 0 1px rgba(217,119,6,0.1);
}

.status-hero__dot {
    width: 12px;
    height: 12px;
    border-radius: 50%;
    margin-bottom: 12px;
}

.status-hero--success .status-hero__dot {
    background: var(--success);
    box-shadow: 0 0 0 4px rgba(5,150,105,0.15);
}

.status-hero--danger .status-hero__dot {
    background: var(--danger);
    box-shadow: 0 0 0 4px rgba(220,38,38,0.15);
}

.status-hero--warning .status-hero__dot {
    background: var(--warning);
    box-shadow: 0 0 0 4px rgba(217,119,6,0.15);
}

.status-hero__label {
    font-size: 28px;
    font-weight: 700;
    font-family: var(--font-heading);
    letter-spacing: -0.02em;
}

.status-hero--success .status-hero__label { color: var(--success); }
.status-hero--danger .status-hero__label { color: var(--danger); }
.status-hero--warning .status-hero__label { color: var(--warning); }

.status-hero__sub {
    font-size: 14px;
    color: var(--text-muted);
    margin-top: 6px;
    font-weight: 400;
}

.pill {
    display: inline-flex;
    align-items: center;
    padding: 3px 10px;
    border-radius: 100px;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.01em;
    margin: 2px 4px 2px 0;
    transition: var(--transition-fast);
    line-height: 1.5;
    border: none;
}

.pill--success { background: var(--success-light); color: var(--success); }
.pill--danger { background: var(--danger-light); color: var(--danger); }
.pill--warning { background: var(--warning-light); color: var(--warning); }
.pill--info { background: var(--info-light); color: var(--info); }
.pill--purple { background: var(--purple-light); color: var(--purple); }
.pill--default { background: var(--border-light); color: var(--text-muted); }

.info-cards-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px;
    margin-bottom: 28px;
}

.info-card {
    background: var(--bg-card);
    border: none;
    border-radius: var(--radius-lg);
    padding: 20px 22px;
    box-shadow: var(--shadow-sm);
    transition: var(--transition);
}

.info-card:hover {
    box-shadow: var(--shadow-md);
    transform: translateY(-2px);
}

.info-card__label {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-faint);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin-bottom: 10px;
    font-family: var(--font-heading);
}

.info-card__value {
    font-size: 14px;
    color: var(--text-primary);
}

.progress-row {
    display: flex;
    align-items: center;
    gap: 12px;
}

.progress-track {
    flex: 1;
    background: var(--border);
    border-radius: 100px;
    height: 6px;
    overflow: hidden;
}

.progress-fill {
    height: 100%;
    border-radius: 100px;
    transition: width 0.6s cubic-bezier(0.4, 0, 0.2, 1);
}

.progress-label {
    font-size: 13px;
    font-weight: 700;
    font-family: var(--font-heading);
    min-width: 50px;
    text-align: right;
}

.section-block {
    margin-bottom: 28px;
}

.section-block__title {
    font-size: 18px;
    font-weight: 600;
    font-family: var(--font-heading);
    color: var(--text-primary);
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border);
    letter-spacing: -0.01em;
}

.violation-card {
    border: none;
    border-radius: var(--radius-lg);
    padding: 22px 24px;
    margin-bottom: 14px;
    background: var(--bg-card);
    box-shadow: var(--shadow-sm);
    transition: var(--transition);
}

.violation-card:hover {
    box-shadow: var(--shadow-md);
}

.violation-card--alert {
    box-shadow: var(--shadow-sm), inset 0 0 0 1px var(--danger);
}

.violation-card__warn {
    background: var(--danger-light);
    color: var(--danger);
    padding: 5px 12px;
    border-radius: var(--radius-sm);
    font-size: 12px;
    font-weight: 600;
    margin-bottom: 12px;
    display: inline-block;
    font-family: var(--font-heading);
}

.violation-card__reason {
    font-size: 15px;
    font-weight: 600;
    font-family: var(--font-heading);
    color: var(--text-primary);
    margin-bottom: 14px;
}

.regulation-quote {
    background: var(--border-light);
    border-left: 3px solid var(--accent);
    padding: 14px 18px;
    border-radius: 0 var(--radius-md) var(--radius-md) 0;
    margin-bottom: 16px;
}

.regulation-quote__source {
    font-size: 12px;
    font-weight: 600;
    color: var(--text-muted);
    margin-bottom: 6px;
    font-family: var(--font-heading);
}

.regulation-quote__text {
    font-size: 14px;
    color: var(--text-primary);
    line-height: 1.8;
}

.violation-card__actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

.btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 6px 14px;
    border-radius: var(--radius-sm);
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: var(--transition-fast);
    border: none;
    line-height: 1.5;
    font-family: var(--font-heading);
}

.btn--sm { padding: 4px 10px; font-size: 12px; }

.btn--ghost {
    background: transparent;
    color: var(--text-muted);
    border: 1px solid var(--border);
}

.btn--ghost:hover {
    background: var(--border-light);
    transform: translateY(-1px);
}

.btn--ghost-success {
    background: transparent;
    color: var(--success);
    border: 1px solid var(--success-border);
}

.btn--ghost-success:hover {
    background: var(--success-light);
    transform: translateY(-1px);
}

.btn--ghost-danger {
    background: transparent;
    color: var(--danger);
    border: 1px solid var(--danger-border);
}

.btn--ghost-danger:hover {
    background: var(--danger-light);
    transform: translateY(-1px);
}

.btn--success-outline {
    background: var(--success-light);
    color: var(--success);
    border: 1px solid var(--success-border);
}
.btn--success-outline:hover { background: #d1fae5; transform: translateY(-1px); }

.btn--danger-outline {
    background: var(--danger-light);
    color: var(--danger);
    border: 1px solid var(--danger-border);
}
.btn--danger-outline:hover { background: #fecaca; transform: translateY(-1px); }

.violation-card__result {
    margin-top: 10px;
    font-size: 13px;
    color: var(--text-muted);
}

.suggestion-card {
    background: var(--success-light);
    border-left: 3px solid var(--success);
    padding: 18px 22px;
    border-radius: 0 var(--radius-md) var(--radius-md) 0;
    font-size: 14px;
    color: #166534;
    line-height: 1.8;
}

.empty-state {
    color: var(--text-faint);
    text-align: center;
    padding: 56px 24px;
    font-size: 15px;
    font-weight: 400;
}

.alert {
    padding: 14px 18px;
    border-radius: var(--radius-md);
    font-size: 14px;
    line-height: 1.6;
}

.alert--danger {
    background: var(--danger-light);
    color: var(--danger);
    border: none;
    box-shadow: inset 0 0 0 1px rgba(220,38,38,0.12);
}

.pending-card {
    border: none;
    border-radius: var(--radius-lg);
    padding: 20px 22px;
    margin-bottom: 12px;
    background: var(--bg-card);
    box-shadow: var(--shadow-sm);
    transition: var(--transition);
}

.pending-card:hover {
    box-shadow: var(--shadow-md);
    transform: translateY(-2px);
}

.pending-card__header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
}

.pending-card__id {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
    font-family: var(--font-heading);
}

.pending-card__time {
    font-size: 12px;
    color: var(--text-faint);
}

.pending-card__content {
    font-size: 13px;
    color: var(--text-muted);
    margin-bottom: 12px;
    line-height: 1.6;
}

.pending-card__meta {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
}

.data-table-wrap {
    overflow-x: auto;
    border-radius: var(--radius-lg);
    background: var(--bg-card);
    box-shadow: var(--shadow-sm);
}

.data-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}

.data-table thead {
    background: var(--border-light);
}

.data-table thead th {
    padding: 12px 18px;
    text-align: left;
    color: var(--text-muted);
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-family: var(--font-heading);
    border-bottom: 1px solid var(--border);
}

.data-table tbody tr {
    border-bottom: 1px solid var(--border-light);
    transition: var(--transition-fast);
}

.data-table tbody tr:nth-child(even) {
    background: rgba(241,245,249,0.4);
}

.data-table tbody tr:hover {
    background: var(--border-light);
}

.data-table tbody td {
    padding: 12px 18px;
    color: var(--text-primary);
}

.td-muted {
    color: var(--text-faint) !important;
}

.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 16px;
}

.stat-card {
    background: var(--bg-card);
    border: none;
    border-radius: var(--radius-lg);
    padding: 24px 22px 20px;
    text-align: center;
    box-shadow: var(--shadow-sm);
    transition: var(--transition);
    position: relative;
    overflow: hidden;
}

.stat-card:hover {
    box-shadow: var(--shadow-md);
    transform: translateY(-2px);
}

.stat-card__accent {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 3px;
    border-radius: 3px 3px 0 0;
}

.stat-card__accent--neutral { background: var(--border); }
.stat-card__accent--success { background: var(--success); }
.stat-card__accent--danger { background: var(--danger); }
.stat-card__accent--warning { background: var(--warning); }

.stat-card__value {
    font-size: 32px;
    font-weight: 700;
    font-family: var(--font-heading);
    color: var(--text-primary);
    letter-spacing: -0.03em;
    line-height: 1.2;
}

.stat-card__label {
    font-size: 11px;
    font-weight: 600;
    color: var(--text-faint);
    margin-top: 6px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-family: var(--font-heading);
}

.model-grid {
    display: grid;
    gap: 12px;
}

.model-card {
    border: none;
    border-radius: var(--radius-lg);
    padding: 20px 22px;
    background: var(--bg-card);
    box-shadow: var(--shadow-sm);
    transition: var(--transition);
}

.model-card:hover {
    box-shadow: var(--shadow-md);
}

.model-card__header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
}

.model-card__name {
    font-size: 15px;
    font-weight: 600;
    color: var(--text-primary);
    font-family: var(--font-heading);
}

.model-card__meta {
    font-size: 12px;
    color: var(--text-muted);
}

.vt-grid {
    display: grid;
    gap: 10px;
}

.vt-card {
    border: none;
    border-radius: var(--radius-md);
    padding: 16px 20px;
    background: var(--bg-card);
    box-shadow: var(--shadow-xs);
    transition: var(--transition);
}

.vt-card:hover {
    box-shadow: var(--shadow-sm);
}

.vt-card__header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 6px;
}

.vt-card__name {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
    font-family: var(--font-heading);
}

.vt-card__badges {
    display: flex;
    gap: 6px;
}

.vt-card__keywords {
    font-size: 12px;
    color: var(--text-muted);
}

.search-summary {
    font-size: 13px;
    color: var(--text-muted);
    margin-bottom: 16px;
    font-weight: 500;
}

.reg-search-item {
    border: none;
    border-radius: var(--radius-md);
    padding: 16px 20px;
    margin-bottom: 10px;
    background: var(--bg-card);
    box-shadow: var(--shadow-xs);
    transition: var(--transition);
}

.reg-search-item:hover {
    box-shadow: var(--shadow-sm);
    transform: translateY(-1px);
}

.reg-search-item__source {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 4px;
    font-family: var(--font-heading);
}

.reg-search-item__text {
    font-size: 13px;
    color: var(--text-muted);
    line-height: 1.7;
}

.review-result {
    font-family: var(--font-body);
}

.review-result__header {
    margin-bottom: 24px;
}

.review-result__id {
    text-align: center;
    font-size: 12px;
    color: var(--text-faint);
    margin-top: 8px;
    font-family: var(--font-heading);
}

.app-header {
    background: var(--bg-card);
    padding: 20px 40px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid var(--border);
}

.app-header__left {
    display: flex;
    align-items: center;
    gap: 12px;
}

.app-header__logo {
    font-size: 20px;
    font-weight: 700;
    font-family: var(--font-heading);
    color: var(--text-primary);
    letter-spacing: -0.02em;
    margin: 0;
}

.app-header__logo-accent {
    color: var(--accent);
}

.app-header__subtitle {
    color: var(--text-faint);
    font-size: 13px;
    font-weight: 400;
    margin: 4px 0 0;
}

.app-header__version {
    display: inline-flex;
    align-items: center;
    padding: 4px 12px;
    border-radius: 100px;
    font-size: 11px;
    font-weight: 600;
    color: var(--accent);
    background: var(--accent-light);
    font-family: var(--font-heading);
    letter-spacing: 0.02em;
}

.app-footer {
    text-align: center;
    padding: 24px 0 16px;
    color: var(--text-faint);
    font-size: 12px;
    border-top: 1px solid var(--border);
    margin-top: 40px;
    font-family: var(--font-heading);
}

.card-section {
    background: var(--bg-card);
    border: none;
    border-radius: var(--radius-xl);
    padding: 28px;
    margin-bottom: 20px;
    box-shadow: var(--shadow-sm);
    transition: var(--transition);
}

.card-section:hover {
    box-shadow: var(--shadow-md);
}

.card-section__title {
    font-size: 16px;
    font-weight: 600;
    font-family: var(--font-heading);
    color: var(--text-primary);
    margin-bottom: 16px;
    letter-spacing: -0.01em;
}

.doc-content {
    max-width: 900px;
    margin: 0 auto;
    line-height: 1.9;
    color: var(--text-muted);
    font-size: 14px;
}

.doc-content h2 {
    color: var(--text-primary);
    font-family: var(--font-heading);
    border-bottom: 1px solid var(--border);
    padding-bottom: 12px;
    margin-top: 36px;
    font-weight: 700;
    letter-spacing: -0.02em;
}

.doc-content h3 {
    color: var(--text-primary);
    font-family: var(--font-heading);
    font-weight: 600;
    margin-top: 24px;
}

.doc-content table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 24px;
    border: none;
    border-radius: var(--radius-md);
    overflow: hidden;
    box-shadow: var(--shadow-xs);
}

.doc-content thead { background: var(--border-light); }
.doc-content thead th {
    padding: 10px 16px;
    text-align: left;
    color: var(--text-muted);
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    font-family: var(--font-heading);
    border-bottom: 1px solid var(--border);
}
.doc-content tbody td {
    padding: 10px 16px;
    border-bottom: 1px solid var(--border-light);
    font-size: 13px;
    color: var(--text-primary);
}
.doc-content ul { padding-left: 20px; }
.doc-content li { margin-bottom: 6px; }

.form-label {
    font-size: 13px;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 6px;
    display: block;
    font-family: var(--font-heading);
}

.form-helper {
    font-size: 12px;
    color: var(--text-faint);
    margin-top: 4px;
}

.examples-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 10px;
    margin-top: 12px;
}

.example-chip {
    padding: 12px 16px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    font-size: 12px;
    color: var(--text-muted);
    cursor: pointer;
    transition: var(--transition-fast);
    background: var(--bg-card);
    line-height: 1.5;
}

.example-chip:hover {
    border-color: var(--accent);
    background: var(--accent-light);
    color: var(--accent);
    box-shadow: var(--shadow-xs);
}

.override-section {
    background: var(--bg-card);
    border: none;
    border-radius: var(--radius-xl);
    padding: 28px;
    box-shadow: var(--shadow-sm);
}

.mgmt-section {
    margin-top: 20px;
    padding-top: 20px;
    border-top: 1px solid var(--border);
}

.mgmt-section__title {
    font-size: 14px;
    font-weight: 600;
    font-family: var(--font-heading);
    color: var(--text-primary);
    margin-bottom: 12px;
}

.mgmt-row {
    display: flex;
    gap: 10px;
    align-items: flex-end;
    flex-wrap: wrap;
    margin-bottom: 8px;
}

.label-text {
    font-size: 13px;
    font-weight: 500;
    color: var(--text-muted);
    margin-bottom: 4px;
    font-family: var(--font-heading);
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: translateY(0); }
}

.review-result,
.pending-card,
.violation-card,
.stat-card,
.info-card,
.reg-search-item,
.model-card,
.vt-card {
    animation: fadeIn 0.3s ease-out;
}

@media (max-width: 768px) {
    .gradio-container { max-width: 100% !important; }
    .tabitem { padding: 20px 16px !important; }
    .info-cards-row { grid-template-columns: 1fr 1fr; }
    .stats-grid { grid-template-columns: 1fr 1fr; }
    textarea { font-size: 16px !important; }
    button { min-height: 44px !important; }
    .status-hero { padding: 24px 16px; }
    .status-hero__label { font-size: 22px; }
    .app-header { padding: 16px 20px; flex-direction: column; gap: 8px; align-items: flex-start; }
    .card-section { padding: 20px; }
}

@media (max-width: 480px) {
    .info-cards-row { grid-template-columns: 1fr; }
    .stats-grid { grid-template-columns: 1fr; }
    .tab-nav button { padding: 12px 16px !important; font-size: 13px !important; }
    .app-header__logo { font-size: 17px; }
}
"""


def create_app():
    with gr.Blocks(
        title="保险营销内容智能审核系统",
        css=CUSTOM_CSS,
        theme=gr.themes.Soft(
            primary_hue=gr.themes.colors.teal,
            secondary_hue=gr.themes.colors.slate,
            neutral_hue=gr.themes.colors.slate,
            font=gr.themes.GoogleFont("Source Sans 3"),
        ),
    ) as app:
        gr.HTML("""
        <div class="app-header">
            <div class="app-header__left">
                <div>
                    <h1 class="app-header__logo"><span class="app-header__logo-accent">Shield</span> Review</h1>
                    <p class="app-header__subtitle">保险营销内容智能合规审核 · 大模型 + RAG + HITL</p>
                </div>
            </div>
            <span class="app-header__version">v3.3</span>
        </div>
        """)

        with gr.Tabs():
            with gr.TabItem("内容审核"):
                review_id_state = gr.State(0)
                review_result_state = gr.State({})

                with gr.Row(equal_height=True):
                    with gr.Column(scale=2, min_width=400):
                        gr.HTML('<div class="card-section">')
                        gr.HTML('<div class="card-section__title">输入审核内容</div>')
                        text_input = gr.Textbox(
                            label="待审核的营销文本",
                            placeholder="请输入保险营销内容，系统将自动进行合规审核...\n\n例如：这款保险产品稳赚不赔，年化收益率高达8%！",
                            lines=8,
                            max_lines=20,
                            show_label=True,
                        )
                        text_review_btn = gr.Button("开始审核", variant="primary", size="lg")
                        gr.HTML('</div>')

                        gr.HTML('<div class="card-section">')
                        gr.HTML('<div class="card-section__title">示例输入</div>')
                        gr.HTML('<div class="examples-grid">')
                        examples_html = ""
                        for example_text, example_desc in EXAMPLE_INPUTS:
                            safe_text = _esc(example_text[:60]) + ("..." if len(example_text) > 60 else "")
                            examples_html += f'<div class="example-chip">{example_desc}<br/><span style="color:var(--text-faint);font-size:11px;">{safe_text}</span></div>'
                        gr.HTML(examples_html)
                        gr.HTML('</div>')
                        gr.HTML('</div>')

                        for example_text, example_desc in EXAMPLE_INPUTS:
                            gr.Examples(
                                examples=[[example_text]],
                                inputs=[text_input],
                                label=example_desc,
                            )

                    with gr.Column(scale=3, min_width=500):
                        text_result = gr.HTML(
                            value='<div class="empty-state">审核结果将在此处显示<br/>请输入内容后点击「开始审核」</div>',
                        )

                        with gr.Accordion("逐项违规确认", open=False, visible=False) as violation_accordion:
                            violation_idx_input = gr.Number(label="违规项序号（从0开始）", value=0, precision=0)
                            with gr.Row():
                                confirm_article_correct_btn = gr.Button("条款正确", size="sm")
                                confirm_article_wrong_btn = gr.Button("条款有误", size="sm")
                            with gr.Row():
                                mark_violation_btn = gr.Button("确实违规", size="sm")
                                mark_compliant_btn = gr.Button("实际合规", size="sm")
                            confirm_result = gr.HTML("")

                        with gr.Accordion("法规搜索", open=False):
                            reg_search_input = gr.Textbox(
                                label="搜索法规关键词",
                                placeholder="输入关键词搜索相关法规条文...",
                                lines=1,
                            )
                            reg_search_btn = gr.Button("搜索", variant="secondary", size="sm")
                            reg_search_result = gr.HTML("")

                        with gr.Accordion("修改建议", open=True):
                            suggestions_output = gr.Markdown("")

                        with gr.Accordion("审核推理", open=False):
                            reasoning_output = gr.Markdown("")

                text_review_btn.click(
                    fn=review_text,
                    inputs=[text_input],
                    outputs=[text_result, reasoning_output, suggestions_output, violation_accordion, review_id_state, review_result_state],
                )

                def _confirm_article_correct(rid, idx):
                    return confirm_violation(int(rid), int(idx), True, True)

                def _confirm_article_wrong(rid, idx):
                    return confirm_violation(int(rid), int(idx), False, True)

                def _mark_violation(rid, idx):
                    return confirm_violation(int(rid), int(idx), True, True)

                def _mark_compliant(rid, idx):
                    return confirm_violation(int(rid), int(idx), True, False)

                confirm_article_correct_btn.click(
                    fn=_confirm_article_correct,
                    inputs=[review_id_state, violation_idx_input],
                    outputs=[confirm_result],
                )
                confirm_article_wrong_btn.click(
                    fn=_confirm_article_wrong,
                    inputs=[review_id_state, violation_idx_input],
                    outputs=[confirm_result],
                )
                mark_violation_btn.click(
                    fn=_mark_violation,
                    inputs=[review_id_state, violation_idx_input],
                    outputs=[confirm_result],
                )
                mark_compliant_btn.click(
                    fn=_mark_compliant,
                    inputs=[review_id_state, violation_idx_input],
                    outputs=[confirm_result],
                )

                reg_search_btn.click(
                    fn=search_regulations,
                    inputs=[reg_search_input],
                    outputs=[reg_search_result],
                )

            with gr.TabItem("人工复核"):
                with gr.Row():
                    refresh_pending_btn = gr.Button("刷新待复核列表", variant="primary", size="lg")

                pending_list = gr.HTML(value='<div class="empty-state">点击刷新加载待复核记录</div>')

                gr.HTML('<div class="override-section" style="margin-top:24px;">')
                gr.HTML('<div class="card-section__title">人工复核操作</div>')
                gr.HTML('<div class="alert" style="background:var(--info-light);color:var(--info);box-shadow:inset 0 0 0 1px rgba(37,99,235,0.12);font-size:13px;margin-bottom:16px;">💡 不论系统决策是什么（包括自动拦截），人工都可以进行修改。每次修改必须填写修改原因。</div>')
                with gr.Row():
                    override_id_input = gr.Number(label="审核ID", value=0, precision=0)
                    override_decision = gr.Dropdown(
                        choices=["auto_pass", "auto_block"],
                        value="auto_pass",
                        label="处置决定",
                    )
                modification_reason_input = gr.Textbox(
                    label="修改原因（必填）",
                    placeholder="请说明为什么修改系统决策，例如：系统误判/实际合规/需要补充审核...",
                    lines=2,
                )
                override_comment_input = gr.Textbox(
                    label="补充说明（选填）",
                    placeholder="其他补充信息...",
                    lines=2,
                )
                with gr.Row():
                    override_pass_btn = gr.Button("通过", variant="primary")
                    override_reject_btn = gr.Button("驳回", variant="secondary")
                override_result = gr.HTML("")
                gr.HTML('</div>')

                def _override_pass(rid, comment, reason):
                    return override_review(int(rid), "auto_pass", comment, reason)

                def _override_reject(rid, comment, reason):
                    return override_review(int(rid), "auto_block", comment, reason)

                refresh_pending_btn.click(
                    fn=load_pending_reviews,
                    outputs=[pending_list],
                )
                override_pass_btn.click(
                    fn=_override_pass,
                    inputs=[override_id_input, override_comment_input, modification_reason_input],
                    outputs=[override_result],
                )
                override_reject_btn.click(
                    fn=_override_reject,
                    inputs=[override_id_input, override_comment_input, modification_reason_input],
                    outputs=[override_result],
                )

            with gr.TabItem("审核历史"):
                with gr.Row():
                    history_limit = gr.Slider(10, 100, value=20, step=10, label="显示条数")
                    history_compliant_filter = gr.Dropdown(
                        choices=["全部", "yes", "no", "unknown"],
                        value="全部",
                        label="合规状态",
                    )
                    refresh_history_btn = gr.Button("刷新", variant="primary")
                    export_btn = gr.Button("导出JSON", variant="secondary")

                history_output = gr.HTML(value='<div class="empty-state">点击刷新加载审核历史</div>')
                history_total = gr.Number(label="总记录数", visible=False)
                export_file = gr.File(label="导出文件", visible=False)

                def _load_history(limit, compliant_filter):
                    html_result, total = load_history(
                        limit=int(limit),
                        compliant_filter=compliant_filter,
                    )
                    return html_result, total

                refresh_history_btn.click(
                    fn=_load_history,
                    inputs=[history_limit, history_compliant_filter],
                    outputs=[history_output, history_total],
                )
                export_btn.click(
                    fn=export_reviews,
                    outputs=[export_file],
                )

            with gr.TabItem("效果评估"):
                with gr.Row():
                    eval_btn = gr.Button("运行标准评估", variant="primary", size="lg")
                    extreme_eval_btn = gr.Button("运行极端用例测试", variant="secondary", size="lg")

                eval_result = gr.HTML(value='<div class="empty-state">点击按钮运行评估</div>')

                def run_evaluation():
                    from src.evaluator import Evaluator
                    _, agent, _ = init_system()
                    evaluator = Evaluator(agent)
                    report = evaluator.evaluate_all()
                    return f"""
<div class="stats-grid">
  <div class="stat-card"><div class="stat-card__value">{report['total_cases']}</div><div class="stat-card__label">总测试用例</div><div class="stat-card__accent stat-card__accent--neutral"></div></div>
  <div class="stat-card"><div class="stat-card__value">{report['compliant_accuracy']:.2%}</div><div class="stat-card__label">合规判断准确率</div><div class="stat-card__accent stat-card__accent--success"></div></div>
  <div class="stat-card"><div class="stat-card__value">{report['violation_type_accuracy']:.2%}</div><div class="stat-card__label">违规类型匹配率</div><div class="stat-card__accent stat-card__accent--success"></div></div>
  <div class="stat-card"><div class="stat-card__value">{report['precision']:.2%}</div><div class="stat-card__label">精确率</div><div class="stat-card__accent stat-card__accent--neutral"></div></div>
  <div class="stat-card"><div class="stat-card__value">{report['recall']:.2%}</div><div class="stat-card__label">召回率</div><div class="stat-card__accent stat-card__accent--neutral"></div></div>
  <div class="stat-card"><div class="stat-card__value">{report['f1_score']:.4f}</div><div class="stat-card__label">F1分数</div><div class="stat-card__accent stat-card__accent--warning"></div></div>
  <div class="stat-card"><div class="stat-card__value">{report['avg_confidence']:.4f}</div><div class="stat-card__label">平均置信度</div><div class="stat-card__accent stat-card__accent--neutral"></div></div>
</div>"""

                def run_extreme_tests():
                    from src.evaluator import Evaluator
                    _, agent, _ = init_system()
                    evaluator = Evaluator(agent)
                    tc_path = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), "eval", "extreme_test_cases.json"
                    )
                    report = evaluator.evaluate_all(tc_path)
                    blocked = sum(1 for d in report["details"] if d["predicted_compliant"] == "unknown")
                    return f"""
<div class="stats-grid">
  <div class="stat-card"><div class="stat-card__value">{blocked}</div><div class="stat-card__label">安全攻击拦截数</div><div class="stat-card__accent stat-card__accent--danger"></div></div>
  <div class="stat-card"><div class="stat-card__value">{report['total_cases']}</div><div class="stat-card__label">总测试用例</div><div class="stat-card__accent stat-card__accent--neutral"></div></div>
  <div class="stat-card"><div class="stat-card__value">{report['compliant_accuracy']:.2%}</div><div class="stat-card__label">合规判断准确率</div><div class="stat-card__accent stat-card__accent--success"></div></div>
  <div class="stat-card"><div class="stat-card__value">{report['avg_confidence']:.4f}</div><div class="stat-card__label">平均置信度</div><div class="stat-card__accent stat-card__accent--neutral"></div></div>
  <div class="stat-card"><div class="stat-card__value">{blocked}/{report['total_cases']} = {blocked/report['total_cases']:.1%}</div><div class="stat-card__label">安全拦截率</div><div class="stat-card__accent stat-card__accent--warning"></div></div>
</div>"""

                eval_btn.click(fn=run_evaluation, outputs=[eval_result])
                extreme_eval_btn.click(fn=run_extreme_tests, outputs=[eval_result])

            with gr.TabItem("系统管理"):
                with gr.Accordion("系统统计", open=True):
                    stats_output = gr.HTML("")
                    stats_btn = gr.Button("查看系统统计", variant="primary")
                    stats_btn.click(fn=get_system_stats, outputs=[stats_output])

                with gr.Accordion("模型状态", open=False):
                    model_status_btn = gr.Button("刷新模型状态", variant="secondary")
                    model_status_output = gr.HTML("")
                    model_status_btn.click(fn=get_model_status, outputs=[model_status_output])

                with gr.Accordion("违规类型管理", open=False):
                    vt_list_btn = gr.Button("刷新违规类型", variant="secondary")
                    vt_list_output = gr.HTML("")
                    vt_list_btn.click(fn=get_violation_types, outputs=[vt_list_output])

                    gr.HTML('<div class="mgmt-section">')
                    gr.HTML('<div class="mgmt-section__title">添加关键词</div>')
                    with gr.Row():
                        vt_id_input = gr.Textbox(label="违规类型ID", placeholder="例如: absolute_language")
                        vt_keyword_input = gr.Textbox(label="关键词", placeholder="例如: 必定")
                    vt_add_btn = gr.Button("添加关键词", variant="secondary")
                    vt_add_result = gr.HTML("")
                    gr.HTML('</div>')
                    vt_add_btn.click(
                        fn=add_violation_keyword,
                        inputs=[vt_id_input, vt_keyword_input],
                        outputs=[vt_add_result],
                    )

                    gr.HTML('<div class="mgmt-section">')
                    gr.HTML('<div class="mgmt-section__title">废弃违规类型</div>')
                    deprecate_type_id_input = gr.Textbox(label="违规类型ID", placeholder="例如: absolute_language")
                    deprecate_btn = gr.Button("废弃类型", variant="secondary")
                    deprecate_result = gr.HTML("")
                    gr.HTML('</div>')
                    deprecate_btn.click(
                        fn=deprecate_violation_type,
                        inputs=[deprecate_type_id_input],
                        outputs=[deprecate_result],
                    )

                    gr.HTML('<div class="mgmt-section">')
                    gr.HTML('<div class="mgmt-section__title">过期映射</div>')
                    with gr.Row():
                        expire_doc_name_input = gr.Textbox(label="法规名称", placeholder="例如: 保险法")
                        expire_article_input = gr.Textbox(label="条款号", placeholder="例如: 第116条")
                    expire_btn = gr.Button("过期映射", variant="secondary")
                    expire_result = gr.HTML("")
                    gr.HTML('</div>')
                    expire_btn.click(
                        fn=expire_mapping,
                        inputs=[expire_doc_name_input, expire_article_input],
                        outputs=[expire_result],
                    )

                    gr.HTML('<div class="mgmt-section">')
                    gr.HTML('<div class="mgmt-section__title">移除关键词</div>')
                    with gr.Row():
                        remove_kw_type_id_input = gr.Textbox(label="违规类型ID", placeholder="例如: absolute_language")
                        remove_kw_input = gr.Textbox(label="关键词", placeholder="例如: 必定")
                    remove_kw_btn = gr.Button("移除关键词", variant="secondary")
                    remove_kw_result = gr.HTML("")
                    gr.HTML('</div>')
                    remove_kw_btn.click(
                        fn=remove_violation_keyword,
                        inputs=[remove_kw_type_id_input, remove_kw_input],
                        outputs=[remove_kw_result],
                    )

                    gr.HTML('<div class="mgmt-section">')
                    gr.HTML('<div class="mgmt-section__title">编辑违规类型</div>')
                    edit_type_id_dropdown = gr.Dropdown(
                        choices=_get_violation_type_ids(),
                        label="选择违规类型",
                    )
                    with gr.Row():
                        edit_type_name = gr.Textbox(label="名称", placeholder="留空则不修改")
                        edit_type_severity = gr.Textbox(label="严重度", placeholder="例如: 0.8，留空则不修改")
                    edit_type_desc = gr.Textbox(label="描述", placeholder="留空则不修改", lines=2)
                    edit_type_btn = gr.Button("更新类型", variant="secondary")
                    edit_type_result = gr.HTML("")
                    gr.HTML('</div>')
                    edit_type_btn.click(
                        fn=update_violation_type,
                        inputs=[edit_type_id_dropdown, edit_type_name, edit_type_severity, edit_type_desc],
                        outputs=[edit_type_result],
                    )

                with gr.Accordion("条款映射管理", open=False):
                    gr.HTML('<div class="mgmt-section">')
                    gr.HTML('<div class="mgmt-section__title">添加映射</div>')
                    with gr.Row():
                        mapping_type_id_input = gr.Textbox(label="违规类型ID", placeholder="例如: absolute_language")
                        mapping_doc_name_input = gr.Textbox(label="法规名称", placeholder="例如: 保险销售行为管理办法")
                    with gr.Row():
                        mapping_article_input = gr.Textbox(label="条款号", placeholder="例如: 二十一")
                        mapping_logic_dropdown = gr.Dropdown(
                            choices=["primary", "secondary"],
                            value="primary",
                            label="映射逻辑",
                        )
                    add_mapping_btn = gr.Button("添加映射", variant="secondary")
                    add_mapping_result = gr.HTML("")
                    gr.HTML('</div>')
                    add_mapping_btn.click(
                        fn=add_clause_mapping,
                        inputs=[mapping_type_id_input, mapping_doc_name_input, mapping_article_input, mapping_logic_dropdown],
                        outputs=[add_mapping_result],
                    )

                    gr.HTML('<div class="mgmt-section">')
                    gr.HTML('<div class="mgmt-section__title">过期映射</div>')
                    with gr.Row():
                        expire_doc_name_input = gr.Textbox(label="法规名称", placeholder="例如: 保险法")
                        expire_article_input = gr.Textbox(label="条款号", placeholder="例如: 第116条")
                    expire_btn = gr.Button("过期映射", variant="secondary")
                    expire_result = gr.HTML("")
                    gr.HTML('</div>')
                    expire_btn.click(
                        fn=expire_mapping,
                        inputs=[expire_doc_name_input, expire_article_input],
                        outputs=[expire_result],
                    )

                with gr.Accordion("法规版本管理", open=False):
                    reg_version_output = gr.HTML("")
                    reg_version_btn = gr.Button("查看法规版本", variant="secondary")
                    reg_version_btn.click(fn=get_regulation_versions, outputs=[reg_version_output])

                    gr.HTML('<div class="mgmt-section">')
                    gr.HTML('<div class="mgmt-section__title">查看法规原文</div>')
                    view_reg_doc_name_input = gr.Textbox(label="法规名称", placeholder="例如: 保险销售行为管理办法")
                    view_reg_text_btn = gr.Button("查看法规原文", variant="secondary")
                    view_reg_text_output = gr.HTML("")
                    gr.HTML('</div>')
                    view_reg_text_btn.click(
                        fn=view_regulation_text,
                        inputs=[view_reg_doc_name_input],
                        outputs=[view_reg_text_output],
                    )

                with gr.Accordion("数据库管理", open=False):
                    with gr.Row():
                        backup_btn = gr.Button("手动备份", variant="secondary")
                        cleanup_btn = gr.Button("清理过期数据", variant="secondary")
                    db_action_result = gr.HTML("")

                    def do_backup():
                        _, _, database = init_system()
                        path = database.backup()
                        return f'<div class="alert" style="background:var(--success-light);color:var(--success);box-shadow:inset 0 0 0 1px rgba(5,150,105,0.12);">✅ 备份完成: {path}</div>'

                    def do_cleanup():
                        _, _, database = init_system()
                        stats = database.cleanup_expired_data()
                        return f'<div class="alert" style="background:var(--success-light);color:var(--success);box-shadow:inset 0 0 0 1px rgba(5,150,105,0.12);">✅ 清理完成: {stats}</div>'

                    backup_btn.click(fn=do_backup, outputs=[db_action_result])
                    cleanup_btn.click(fn=do_cleanup, outputs=[db_action_result])

            with gr.TabItem("系统说明"):
                gr.HTML("""
<div class="doc-content">
<h2 style="color:var(--text-primary);border-bottom:1px solid var(--border);padding-bottom:12px;">生产级架构</h2>

<h3 style="color:var(--text-primary);">技术栈</h3>
<table>
  <thead><tr><th>层次</th><th>技术</th></tr></thead>
  <tbody>
    <tr><td>前端</td><td>Gradio v3.3 (响应式+暗色模式+快捷键)</td></tr>
    <tr><td>API</td><td>FastAPI + Uvicorn</td></tr>
    <tr><td>认证</td><td>API Key + RBAC (90天过期)</td></tr>
    <tr><td>数据库</td><td>SQLite (WAL模式)</td></tr>
    <tr><td>向量库</td><td>ChromaDB</td></tr>
    <tr><td>LLM</td><td>百炼 qwen-plus + LLM Gateway 多模型路由</td></tr>
    <tr><td>Embedding</td><td>text-embedding-v3</td></tr>
    <tr><td>监控</td><td>Prometheus + AlertManager</td></tr>
    <tr><td>异步</td><td>ThreadPoolExecutor + Semaphore</td></tr>
  </tbody>
</table>

<h3 style="color:var(--text-primary);">安全防护</h3>
<ul>
  <li>7层纵深防御：WAF → 网关 → 限流 → 输入校验 → Prompt注入检测 → LLM安全Prompt → 输出校验</li>
  <li>17种注入模式检测（中英文+Token边界）</li>
  <li>XSS/SQL注入/控制字符过滤</li>
  <li>审计日志（JSONL格式，按日分割，HMAC签名）</li>
  <li>API Key 90天自动过期</li>
  <li>PBKDF2-HMAC-SHA256 密码哈希</li>
</ul>

<h3 style="color:var(--text-primary);">鲁棒性</h3>
<ul>
  <li>熔断器：三态模型 (Closed/Open/Half-Open)</li>
  <li>重试：指数退避+随机抖动</li>
  <li>降级：LLM→规则引擎，向量→关键词</li>
  <li>缓存：LRU+TTL (可配置)</li>
  <li>并发控制：Semaphore (可配置)</li>
</ul>

<h3 style="color:var(--text-primary);">HITL 人机协同</h3>
<ul>
  <li>风险评分 → 自动通过/人工复核/自动拦截 三级决策</li>
  <li>人工复核队列 + 逐项违规确认</li>
  <li>复核结果自动生成 Few-Shot 样本回流</li>
  <li>条款引用验证（幻觉检测）</li>
</ul>

<h3 style="color:var(--text-primary);">可观测性</h3>
<ul>
  <li>Prometheus 指标：审核总数/延迟/缓存/安全拦截/熔断状态</li>
  <li>OpenTelemetry 风格 Trace：rag_retrieve/llm_call/review 全链路追踪</li>
  <li>AlertManager：熔断/缓存命中率/队列容量告警</li>
  <li>HealthCheck：数据库/RAG/熔断器/任务队列健康检查</li>
</ul>

<h3 style="color:var(--text-primary);">API端点</h3>
<table>
  <thead><tr><th>端点</th><th>方法</th><th>说明</th></tr></thead>
  <tbody>
    <tr><td style="font-family:monospace;font-size:12px;">/health</td><td>GET</td><td>健康检查</td></tr>
    <tr><td style="font-family:monospace;font-size:12px;">/ready</td><td>GET</td><td>就绪检查</td></tr>
    <tr><td style="font-family:monospace;font-size:12px;">/metrics</td><td>GET</td><td>Prometheus指标</td></tr>
    <tr><td style="font-family:monospace;font-size:12px;">/api/v1/review</td><td>POST</td><td>单条审核</td></tr>
    <tr><td style="font-family:monospace;font-size:12px;">/api/v1/review/async</td><td>POST</td><td>异步审核</td></tr>
    <tr><td style="font-family:monospace;font-size:12px;">/api/v1/review/batch</td><td>POST</td><td>批量审核</td></tr>
    <tr><td style="font-family:monospace;font-size:12px;">/api/v1/feedback</td><td>POST</td><td>提交反馈</td></tr>
    <tr><td style="font-family:monospace;font-size:12px;">/api/v1/reviews</td><td>GET</td><td>审核历史</td></tr>
    <tr><td style="font-family:monospace;font-size:12px;">/api/v1/stats</td><td>GET</td><td>系统统计</td></tr>
  </tbody>
</table>

</div>
""")

        gr.HTML("""
        <div class="app-footer">
            Shield Review v3.3 · 保险营销内容智能合规审核 · 百炼大模型API + RAG + HITL
        </div>
        """)

    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("正在初始化系统...")
    init_system()
    print("系统初始化完成！")

    app = create_app()
    app.launch(
        server_name=config.SERVER_HOST,
        server_port=config.SERVER_PORT,
        share=False,
    )
