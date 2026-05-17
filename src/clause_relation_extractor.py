import re
import logging

logger = logging.getLogger(__name__)

REFERENCE_PATTERNS = [
    (r'依照第([一二三四五六七八九十百零〇]+)条', 'references'),
    (r'适用第([一二三四五六七八九十百零〇]+)条', 'references'),
    (r'参照第([一二三四五六七八九十百零〇]+)条', 'references'),
    (r'按照第([一二三四五六七八九十百零〇]+)条', 'references'),
    (r'违反[^。]*第([一二三四五六七八九十百零〇]+)条', 'consequence'),
]

EXCEPTION_PATTERNS = [
    (r'除[^。]{0,50}外[,，]', 'exception'),
    (r'但[^。]{0,80}除外', 'exception'),
    (r'另有规定的(?:除外|从其规定)', 'exception'),
]

DEFINITION_PATTERNS = [
    (r'本办法所称(.+?)(?:是指|包括)', 'definition'),
]

APPLICABILITY_PATTERNS = [
    (r'参照本办法(?:相关规定)?执行', 'applicability'),
    (r'不适用本办法', 'applicability'),
]

SUPPLEMENT_PATTERNS = [
    (r'还应当', 'supplement'),
    (r'同时遵守', 'supplement'),
]

CN_NUM = {
    '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
    '十一': 11, '十二': 12, '十三': 13, '十四': 14, '十五': 15,
    '十六': 16, '十七': 17, '十八': 18, '十九': 19, '二十': 20,
    '二十一': 21, '二十二': 22, '二十三': 23, '二十四': 24, '二十五': 25,
    '二十六': 26, '二十七': 27, '二十八': 28, '二十九': 29, '三十': 30,
    '三十一': 31, '三十二': 32, '三十三': 33, '三十四': 34, '三十五': 35,
    '三十六': 36, '三十七': 37, '三十八': 38, '三十九': 39, '四十': 40,
    '四十一': 41, '四十二': 42, '四十三': 43, '四十四': 44, '四十五': 45,
    '四十六': 46, '四十七': 47, '四十八': 48, '四十九': 49, '五十': 50,
    '五十一': 51, '五十二': 52, '五十三': 53, '五十四': 54, '五十五': 55,
    '五十六': 56, '五十七': 57, '五十八': 58, '五十九': 59, '六十': 60,
    '六十一': 61, '六十二': 62, '六十三': 63, '六十四': 64, '六十五': 65,
    '六十六': 66, '六十七': 67, '六十八': 68, '六十九': 69, '七十': 70,
    '七十一': 71, '七十二': 72, '七十三': 73, '七十四': 74, '七十五': 75,
    '七十六': 76, '七十七': 77, '七十八': 78, '七十九': 79, '八十': 80,
    '八十一': 81, '八十二': 82, '八十三': 83,
}

def cn_to_num(cn_str):
    return CN_NUM.get(cn_str, 0)


class ClauseRelationExtractor:
    def __init__(self):
        self.relations = []

    def extract_from_documents(self, documents):
        self.relations = []
        for doc in documents:
            doc_name = doc.get('doc_name', '')
            article_number = doc.get('article_number', '')
            article_text = doc.get('article_text', '')
            if not article_text or not article_number:
                continue
            self._extract_references(doc_name, article_number, article_text)
            self._extract_exceptions(doc_name, article_number, article_text)
            self._extract_definitions(doc_name, article_number, article_text)
            self._extract_consequences(doc_name, article_number, article_text)
            self._extract_applicability(doc_name, article_number, article_text)
            self._extract_supplements(doc_name, article_number, article_text)
        return self.relations

    def _extract_references(self, doc_name, article_number, text):
        for pattern, rel_type in REFERENCE_PATTERNS:
            for match in re.finditer(pattern, text):
                target_article = match.group(1)
                evidence = match.group(0)
                self._add_relation(doc_name, article_number, doc_name, target_article, rel_type, 1.0, evidence, 'regex')

    def _extract_exceptions(self, doc_name, article_number, text):
        for pattern, rel_type in EXCEPTION_PATTERNS:
            for match in re.finditer(pattern, text):
                evidence = match.group(0)
                self._add_relation(doc_name, article_number, doc_name, article_number, rel_type, 0.8, evidence, 'regex')

    def _extract_definitions(self, doc_name, article_number, text):
        for pattern, rel_type in DEFINITION_PATTERNS:
            for match in re.finditer(pattern, text):
                term = match.group(1)
                evidence = match.group(0)
                self._add_relation(doc_name, article_number, doc_name, article_number, rel_type, 0.9, f"定义术语: {term} - {evidence}", 'regex')

    def _extract_consequences(self, doc_name, article_number, text):
        for match in re.finditer(r'违反[^。]*第([一二三四五六七八九十百零〇]+)条[^。]*的[，,]由', text):
            target_article = match.group(1)
            evidence = match.group(0)
            self._add_relation(doc_name, article_number, doc_name, target_article, 'consequence', 1.0, evidence, 'regex')

    def _extract_applicability(self, doc_name, article_number, text):
        for pattern, rel_type in APPLICABILITY_PATTERNS:
            for match in re.finditer(pattern, text):
                evidence = match.group(0)
                self._add_relation(doc_name, article_number, doc_name, article_number, rel_type, 0.7, evidence, 'regex')

    def _extract_supplements(self, doc_name, article_number, text):
        for pattern, rel_type in SUPPLEMENT_PATTERNS:
            for match in re.finditer(pattern, text):
                evidence = match.group(0)
                self._add_relation(doc_name, article_number, doc_name, article_number, rel_type, 0.7, evidence, 'regex')

    def _add_relation(self, from_doc, from_article, to_doc, to_article, relation_type, confidence, evidence, source):
        if from_doc == to_doc and from_article == to_article and relation_type == 'references':
            return
        existing = any(
            r['from_doc'] == from_doc and r['from_article'] == from_article and
            r['to_doc'] == to_doc and r['to_article'] == to_article and
            r['relation_type'] == relation_type
            for r in self.relations
        )
        if not existing:
            self.relations.append({
                'from_doc': from_doc,
                'from_article': from_article,
                'to_doc': to_doc,
                'to_article': to_article,
                'relation_type': relation_type,
                'confidence': confidence,
                'evidence_text': evidence,
                'source': source,
            })


PREDEFINED_RELATIONS = [
    {"from_doc": "保险销售行为管理办法", "from_article": "四十三", "to_doc": "保险销售行为管理办法", "to_article": "三", "relation_type": "consequence", "confidence": 1.0, "evidence_text": "违反本办法第三条、第三十九条规定的，由金融监管总局及其派出机构依照《中华人民共和国保险法》等法律法规和监管制度的相关规定处理", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "四十三", "to_doc": "保险销售行为管理办法", "to_article": "三十九", "relation_type": "consequence", "confidence": 1.0, "evidence_text": "违反本办法第三条、第三十九条规定的，由金融监管总局及其派出机构依照《中华人民共和国保险法》等法律法规和监管制度的相关规定处理", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "四十四", "to_doc": "保险销售行为管理办法", "to_article": "三", "relation_type": "consequence", "confidence": 1.0, "evidence_text": "保险公司、保险中介机构、保险销售人员违反本办法规定和金融监管总局关于财产保险、人身保险、保险中介销售管理的其他相关规定", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "四十六", "to_doc": "保险销售行为管理办法", "to_article": "三十六", "relation_type": "consequence", "confidence": 1.0, "evidence_text": "违反本办法第三十六条、第三十七条规定的", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "四十六", "to_doc": "保险销售行为管理办法", "to_article": "三十七", "relation_type": "consequence", "confidence": 1.0, "evidence_text": "违反本办法第三十六条、第三十七条规定的", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "十九", "to_doc": "保险销售行为管理办法", "to_article": "十九", "relation_type": "exception", "confidence": 1.0, "evidence_text": "但保险公司在经审批或者备案的费率浮动区间或者费率参数调整区间内调整价格的除外", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "二十五", "to_doc": "保险销售行为管理办法", "to_article": "二十五", "relation_type": "exception", "confidence": 0.9, "evidence_text": "经投保人同意，对于权利义务简单且投保人在三个月内再次投保同一保险公司的同一保险产品的，可以合理简化相应的提示内容", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "十四", "to_doc": "保险销售行为管理办法", "to_article": "十四", "relation_type": "exception", "confidence": 0.8, "evidence_text": "除法律法规及监管制度另有规定的外", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "二十七", "to_doc": "保险销售行为管理办法", "to_article": "二十七", "relation_type": "exception", "confidence": 0.8, "evidence_text": "法律法规另有规定的除外", "source": "manual"},
    {"from_doc": "互联网保险业务监管办法", "from_article": "五十六", "to_doc": "互联网保险业务监管办法", "to_article": "五十一", "relation_type": "references", "confidence": 1.0, "evidence_text": "参照本办法第五十一条、第五十三条规定", "source": "manual"},
    {"from_doc": "互联网保险业务监管办法", "from_article": "五十六", "to_doc": "互联网保险业务监管办法", "to_article": "五十三", "relation_type": "references", "confidence": 1.0, "evidence_text": "参照本办法第五十一条、第五十三条规定", "source": "manual"},
    {"from_doc": "互联网保险业务监管办法", "from_article": "六十九", "to_doc": "互联网保险业务监管办法", "to_article": "四十九", "relation_type": "references", "confidence": 1.0, "evidence_text": "参照本办法第四十九条", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法", "from_article": "三十三", "to_doc": "金融产品网络营销管理办法", "to_article": "八", "relation_type": "consequence", "confidence": 1.0, "evidence_text": "第三方互联网平台违反本办法第八条、第九条、第十六条第一款、第二十三条、第二十四条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法", "from_article": "三十三", "to_doc": "金融产品网络营销管理办法", "to_article": "九", "relation_type": "consequence", "confidence": 1.0, "evidence_text": "第三方互联网平台违反本办法第八条、第九条、第十六条第一款、第二十三条、第二十四条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法", "from_article": "三十三", "to_doc": "金融产品网络营销管理办法", "to_article": "十六", "relation_type": "consequence", "confidence": 1.0, "evidence_text": "第三方互联网平台违反本办法第八条、第九条、第十六条第一款、第二十三条、第二十四条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法", "from_article": "三十三", "to_doc": "金融产品网络营销管理办法", "to_article": "二十三", "relation_type": "consequence", "confidence": 1.0, "evidence_text": "第三方互联网平台违反本办法第八条、第九条、第十六条第一款、第二十三条、第二十四条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法", "from_article": "三十三", "to_doc": "金融产品网络营销管理办法", "to_article": "二十四", "relation_type": "consequence", "confidence": 1.0, "evidence_text": "第三方互联网平台违反本办法第八条、第九条、第十六条第一款、第二十三条、第二十四条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法", "from_article": "三十三", "to_doc": "金融产品网络营销管理办法", "to_article": "二十一", "relation_type": "consequence", "confidence": 1.0, "evidence_text": "第三方互联网平台违反本办法第二十一条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法", "from_article": "三十四", "to_doc": "金融产品网络营销管理办法", "to_article": "五", "relation_type": "consequence", "confidence": 1.0, "evidence_text": "违反本办法第五条、第六条、第十四条、第十七条第二和第三款、第二十二条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法", "from_article": "三十四", "to_doc": "金融产品网络营销管理办法", "to_article": "六", "relation_type": "consequence", "confidence": 1.0, "evidence_text": "违反本办法第五条、第六条、第十四条、第十七条第二和第三款、第二十二条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法", "from_article": "三十四", "to_doc": "金融产品网络营销管理办法", "to_article": "十四", "relation_type": "consequence", "confidence": 1.0, "evidence_text": "违反本办法第五条、第六条、第十四条、第十七条第二和第三款、第二十二条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法", "from_article": "三十四", "to_doc": "金融产品网络营销管理办法", "to_article": "十七", "relation_type": "consequence", "confidence": 1.0, "evidence_text": "违反本办法第五条、第六条、第十四条、第十七条第二和第三款、第二十二条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法", "from_article": "三十四", "to_doc": "金融产品网络营销管理办法", "to_article": "二十二", "relation_type": "consequence", "confidence": 1.0, "evidence_text": "违反本办法第五条、第六条、第十四条、第十七条第二和第三款、第二十二条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法", "from_article": "三", "to_doc": "金融产品网络营销管理办法", "to_article": "九", "relation_type": "definition", "confidence": 0.9, "evidence_text": "本办法所称金融产品，是指金融机构设计、开发、销售的产品和服务，包括但不限于存款、贷款、资产管理产品、保险、支付、贵金属等", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法", "from_article": "二", "to_doc": "金融产品网络营销管理办法", "to_article": "二", "relation_type": "exception", "confidence": 0.8, "evidence_text": "法律法规、规章和规范性文件对金融产品网络营销另有规定的，从其规定", "source": "manual"},
]


def populate_predefined_relations(database):
    count = 0
    for rel in PREDEFINED_RELATIONS:
        success = database.save_clause_relation(
            from_doc=rel['from_doc'],
            from_article=rel['from_article'],
            to_doc=rel['to_doc'],
            to_article=rel['to_article'],
            relation_type=rel['relation_type'],
            confidence=rel['confidence'],
            evidence_text=rel['evidence_text'],
            source=rel['source'],
        )
        if success:
            count += 1
    logger.info(f"已预填充 {count} 条条款关系数据")
    return count
