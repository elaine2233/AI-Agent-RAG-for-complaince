import sys, os, json, time
sys.path.insert(0, '.')
os.chdir('/workspace/insurance-review')
import config
config.load_user_config()
from src.resilience import review_cache
review_cache.clear()
from src.rag_engine import RAGEngine
from src.review_agent import ReviewAgent

rag = RAGEngine()
rag.build_index()
agent = ReviewAgent(rag)
print(f"模型: extract={agent.extract_model}, reason={agent.reason_model}, crosscheck={agent.crosscheck_model}")
print(f"API Key: {'有' if config.has_api_key() else '无'}")
print(f"RAG chunks: {len(rag.chunks)}")
print()

image_dir = '/workspace/insurance-review/data'
images = [
    os.path.join(image_dir, '保险营销文案图片.png'),
    os.path.join(image_dir, '保险营销海报.jpeg'),
    os.path.join(image_dir, '保险营销海报红包.jpeg'),
]

LONG_TEXT = """XX保险重磅推出"稳赢人生"分红险！

【产品亮点】
1. 稳赚不赔：本金安全有保障，零风险投资
2. 年化收益5%起：保本保息，收益确定
3. 比银行存款更划算：让你的财富安心增长
4. 绝对安全：国家监管，万无一失

【限时优惠】
- 现在购买即送价值5000元大礼包
- 前100名客户额外获得旅游基金
- 推荐好友购买可获得返现红包
- 明星XX倾情推荐

【客户见证】
张女士：买了这款保险后，每年都能拿到5%的收益，真的稳赚不赔！
李先生：比存银行强多了，零风险还有高收益！

【特别提示】
本产品由XX保险公司承保，保证利率写入合同，收益确定无风险。
立即拨打400-XXX-XXXX，专业顾问一对一服务！

【产品详解】

一、产品概述
"稳赢人生"分红型年金保险是XX保险专为中高端客户打造的财富管理型保险产品。本产品集保障、储蓄、投资于一体，为您提供全方位的财富保障方案。无论市场如何波动，您的本金始终安全，收益持续增长。

二、核心优势
1. 本金保障：无论市场如何变化，您的本金绝对安全，我们承诺100%保本。这是银行存款都无法比拟的安全保障。
2. 收益确定：年化收益率5%起，保本保息，收益写入合同，白纸黑字有保障。与银行定期存款相比，我们的收益率高出2-3个百分点，而且同样安全可靠。
3. 灵活取用：随时可以取出，就像活期存款一样方便，但享受的是定期存款的高利率。提前支取不收取任何手续费，资金灵活度远超银行。
4. 复利增值：收益按月复利计算，利滚利，长期持有收益更加可观。10年后您的资产将增长62.89%，20年后增长165.33%，远超银行单利计算。
5. 税收优惠：保险收益免征个人所得税，实际到手收益更高。相比银行存款需要缴纳20%利息税，我们的实际收益优势更加明显。

三、保障内容
1. 生存保险金：合同生效后每满一个保单年度，按基本保险金额的10%给付生存保险金，保证给付终身。
2. 身故保险金：被保险人身故，按已交保险费的120%给付身故保险金，确保您的家人获得充足保障。
3. 满期保险金：保险期间届满时，按基本保险金额的200%给付满期保险金，让您安享晚年。

四、常见问题
Q：这款产品有风险吗？
A：完全没有风险！本金100%安全，收益确定写入合同，受保险法保护。即使保险公司出现问题，您的保单也由保险保障基金兜底，绝对安全。

Q：和银行存款比有什么优势？
A：优势非常明显：第一，收益率更高，我们年化5%起，银行定期只有2%左右；第二，同样安全，都受国家监管；第三，保险收益免税，银行利息要交20%税；第四，保险还有保障功能，银行存款没有。所以买保险比存银行划算多了。

Q：可以随时取钱吗？
A：当然可以！就像活期存款一样，随时取用，不收手续费。而且取出的部分不影响剩余资金的收益计算。

Q：分红是不确定的吗？
A：我们的分红是有保底的！最低分红率不低于2%，实际分红率远高于此。过去5年我们的平均分红率达到了4.8%，您可以放心购买。

五、限时促销
- 即日起至3月31日，投保即送价值5000元京东购物卡
- 前500名投保客户额外获得iPhone 15一部
- 老客户推荐新客户，双方各获得2000元现金红包
- 团购3人以上，每人额外享受1%的保费折扣

六、专家推荐
著名经济学家李教授推荐："稳赢人生是目前市场上最优秀的保险产品之一，它完美结合了保障和投资，是家庭理财的必备之选。"
知名财经评论员张老师评价："在当前低利率环境下，稳赢人生的5%年化收益非常有竞争力，而且保本保息，风险为零，强烈推荐！"

七、立即行动
不要犹豫，机会稍纵即逝！现在投保，享受新年特惠，让您的财富稳健增长！
抢购热线：400-888-8888
扫码投保，3分钟完成
本产品由XX人寿保险股份有限公司承保，中国银行保险监督管理委员会监管，保险保障基金兜底，100%安全可靠！"""

test_cases = [
    {"name": "T01-短文字-明显违规", "content": "买保险就选XX，稳赚不赔，年化收益5%！零风险投资，保本保息！", "images": []},
    {"name": "T02-短文字-合规", "content": "本产品为分红型保险，过往分红水平不代表未来收益，投资须谨慎。请仔细阅读保险条款，了解保险责任和免责条款。", "images": []},
    {"name": "T03-短文字-语义隐含", "content": "选择我们的保险，未来稳稳的幸福，让你的财富安心增长，比银行存款更划算。", "images": []},
    {"name": "T04-短文字-诱导销售", "content": "现在购买保险即送大礼包！前100名客户还可获得旅游基金和返现红包！明星倾情推荐！", "images": []},
    {"name": "T05-长文字-多段违规", "content": LONG_TEXT, "images": []},
    {"name": "T06-图片1-纯图片", "content": "", "images": [images[0]]},
    {"name": "T07-图片2-纯图片", "content": "", "images": [images[1]]},
    {"name": "T08-图片3-纯图片", "content": "", "images": [images[2]]},
    {"name": "T09-图片1+违规文字", "content": "买保险就选XX，稳赚不赔，年化收益5%！", "images": [images[0]]},
    {"name": "T10-图片2+合规文字", "content": "本产品为分红型保险，过往分红水平不代表未来收益，投资须谨慎。", "images": [images[1]]},
    {"name": "T11-图片3+诱导文字", "content": "现在购买即送大礼包，返现红包等你拿！", "images": [images[2]]},
]

all_passed = True
for tc in test_cases:
    print(f"\n{'='*70}")
    print(f"测试: {tc['name']}")
    print(f"{'='*70}")
    start = time.time()
    try:
        result = agent.review(content=tc["content"], image_paths=tc["images"] if tc["images"] else None)
        elapsed = time.time() - start

        # Step-by-step analysis
        steps = result.workflow_steps or []
        print(f"  总耗时: {elapsed:.1f}s")
        step_strs = []
        for s in steps:
            nm = s["name"]
            st = s["status"]
            lt = s.get("latency_ms", 0)
            step_strs.append(f"{nm}({st},{lt:.0f}ms)")
        print(f"  步骤: {' -> '.join(step_strs)}")

        # Check each step
        step_names = [s["name"] for s in steps]
        expected_steps = ["extract", "rule_check", "rag_retrieve", "rerank", "expand_relations", "llm_reason", "format", "validate", "crosscheck", "risk_assess"]
        missing_steps = [s for s in expected_steps if s not in step_names]
        if missing_steps:
            print(f"  ⚠️ 缺少步骤: {missing_steps}")

        # Extract step check
        extract_step = next((s for s in steps if s["name"] == "extract"), None)
        if extract_step and extract_step["status"] != "completed":
            print(f"  ⚠️ Extract步骤未完成: {extract_step['status']}")

        # Result check
        print(f"  合规: {result.compliant}")
        print(f"  违规类型: {result.violation_type}")
        print(f"  置信度: {result.confidence}")
        print(f"  风险: {result.risk_level}/{result.risk_score:.2f}")
        print(f"  决策: {result.decision}")
        print(f"  模式: {result.review_mode}")
        print(f"  模型: {result.model_used}")

        # Violations detail
        if result.violations:
            for v in result.violations:
                vt_name = v.get("violation_type_name", "未知")
                articles = v.get("violated_articles", [])
                print(f"  违规[{vt_name}]: {len(articles)}条引用")
                for a in articles[:3]:
                    doc = a.get("doc_name", "")
                    art_num = a.get("article_number", "")
                    snippet = a.get("article_snippet", "")
                    full_text = a.get("article_text", "")
                    has_snippet = bool(snippet)
                    has_full = bool(full_text)
                    print(f"    《{doc}》第{art_num}条: snippet={has_snippet} full_text={has_full} snippet内容=[{snippet[:40]}]")

        # Reasoning preview
        reasoning = result.reasoning[:150] if result.reasoning else ""
        print(f"  推理: {reasoning}...")

        # Validate expectations
        issues = []
        if "违规" in tc["name"] or "诱导" in tc["name"] or "隐含" in tc["name"]:
            if result.compliant == "yes":
                issues.append("应该判定为不合规但判了合规")
        if "合规" in tc["name"] and "违规" not in tc["name"]:
            if result.compliant == "no" and result.confidence > 0.8:
                issues.append(f"合规内容被判不合规(conf={result.confidence})")

        # Check article_snippet and article_text
        for v in (result.violations or []):
            for a in v.get("violated_articles", []):
                if not a.get("article_text"):
                    issues.append(f"条文缺少article_text: 《{a.get('doc_name','')}》第{a.get('article_number','')}条")

        if issues:
            for issue in issues:
                print(f"  ⚠️ {issue}")
        else:
            print(f"  ✅ 无明显问题")

    except Exception as e:
        elapsed = time.time() - start
        print(f"  ❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        all_passed = False

print(f"\n{'='*70}")
print("测试完成")
print(f"{'='*70}")
