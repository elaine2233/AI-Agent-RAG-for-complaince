# 保险营销内容智能审核系统 — 架构文档索引

> 版本: v2.0 | 更新日期: 2026-05-16

## 文档体系

| 文档 | 路径 | 受众 | 说明 |
|------|------|------|------|
| **架构总览** | [docs/architecture-overview.md](docs/architecture-overview.md) | 架构师、客户 | 六层解耦架构图、数据流图、安全架构、模块职责、多格式/多模态设计 |
| **技术选型** | [docs/technology-selection.md](docs/technology-selection.md) | 架构师、开发负责人 | 8大技术选型决策、候选对比、选型风险、成本估算 |
| **风险分析** | [docs/risk-analysis.md](docs/risk-analysis.md) | 安全工程师、合规团队 | 14项风险矩阵、安全/业务/技术/运维/合规5类风险、缓解措施 |
| **开发者指南** | [docs/developer-guide.md](docs/developer-guide.md) | 后端开发、AI工程师 | 快速开始、项目结构、扩展开发指南、配置说明、编码规范 |
| **API参考** | [docs/api-reference.md](docs/api-reference.md) | 前端开发、第三方集成 | 20+API端点、请求/响应示例、错误码 |
| **部署指南** | [docs/deployment-guide.md](docs/deployment-guide.md) | 运维工程师、DevOps | Demo/Docker/K8s三阶段部署、监控配置、备份恢复、安全加固 |

## 架构自评

| 维度 | 评分 | 变化 |
|------|------|------|
| 功能完整性 | 8/10 | — |
| 安全性 | 8/10 | +1 (API Key过期+HMAC签名+19种注入) |
| 鲁棒性 | 8/10 | +1 (异步队列+并发控制) |
| 数据层 | 7/10 | — |
| 可扩展性 | 7/10 | +2 (接口抽象+插件注册表+异步API) |
| 可观测性 | 7/10 | +2 (Prometheus+Trace+Alert) |
| 前端体验 | 7/10 | +1 (暗色模式+快捷键) |
| 代码质量 | 8/10 | +1 (配置集中+类型注解+迁移) |
| 文档完整性 | 9/10 | +1 (6份系列文档) |
| **总分** | **7.7/10** | **+1.0** |
