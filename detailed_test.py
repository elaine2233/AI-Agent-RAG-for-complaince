import sys
import os
import json
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import config
config.load_user_config()

from src.review_agent import ReviewAgent
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
    },
    {
        "id": "T02", "name": "短文字-合规",
        "text": "本产品为分红型保险，过往分红水平不代表未来收益。投资须谨慎，请仔细阅读保险条款，了解保险责任和免责条款。",
        "images": [],
    },
    {
        "id": "T06", "name": "图片1-8KB小图",
        "text": "", "images": ["data/保险营销文案图片.png"],
    },
    {
        "id": "T07", "name": "图片2-海报",
        "text": "", "images": ["data/保险营销海报.jpeg"],
    },
    {
        "id": "T08", "name": "图片3-海报红包",
        "text": "", "images": ["data/保险营销海报红包.jpeg"],
    },
    {
        "id": "T09", "name": "图片1+违规文字",
        "text": "稳赚不赔！年化收益5%！比存款更划算！",
        "images": ["data/保险营销文案图片.png"],
    },
    {
        "id": "T10", "name": "图片2+合规文字",
        "text": "本产品为分红型保险，过往分红水平不代表未来收益。投资须谨慎，请仔细阅读保险条款。",
        "images": ["data/保险营销海报.jpeg"],
    },
    {
        "id": "T11", "name": "图片3+诱导文字",
        "text": "现在购买即送大礼包！返现红包等你拿！",
        "images": ["data/保险营销海报红包.jpeg"],
    },
    {
        "id": "T12", "name": "图片1+2组合",
        "text": "", "images": ["data/保险营销文案图片.png", "data/保险营销海报.jpeg"],
    },
]

for tc in test_cases:
    print(f"\n{'='*70}")
    print(f"测试: {tc['id']}-{tc['name']}")
    print(f"{'='*70}")
    print(f"输入文字: {tc['text'][:80]}{'...' if len(tc['text'])>80 else ''}")
    print(f"输入图片: {tc['images']}")

    # Check image files exist
    for img in tc['images']:
        exists = os.path.exists(img)
        size = os.path.getsize(img) if exists else 0
        print(f"  图片 {img}: exists={exists}, size={size} bytes")

    t0 = time.time()
    result = agent.review(
        content=tc["text"],
        image_paths=tc["images"],
    )
    elapsed = time.time() - t0

    meta = result.metadata if hasattr(result, 'metadata') and result.metadata else {}
    
    print(f"\n--- EXTRACT 步骤 ---")
    print(f"  keywords: {meta.get('keywords', [])}")
    print(f"  has_risk_disclosure: {meta.get('has_risk_disclosure', 'N/A')}")
    print(f"  has_return_promise: {meta.get('has_return_promise', 'N/A')}")
    print(f"  has_absolute_language: {meta.get('has_absolute_language', 'N/A')}")
    print(f"  image_text: {repr(meta.get('image_text', ''))}")
    print(f"  image_description: {repr(meta.get('image_description', ''))}")
    eff = meta.get('effective_text', '')
    print(f"  effective_text: {repr(eff)[:200]}")

    print(f"\n--- 最终结果 ---")
    print(f"  合规: {result.compliant}")
    print(f"  违规类型: {result.violation_type}")
    print(f"  置信度: {result.confidence}")
    print(f"  风险: {result.risk_level}/{result.risk_score}")
    print(f"  决策: {result.decision}")
    print(f"  模式: {meta.get('review_mode', 'N/A')}")
    print(f"  模型: {meta.get('model_used', 'N/A')}")
    print(f"  耗时: {elapsed:.1f}s")

    if result.violated_articles:
        print(f"  违规条文 ({len(result.violated_articles)}条):")
        for a in result.violated_articles[:5]:
            snip = a.get('article_snippet', '')
            ft = a.get('article_text', '')
            print(f"    《{a.get('doc_name','')}》第{a.get('article_number','')}条: snippet={bool(snip)} full_text={bool(ft)}")
            if snip:
                print(f"      snippet: {snip[:80]}")

    reasoning = result.reasoning or ""
    if reasoning:
        print(f"  推理: {reasoning[:200]}{'...' if len(reasoning)>200 else ''}")

print("\n\nDone.")
