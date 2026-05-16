# 保险营销内容智能审核系统 — 架构文档索引

> 版本: v3.5 | 更新日期: 2026-05-16

## 文档体系

### 架构设计

| 文档 | 路径 | 受众 | 说明 |
|------|------|------|------|
| **Demo架构设计** | [docs/architecture-demo.md](docs/architecture-demo.md) | 架构师、客户、开发 | Demo版完整架构：系统上下文图、容器图、组件图、数据流图、Demo限制说明、部署架构 |
| **生产架构设计** | [docs/architecture-production.md](docs/architecture-production.md) | 架构师、运维、客户 | 生产版完整架构：微服务拆分、安全架构、高可用设计、可观测性、性能目标、K8s部署 |
| **架构总览** | [docs/architecture-overview.md](docs/architecture-overview.md) | 架构师、开发 | 六层解耦架构、9步Workflow数据流、Rule+LLM协同模式、AI核心详解 |

### 核心设计

| 文档 | 路径 | 受众 | 说明 |
|------|------|------|------|
| **违规类型体系** | [docs/violation-types.md](docs/violation-types.md) | 合规团队、AI工程师 | L1/L2分级、11个L2类型、139条映射、Few-Shot机制、REASON_SYSTEM_PROMPT、语义隐含分析 |
| **条款映射关系** | [docs/clause-mapping.md](docs/clause-mapping.md) | 合规团队、开发 | 83条条文的条款级映射、3部法规逐条对照、违规类型反向索引 |
| **Demo-生产差距** | [docs/demo-production-gap.md](docs/demo-production-gap.md) | 项目经理、架构师 | 18模块差距分析、优先级排序、Demo限制说明、生产改进路径 |

### 技术参考

| 文档 | 路径 | 受众 | 说明 |
|------|------|------|------|
| **技术细节** | [docs/technical-details.md](docs/technical-details.md) | AI工程师、后端开发 | 文档处理Pipeline、分块算法、向量搜索、Reranker、LLM调用、评估框架(4层11节) |
| **数据库设计** | [docs/database-design.md](docs/database-design.md) | 后端开发、DBA | Schema v6、review_violations表、violation_feedback表、法规版本管理 |
| **API参考** | [docs/api-reference.md](docs/api-reference.md) | 前端开发、第三方集成 | 35+API端点、ReviewResponse字段、请求/响应示例 |
| **技术选型** | [docs/technology-selection.md](docs/technology-selection.md) | 架构师、开发负责人 | 12大技术选型决策、候选对比、选型风险、成本估算 |

### 运维与安全

| 文档 | 路径 | 受众 | 说明 |
|------|------|------|------|
| **部署指南** | [docs/deployment-guide.md](docs/deployment-guide.md) | 运维工程师、DevOps | Demo/Docker/K8s三阶段部署、监控配置、备份恢复、安全加固 |
| **风险分析** | [docs/risk-analysis.md](docs/risk-analysis.md) | 安全工程师、合规团队 | 17项风险矩阵、5类风险、缓解措施 |
| **开发者指南** | [docs/developer-guide.md](docs/developer-guide.md) | 后端开发、AI工程师 | 快速开始、项目结构、编码规范、模型注册 |

## 架构自评

| 维度 | v3.5评分 | 关键改进 |
|------|---------|---------|
| 功能完整性 | 9.5 | 图片独立审核、auto_block人工覆盖 |
| 安全性 | 8.5 | 7层纵深防御 |
| 鲁棒性 | 9.5 | CrossCheck+熔断+重试+降级 |
| 数据层 | 8.5 | regulation_snapshot+review_violations |
| 可扩展性 | 9.5 | 动态违规类型注册表 |
| 可观测性 | 7.5 | Prometheus+OpenTelemetry |
| 前端体验 | 8.0 | 独立HTML前端(替代Gradio) |
| 代码质量 | 9.0 | 配置化参数+markdown表格 |
| 文档完整性 | 9.5 | Demo/生产架构设计+条款映射 |
| AI架构 | 9.5 | CrossCheck+语义隐含+上下文扩展 |
| **总分** | **8.9** | — |
