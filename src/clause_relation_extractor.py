import re
import logging

logger = logging.getLogger(__name__)

REFERENCE_PATTERNS = [
    (r'依照第([一二三四五六七八九十百零〇]+)条', '明确引用'),
    (r'适用第([一二三四五六七八九十百零〇]+)条', '明确引用'),
    (r'参照第([一二三四五六七八九十百零〇]+)条', '明确引用'),
    (r'按照第([一二三四五六七八九十百零〇]+)条', '明确引用'),
    (r'违反[^。]*第([一二三四五六七八九十百零〇]+)条', '处罚引用'),
]

EXCEPTION_PATTERNS = [
    (r'除[^。]{0,50}外[,，]', '例外条款'),
    (r'但[^。]{0,80}除外', '例外条款'),
    (r'另有规定的(?:除外|从其规定)', '例外条款'),
]

DEFINITION_PATTERNS = [
    (r'本办法所称(.+?)(?:是指|包括)', '定义条款'),
]

APPLICABILITY_PATTERNS = [
    (r'参照本办法(?:相关规定)?执行', '适用范围'),
    (r'不适用本办法', '适用范围'),
]

SUPPLEMENT_PATTERNS = [
    (r'还应当', '补充具体化'),
    (r'同时遵守', '补充具体化'),
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
            self._add_relation(doc_name, article_number, doc_name, target_article, '处罚引用', 1.0, evidence, 'regex')

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
        if from_doc == to_doc and from_article == to_article:
            return
        if not to_article:
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
    {"from_doc": "保险销售行为管理办法", "from_article": "四十三", "to_doc": "保险销售行为管理办法", "to_article": "三", "relation_type": "处罚引用", "confidence": 1.0, "evidence_text": "违反本办法第三条、第三十九条规定的，由金融监管总局及其派出机构依照《中华人民共和国保险法》等法律法规和监管制度的相关规定处理", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "四十三", "to_doc": "保险销售行为管理办法", "to_article": "三十九", "relation_type": "处罚引用", "confidence": 1.0, "evidence_text": "违反本办法第三条、第三十九条规定的，由金融监管总局及其派出机构依照《中华人民共和国保险法》等法律法规和监管制度的相关规定处理", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "四十四", "to_doc": "保险销售行为管理办法", "to_article": "三", "relation_type": "处罚引用", "confidence": 1.0, "evidence_text": "保险公司、保险中介机构、保险销售人员违反本办法规定和金融监管总局关于财产保险、人身保险、保险中介销售管理的其他相关规定", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "四十六", "to_doc": "保险销售行为管理办法", "to_article": "三十六", "relation_type": "处罚引用", "confidence": 1.0, "evidence_text": "违反本办法第三十六条、第三十七条规定的", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "四十六", "to_doc": "保险销售行为管理办法", "to_article": "三十七", "relation_type": "处罚引用", "confidence": 1.0, "evidence_text": "违反本办法第三十六条、第三十七条规定的", "source": "manual"},
    {"from_doc": "互联网保险业务监管办法", "from_article": "五十六", "to_doc": "互联网保险业务监管办法", "to_article": "五十一", "relation_type": "明确引用", "confidence": 1.0, "evidence_text": "参照本办法第五十一条、第五十三条规定", "source": "manual"},
    {"from_doc": "互联网保险业务监管办法", "from_article": "五十六", "to_doc": "互联网保险业务监管办法", "to_article": "五十三", "relation_type": "明确引用", "confidence": 1.0, "evidence_text": "参照本办法第五十一条、第五十三条规定", "source": "manual"},
    {"from_doc": "互联网保险业务监管办法", "from_article": "六十九", "to_doc": "互联网保险业务监管办法", "to_article": "四十九", "relation_type": "明确引用", "confidence": 1.0, "evidence_text": "参照本办法第四十九条", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法（征求意见稿）", "from_article": "三十三", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "八", "relation_type": "处罚引用", "confidence": 1.0, "evidence_text": "第三方互联网平台违反本办法第八条、第九条、第十六条第一款、第二十三条、第二十四条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法（征求意见稿）", "from_article": "三十三", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "九", "relation_type": "处罚引用", "confidence": 1.0, "evidence_text": "第三方互联网平台违反本办法第八条、第九条、第十六条第一款、第二十三条、第二十四条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法（征求意见稿）", "from_article": "三十三", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "十六", "relation_type": "处罚引用", "confidence": 1.0, "evidence_text": "第三方互联网平台违反本办法第八条、第九条、第十六条第一款、第二十三条、第二十四条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法（征求意见稿）", "from_article": "三十三", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "二十三", "relation_type": "处罚引用", "confidence": 1.0, "evidence_text": "第三方互联网平台违反本办法第八条、第九条、第十六条第一款、第二十三条、第二十四条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法（征求意见稿）", "from_article": "三十三", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "二十四", "relation_type": "处罚引用", "confidence": 1.0, "evidence_text": "第三方互联网平台违反本办法第八条、第九条、第十六条第一款、第二十三条、第二十四条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法（征求意见稿）", "from_article": "三十三", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "二十一", "relation_type": "处罚引用", "confidence": 1.0, "evidence_text": "第三方互联网平台违反本办法第二十一条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法（征求意见稿）", "from_article": "三十四", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "五", "relation_type": "处罚引用", "confidence": 1.0, "evidence_text": "违反本办法第五条、第六条、第十四条、第十七条第二和第三款、第二十二条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法（征求意见稿）", "from_article": "三十四", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "六", "relation_type": "处罚引用", "confidence": 1.0, "evidence_text": "违反本办法第五条、第六条、第十四条、第十七条第二和第三款、第二十二条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法（征求意见稿）", "from_article": "三十四", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "十四", "relation_type": "处罚引用", "confidence": 1.0, "evidence_text": "违反本办法第五条、第六条、第十四条、第十七条第二和第三款、第二十二条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法（征求意见稿）", "from_article": "三十四", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "十七", "relation_type": "处罚引用", "confidence": 1.0, "evidence_text": "违反本办法第五条、第六条、第十四条、第十七条第二和第三款、第二十二条规定", "source": "manual"},
    {"from_doc": "金融产品网络营销管理办法（征求意见稿）", "from_article": "三十四", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "二十二", "relation_type": "处罚引用", "confidence": 1.0, "evidence_text": "违反本办法第五条、第六条、第十四条、第十七条第二和第三款、第二十二条规定", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "二十四", "to_doc": "互联网保险业务监管办法", "to_article": "十五", "relation_type": "明确引用", "confidence": 0.95, "evidence_text": "保险销售行为管理办法第二十四条'以互联网方式销售保险产品的'，直接指向互联网保险业务领域，互联网保险业务监管办法第十五条详细规定了互联网保险营销宣传的身份标识要求", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "十七", "to_doc": "互联网保险业务监管办法", "to_article": "十五", "relation_type": "主题重叠", "confidence": 0.95, "evidence_text": "销售行为管理办法第十七条要求销售宣传不得引用不真实不准确的数据和资料、不得进行虚假或夸大表述；互联网保险办法第十五条(四)要求不得进行不实陈述或误导性描述、不得片面或夸大宣传", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "二十三", "to_doc": "互联网保险业务监管办法", "to_article": "十七", "relation_type": "主题重叠", "confidence": 0.95, "evidence_text": "销售行为管理办法第二十三条禁止强制搭售、网页默认勾选等方式；互联网保险办法第十七条(五)禁止默认勾选、限制取消自动扣费功能等方式剥夺消费者自主选择权", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "三", "to_doc": "互联网保险业务监管办法", "to_article": "三", "relation_type": "主题重叠", "confidence": 0.9, "evidence_text": "销售行为管理办法第三条'除下列机构和人员外，其他机构和个人不得从事保险销售行为'；互联网保险办法第三条'互联网保险业务应由依法设立的保险机构开展，其他机构和个人不得开展互联网保险业务'，均确立持牌经营原则", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "二十九", "to_doc": "互联网保险业务监管办法", "to_article": "三十三", "relation_type": "明确引用", "confidence": 0.9, "evidence_text": "销售行为管理办法第二十九条'通过互联网开展保险销售的，可以通过互联网保险销售行为可回溯方式确认投保人投保意愿，并符合监管制度规定'，其中监管制度规定即指互联网保险办法第三十三条", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "七", "to_doc": "互联网保险业务监管办法", "to_article": "三十八", "relation_type": "主题重叠", "confidence": 0.9, "evidence_text": "销售行为管理办法第七条要求按合法正当必要诚信原则收集处理个人信息并防止泄露；互联网保险办法第三十八条要求收集处理使用个人信息应遵循合法正当必要原则，个人信息保护原则完全一致", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "二十一", "to_doc": "互联网保险业务监管办法", "to_article": "十七", "relation_type": "主题重叠", "confidence": 0.9, "evidence_text": "销售行为管理办法第二十一条要求了解投保人保险需求风险特征保费承担能力确定可购买产品范围；互联网保险办法第十七条要求识别消费者的保险保障需求和消费能力把合适的保险产品提供给消费者", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "二十五", "to_doc": "互联网保险业务监管办法", "to_article": "十四", "relation_type": "主题重叠", "confidence": 0.9, "evidence_text": "销售行为管理办法第二十五条要求向投保人明确提示保险合同基本内容；互联网保险办法第十四条要求在销售页面展示产品名称条款免责条款犹豫期退保损失等，规制同一披露事项", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "二十四", "to_doc": "互联网保险业务监管办法", "to_article": "十五", "relation_type": "补充具体化", "confidence": 0.9, "evidence_text": "销售行为管理办法第二十四条一般性要求互联网销售时提示机构名称；互联网保险办法第十五条(六)具体要求标明保险产品全称、承保保险公司全称以及中介机构全称，后者是前者在互联网场景的具体化", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "三十一", "to_doc": "互联网保险业务监管办法", "to_article": "三十三", "relation_type": "补充具体化", "confidence": 0.9, "evidence_text": "销售行为管理办法第三十一条规定一般性可回溯管理；互联网保险办法第三十三条专门规定互联网保险可回溯管理具体要求（销售页面内容、操作轨迹等），后者是前者在互联网场景的具体化", "source": "manual"},
    {"from_doc": "互联网保险业务监管办法", "from_article": "二十三", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "十七", "relation_type": "主题重叠", "confidence": 0.9, "evidence_text": "互联网保险办法第二十三条非保险机构不得开展互联网保险业务；网络营销办法第十七条未经批准第三方互联网平台不得介入或变相介入金融产品销售业务环节，均限制非持牌机构介入销售", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "十七", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "九", "relation_type": "主题重叠", "confidence": 0.9, "evidence_text": "销售行为管理办法第十七条不得引用不真实不准确的数据和资料；网络营销办法第九条(二)引用不真实不准确或未经核实的数据和资料，(四)夸大保险责任或产品收益，高度一致", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "二十三", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "十三", "relation_type": "主题重叠", "confidence": 0.9, "evidence_text": "销售行为管理办法第二十三条禁止网页默认勾选方式强制搭售；网络营销办法第十三条不得将组合销售金融产品的选项设定为默认或首选，规制同一类默认勾选搭售行为", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "十八", "to_doc": "互联网保险业务监管办法", "to_article": "十五", "relation_type": "主题重叠", "confidence": 0.9, "evidence_text": "销售行为管理办法第十八条保险销售人员未经授权不得发布宣传信息应事前审核授权发布；互联网保险办法第十五条(三)从业人员应在保险机构授权范围内开展互联网保险营销宣传", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "二十六", "to_doc": "互联网保险业务监管办法", "to_article": "十四", "relation_type": "主题重叠", "confidence": 0.85, "evidence_text": "销售行为管理办法第二十六条要求对免责条款以足以引起投保人注意的文字字体符号作出提示；互联网保险办法第十四条(二)要求突出提示和说明免除保险公司责任的条款", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "二十二", "to_doc": "互联网保险业务监管办法", "to_article": "十四", "relation_type": "主题重叠", "confidence": 0.85, "evidence_text": "销售行为管理办法第二十二条要求销售人身保险新型产品时提示保单利益的不确定性；互联网保险办法第十四条(三)要求投连险万能险等用不小于产品名称字号的黑体字标注保单利益具有不确定性", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "三十五", "to_doc": "互联网保险业务监管办法", "to_article": "二十", "relation_type": "主题重叠", "confidence": 0.85, "evidence_text": "销售行为管理办法第三十五条要求通过互联网电话等方式对相关保险产品业务进行回访；互联网保险办法第二十条可通过互联网电话等多种方式开展回访工作", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "四十", "to_doc": "互联网保险业务监管办法", "to_article": "二十九", "relation_type": "主题重叠", "confidence": 0.85, "evidence_text": "销售行为管理办法第四十条不得设置不合法不合理的退保阻却条件、设立便捷的退保渠道；互联网保险办法第二十九条不得隐藏相关业务办理入口不得阻碍或限制客户退保", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "四十七", "to_doc": "互联网保险业务监管办法", "to_article": "一", "relation_type": "明确引用", "confidence": 0.85, "evidence_text": "销售行为管理办法第四十七条应当符合法律法规和金融监管总局关于财产保险人身保险保险中介销售管理的其他相关规定，兜底条款指向互联网保险业务监管办法等专项规定", "source": "manual"},
    {"from_doc": "互联网保险业务监管办法", "from_article": "十五", "to_doc": "保险销售行为管理办法", "to_article": "十七", "relation_type": "明确引用", "confidence": 0.85, "evidence_text": "互联网保险办法第十五条要求保险机构开展互联网保险营销宣传活动应符合银保监会相关规定，销售行为管理办法第十七条是保险销售宣传管理的一般性规定", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "十八", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "七", "relation_type": "主题重叠", "confidence": 0.85, "evidence_text": "销售行为管理办法第十八条要求对销售人员宣传信息进行事前审核及授权发布；网络营销办法第七条要求建立内容审核机制，从业人员口径应与金融机构审核的网络营销宣传内容保持一致", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "二十四", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "二十四", "relation_type": "主题重叠", "confidence": 0.85, "evidence_text": "销售行为管理办法第二十四条以互联网方式销售保险产品的应当向对方当事人提示本机构足以识别的名称；网络营销办法第二十四条第三方互联网平台应当以清晰醒目的方式展示金融产品提供者名称或相关标识", "source": "manual"},
    {"from_doc": "互联网保险业务监管办法", "from_article": "十五", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "二十四", "relation_type": "主题重叠", "confidence": 0.85, "evidence_text": "互联网保险办法第十五条(六)标明保险产品全称承保保险公司全称以及中介机构全称；网络营销办法第二十四条以清晰醒目的方式展示金融产品提供者名称或相关标识", "source": "manual"},
    {"from_doc": "互联网保险业务监管办法", "from_article": "六十五", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "十七", "relation_type": "补充具体化", "confidence": 0.85, "evidence_text": "互联网保险办法第六十五条规定互联网企业代理保险业务需获得经营保险代理业务许可；网络营销办法第十七条进一步明确第三方互联网平台不得介入销售业务环节，互补规制", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "九", "to_doc": "互联网保险业务监管办法", "to_article": "三十四", "relation_type": "主题重叠", "confidence": 0.8, "evidence_text": "销售行为管理办法第九条要求在相关协议中确定合作范围明确双方权利义务；互联网保险办法第三十四条要求签订合作或委托协议确定合作和委托范围明确双方权利义务", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "三十二", "to_doc": "互联网保险业务监管办法", "to_article": "四十", "relation_type": "主题重叠", "confidence": 0.8, "evidence_text": "销售行为管理办法第三十二条保险销售人员不得经手或通过非投保人被保险人受益人本人账户支付保费领取退保金保险金；互联网保险办法第四十条原则上应要求投保人使用本人账户支付保费", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "三十四", "to_doc": "互联网保险业务监管办法", "to_article": "二十二", "relation_type": "主题重叠", "confidence": 0.8, "evidence_text": "销售行为管理办法第三十四条要求及时向投保人提供纸质或电子保单、在官方线上平台设置保单查询功能；互联网保险办法第二十二条要求向客户提供保单和发票可优先提供电子保单", "source": "manual"},
    {"from_doc": "保险销售行为管理办法", "from_article": "二十一", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "十一", "relation_type": "主题重叠", "confidence": 0.8, "evidence_text": "销售行为管理办法第二十一条要求根据投保人需求风险特征确定可购买产品范围；网络营销办法第十一条开展精准营销应当遵守适当性管理要求将金融产品推介给适当的金融消费者", "source": "manual"},
    {"from_doc": "互联网保险业务监管办法", "from_article": "十五", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "九", "relation_type": "主题重叠", "confidence": 0.85, "evidence_text": "互联网保险办法第十五条(四)不得片面或夸大宣传不得违规承诺收益或承担损失；网络营销办法第九条(四)夸大保险责任或保险产品收益将保险产品收益与存款等金融产品简单类比", "source": "manual"},
    {"from_doc": "互联网保险业务监管办法", "from_article": "十五", "to_doc": "金融产品网络营销管理办法（征求意见稿）", "to_article": "七", "relation_type": "主题重叠", "confidence": 0.85, "evidence_text": "互联网保险办法第十五条(一)要求建立从业人员互联网保险营销宣传的资质培训内容审核和行为管理制度；网络营销办法第七条要求建立内容审核机制", "source": "manual"},
]


def populate_predefined_relations(database):
    existing = database.get_all_clause_relations()
    existing_keys = {
        (r['from_doc'], r['from_article'], r['to_doc'], r['to_article'], r['relation_type'])
        for r in existing
    }
    count = 0
    for rel in PREDEFINED_RELATIONS:
        key = (rel['from_doc'], rel['from_article'], rel['to_doc'], rel['to_article'], rel['relation_type'])
        if key in existing_keys:
            continue
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
    logger.info(f"预填充条款关系: 新增{count}条, 已存在{len(existing_keys)}条")
    return count
