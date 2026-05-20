# 保险营销内容智能审核系统

基于 LLM + RAG 的金融保险营销内容合规审核系统。规则引擎做关键词预检，LLM 执行完整语义审核，10 步流水线驱动，Risk Engine 评分决定三级处置。

## 快速启动

```bash
pip install -r requirements.txt
python api_server.py
# 访问 http://localhost:7861
```

无需数据库安装，SQLite + ChromaDB 本地持久化，零配置启动。配置 DashScope API Key 后启用完整 LLM 审核。

### 法规文件

系统启动时需要法规原文文件，请自行获取以下文件并放入 `data/regulations/` 目录：

- `保险销售行为管理办法.pdf`
- `互联网保险业务监管办法.docx`
- `金融产品网络营销管理办法（征求意见稿）.doc`

> 这些文件为公开发布的监管法规，可从银保监会/国家金融监督管理总局官网获取。放入目录后重启服务即可自动解析并建立索引。

## 推荐阅读顺序

| 顺序 | 文档                                                           | 说明                                    |
| -- | ------------------------------------------------------------ | ------------------------------------- |
| 1  | [docs/architecture-unified.md](docs/architecture-unified.md) | **统一架构文档**：六层解耦、10步管线、四条数据流、安全架构、部署架构 |
| 2  | 运行 Demo                                                      | `python api_server.py` → 输入营销文案体验审核流程 |
| 3  | [docs/technology-selection.md](docs/technology-selection.md) | 技术选型决策：12大选型对比、候选分析、成本估算              |
| 4  | [docs/demo-production-gap.md](docs/demo-production-gap.md)   | Demo→生产差异：29项差距分析、迁移路线图、检查清单          |
| 5  | [docs/api-reference.md](docs/api-reference.md)               | API参考：54个端点、请求/响应示例                   |

## 项目结构

```
├── api_server.py          # FastAPI 服务入口（54个API端点）
├── config.py              # 配置管理（环境变量 + 默认值）
├── requirements.txt       # Python 依赖
├── start.sh               # 一键启动脚本
├── frontend/
│   └── index.html         # 纯 HTML 单页应用
├── src/                   # 核心业务代码
│   ├── workflow.py         # 10步审核流水线引擎
│   ├── review_agent.py     # ReviewAgent 编排调度
│   ├── llm_gateway.py      # LLM 多模型路由网关（熔断+降级）
│   ├── rag_engine.py       # RAG 检索引擎（ChromaDB + 关键词降级）
│   ├── reranker.py         # 重排序（Cross-Encoder + 规则降级）
│   ├── risk_engine.py      # 风险评估引擎（4级分类 + 3级决策）
│   ├── security.py         # 安全中间件（33种检测 + 限流 + 审计）
│   ├── violation_registry.py # 动态违规类型注册表（5L1+11L2+209映射）
│   ├── clause_relation_extractor.py # 条款关系提取（14正则+49预标注）
│   ├── prompt_manager.py   # Prompt 版本管理 + Few-Shot
│   ├── document_processor.py # 法规文档处理（4种分块策略）
│   ├── input_processors.py # 多模态输入处理（图片预处理+OCR）
│   ├── database.py         # 数据持久化（SQLite WAL + 13张表 schema v8）
│   ├── observability.py    # 可观测性（Prometheus + 告警 + 链路追踪）
│   ├── resilience.py       # 韧性（熔断器 + 重试 + 降级）
│   ├── async_engine.py     # 异步任务引擎（Semaphore 并发控制）
│   └── interfaces.py       # 抽象接口（VectorStore/LLMProvider/ReviewStorage）
├── eval/                  # 评估测试集
├── data/                  # 运行时数据（SQLite/ChromaDB/法规文件/审计日志）
└── docs/                  # 文档
    ├── architecture-unified.md  # 统一架构文档
    ├── technology-selection.md  # 技术选型决策
    ├── demo-production-gap.md  # Demo→生产差异清单
    ├── api-reference.md        # API参考文档
    └── archive/                # 详细参考文档（12份）
```

## 核心架构

**六层解耦**：展示层 → 网关层 → 业务服务层 → AI能力层 → 数据处理层 → 基础设施层

**10步审核管线**：Extract → RuleCheck → RAGRetrieve → Rerank → ExpandRelations → LLMReason → Format → Validate → CrossCheck → RiskAssess

**关键设计**：

- Rule + LLM 协同：规则命中不跳过 LLM，注入 Prompt 继续深层检测
- 条款关系图：14条正则 + 49条预标注，追踪引用/例外/补充关系
- 多级降级：LLM→规则引擎、向量→关键词、Cross-Encoder→规则重排
- 接口抽象：4个核心接口隔离 Demo/生产实现，业务代码零改动

## License

本项目基于 [Apache License 2.0](LICENSE) 开源。

```
Copyright 2024-2026 AI-Agent-RAG-for-compliance Contributors

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```

