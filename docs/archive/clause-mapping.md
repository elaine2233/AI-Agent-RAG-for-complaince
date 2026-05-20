# 条款-违规类型映射关系文档

> 版本: v1.0 | 更新日期: 2026-05-16 16:31

---

## 一、概述

本文档以**条款为维度**，展示三部监管法规文档中所有条文与违规类型之间的映射关系。与 [violation-types.md](violation-types.md) 以违规类型为维度的组织方式不同，本文档从法规条文出发，逐条列出每个条文映射的违规类型及映射逻辑，便于合规专家从法规原文角度审查映射的完整性和准确性。

### 1.1 文档范围

| 法规文档 | 条文范围 | 总条文数 |
|---|---|---|
| 《保险销售行为管理办法》 | 第一条 ~ 第五十条 | 50 |
| 《互联网保险业务监管办法》 | 第一条 ~ 第八十三条 | 83 |
| 《金融产品网络营销管理办法》 | 第一条 ~ 第三十七条 | 37 |
| **合计** | | **170** |

### 1.2 映射逻辑说明

| 映射逻辑 | 含义 | 条文性质 |
|---|---|---|
| `primary` | 主要映射 — 条文的核心违规类型，审核引用时优先展示 | 内容审核 |
| `secondary` | 次要映射 — 条文的关联违规类型，作为补充引用 | 内容审核 |
| `not_applicable` | 程序性条款 — 不属于营销内容审核范畴 | 程序性 |

### 1.3 数据来源

本文档所有映射关系基于 `_DEFAULT_MAPPINGS` 数据（[violation_registry.py](../src/violation_registry.py)），与系统运行时加载的映射数据一致。

---

## 二、《保险销售行为管理办法》条款映射

> 法规简称：销售办法 | 总条文数：50

| 条文编号 | 映射的违规类型 | 映射逻辑 | 条文性质 |
|---|---|---|---|
| 一 | procedural | not_applicable | 程序性 |
| 二 | procedural | not_applicable | 程序性 |
| 三 | qualification_violation | primary | 内容审核 |
| 四 | qualification_violation | primary | 内容审核 |
| 五 | qualification_violation | primary | 内容审核 |
| 六 | sales_misconduct, inducement_sales, unauthorized_endorsement | primary, primary, secondary | 内容审核 |
| 七 | sales_misconduct, inducement_sales, unauthorized_endorsement | primary, primary, secondary | 内容审核 |
| 八 | info_disclosure, insufficient_risk_disclosure | primary, primary | 内容审核 |
| 九 | info_disclosure, insufficient_risk_disclosure | primary, primary | 内容审核 |
| 十 | info_disclosure, insufficient_risk_disclosure | primary, primary | 内容审核 |
| 十一 | inducement_sales, return_promise | primary, secondary | 内容审核 |
| 十二 | inducement_sales, return_promise | primary, secondary | 内容审核 |
| 十三 | inducement_sales, return_promise | primary, secondary | 内容审核 |
| 十四 | inducement_sales, return_promise | primary, secondary | 内容审核 |
| 十五 | info_disclosure, concealment | primary, secondary | 内容审核 |
| 十六 | info_disclosure, concealment | primary, secondary | 内容审核 |
| 十七 | info_disclosure, concealment | primary, secondary | 内容审核 |
| 十八 | absolute_language | primary | 内容审核 |
| 十九 | return_promise | primary | 内容审核 |
| 二十 | exaggerated_return | primary | 内容审核 |
| 二十一 | product_confusion, concealment | primary, primary | 内容审核 |
| 二十二 | procedural | not_applicable | 程序性 |
| 二十三 | procedural | not_applicable | 程序性 |
| 二十四 | procedural | not_applicable | 程序性 |
| 二十五 | inducement_sales | primary | 内容审核 |
| 二十六 | inducement_sales | primary | 内容审核 |
| 二十七 | inducement_sales, concealment | primary, secondary | 内容审核 |
| 二十八 | inducement_sales, concealment | primary, secondary | 内容审核 |
| 二十九 | insufficient_risk_disclosure | primary | 内容审核 |
| 三十 | insufficient_risk_disclosure | primary | 内容审核 |
| 三十一 | inducement_sales | primary | 内容审核 |
| 三十二 | procedural | not_applicable | 程序性 |
| 三十三 | procedural | not_applicable | 程序性 |
| 三十四 | procedural | not_applicable | 程序性 |
| 三十五 | procedural | not_applicable | 程序性 |
| 三十六 | procedural | not_applicable | 程序性 |
| 三十七 | procedural | not_applicable | 程序性 |
| 三十八 | procedural | not_applicable | 程序性 |
| 三十九 | procedural | not_applicable | 程序性 |
| 四十 | procedural | not_applicable | 程序性 |
| 四十一 | procedural | not_applicable | 程序性 |
| 四十二 | procedural | not_applicable | 程序性 |
| 四十三 | procedural | not_applicable | 程序性 |
| 四十四 | procedural | not_applicable | 程序性 |
| 四十五 | procedural | not_applicable | 程序性 |
| 四十六 | procedural | not_applicable | 程序性 |
| 四十七 | procedural | not_applicable | 程序性 |
| 四十八 | procedural | not_applicable | 程序性 |
| 四十九 | procedural | not_applicable | 程序性 |
| 五十 | procedural | not_applicable | 程序性 |

---

## 三、《互联网保险业务监管办法》条款映射

> 法规简称：互联网保险办法 | 总条文数：83

| 条文编号 | 映射的违规类型 | 映射逻辑 | 条文性质 |
|---|---|---|---|
| 一 | procedural | not_applicable | 程序性 |
| 二 | procedural | not_applicable | 程序性 |
| 三 | procedural | not_applicable | 程序性 |
| 四 | qualification_violation | primary | 内容审核 |
| 五 | qualification_violation | primary | 内容审核 |
| 六 | qualification_violation | primary | 内容审核 |
| 七 | qualification_violation | primary | 内容审核 |
| 八 | qualification_violation | primary | 内容审核 |
| 九 | info_disclosure, insufficient_risk_disclosure | primary, primary | 内容审核 |
| 十 | info_disclosure, insufficient_risk_disclosure | primary, primary | 内容审核 |
| 十一 | info_disclosure, insufficient_risk_disclosure | primary, primary | 内容审核 |
| 十二 | info_disclosure, insufficient_risk_disclosure | primary, primary | 内容审核 |
| 十三 | info_disclosure, insufficient_risk_disclosure | primary, primary | 内容审核 |
| 十四 | sales_misconduct, return_promise | primary, secondary | 内容审核 |
| 十五 | sales_misconduct, return_promise | primary, secondary | 内容审核 |
| 十六 | sales_misconduct, return_promise | primary, secondary | 内容审核 |
| 十七 | sales_misconduct, return_promise | primary, secondary | 内容审核 |
| 十八 | sales_misconduct, return_promise | primary, secondary | 内容审核 |
| 十九 | qualification_violation, product_confusion | primary, primary | 内容审核 |
| 二十 | qualification_violation, product_confusion | primary, primary | 内容审核 |
| 二十一 | qualification_violation, product_confusion | primary, primary | 内容审核 |
| 二十二 | qualification_violation, product_confusion | primary, primary | 内容审核 |
| 二十三 | qualification_violation, product_confusion | primary, primary | 内容审核 |
| 二十四 | info_protection, info_disclosure | primary, primary | 内容审核 |
| 二十五 | info_protection, info_disclosure | primary, primary | 内容审核 |
| 二十六 | info_protection, info_disclosure | primary, primary | 内容审核 |
| 二十七 | info_protection, info_disclosure | primary, primary | 内容审核 |
| 二十八 | info_protection, info_disclosure | primary, primary | 内容审核 |
| 二十九 | info_protection, info_disclosure | primary, primary | 内容审核 |
| 三十 | info_protection, info_disclosure | primary, primary | 内容审核 |
| 三十一 | procedural | not_applicable | 程序性 |
| 三十二 | procedural | not_applicable | 程序性 |
| 三十三 | procedural | not_applicable | 程序性 |
| 三十四 | procedural | not_applicable | 程序性 |
| 三十五 | procedural | not_applicable | 程序性 |
| 三十六 | procedural | not_applicable | 程序性 |
| 三十七 | procedural | not_applicable | 程序性 |
| 三十八 | procedural | not_applicable | 程序性 |
| 三十九 | procedural | not_applicable | 程序性 |
| 四十 | procedural | not_applicable | 程序性 |
| 四十一 | procedural | not_applicable | 程序性 |
| 四十二 | procedural | not_applicable | 程序性 |
| 四十三 | procedural | not_applicable | 程序性 |
| 四十四 | procedural | not_applicable | 程序性 |
| 四十五 | procedural | not_applicable | 程序性 |
| 四十六 | procedural | not_applicable | 程序性 |
| 四十七 | procedural | not_applicable | 程序性 |
| 四十八 | procedural | not_applicable | 程序性 |
| 四十九 | procedural | not_applicable | 程序性 |
| 五十 | procedural | not_applicable | 程序性 |
| 五十一 | procedural | not_applicable | 程序性 |
| 五十二 | procedural | not_applicable | 程序性 |
| 五十三 | procedural | not_applicable | 程序性 |
| 五十四 | procedural | not_applicable | 程序性 |
| 五十五 | procedural | not_applicable | 程序性 |
| 五十六 | procedural | not_applicable | 程序性 |
| 五十七 | procedural | not_applicable | 程序性 |
| 五十八 | procedural | not_applicable | 程序性 |
| 五十九 | procedural | not_applicable | 程序性 |
| 六十 | procedural | not_applicable | 程序性 |
| 六十一 | procedural | not_applicable | 程序性 |
| 六十二 | procedural | not_applicable | 程序性 |
| 六十三 | procedural | not_applicable | 程序性 |
| 六十四 | procedural | not_applicable | 程序性 |
| 六十五 | procedural | not_applicable | 程序性 |
| 六十六 | procedural | not_applicable | 程序性 |
| 六十七 | procedural | not_applicable | 程序性 |
| 六十八 | procedural | not_applicable | 程序性 |
| 六十九 | procedural | not_applicable | 程序性 |
| 七十 | procedural | not_applicable | 程序性 |
| 七十一 | procedural | not_applicable | 程序性 |
| 七十二 | procedural | not_applicable | 程序性 |
| 七十三 | procedural | not_applicable | 程序性 |
| 七十四 | procedural | not_applicable | 程序性 |
| 七十五 | procedural | not_applicable | 程序性 |
| 七十六 | procedural | not_applicable | 程序性 |
| 七十七 | procedural | not_applicable | 程序性 |
| 七十八 | procedural | not_applicable | 程序性 |
| 七十九 | procedural | not_applicable | 程序性 |
| 八十 | procedural | not_applicable | 程序性 |
| 八十一 | procedural | not_applicable | 程序性 |
| 八十二 | procedural | not_applicable | 程序性 |
| 八十三 | procedural | not_applicable | 程序性 |

---

## 四、《金融产品网络营销管理办法》条款映射

> 法规简称：网络营销办法 | 总条文数：37

| 条文编号 | 映射的违规类型 | 映射逻辑 | 条文性质 |
|---|---|---|---|
| 一 | procedural | not_applicable | 程序性 |
| 二 | procedural | not_applicable | 程序性 |
| 三 | procedural | not_applicable | 程序性 |
| 四 | sales_misconduct, absolute_language | primary, primary | 内容审核 |
| 五 | sales_misconduct, absolute_language | primary, primary | 内容审核 |
| 六 | sales_misconduct, absolute_language | primary, primary | 内容审核 |
| 七 | sales_misconduct, absolute_language | primary, primary | 内容审核 |
| 八 | info_disclosure, insufficient_risk_disclosure | primary, primary | 内容审核 |
| 九 | info_disclosure, insufficient_risk_disclosure | primary, primary | 内容审核 |
| 十 | info_disclosure, insufficient_risk_disclosure | primary, primary | 内容审核 |
| 十一 | info_disclosure, insufficient_risk_disclosure | primary, primary | 内容审核 |
| 十二 | info_disclosure, insufficient_risk_disclosure | primary, primary | 内容审核 |
| 十三 | return_promise, exaggerated_return, inducement_sales | primary, primary, primary | 内容审核 |
| 十四 | return_promise, exaggerated_return, inducement_sales | primary, primary, primary | 内容审核 |
| 十五 | return_promise, exaggerated_return, inducement_sales | primary, primary, primary | 内容审核 |
| 十六 | return_promise, exaggerated_return, inducement_sales | primary, primary, primary | 内容审核 |
| 十七 | info_protection, concealment | primary, secondary | 内容审核 |
| 十八 | info_protection, concealment | primary, secondary | 内容审核 |
| 十九 | info_protection, concealment | primary, secondary | 内容审核 |
| 二十 | info_protection, concealment | primary, secondary | 内容审核 |
| 二十一 | procedural | not_applicable | 程序性 |
| 二十二 | procedural | not_applicable | 程序性 |
| 二十三 | procedural | not_applicable | 程序性 |
| 二十四 | procedural | not_applicable | 程序性 |
| 二十五 | procedural | not_applicable | 程序性 |
| 二十六 | procedural | not_applicable | 程序性 |
| 二十七 | procedural | not_applicable | 程序性 |
| 二十八 | procedural | not_applicable | 程序性 |
| 二十九 | procedural | not_applicable | 程序性 |
| 三十 | procedural | not_applicable | 程序性 |
| 三十一 | procedural | not_applicable | 程序性 |
| 三十二 | procedural | not_applicable | 程序性 |
| 三十三 | procedural | not_applicable | 程序性 |
| 三十四 | procedural | not_applicable | 程序性 |
| 三十五 | procedural | not_applicable | 程序性 |
| 三十六 | procedural | not_applicable | 程序性 |
| 三十七 | procedural | not_applicable | 程序性 |

---

## 五、汇总统计

### 5.1 各法规文档统计

| 法规文档 | 总条文数 | 内容审核条文数 | 程序性条文数 | 映射条目数 |
|---|---|---|---|---|
| 《保险销售行为管理办法》 | 50 | 26 | 24 | 43 |
| 《互联网保险业务监管办法》 | 83 | 27 | 56 | 49 |
| 《金融产品网络营销管理办法》 | 37 | 17 | 20 | 38 |
| **合计** | **170** | **70** | **100** | **130** |

> **映射条目数**：指内容审核条文中所有违规类型映射的累计数量（一个条文映射多个违规类型时分别计数）。程序性条文的 `procedural/not_applicable` 映射不计入映射条目数。

### 5.2 映射逻辑分布

| 映射逻辑 | 条目数 | 占比 |
|---|---|---|
| primary | 110 | 84.6% |
| secondary | 20 | 15.4% |
| **合计** | **130** | **100%** |

### 5.3 条文性质分布

| 条文性质 | 条文数 | 占比 |
|---|---|---|
| 内容审核 | 70 | 41.2% |
| 程序性 | 100 | 58.8% |
| **合计** | **170** | **100%** |

---

## 六、违规类型反向索引

以下按违规类型维度，列出每个违规类型在三部法规中映射的所有条文，便于从违规类型角度快速定位法规依据。

### 6.1 L1 大类：资质违规（qualification_violation）

| 法规文档 | 条文编号 | 映射逻辑 |
|---|---|---|
| 《保险销售行为管理办法》 | 三 | primary |
| 《保险销售行为管理办法》 | 四 | primary |
| 《保险销售行为管理办法》 | 五 | primary |
| 《互联网保险业务监管办法》 | 四 | primary |
| 《互联网保险业务监管办法》 | 五 | primary |
| 《互联网保险业务监管办法》 | 六 | primary |
| 《互联网保险业务监管办法》 | 七 | primary |
| 《互联网保险业务监管办法》 | 八 | primary |
| 《互联网保险业务监管办法》 | 十九 | primary |
| 《互联网保险业务监管办法》 | 二十 | primary |
| 《互联网保险业务监管办法》 | 二十一 | primary |
| 《互联网保险业务监管办法》 | 二十二 | primary |
| 《互联网保险业务监管办法》 | 二十三 | primary |

> 共 13 条映射，覆盖 2 部法规

### 6.2 L2 子类：无资质代言（unauthorized_endorsement）

| 法规文档 | 条文编号 | 映射逻辑 |
|---|---|---|
| 《保险销售行为管理办法》 | 六 | secondary |
| 《保险销售行为管理办法》 | 七 | secondary |

> 共 2 条映射，覆盖 1 部法规

### 6.3 L1 大类：销售行为违规（sales_misconduct）

| 法规文档 | 条文编号 | 映射逻辑 |
|---|---|---|
| 《保险销售行为管理办法》 | 六 | primary |
| 《保险销售行为管理办法》 | 七 | primary |
| 《互联网保险业务监管办法》 | 十四 | primary |
| 《互联网保险业务监管办法》 | 十五 | primary |
| 《互联网保险业务监管办法》 | 十六 | primary |
| 《互联网保险业务监管办法》 | 十七 | primary |
| 《互联网保险业务监管办法》 | 十八 | primary |
| 《金融产品网络营销管理办法》 | 四 | primary |
| 《金融产品网络营销管理办法》 | 五 | primary |
| 《金融产品网络营销管理办法》 | 六 | primary |
| 《金融产品网络营销管理办法》 | 七 | primary |

> 共 11 条映射，覆盖 3 部法规

### 6.4 L2 子类：诱导销售（inducement_sales）

| 法规文档 | 条文编号 | 映射逻辑 |
|---|---|---|
| 《保险销售行为管理办法》 | 六 | primary |
| 《保险销售行为管理办法》 | 七 | primary |
| 《保险销售行为管理办法》 | 十一 | primary |
| 《保险销售行为管理办法》 | 十二 | primary |
| 《保险销售行为管理办法》 | 十三 | primary |
| 《保险销售行为管理办法》 | 十四 | primary |
| 《保险销售行为管理办法》 | 二十五 | primary |
| 《保险销售行为管理办法》 | 二十六 | primary |
| 《保险销售行为管理办法》 | 二十七 | primary |
| 《保险销售行为管理办法》 | 二十八 | primary |
| 《保险销售行为管理办法》 | 三十一 | primary |
| 《金融产品网络营销管理办法》 | 十三 | primary |
| 《金融产品网络营销管理办法》 | 十四 | primary |
| 《金融产品网络营销管理办法》 | 十五 | primary |
| 《金融产品网络营销管理办法》 | 十六 | primary |

> 共 15 条映射，覆盖 2 部法规

### 6.5 L1 大类：信息披露违规（info_disclosure）

| 法规文档 | 条文编号 | 映射逻辑 |
|---|---|---|
| 《保险销售行为管理办法》 | 八 | primary |
| 《保险销售行为管理办法》 | 九 | primary |
| 《保险销售行为管理办法》 | 十 | primary |
| 《保险销售行为管理办法》 | 十五 | primary |
| 《保险销售行为管理办法》 | 十六 | primary |
| 《保险销售行为管理办法》 | 十七 | primary |
| 《互联网保险业务监管办法》 | 九 | primary |
| 《互联网保险业务监管办法》 | 十 | primary |
| 《互联网保险业务监管办法》 | 十一 | primary |
| 《互联网保险业务监管办法》 | 十二 | primary |
| 《互联网保险业务监管办法》 | 十三 | primary |
| 《互联网保险业务监管办法》 | 二十四 | primary |
| 《互联网保险业务监管办法》 | 二十五 | primary |
| 《互联网保险业务监管办法》 | 二十六 | primary |
| 《互联网保险业务监管办法》 | 二十七 | primary |
| 《互联网保险业务监管办法》 | 二十八 | primary |
| 《互联网保险业务监管办法》 | 二十九 | primary |
| 《互联网保险业务监管办法》 | 三十 | primary |
| 《金融产品网络营销管理办法》 | 八 | primary |
| 《金融产品网络营销管理办法》 | 九 | primary |
| 《金融产品网络营销管理办法》 | 十 | primary |
| 《金融产品网络营销管理办法》 | 十一 | primary |
| 《金融产品网络营销管理办法》 | 十二 | primary |

> 共 23 条映射，覆盖 3 部法规

### 6.6 L2 子类：风险提示不足（insufficient_risk_disclosure）

| 法规文档 | 条文编号 | 映射逻辑 |
|---|---|---|
| 《保险销售行为管理办法》 | 八 | primary |
| 《保险销售行为管理办法》 | 九 | primary |
| 《保险销售行为管理办法》 | 十 | primary |
| 《保险销售行为管理办法》 | 二十九 | primary |
| 《保险销售行为管理办法》 | 三十 | primary |
| 《互联网保险业务监管办法》 | 九 | primary |
| 《互联网保险业务监管办法》 | 十 | primary |
| 《互联网保险业务监管办法》 | 十一 | primary |
| 《互联网保险业务监管办法》 | 十二 | primary |
| 《互联网保险业务监管办法》 | 十三 | primary |
| 《金融产品网络营销管理办法》 | 八 | primary |
| 《金融产品网络营销管理办法》 | 九 | primary |
| 《金融产品网络营销管理办法》 | 十 | primary |
| 《金融产品网络营销管理办法》 | 十一 | primary |
| 《金融产品网络营销管理办法》 | 十二 | primary |

> 共 15 条映射，覆盖 3 部法规

### 6.7 L2 子类：隐瞒信息（concealment）

| 法规文档 | 条文编号 | 映射逻辑 |
|---|---|---|
| 《保险销售行为管理办法》 | 十五 | secondary |
| 《保险销售行为管理办法》 | 十六 | secondary |
| 《保险销售行为管理办法》 | 十七 | secondary |
| 《保险销售行为管理办法》 | 二十一 | primary |
| 《保险销售行为管理办法》 | 二十七 | secondary |
| 《保险销售行为管理办法》 | 二十八 | secondary |
| 《金融产品网络营销管理办法》 | 十七 | secondary |
| 《金融产品网络营销管理办法》 | 十八 | secondary |
| 《金融产品网络营销管理办法》 | 十九 | secondary |
| 《金融产品网络营销管理办法》 | 二十 | secondary |

> 共 10 条映射，覆盖 2 部法规

### 6.8 L2 子类：绝对化用语（absolute_language）

| 法规文档 | 条文编号 | 映射逻辑 |
|---|---|---|
| 《保险销售行为管理办法》 | 十八 | primary |
| 《金融产品网络营销管理办法》 | 四 | primary |
| 《金融产品网络营销管理办法》 | 五 | primary |
| 《金融产品网络营销管理办法》 | 六 | primary |
| 《金融产品网络营销管理办法》 | 七 | primary |

> 共 5 条映射，覆盖 2 部法规

### 6.9 L2 子类：收益承诺（return_promise）

| 法规文档 | 条文编号 | 映射逻辑 |
|---|---|---|
| 《保险销售行为管理办法》 | 十一 | secondary |
| 《保险销售行为管理办法》 | 十二 | secondary |
| 《保险销售行为管理办法》 | 十三 | secondary |
| 《保险销售行为管理办法》 | 十四 | secondary |
| 《保险销售行为管理办法》 | 十九 | primary |
| 《互联网保险业务监管办法》 | 十四 | secondary |
| 《互联网保险业务监管办法》 | 十五 | secondary |
| 《互联网保险业务监管办法》 | 十六 | secondary |
| 《互联网保险业务监管办法》 | 十七 | secondary |
| 《互联网保险业务监管办法》 | 十八 | secondary |
| 《金融产品网络营销管理办法》 | 十三 | primary |
| 《金融产品网络营销管理办法》 | 十四 | primary |
| 《金融产品网络营销管理办法》 | 十五 | primary |
| 《金融产品网络营销管理办法》 | 十六 | primary |

> 共 14 条映射，覆盖 3 部法规

### 6.10 L2 子类：夸大收益（exaggerated_return）

| 法规文档 | 条文编号 | 映射逻辑 |
|---|---|---|
| 《保险销售行为管理办法》 | 二十 | primary |
| 《金融产品网络营销管理办法》 | 十三 | primary |
| 《金融产品网络营销管理办法》 | 十四 | primary |
| 《金融产品网络营销管理办法》 | 十五 | primary |
| 《金融产品网络营销管理办法》 | 十六 | primary |

> 共 5 条映射，覆盖 2 部法规

### 6.11 L2 子类：产品混淆（product_confusion）

| 法规文档 | 条文编号 | 映射逻辑 |
|---|---|---|
| 《保险销售行为管理办法》 | 二十一 | primary |
| 《互联网保险业务监管办法》 | 十九 | primary |
| 《互联网保险业务监管办法》 | 二十 | primary |
| 《互联网保险业务监管办法》 | 二十一 | primary |
| 《互联网保险业务监管办法》 | 二十二 | primary |
| 《互联网保险业务监管办法》 | 二十三 | primary |

> 共 6 条映射，覆盖 2 部法规

### 6.12 L1 大类：信息保护违规（info_protection）

| 法规文档 | 条文编号 | 映射逻辑 |
|---|---|---|
| 《互联网保险业务监管办法》 | 二十四 | primary |
| 《互联网保险业务监管办法》 | 二十五 | primary |
| 《互联网保险业务监管办法》 | 二十六 | primary |
| 《互联网保险业务监管办法》 | 二十七 | primary |
| 《互联网保险业务监管办法》 | 二十八 | primary |
| 《互联网保险业务监管办法》 | 二十九 | primary |
| 《互联网保险业务监管办法》 | 三十 | primary |
| 《金融产品网络营销管理办法》 | 十七 | primary |
| 《金融产品网络营销管理办法》 | 十八 | primary |
| 《金融产品网络营销管理办法》 | 十九 | primary |
| 《金融产品网络营销管理办法》 | 二十 | primary |

> 共 11 条映射，覆盖 2 部法规

### 6.13 反向索引汇总

| 违规类型 | 层级 | 映射条目数 | 覆盖法规数 |
|---|---|---|---|
| qualification_violation | L1 | 13 | 2 |
| unauthorized_endorsement | L2 | 2 | 1 |
| sales_misconduct | L1 | 11 | 3 |
| inducement_sales | L2 | 15 | 2 |
| info_disclosure | L1 | 23 | 3 |
| insufficient_risk_disclosure | L2 | 15 | 3 |
| concealment | L2 | 10 | 2 |
| absolute_language | L2 | 5 | 2 |
| return_promise | L2 | 14 | 3 |
| exaggerated_return | L2 | 5 | 2 |
| product_confusion | L2 | 6 | 2 |
| info_protection | L1 | 11 | 2 |
| **合计** | | **130** | |

---

## 七、跨法规条文对照

以下展示同一违规类型在不同法规文档中的条文分布，便于合规专家进行跨法规对照审查。

### 7.1 三部法规共同覆盖的违规类型

| 违规类型 | 销售办法条文 | 互联网保险办法条文 | 网络营销办法条文 |
|---|---|---|---|
| sales_misconduct | 六, 七 | 十四~十八 | 四~七 |
| info_disclosure | 八~十, 十五~十七 | 九~十三, 二十四~三十 | 八~十二 |

### 7.2 两部法规覆盖的违规类型

| 违规类型 | 覆盖法规 | 条文分布 |
|---|---|---|
| qualification_violation | 销售办法 + 互联网保险办法 | 销售办法: 三~五; 互联网保险办法: 四~八, 十九~二十三 |
| inducement_sales | 销售办法 + 网络营销办法 | 销售办法: 六, 七, 十一~十四, 二十五~二十八, 三十一; 网络营销办法: 十三~十六 |
| insufficient_risk_disclosure | 销售办法 + 互联网保险办法 + 网络营销办法 | 销售办法: 八~十, 二十九~三十; 互联网保险办法: 九~十三; 网络营销办法: 八~十二 |
| concealment | 销售办法 + 网络营销办法 | 销售办法: 十五~十七(secondary), 二十一(primary), 二十七~二十八(secondary); 网络营销办法: 十七~二十(secondary) |
| absolute_language | 销售办法 + 网络营销办法 | 销售办法: 十八; 网络营销办法: 四~七 |
| return_promise | 销售办法 + 互联网保险办法 + 网络营销办法 | 销售办法: 十一~十四(secondary), 十九(primary); 互联网保险办法: 十四~十八(secondary); 网络营销办法: 十三~十六(primary) |
| exaggerated_return | 销售办法 + 网络营销办法 | 销售办法: 二十; 网络营销办法: 十三~十六 |
| product_confusion | 销售办法 + 互联网保险办法 | 销售办法: 二十一; 互联网保险办法: 十九~二十三 |
| info_protection | 互联网保险办法 + 网络营销办法 | 互联网保险办法: 二十四~三十; 网络营销办法: 十七~二十 |

### 7.3 单部法规覆盖的违规类型

| 违规类型 | 覆盖法规 | 条文分布 |
|---|---|---|
| unauthorized_endorsement | 销售办法 | 销售办法: 六(secondary), 七(secondary) |
