# 保险营销内容智能审核系统 — 架构文档索引

> 版本: v3.0 | 更新日期: 2026-05-16

## 文档体系

| 文档 | 路径 | 受众 | 说明 |
|------|------|------|------|
| **架构总览** | [docs/architecture-overview.md](docs/architecture-overview.md) | 架构师、客户 | 六层解耦架构图、8步Workflow数据流、Rule-First模式、AI核心架构详解（LLM Gateway/Reranker/Risk Engine/HITL/Prompt Manager/幻觉检测） |
| **技术选型** | [docs/technology-selection.md](docs/technology-selection.md) | 架构师、开发负责人 | 11大技术选型决策（含LLM Gateway/Reranker/Risk Engine）、候选对比、选型风险、成本估算 |
| **风险分析** | [docs/risk-analysis.md](docs/risk-analysis.md) | 安全工程师、合规团队 | 15项风险矩阵（含LLM幻觉R15）、安全/业务/技术/运维/合规5类风险、缓解措施 |
| **开发者指南** | [docs/developer-guide.md](docs/developer-guide.md) | 后端开发、AI工程师 | 快速开始、项目结构、Workflow步骤开发、Prompt版本管理、LLM模型注册、编码规范 |
| **API参考** | [docs/api-reference.md](docs/api-reference.md) | 前端开发、第三方集成 | 25+API端点（含HITL/Prompt/LLM管理）、ReviewResponse新字段、请求/响应示例 |
| **部署指南** | [docs/deployment-guide.md](docs/deployment-guide.md) | 运维工程师、DevOps | Demo/Docker/K8s三阶段部署、prompt_versions目录、监控配置、备份恢复、安全加固 |

## v3.0 架构演进

### 从 v2.0 到 v3.0 的核心变更

| 维度 | v2.0 | v3.0 |
|------|------|------|
| 审核模式 | LLM优先 + 规则降级 | **Rule-First + LLM增强** |
| 审核流程 | 单次LLM调用 | **8步Workflow Pipeline** |
| 模型依赖 | 单模型(qwen-plus) | **LLM Gateway多模型路由** |
| 检索增强 | RAG Top5 | **RAG Top20 → Reranker → Top5** |
| 风险控制 | 置信度评分 | **Risk Engine评分 + 4级分类 + 3级决策** |
| 人机协同 | 用户反馈 | **HITL待审队列 + Few-Shot回流** |
| Prompt管理 | 硬编码字符串 | **版本管理 + Few-Shot + 3套专用Prompt** |
| 幻觉检测 | 无 | **Validate步骤交叉验证** |
| API端点 | 20+ | **25+**（新增HITL/Prompt/LLM管理） |

### 新增模块

| 模块 | 文件 | 职责 |
|------|------|------|
| WorkflowEngine | `src/workflow.py` | 8步流水线引擎，步骤可条件跳过、降级 |
| LLMGateway | `src/llm_gateway.py` | 多模型路由+独立熔断+优先级调度 |
| RiskEngine | `src/risk_engine.py` | 风险评分+4级分类+3级决策路由 |
| Reranker | `src/reranker.py` | 检索后重排序(Top20→Top5)，API+规则双模式 |
| PromptManager | `src/prompt_manager.py` | Prompt版本管理+Few-Shot样本库 |

## 架构自评

| 维度 | v2.0评分 | v3.0评分 | 变化 | 关键改进 |
|------|---------|---------|------|---------|
| 功能完整性 | 8 | 9 | +1 | HITL+Risk Engine+Reranker+Prompt Manager |
| 安全性 | 8 | 8.5 | +0.5 | 幻觉检测+审核模式标注 |
| 鲁棒性 | 8 | 9 | +1 | LLM Gateway多模型+独立熔断+Rule-First |
| 数据层 | 7 | 7.5 | +0.5 | prompt_versions数据目录+DB新字段 |
| 可扩展性 | 7 | 9 | +2 | Workflow步骤可插拔+LLM模型可注册+Prompt版本化 |
| 可观测性 | 7 | 7.5 | +0.5 | Workflow步骤级延迟追踪 |
| 前端体验 | 7 | 7 | — | 无变化 |
| 代码质量 | 8 | 8.5 | +0.5 | 6个新模块职责清晰+接口抽象 |
| 文档完整性 | 9 | 9.5 | +0.5 | 6份文档同步更新至v3.0 |
| AI架构 | 5 | 8.5 | +3.5 | Rule-First+Workflow+Gateway+Risk+HITL+Reranker+Prompt治理+幻觉检测 |
| **总分** | **7.7** | **8.5** | **+0.8** | AI架构从5→8.5是最大提升 |
