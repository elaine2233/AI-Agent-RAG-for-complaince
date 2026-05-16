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


def format_review_result(result_dict: dict, review_id: int = 0) -> str:
    result = result_dict["result"]
    compliant = result["compliant"]

    if compliant == "yes":
        status_icon = "✅"
        status_text = "合规"
        status_color = "#10b981"
    elif compliant == "no":
        status_icon = "❌"
        status_text = "违规"
        status_color = "#ef4444"
    else:
        status_icon = "⚠️"
        status_text = "无法判断"
        status_color = "#f59e0b"

    output = f"""<div style="border-left: 4px solid {status_color}; padding-left: 16px; margin-bottom: 16px;">
<h2 style="color: {status_color}; margin: 0;">{status_icon} 审核结论：{status_text}</h2>
</div>

| 项目 | 结果 |
|------|------|
| 合规判断 | **{_esc(compliant)}** |
| 违规类型 | **{_esc(result['violation_type'])}** |
| 置信度 | **{result['confidence']:.1%}** |
| 审核ID | {review_id} |

---

### 🔍 审核推理

{_esc(result['reasoning'])}

---

### 📑 引用法规条文
"""

    if result["violated_articles"]:
        for i, article in enumerate(result["violated_articles"], 1):
            output += f"""
**{i}. 《{_esc(article['doc_name'])}》第{_esc(article['article_number'])}条**

> {_esc(article['article_text'])}

**违反原因**: {_esc(article['violation_reason'])}

"""
    else:
        output += "\n无违规条文引用。\n"

    output += f"""
---

### 💡 修改建议

{_esc(result['suggestions'])}
"""

    return output


def format_retrieved_rules(retrieved: list) -> str:
    if not retrieved:
        return "未检索到相关法规条文。"
    output = ""
    for i, rule in enumerate(retrieved, 1):
        output += f"""**{i}. 《{rule['doc_name']}》第{rule['article_number']}条** (相关度: {rule['similarity']})

> {rule['article_text']}

"""
    return output


def review_text(content: str):
    if not content or not content.strip():
        return "⚠️ 请输入待审核的营销内容。", "", gr.update(visible=False), 0

    _, agent, database = init_system()
    start_time = time.time()

    validation = security_middleware.validate_and_sanitize(content.strip())
    if not validation.is_valid:
        error_msg = f"⚠️ 输入校验失败：\n" + "\n".join(f"- {t}" for t in validation.threats)
        return error_msg, "", gr.update(visible=False), 0

    details = agent.review_with_details(validation.sanitized_input, client_id="web_user")
    latency_ms = (time.time() - start_time) * 1000

    result = details["result"]
    review_data = {
        "user_id": None,
        "input_content": validation.sanitized_input,
        "input_hash": hashlib.sha256(validation.sanitized_input.encode()).hexdigest()[:16],
        "input_length": len(validation.sanitized_input),
        "compliant": result["compliant"],
        "violation_type": result["violation_type"],
        "violated_articles": result.get("violated_articles", []),
        "confidence": result["confidence"],
        "reasoning": result["reasoning"],
        "suggestions": result["suggestions"],
        "review_mode": "rule" if config.DEMO_MODE else "llm",
        "latency_ms": latency_ms,
        "client_id": "web_user",
        "threats": validation.threats,
    }
    review_id = database.save_review(review_data)

    result_text = format_review_result(details, review_id)
    rules_text = format_retrieved_rules(details["retrieved_rules"])

    return result_text, rules_text, gr.update(visible=True), review_id


def submit_feedback(review_id: int, is_correct: bool, comment: str):
    _, _, database = init_system()
    if not review_id or review_id <= 0:
        return "⚠️ 无有效审核ID"
    try:
        database.save_feedback(review_id, is_correct, comment)
        return f"✅ 反馈已提交（审核ID: {review_id}，{'正确' if is_correct else '错误'}）"
    except Exception as e:
        return f"❌ 提交失败: {str(e)}"


def load_history(limit: int = 20, offset: int = 0):
    _, _, database = init_system()
    reviews, total = database.list_reviews(limit=limit, offset=offset)
    if not reviews:
        return "暂无审核记录", total

    output = f"**共 {total} 条审核记录**\n\n"
    output += "| ID | 输入摘要 | 结论 | 违规类型 | 置信度 | 耗时 | 时间 |\n"
    output += "|----|---------|------|---------|--------|------|------|\n"
    for r in reviews:
        compliant_icon = "✅" if r["compliant"] == "yes" else "❌" if r["compliant"] == "no" else "⚠️"
        output += f"| {r['id']} | {r['input_hash'][:8]}... | {compliant_icon} {r['compliant']} | {r['violation_type'][:15]} | {r['confidence']:.0%} | {r['latency_ms']:.0f}ms | {r['created_at'][:16]} |\n"

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

    return f"""### 📊 系统统计

| 指标 | 值 |
|------|------|
| 总审核数 | {stats['total_reviews']} |
| 违规数 | {stats['violation_reviews']} |
| 合规数 | {stats['compliant_reviews']} |
| 违规率 | {stats['violation_rate']:.1%} |
| 平均延迟 | {stats['avg_latency_ms']:.0f}ms |
| 平均置信度 | {stats['avg_confidence']:.2%} |
| 反馈总数 | {feedback['total_feedback']} |
| 反馈准确率 | {feedback['accuracy']:.1%} |
| 数据库大小 | {stats['db_size_mb']:.2f}MB |
"""


EXAMPLE_INPUTS = [
    ["这款保险产品稳赚不赔，年化收益率高达8%，保本保息，零风险！现在购买还送价值5000元的黄金大礼包！", "❌ 典型违规"],
    ["本产品由XX保险公司承保，保险责任包括重大疾病保障，责任免除包括投保前已患疾病，犹豫期为15天，退保可能产生损失。请仔细阅读保险条款。", "✅ 合规案例"],
    ["比银行存款利息高多了！存钱不如买保险，这款理财险收益确定，比基金还稳！", "❌ 产品混淆"],
    ["著名影星XXX倾情推荐！这款保险产品保障全面！", "❌ 无资质代言"],
    ["限时特惠！今天购买这款重疾险，还额外赠送体检套餐和旅游基金！", "❌ 诱导销售"],
]

RESPONSIVE_CSS = """
@media (max-width: 768px) {
    .gradio-container { max-width: 100% !important; padding: 8px !important; }
    .contain { flex-direction: column !important; }
    textarea { font-size: 16px !important; }
    button { min-height: 44px !important; font-size: 16px !important; }
}
@media (max-width: 480px) {
    .gradio-container { padding: 4px !important; }
    h1 { font-size: 1.5em !important; }
    .example-label { font-size: 14px !important; }
}
.feedback-row { display: flex; gap: 8px; align-items: center; }

/* Loading spinner */
.loading-overlay {
    position: relative;
    min-height: 60px;
}
.loading-overlay::after {
    content: '⏳ 审核中...';
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    font-size: 1.2em;
    color: #6366f1;
    animation: pulse 1.5s ease-in-out infinite;
}
@keyframes pulse {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
}

/* Error state */
.error-box {
    background: #fef2f2;
    border: 1px solid #fecaca;
    border-radius: 8px;
    padding: 16px;
    color: #991b1b;
}
.success-box {
    background: #f0fdf4;
    border: 1px solid #bbf7d0;
    border-radius: 8px;
    padding: 16px;
    color: #166534;
}

/* Dark mode */
@media (prefers-color-scheme: dark) {
    .gradio-container {
        background: #1a1a2e !important;
        color: #e0e0e0 !important;
    }
    .error-box {
        background: #3b1c1c;
        border-color: #7f1d1d;
        color: #fca5a5;
    }
    .success-box {
        background: #1a3a2a;
        border-color: #166534;
        color: #86efac;
    }
}

/* Dark mode toggle */
.dark .gradio-container {
    background: #1a1a2e !important;
    color: #e0e0e0 !important;
}
.dark .error-box {
    background: #3b1c1c;
    border-color: #7f1d1d;
    color: #fca5a5;
}
.dark .success-box {
    background: #1a3a2a;
    border-color: #166534;
    color: #86efac;
}

/* Keyboard shortcut hint */
.kbd-hint {
    display: inline-block;
    padding: 2px 6px;
    font-size: 11px;
    font-family: monospace;
    color: #555;
    background: #f5f5f5;
    border: 1px solid #ccc;
    border-radius: 3px;
}
"""


def create_app():
    with gr.Blocks(
        title="保险营销内容智能审核系统",
        css=RESPONSIVE_CSS,
        theme=gr.themes.Soft(),
    ) as app:
        gr.HTML("""
        <div style="text-align: center; padding: 16px 0;">
            <h1 style="margin:0; font-size: 1.8em;">🛡️ 保险营销内容智能审核系统</h1>
            <p style="color: #666; margin: 4px 0;">基于大模型 + RAG 的金融营销内容合规审核 · 生产级架构</p>
            <p style="color: #999; font-size: 12px;">
                <span class="kbd-hint">Ctrl+Enter</span> 提交审核 |
                <span class="kbd-hint">Ctrl+L</span> 清空输入 |
                <span class="kbd-hint">Ctrl+D</span> 切换暗色模式
            </p>
        </div>
        <script>
        document.addEventListener('keydown', function(e) {
            if (e.ctrlKey && e.key === 'Enter') {
                var btn = document.querySelector('button[variant="primary"]');
                if (btn) { btn.click(); e.preventDefault(); }
            }
            if (e.ctrlKey && e.key === 'l') {
                var ta = document.querySelector('textarea');
                if (ta) { ta.value = ''; ta.dispatchEvent(new Event('input')); e.preventDefault(); }
            }
            if (e.ctrlKey && e.key === 'd') {
                document.body.classList.toggle('dark');
                e.preventDefault();
            }
        });
        </script>
        """)

        with gr.Tabs():
            with gr.TabItem("📝 文本审核"):
                with gr.Row():
                    with gr.Column(scale=1, min_width=300):
                        text_input = gr.Textbox(
                            label="待审核的营销文本",
                            placeholder="请输入保险营销内容，系统将自动进行合规审核...",
                            lines=6,
                            max_lines=20,
                        )
                        text_review_btn = gr.Button("🔍 开始审核", variant="primary", size="lg")

                        gr.Markdown("### 📌 示例输入")
                        for example_text, example_desc in EXAMPLE_INPUTS:
                            gr.Examples(
                                examples=[[example_text]],
                                inputs=[text_input],
                                label=example_desc,
                            )

                    with gr.Column(scale=1, min_width=300):
                        text_result = gr.HTML(
                            label="审核结果",
                            value="<div style='color:#999; text-align:center; padding:40px;'>审核结果将在此处显示...</div>",
                        )

                        feedback_row = gr.Row(visible=False)
                        with feedback_row:
                            review_id_state = gr.State(0)
                            gr.Markdown("**此审核结果是否正确？**")
                            fb_correct_btn = gr.Button("✅ 正确", size="sm")
                            fb_incorrect_btn = gr.Button("❌ 错误", size="sm")
                            fb_comment = gr.Textbox(placeholder="补充说明（可选）", lines=1, scale=2)
                        feedback_result = gr.Markdown("", visible=True)

                with gr.Row():
                    with gr.Column():
                        gr.Markdown("### 📚 RAG 检索到的相关法规")
                        text_rules = gr.Markdown(
                            value="相关法规条文将在此处显示...",
                        )

                text_review_btn.click(
                    fn=review_text,
                    inputs=[text_input],
                    outputs=[text_result, text_rules, feedback_row, review_id_state],
                )

                fb_correct_btn.click(
                    fn=lambda rid, cmt: submit_feedback(rid, True, cmt),
                    inputs=[review_id_state, fb_comment],
                    outputs=[feedback_result],
                )
                fb_incorrect_btn.click(
                    fn=lambda rid, cmt: submit_feedback(rid, False, cmt),
                    inputs=[review_id_state, fb_comment],
                    outputs=[feedback_result],
                )

            with gr.TabItem("🖼️ 图文审核"):
                with gr.Row():
                    with gr.Column(scale=1, min_width=300):
                        img_text_input = gr.Textbox(
                            label="营销文本内容",
                            placeholder="请输入营销文本内容...",
                            lines=4,
                        )
                        img_input = gr.File(
                            label="上传营销图片（支持多张，最多5张）",
                            file_count="multiple",
                            file_types=["image"],
                        )
                        img_review_btn = gr.Button("🔍 开始图文审核", variant="primary", size="lg")

                    with gr.Column(scale=1, min_width=300):
                        img_result = gr.HTML(
                            value="<div style='color:#999; text-align:center; padding:40px;'>审核结果将在此处显示...</div>",
                        )

                with gr.Row():
                    with gr.Column():
                        gr.Markdown("### 📚 RAG 检索到的相关法规")
                        img_rules = gr.Markdown(value="相关法规条文将在此处显示...")

                def review_image_text(content, images):
                    if not content or not content.strip():
                        return "<div style='color:#999;'>请输入内容</div>", ""
                    image_descriptions = []
                    if images:
                        for img in images[:5]:
                            if img is not None:
                                image_descriptions.append("[用户上传的图片]")
                    _, agent, _ = init_system()
                    details = agent.review_with_details(content.strip(), image_descriptions or None, client_id="web_user")
                    result_text = format_review_result(details)
                    rules_text = format_retrieved_rules(details["retrieved_rules"])
                    return result_text, rules_text

                img_review_btn.click(
                    fn=review_image_text,
                    inputs=[img_text_input, img_input],
                    outputs=[img_result, img_rules],
                )

            with gr.TabItem("📋 审核历史"):
                with gr.Row():
                    history_limit = gr.Slider(10, 100, value=20, step=10, label="显示条数")
                    refresh_btn = gr.Button("🔄 刷新", variant="secondary")
                    export_btn = gr.Button("📥 导出JSON", variant="secondary")

                history_output = gr.Markdown(value="点击刷新加载审核历史...")
                export_file = gr.File(label="导出文件", visible=False)

                refresh_btn.click(
                    fn=lambda limit: load_history(int(limit))[0],
                    inputs=[history_limit],
                    outputs=[history_output],
                )
                export_btn.click(
                    fn=export_reviews,
                    outputs=[export_file],
                )

            with gr.TabItem("📊 效果评估"):
                with gr.Row():
                    eval_btn = gr.Button("🚀 运行标准评估", variant="primary", size="lg")
                    extreme_eval_btn = gr.Button("🔥 运行极端用例测试", variant="secondary", size="lg")

                eval_result = gr.Markdown(value="点击按钮运行评估...")

                def run_evaluation():
                    from src.evaluator import Evaluator
                    _, agent, _ = init_system()
                    evaluator = Evaluator(agent)
                    report = evaluator.evaluate_all()
                    return f"""### 📊 评估报告

| 指标 | 值 |
|------|------|
| 总测试用例 | {report['total_cases']} |
| 合规判断准确率 | {report['compliant_accuracy']:.2%} |
| 违规类型匹配率 | {report['violation_type_accuracy']:.2%} |
| 精确率 | {report['precision']:.2%} |
| 召回率 | {report['recall']:.2%} |
| F1分数 | {report['f1_score']:.4f} |
| 平均置信度 | {report['avg_confidence']:.4f} |
"""

                def run_extreme_tests():
                    from src.evaluator import Evaluator
                    _, agent, _ = init_system()
                    evaluator = Evaluator(agent)
                    tc_path = os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), "eval", "extreme_test_cases.json"
                    )
                    report = evaluator.evaluate_all(tc_path)
                    blocked = sum(1 for d in report["details"] if d["predicted_compliant"] == "unknown")
                    return f"""### 🔥 极端用例测试报告

| 指标 | 值 |
|------|------|
| 总测试用例 | {report['total_cases']} |
| 安全攻击拦截数 | {blocked} |
| 合规判断准确率 | {report['compliant_accuracy']:.2%} |
| 平均置信度 | {report['avg_confidence']:.4f} |

**安全拦截率**: {blocked}/{report['total_cases']} = {blocked/report['total_cases']:.1%}
"""

                eval_btn.click(fn=run_evaluation, outputs=[eval_result])
                extreme_eval_btn.click(fn=run_extreme_tests, outputs=[eval_result])

            with gr.TabItem("⚙️ 系统管理"):
                stats_output = gr.Markdown()
                stats_btn = gr.Button("📊 查看系统统计", variant="primary")
                stats_btn.click(fn=get_system_stats, outputs=[stats_output])

                gr.Markdown("---")
                gr.Markdown("### 🗄️ 数据库管理")
                with gr.Row():
                    backup_btn = gr.Button("💾 手动备份", variant="secondary")
                    cleanup_btn = gr.Button("🧹 清理过期数据", variant="secondary")
                db_action_result = gr.Markdown()

                def do_backup():
                    _, _, database = init_system()
                    path = database.backup()
                    return f"✅ 备份完成: {path}"

                def do_cleanup():
                    _, _, database = init_system()
                    stats = database.cleanup_expired_data()
                    return f"✅ 清理完成: {stats}"

                backup_btn.click(fn=do_backup, outputs=[db_action_result])
                cleanup_btn.click(fn=do_cleanup, outputs=[db_action_result])

            with gr.TabItem("📖 系统说明"):
                gr.Markdown("""
## 🏗️ 生产级架构

### 技术栈
| 层次 | 技术 |
|------|------|
| 前端 | Gradio (响应式+暗色模式+快捷键) |
| API | FastAPI + Uvicorn |
| 认证 | API Key + RBAC (90天过期) |
| 数据库 | SQLite (WAL模式) |
| 向量库 | ChromaDB |
| LLM | 百炼 qwen-plus |
| Embedding | text-embedding-v3 |
| 监控 | Prometheus + AlertManager |
| 异步 | ThreadPoolExecutor + Semaphore |

### 安全防护
- 7层纵深防御：WAF → 网关 → 限流 → 输入校验 → Prompt注入检测 → LLM安全Prompt → 输出校验
- 17种注入模式检测（中英文+Token边界）
- XSS/SQL注入/控制字符过滤
- 审计日志（JSONL格式，按日分割，HMAC签名）
- API Key 90天自动过期
- PBKDF2-HMAC-SHA256 密码哈希

### 鲁棒性
- 熔断器：三态模型 (Closed/Open/Half-Open)
- 重试：指数退避+随机抖动
- 降级：LLM→规则引擎，向量→关键词
- 缓存：LRU+TTL (可配置)
- 并发控制：Semaphore (可配置)

### 可观测性
- Prometheus 指标：审核总数/延迟/缓存/安全拦截/熔断状态
- OpenTelemetry 风格 Trace：rag_retrieve/llm_call/review 全链路追踪
- AlertManager：熔断/缓存命中率/队列容量告警
- HealthCheck：数据库/RAG/熔断器/任务队列健康检查

### 数据管理
- 审核结果持久化（SQLite+事务）
- 法规版本管理
- 用户反馈闭环
- 自动备份+数据清理
- 软删除+硬删除

### API端点
| 端点 | 方法 | 说明 |
|------|------|------|
| /health | GET | 健康检查 |
| /ready | GET | 就绪检查 |
| /metrics | GET | Prometheus指标 |
| /api/v1/health/detail | GET | 详细健康检查 |
| /api/v1/alerts | GET | 活跃告警 |
| /api/v1/review | POST | 单条审核 |
| /api/v1/review/async | POST | 异步审核 |
| /api/v1/review/batch | POST | 批量审核 |
| /api/v1/task/{task_id} | GET | 异步任务状态 |
| /api/v1/task/stats | GET | 任务队列统计 |
| /api/v1/feedback | POST | 提交反馈 |
| /api/v1/reviews | GET | 审核历史 |
| /api/v1/stats | GET | 系统统计 |
| /api/v1/backup | POST | 手动备份 |
| /api/v1/cleanup | POST | 数据清理 |
| /api/v1/regulations/reindex | POST | 重建索引 |
""")

        gr.HTML("""
        <div style="text-align: center; padding: 12px 0; color: #999; font-size: 11px;">
            保险营销内容智能审核系统 v2.0 · 生产级架构 · 百炼大模型API + RAG
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
