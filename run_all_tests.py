import sys
import os
import json
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import config
config.load_user_config()

from src.review_agent import ReviewAgent, WorkflowState
from src.rag_engine import RAGEngine
from src.resilience import review_cache

rag_engine = RAGEngine()
rag_engine.build_index()
review_cache.clear()
agent = ReviewAgent(rag_engine=rag_engine)

test_cases = [
    {
        "id": "T01", "name": "短文字-明显违规",
        "text": "稳赚不赔！年化收益5%！零风险投资！保本保息！立即购买，名额有限！",
        "images": [],
        "expect": "不合规，应检测到收益承诺、绝对化用语等违规",
    },
    {
        "id": "T02", "name": "短文字-合规",
        "text": "本产品为分红型保险，过往分红水平不代表未来收益。投资须谨慎，请仔细阅读保险条款，了解保险责任和免责条款。",
        "images": [],
        "expect": "合规",
    },
    {
        "id": "T03", "name": "短文字-语义隐含违规",
        "text": "未来稳稳的幸福，财富安心增长，比银行存款更划算！",
        "images": [],
        "expect": "不合规，应检测到隐含的收益承诺和产品混淆",
    },
    {
        "id": "T04", "name": "短文字-诱导销售",
        "text": "明星倾情推荐！即送大礼包，前100名再送旅游基金和返现红包！",
        "images": [],
        "expect": "不合规，应检测到诱导销售和无资质代言",
    },
    {
        "id": "T05", "name": "长文字-多段违规",
        "text": """【限时特惠】XX终身寿险（分红型）—— 您的财富守护者！

一、产品亮点
零风险稳赚不赔！年化收益高达5%，远超银行存款利率！
保本保息，本金绝对安全，收益写进合同！

二、明星推荐
著名影视明星张XX倾情推荐："我自己也买了这款保险，放心！"
前100名下单即送价值5000元大礼包+旅游基金！

三、产品对比
比银行定期收益高3倍！相当于存银行但收益翻倍！
基金定投的收益，存款的安全性，保险的保障性——三合一！

四、限时优惠
仅限今日！名额有限，先到先得！
扫码立即抢购，错过再等一年！

五、收益演示
投入10万，首年即返5000元，年年递增！
分红按历史最高水平演示：第10年账户价值可达15万！

六、投保须知
无需健康告知！无需体检！任何人都能买！
犹豫期可全额退保，零风险尝试！

七、公司背书
世界500强企业承保，国家兜底，绝对安全！
偿付能力充足率300%，远超监管要求！""",
        "images": [],
        "expect": "不合规，应检测到收益承诺、绝对化用语、诱导销售、无资质代言、产品混淆、隐瞒信息、风险提示不足等多种违规",
    },
    {
        "id": "T06", "name": "图片1-8KB小图(纯图片)",
        "text": "", "images": ["data/保险营销文案图片.png"],
        "expect": "应提取图片中的文字并审核",
    },
    {
        "id": "T07", "name": "图片2-海报(纯图片)",
        "text": "", "images": ["data/保险营销海报.jpeg"],
        "expect": "应提取图片中的文字并审核",
    },
    {
        "id": "T08", "name": "图片3-红包海报(纯图片)",
        "text": "", "images": ["data/保险营销海报红包.jpeg"],
        "expect": "应提取图片中的文字并审核",
    },
    {
        "id": "T09", "name": "图片1+违规文字",
        "text": "稳赚不赔！年化收益5%！比存款更划算！",
        "images": ["data/保险营销文案图片.png"],
        "expect": "不合规，图片+文字双重违规",
    },
    {
        "id": "T10", "name": "图片2+合规文字",
        "text": "本产品为分红型保险，过往分红水平不代表未来收益。投资须谨慎，请仔细阅读保险条款。",
        "images": ["data/保险营销海报.jpeg"],
        "expect": "图片本身可能有违规，但文字合规",
    },
    {
        "id": "T11", "name": "图片3+诱导文字",
        "text": "现在购买即送大礼包！返现红包等你拿！",
        "images": ["data/保险营销海报红包.jpeg"],
        "expect": "不合规，图片+文字双重违规",
    },
]

results_doc = []
results_doc.append("# 保险营销内容合规审核系统 - 测试结果记录")
results_doc.append(f"\n测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
results_doc.append(f"模型: {config.LLM_MODEL}")
results_doc.append(f"后备模型: {config.LLM_FALLBACK_MODEL}")
results_doc.append(f"Reranker: {config.RERANKER_MODEL}")
results_doc.append(f"API Key: {'有' if config.has_api_key() else '无'}")
results_doc.append(f"RAG chunks: {len(rag_engine.chunks)}")
results_doc.append("")

for tc in test_cases:
    header = f"## {tc['id']}: {tc['name']}"
    results_doc.append(header)
    results_doc.append(f"**输入文字**: {tc['text'][:100]}{'...' if len(tc['text'])>100 else ''}")
    results_doc.append(f"**输入图片**: {tc['images'] if tc['images'] else '无'}")
    results_doc.append(f"**预期结果**: {tc['expect']}")
    results_doc.append("")

    # Check images exist
    for img in tc['images']:
        if os.path.exists(img):
            from PIL import Image
            im = Image.open(img)
            results_doc.append(f"图片 `{img}`: {os.path.getsize(img)} bytes, {im.size[0]}x{im.size[1]}px, {im.mode}")
        else:
            results_doc.append(f"图片 `{img}`: **不存在！**")

    results_doc.append("")
    results_doc.append("### 各步骤详细输出")
    results_doc.append("")

    t0 = time.time()
    try:
        result = agent.review(
            content=tc["text"],
            image_paths=tc["images"],
        )
        elapsed = time.time() - t0
        meta = result.metadata if hasattr(result, 'metadata') and result.metadata else {}

        # Step 1: Extract
        results_doc.append("#### Step 1: Extract (信息提取)")
        results_doc.append(f"- keywords: `{meta.get('keywords', [])}`")
        results_doc.append(f"- has_risk_disclosure: `{meta.get('has_risk_disclosure', 'N/A')}`")
        results_doc.append(f"- has_return_promise: `{meta.get('has_return_promise', 'N/A')}`")
        results_doc.append(f"- has_absolute_language: `{meta.get('has_absolute_language', 'N/A')}`")
        it = meta.get('image_text', '')
        idesc = meta.get('image_description', '')
        results_doc.append(f"- image_text: `{it}`")
        results_doc.append(f"- image_description: `{idesc}`")
        eff = meta.get('effective_text', '')
        results_doc.append(f"- effective_text: `{eff[:300]}{'...' if len(eff)>300 else ''}`")
        results_doc.append("")

        # Step 2: RuleCheck
        results_doc.append("#### Step 2: RuleCheck (规则引擎预检)")
        rc = meta.get('rule_check_result', {})
        if rc:
            results_doc.append(f"- hit: `{rc.get('hit', False)}`")
            results_doc.append(f"- violation_type: `{rc.get('violation_type', '')}`")
            results_doc.append(f"- matched_keywords: `{rc.get('matched_keywords', [])}`")
            va = rc.get('violated_articles', [])
            if va:
                results_doc.append(f"- violated_articles ({len(va)}条):")
                for a in va[:5]:
                    results_doc.append(f"  - 《{a.get('doc_name','')}》第{a.get('article_number','')}条")
            else:
                results_doc.append("- violated_articles: 无")
        else:
            results_doc.append("- 规则引擎结果: N/A")
        results_doc.append("")

        # Step 3-5: RAG + Rerank + Expand
        results_doc.append("#### Step 3: RAGRetrieve (法规检索)")
        retrieved = meta.get('rag_results', [])
        if retrieved:
            results_doc.append(f"- 检索到 {len(retrieved)} 条相关法规")
            for i, r in enumerate(retrieved[:3]):
                results_doc.append(f"  - [{i+1}] 《{r.get('doc_name','')}》第{r.get('article_number','')}条 (相关度: {r.get('similarity','')})")
        else:
            results_doc.append("- 检索结果: N/A (metadata中未存储)")
        results_doc.append("")

        results_doc.append("#### Step 4: Rerank (重排序)")
        reranked = meta.get('reranked_laws', [])
        if reranked:
            results_doc.append(f"- 重排序后保留 {len(reranked)} 条")
            for i, r in enumerate(reranked[:3]):
                results_doc.append(f"  - [{i+1}] 《{r.get('doc_name','')}》第{r.get('article_number','')}条 (相关度: {r.get('relevance_score','')})")
        else:
            results_doc.append("- 重排序结果: 无")
        results_doc.append("")

        results_doc.append("#### Step 5: ExpandRelations (条款关联扩展)")
        er = meta.get('expanded_relations', [])
        if er:
            results_doc.append(f"- 扩展了 {len(er)} 条关联条款")
            for r in er[:3]:
                results_doc.append(f"  - 《{r.get('from_doc','')}》第{r.get('from_article','')}条 → 《{r.get('to_doc','')}》第{r.get('to_article','')}条 ({r.get('relation_type','')})")
        else:
            results_doc.append("- 关联扩展: 无")
        results_doc.append("")

        # Step 6: LLMReason
        results_doc.append("#### Step 6: LLMReason (LLM推理)")
        lr = meta.get('reasoning_result', {})
        if lr:
            results_doc.append(f"- compliant: `{lr.get('compliant', 'N/A')}`")
            results_doc.append(f"- confidence: `{lr.get('confidence', 'N/A')}`")
            violations = lr.get('violations', [])
            if violations:
                results_doc.append(f"- violations ({len(violations)}种):")
                for v in violations:
                    vtype = v.get('violation_type_name', '')
                    articles = v.get('violated_articles', [])
                    results_doc.append(f"  - {vtype}: {len(articles)}条引用")
                    for a in articles[:3]:
                        snip = a.get('article_snippet', '')
                        results_doc.append(f"    - 《{a.get('doc_name','')}》第{a.get('article_number','')}条 snippet=`{snip[:50]}`")
            else:
                results_doc.append("- violations: 无")
        else:
            results_doc.append("- LLM推理结果: N/A")
        results_doc.append("")

        # Step 7: Format
        results_doc.append("#### Step 7: Format (结构化归一化)")
        results_doc.append("- 格式化结果已合并到最终结果中")
        results_doc.append("")

        # Step 8: Validate
        results_doc.append("#### Step 8: Validate (幻觉检测与条文验证)")
        halluc_count = sum(1 for a in result.violated_articles if a.get('hallucination_detected'))
        verified_count = sum(1 for a in result.violated_articles if a.get('article_text'))
        results_doc.append(f"- 幻觉条文数: {halluc_count}")
        results_doc.append(f"- 验证通过条文数: {verified_count}")
        results_doc.append("")

        # Step 9: CrossCheck
        results_doc.append("#### Step 9: CrossCheck (交叉复核)")
        results_doc.append(f"- crosscheck_passed: `{result.crosscheck_passed}`")
        cc = meta.get('crosscheck_result', {})
        if cc:
            results_doc.append(f"- passed: `{cc.get('passed', 'N/A')}`")
            issues = cc.get('issues', [])
            if issues:
                results_doc.append(f"- issues ({len(issues)}条):")
                for iss in issues[:3]:
                    results_doc.append(f"  - {iss[:100]}")
            else:
                results_doc.append("- issues: 无")
            results_doc.append(f"- confidence_adjustment: `{cc.get('confidence_adjustment', 0)}`")
            results_doc.append(f"- recommend_human_review: `{cc.get('recommend_human_review', False)}`")
        else:
            results_doc.append("- CrossCheck详细结果: N/A")
        results_doc.append("")

        # Step 10: RiskAssess
        results_doc.append("#### Step 10: RiskAssess (风险评估)")
        results_doc.append(f"- risk_level: `{result.risk_level}`")
        results_doc.append(f"- risk_score: `{result.risk_score}`")
        results_doc.append(f"- decision: `{result.decision}`")
        results_doc.append("")

        # Final result
        results_doc.append("### 最终结果")
        results_doc.append(f"- **合规**: `{result.compliant}`")
        results_doc.append(f"- **违规类型**: `{result.violation_type}`")
        results_doc.append(f"- **置信度**: `{result.confidence}`")
        results_doc.append(f"- **风险**: `{result.risk_level}/{result.risk_score}`")
        results_doc.append(f"- **决策**: `{result.decision}`")
        results_doc.append(f"- **审核模式**: `{meta.get('review_mode', 'N/A')}`")
        results_doc.append(f"- **使用模型**: `{meta.get('model_used', 'N/A')}`")
        results_doc.append(f"- **总耗时**: `{elapsed:.1f}s`")

        if result.violated_articles:
            results_doc.append(f"\n**违规条文** ({len(result.violated_articles)}条):")
            results_doc.append("")
            results_doc.append("| 法规 | 条款 | snippet | full_text |")
            results_doc.append("|------|------|---------|-----------|")
            for a in result.violated_articles:
                snip = a.get('article_snippet', '')
                ft = a.get('article_text', '')
                snip_display = snip[:40] + '...' if len(snip) > 40 else snip
                ft_display = '✅' if ft else '❌'
                snip_display = snip_display if snip else '❌'
                results_doc.append(f"| {a.get('doc_name','')} | 第{a.get('article_number','')}条 | {snip_display} | {ft_display} |")

        reasoning = result.reasoning or ""
        if reasoning:
            results_doc.append(f"\n**推理过程**: {reasoning[:500]}{'...' if len(reasoning)>500 else ''}")

        results_doc.append("")
        results_doc.append("---")
        results_doc.append("")

    except Exception as e:
        elapsed = time.time() - t0
        results_doc.append(f"**❌ 测试异常**: {e}")
        results_doc.append(f"```")
        results_doc.append(traceback.format_exc())
        results_doc.append(f"```")
        results_doc.append(f"耗时: {elapsed:.1f}s")
        results_doc.append("")
        results_doc.append("---")
        results_doc.append("")

output = "\n".join(results_doc)
with open("test_results.md", "w", encoding="utf-8") as f:
    f.write(output)
print(output)
print("\n\n结果已保存到 test_results.md")
