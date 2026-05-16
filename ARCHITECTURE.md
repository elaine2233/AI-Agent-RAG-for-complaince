# 保险营销内容智能审核系统 — 架构文档索引

> 版本: v3.2 | 更新日期: 2026-05-16

## 文档体系

| 文档 | 路径 | 受众 | 说明 |
|------|------|------|------|
| **架构总览** | [docs/architecture-overview.md](docs/architecture-overview.md) | 架构师、客户 | 六层解耦架构图、9步Workflow数据流、Rule-First模式、AI核心架构详解（LLM Gateway/Reranker/Risk Engine/HITL/Prompt Manager/幻觉检测/CrossCheck/动态违规类型体系） |
| **技术选型** | [docs/technology-selection.md](docs/technology-selection.md) | 架构师、开发负责人 | 12大技术选型决策（含LLM Gateway/Reranker/Risk Engine/ViolationRegistry）、候选对比、选型风险、成本估算 |
| **风险分析** | [docs/risk-analysis.md](docs/risk-analysis.md) | 安全工程师、合规团队 | 17项风险矩阵（含LLM幻觉R15/类型体系膨胀R16/单一LLM自圆其说R17）、安全/业务/技术/运维/合规5类风险、缓解措施 |
| **开发者指南** | [docs/developer-guide.md](docs/developer-guide.md) | 后端开发、AI工程师 | 快速开始、项目结构、Workflow步骤开发、Prompt版本管理、LLM模型注册、违规类型管理、编码规范 |
| **API参考** | [docs/api-reference.md](docs/api-reference.md) | 前端开发、第三方集成 | 35+API端点（含HITL/Prompt/LLM/违规类型管理）、ReviewResponse新字段、请求/响应示例 |
| **部署指南** | [docs/deployment-guide.md](docs/deployment-guide.md) | 运维工程师、DevOps | Demo/Docker/K8s三阶段部署、violation_types目录、监控配置、备份恢复、安全加固 |

## v3.1 架构演进

### 从 v3.1 到 v3.2 的核心变更

| 维度 | v3.1 | v3.2 |
|------|------|------|
| Workflow步骤 | 8步 | **9步（新增CrossCheck）** |
| LLM推理 | 单路推理 | **单路推理 + 轻量模型交叉验证** |
| Prompt | 通用CoT | **CoT + 语义隐含分析引导（6种隐含模式）** |
| Reranker | Top5 | **Top5 + 相邻条款上下文扩展** |
| 审核记录 | 无版本快照 | **regulation_snapshot法规版本快照** |

### 从 v3.0 到 v3.1 的核心变更

| 维度 | v3.0 | v3.1 |
|------|------|------|
| 违规类型 | 硬编码6种(`VIOLATION_RULES`) | **动态注册表+L1/L2分级+条款映射** |
| 严重度 | 硬编码`VIOLATION_SEVERITY` | **从注册表动态读取** |
| 建议文本 | 硬编码`suggestion_map` | **从注册表动态读取** |
| 新法规入库 | 仅解析+分块+索引 | **解析+分块+LLM辅助标注+人工审批** |
| 条款-类型关系 | 一对多(每规则一组条款) | **多对多+生效/失效时间** |
| API端点 | 25+ | **35+**（新增9个违规类型管理端点） |

### 新增模块

| 模块 | 文件 | 职责 |
|------|------|------|
| ViolationRegistry | `src/violation_registry.py` | 动态违规类型注册表+L1/L2分级+条款-类型映射+LLM辅助标注+人工审批 |

### 核心设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 违规类型存储 | JSON文件 | 轻量无额外依赖，与prompt_versions一致 |
| 类型分级 | L1(固定)+L2(半固定) | L1对应监管框架顶层逻辑极少变动，L2可按需扩展 |
| 条款映射 | 多对多+生效/失效时间 | 一个条款可关联多个违规类型，法规废止时标记失效 |
| 标注方式 | LLM辅助+人工确认 | LLM建议提高效率，人工确认保证准确性 |
| 程序性条款 | LLM过滤 | 程序性条款不属于内容审核范畴，不建违规类型 |

## 架构自评

| 维度 | v2.0评分 | v3.0评分 | v3.1评分 | v3.2评分 | 变化(v3.2) | 关键改进 |
|------|---------|---------|---------|---------|-----------|---------|
| 功能完整性 | 8 | 9 | 9.5 | 9.5 | — | — |
| 安全性 | 8 | 8.5 | 8.5 | 8.5 | — | — |
| 鲁棒性 | 8 | 9 | 9 | 9.5 | +0.5 | CrossCheck降低漏判 |
| 数据层 | 7 | 7.5 | 8 | 8.5 | +0.5 | regulation_snapshot |
| 可扩展性 | 7 | 9 | 9.5 | 9.5 | — | — |
| 可观测性 | 7 | 7.5 | 7.5 | 7.5 | — | — |
| 前端体验 | 7 | 7 | 7 | 7 | — | — |
| 代码质量 | 8 | 8.5 | 9 | 9 | — | — |
| 文档完整性 | 9 | 9.5 | 9.5 | 9.5 | — | — |
| AI架构 | 5 | 8.5 | 9 | 9.5 | +0.5 | CrossCheck+语义隐含+上下文扩展 |
| **总分** | **7.7** | **8.5** | **8.7** | **8.9** | **+0.2** | AI架构持续提升 |
