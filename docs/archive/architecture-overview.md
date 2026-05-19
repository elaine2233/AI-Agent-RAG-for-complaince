# 保险营销内容智能审核系统 — 架构总览

> 版本: v3.5 | 更新日期: 2026-05-17 | 受众: 架构师、技术负责人、客户技术评审

---

## 一、系统定位

基于大语言模型（LLM）+ 检索增强生成（RAG）的金融保险营销内容合规审核系统，采用 **Rule-First + Workflow** 架构，支持多格式文档摄入、多模态用户输入、实时审核与异步审核双模式，输出结构化审核结论（合规判定、违规类型、引用法规条文、风险评分、处置决策）。

### 核心架构理念

- **Rule+LLM 协同**：规则引擎做关键词预检，LLM始终执行完整语义审核；规则命中时将结果注入LLM Prompt，两者结果合并输出，避免浅层命中掩盖深层违规
- **Workflow Pipeline**：10步流水线（Extract→RuleCheck→RAGRetrieve→Rerank→ExpandRelations→LLMReason→Format→Validate→CrossCheck→RiskAssess），每步独立可测、可跳过、可降级
- **Risk-Gated Decision**：风险评分驱动的三级决策路由（auto_pass / human_review / auto_block）

### 相关文档

| 文档 | 说明 |
|------|------|
| [数据库设计文档](database-design.md) | 表结构、索引、迁移策略、备份方案 |
| [违规类型系统文档](violation-types.md) | L1/L2分级、条款映射、动态注册表 |

---

## 二、系统架构图

### 2.1 系统上下文图（System Context）

展示系统与外部参与者及外部系统的交互关系。

```mermaid
graph TB
    subgraph 外部参与者
        BU["👤 业务人员<br/>提交营销内容审核"]
        ADMIN["👤 合规管理员<br/>管理法规文档入库"]
        REVIEWER["👤 合规审核员<br/>人工复核 flagged 内容"]
        SYSADMIN["👤 系统管理员<br/>管理违规类型 & 评估效果"]
    end

    subgraph 核心系统
        SYS["🛡️ 保险营销内容<br/>智能审核系统"]
    end

    subgraph 外部系统
        LLM["🤖 LLM API<br/>qwen3.6-plus / qwen3.6-flash(后备)"]
        REG["📖 法规文档源<br/>监管机构发布的法规文件"]
        MON["📊 Prometheus<br/>监控指标采集"]
    end

    BU -->|"提交审核请求"| SYS
    SYS -->|"返回审核结论"| BU
    ADMIN -->|"上传法规文档"| SYS
    SYS -->|"标注审批待办"| ADMIN
    REVIEWER -->|"查看待审队列"| SYS
    SYS -->|"推送 flagged 内容"| REVIEWER
    REVIEWER -->|"override 决策"| SYS
    SYSADMIN -->|"管理违规类型"| SYS
    SYSADMIN -->|"运行效果评估"| SYS
    SYS -->|"调用推理/提取"| LLM
    LLM -->|"返回审核结果"| SYS
    REG -->|"法规文件摄入"| SYS
    SYS -->|"暴露指标"| MON
```

### 2.2 六层架构图（Layer Architecture）

展示系统的六层解耦架构及各层包含的模块。

```mermaid
graph TB
    subgraph L1["🖥️ 展示层 Presentation"]
        HTML["FastAPI + 纯HTML前端<br/>(Demo/运营)"]
        FASTAPI["FastAPI REST<br/>(生产API)"]
        PROM["Prometheus<br/>(监控面板)"]
    end

    subgraph L2["🚪 API网关层 Gateway"]
        AUTH["认证<br/>RBAC + API Key"]
        RATE["限流<br/>滑动窗口"]
        SEC_CHECK["安全校验<br/>25种模式"]
        CORS["CORS白名单"]
        REQLOG["请求日志"]
        CIRCUIT_CHK["熔断检查"]
    end

    subgraph L3["💼 业务服务层 Business"]
        RA["ReviewAgent<br/>(审核编排)"]
        ASYNC["AsyncTaskQ<br/>(异步任务)"]
        ALERT["AlertManager<br/>(告警管理)"]
    end

    subgraph L4["🧠 AI能力层 AI Capability"]
        WF["WorkflowEngine<br/>(10步流水线)"]
        LLM_GW["LLM Gateway<br/>(多模型路由)"]
        RISK_E["Risk Engine<br/>(风险评分)"]
        RAG["RAG Engine<br/>(检索增强)"]
        RERANK["Reranker<br/>(重排序)"]
        RULE["Rule Engine<br/>(规则优先)"]
        PM["PromptManager<br/>(版本+FewShot)"]
    end

    subgraph L5["⚙️ 数据处理层 Data Processing"]
        DOC_PARSER["DocParserReg<br/>(多格式解析)<br/>TXT/MD/PDF/DOCX/IMAGE"]
        INPUT_PROC["InputProcChn<br/>(多模态输入)<br/>Text/Image/File/Mixed"]
        CHUNK["ChunkStrat<br/>(分块策略)<br/>Article/Chapter/Semantic/Fixed"]
    end

    subgraph L6["🏗️ 基础设施层 Infrastructure"]
        SQLITE["SQLite<br/>(WAL)"]
        CHROMA["ChromaDB<br/>(向量库)"]
        AUDIT["审计日志<br/>(HMAC)"]
        CONFIG["配置中心<br/>(config)"]
        CB["熔断器<br/>(3-state)"]
        RETRY["重试策略<br/>(退避+抖)"]
        CACHE["结果缓存<br/>(LRU+TTL)"]
        SEM["并发控制<br/>(Semaphore)"]
    end

    L1 --> L2
    L2 --> L3
    L3 --> L4
    L4 --> L5
    L5 --> L6
    L3 --> L6
    L4 --> L6
```

### 2.3 完整数据流图（四条主线）

系统包含审核主流程、法规管理、反馈学习、违规类型管理四条数据流。四条主线相互关联，共同构成完整的业务闭环。

**关键修正**：违规类型管理流中的"新法规入库"来源于法规管理流的上传步骤，而非独立起点。法规管理流的 upload → parse → annotate → approve 流程完成后，才触发违规类型映射的创建。

```mermaid
flowchart TB
    subgraph REG_FLOW["📚 法规管理流"]
        A1["法规文档上传<br/>(Admin)"]
        A2["多格式解析<br/>(DocParserReg)"]
        A3["分块策略<br/>(ChunkStrat)"]
        A4["LLM辅助标注<br/>(行为模式提取)"]
        A5["管理员审批标注"]
        A7["Embedding向量化"]
        A8["ChromaDB索引构建"]
        A1 --> A2 --> A3 --> A4 --> A5
        A5 --> A7 --> A8
    end

    subgraph REVIEW_FLOW["🔍 审核主流程"]
        B1["用户输入<br/>(多模态)"]
        B2["多模态输入处理<br/>(InputProcChn)"]
        B3["安全校验<br/>(25种模式)"]
        B4["10步Workflow Pipeline"]
        B5{"Risk决策<br/>(Risk Engine)"}
        B6["持久化 + 审计日志"]
        B7["HITL待审队列"]
        B8["拦截记录"]
        B1 --> B2 --> B3 --> B4 --> B5
        B5 -->|"auto_pass<br/>risk < 0.1"| B6
        B5 -->|"human_review<br/>0.1 ≤ risk < 0.7"| B7
        B5 -->|"auto_block<br/>risk ≥ 0.7"| B8
    end

    subgraph FEEDBACK_FLOW["🔄 反馈学习流"]
        C1["人工override"]
        C2["Few-Shot样本生成"]
        C3["few_shots.json"]
        C4["审核反馈统计"]
        C5["违规类型severity校准"]
        C1 --> C2 --> C3
        C1 --> C4 --> C5
    end

    subgraph VIOLATION_FLOW["🏷️ 违规类型管理流"]
        D1["管理员审批标注<br/>(来自法规管理流)"]
        D2["条款-类型映射入库"]
        D3{"建议新类型?"}
        D4["创建新违规类型"]
        D5["补充关键词规则"]
        D6["映射到现有类型"]
        D1 --> D2
        D1 --> D3
        D3 -->|"是"| D4 --> D5
        D3 -->|"否"| D6
    end

    A5 -.->|"审批通过<br/>触发映射"| D1
    A8 -->|"法规索引就绪"| B4
    D2 -->|"类型映射就绪"| B4
    D5 -->|"关键词规则就绪"| B4
    D6 -->|"映射完成"| B4
    C3 -.->|"Few-Shot注入"| B4
    B7 -->|"flagged内容"| C1

    style A5 fill:#fbbf24,stroke:#92400e
    style D1 fill:#fbbf24,stroke:#92400e
```

### 2.4 安全架构图（7层纵深防御）

```mermaid
graph LR
    REQ["📨 请求"] --> L1
    L1["🛡️ L1: WAF/CDN<br/>网络层防护"] --> L2
    L2["🚪 L2: API网关<br/>限流 + CORS白名单"] --> L3
    L3["🔑 L3: 认证<br/>RBAC + API Key过期检查"] --> L4
    L4["✅ L4: 输入校验<br/>XSS / SQL注入 / 控制字符"] --> L5
    L5["🤖 L5: Prompt注入检测<br/>25种攻击模式识别"] --> L6
    L6["🔒 L6: LLM安全Prompt<br/>角色约束 + 输出格式限定"] --> L7
    L7["📤 L7: 输出校验<br/>JSON Schema + 幻觉检测"]

    style L1 fill:#fee2e2,stroke:#991b1b
    style L2 fill:#fef3c7,stroke:#92400e
    style L3 fill:#fef9c3,stroke:#854d0e
    style L4 fill:#ecfccb,stroke:#3f6212
    style L5 fill:#d1fae5,stroke:#065f46
    style L6 fill:#dbeafe,stroke:#1e40af
    style L7 fill:#ede9fe,stroke:#5b21b6
```

### 2.5 AI核心架构图

展示 Rule+LLM 协同、Workflow Pipeline、LLM Gateway、Reranker、Risk Engine、CrossCheck 六大AI组件的协作关系。

**API Key转发机制**：前端通过 `X-API-Key` 请求头传入的API Key，在认证通过后同时作为 DashScope API Key 使用。当用户提供了有效的 DashScope API Key 时，系统将使用该 Key 调用 LLM 和 Embedding 服务，而非依赖服务端配置的 `DASHSCOPE_API_KEY`。这使得 API Key缺失时用户可使用自己的 DashScope Key 获得完整 LLM 功能。

```mermaid
flowchart TB
    INPUT["审核输入"] --> EXTRACT["① Extract<br/>要素提取"]
    EXTRACT --> RULE_CHK["② RuleCheck<br/>规则引擎预检"]

    RULE_CHK -->|"规则命中<br/>注入Prompt"| RAG_RET
    RULE_CHK -->|"规则未命中<br/>正常流转"| RAG_RET

    RAG_RET["③ RAGRetrieve<br/>向量+关键词双模检索"] --> RERANK["④ Rerank<br/>Top20→Top5+上下文扩展"]
    RERANK --> EXPAND_REL["⑤ ExpandRelations<br/>条款关联扩展"]
    EXPAND_REL --> LLM_REASON["⑥ LLMReason<br/>CoT推理审核"]

    subgraph LLM_GW["LLM Gateway 多模型路由"]
        direction TB
        GW_ENTRY["请求入口"]
        GW_ENTRY --> P1["qwen3.6-plus<br/>PRIMARY<br/>priority=0"]
        GW_ENTRY --> P2["qwen3.6-flash<br/>FALLBACK<br/>priority=5"]
        P1 --> CB1["CircuitBreaker"]
        P2 --> CB2["CircuitBreaker"]
        CB1 --> GW_EXIT["响应"]
        CB2 --> GW_EXIT
    end

    LLM_REASON -.->|"调用"| LLM_GW
    LLM_GW -.->|"返回"| LLM_REASON

    LLM_REASON --> FORMAT["⑦ Format<br/>结构化归一化+降级兜底"]
    FORMAT --> VALIDATE["⑧ Validate<br/>幻觉检测+交叉验证"]
    VALIDATE --> CROSS_CHK["⑨ CrossCheck<br/>轻量模型复核"]
    CROSS_CHK --> RISK_ASSESS["⑩ RiskAssess<br/>风险评分+决策路由"]

    CROSS_CHK -.->|"调用qwen3.6-plus"| LLM_GW

    RISK_ASSESS --> DECISION{"决策路由"}
    DECISION -->|"risk < 0.1"| AUTO_PASS["auto_pass"]
    DECISION -->|"0.1 ≤ risk < 0.7"| HUMAN_REVIEW["human_review"]
    DECISION -->|"risk ≥ 0.7"| AUTO_BLOCK["auto_block"]

    subgraph RERANK_DETAIL["Reranker 详情"]
        direction TB
        RAG_TOP20["RAG检索 Top20"]
        API_RERANK{"DASHSCOPE_API_KEY<br/>已配置?"}
        RAG_TOP20 --> API_RERANK
        API_RERANK -->|"是"| CE_RERANK["Cross-Encoder Rerank<br/>(qwen3-rerank)<br/>语义精排"]
        API_RERANK -->|"否"| RULE_RERANK["规则重排序<br/>字符重叠+关键词加权<br/>(API Key缺失时)"]
        CE_RERANK --> TOP5["Top5"]
        RULE_RERANK --> TOP5
        TOP5 --> CTX_EXPAND["上下文扩展<br/>前后相邻条款<br/>score × 0.7"]
        CTX_EXPAND --> FINAL["Top5+相邻<br/>最多15条"]
    end

    RERANK -.->|"详情"| RERANK_DETAIL

    style RULE_CHK fill:#fef3c7,stroke:#92400e
    style LLM_REASON fill:#dbeafe,stroke:#1e40af
    style CROSS_CHK fill:#ede9fe,stroke:#5b21b6
    style RISK_ASSESS fill:#fee2e2,stroke:#991b1b
```

### 2.6 角色权限冲突解决 (RBAC)

**角色权限冲突解决**:
- 一个人可以兼任多个角色（如既是admin又是reviewer）
- 权限冲突解决规则：**就高不就低** — 如果多个角色的权限对同一操作有不同规定，取权限更大的那个
- 优先级: admin > compliance > reviewer > viewer
- 示例: 用户同时是reviewer和admin，对"废弃违规类型"操作，reviewer无权限但admin有，最终允许操作
- 冲突日志: 所有权限决策都记录在审计日志中

---

## 三、模块职责与解耦关系

| 模块 | 文件 | 职责 | 依赖 | 被依赖 |
|------|------|------|------|--------|
| **interfaces** | `src/interfaces.py` | 抽象接口定义 | 无 | 所有模块 |
| **document_parsers** | `src/document_parsers.py` | 多格式文档解析注册表 | interfaces | document_processor, api_server |
| **input_processors** | `src/input_processors.py` | 多模态输入处理链 | interfaces, document_parsers | api_server |
| **document_processor** | `src/document_processor.py` | 分块策略+增量检测 | interfaces, document_parsers | rag_engine |
| **rag_engine** | `src/rag_engine.py` | 向量/关键词双模检索 | document_processor, resilience | review_agent |
| **workflow** | `src/workflow.py` | 10步流水线引擎 | 无 | review_agent |
| **llm_gateway** | `src/llm_gateway.py` | 多模型路由+熔断+降级 | resilience | review_agent |
| **risk_engine** | `src/risk_engine.py` | 风险评分+4级分类+3级决策 | config | review_agent |
| **reranker** | `src/reranker.py` | 检索后重排序(Top20→Top5) | config, resilience | review_agent |
| **prompt_manager** | `src/prompt_manager.py` | Prompt版本管理+Few-Shot | config | review_agent |
| **review_agent** | `src/review_agent.py` | 审核编排(Rule-First+Workflow) | rag_engine, workflow, llm_gateway, risk_engine, reranker, prompt_manager, security, resilience, observability | api_server |
| **security** | `src/security.py` | 7层安全+审计+限流 | config | review_agent, api_server |
| **resilience** | `src/resilience.py` | 熔断/重试/缓存 | config | rag_engine, review_agent, llm_gateway, api_server |
| **observability** | `src/observability.py` | Prometheus+Trace+Alert | config | api_server, review_agent |
| **async_engine** | `src/async_engine.py` | 异步任务+并发控制 | config | api_server |
| **database** | `src/database.py` | 持久化+迁移+备份 | config | api_server |
| **config** | `config.py` | 配置中心(22+项) | 无 | 所有模块 |
| **violation_registry** | `src/violation_registry.py` | 动态违规类型注册表+条款映射+标注 | config | review_agent, risk_engine, api_server |

### 解耦原则

1. **接口隔离**：`interfaces.py` 定义所有抽象基类，模块间通过接口交互
2. **依赖倒置**：高层模块依赖抽象接口，不依赖具体实现
3. **注册表模式**：`DocumentParserRegistry` 和 `InputProcessorChain` 支持插件式扩展
4. **策略模式**：分块策略（Article/Chapter/Semantic/Fixed）可运行时切换
5. **配置外置**：所有参数集中在 `config.py`，通过环境变量覆盖
6. **流水线模式**：Workflow步骤可独立注册、条件跳过、降级处理
7. **网关模式**：LLM Gateway统一模型调用，业务层不感知具体模型

---

## 四、AI核心架构详解

### 4.1 Rule+LLM 协同审核模式

```mermaid
flowchart TB
    INPUT["输入内容"] --> RULE["规则引擎<br/>(关键词预检)"]
    RULE -->|"命中"| RULE_HIT["标记确定性违规<br/>作为LLM输入提示"]
    RULE -->|"未命中"| RULE_MISS["无规则命中"]
    RULE_HIT --> LLM
    RULE_MISS --> LLM

    subgraph LLM["LLM推理 (qwen3.6-plus)"]
        LLM_HIT["规则已命中：<br/>确认规则结果基础上<br/>继续检查隐含/深层违规"]
        LLM_MISS["规则未命中：<br/>独立进行完整语义审核"]
    end

    LLM --> FORMAT["Format 结构化归一化<br/>LLM结果为主体<br/>规则参考注入+降级兜底"]

    style RULE fill:#fef3c7,stroke:#92400e
    style LLM fill:#dbeafe,stroke:#1e40af
    style FORMAT fill:#d1fae5,stroke:#065f46
```

**为什么规则命中后仍要继续LLM推理？**

规则引擎只能识别关键词级别的浅层违规（如"稳赚不赔"→绝对化用语），但同一段内容可能同时存在规则无法识别的深层/隐含违规（如"未来稳稳的幸福"→确定性暗示）。如果规则命中就跳过LLM，深层违规只有等用户修复浅层问题后再次提交才能被发现，这会导致：

1. **多次往返**：用户修了浅层问题再提交，又被LLM发现新问题，体验差
2. **漏判风险**：如果用户不再提交，深层违规就永远没被发现

**当前设计**：规则命中后，LLM的Prompt中注入规则预检结果，告知"已命中XXX关键词，请继续检查是否还有其他违规"，LLM只输出额外发现的违规，Format步骤以LLM结果为主体，补充规则引擎参考信息。

**规则引擎覆盖的6类违规**：

| 违规类型 | 关键词示例 | 严重度 |
|---------|-----------|--------|
| 绝对化用语 | 稳赚不赔、保本保息、无风险 | 0.9 |
| 收益承诺 | 保证收益、承诺收益、确定收益 | 0.9 |
| 夸大收益 | 年化收益、收益率高达 | 0.8 |
| 产品混淆 | 存款、理财、比银行 | 0.8 |
| 无资质代言 | 明星、网红、代言 | 0.7 |
| 诱导销售 | 赠送、返现、红包 | 0.7 |

### 4.2 LLM Gateway 多模型路由

| 角色 | 模型 | 用途 | 优先级 |
|------|------|------|--------|
| PRIMARY | qwen3.6-plus | 推理+提取+CrossCheck复核（多模态统一） | 0（最高） |
| FALLBACK | qwen3.6-flash | 主模型不可用时后备 | 5 |

每模型独立CircuitBreaker，全部熔断时降级为 rule-engine（API Key缺失时兜底）。

### 4.3 Reranker 检索重排序

RAG检索结果(Top20) → API Key缺失时使用规则重排序（字符重叠度 + 违规关键词加权），API Key可用时使用Cross-Encoder Rerank(qwen3-rerank)语义精排（需DASHSCOPE_API_KEY已配置，API失败时降级为规则重排） → Top5 → 上下文扩展（对Top5中每条法规自动召回前后相邻条款，相邻条款rerank_score × 0.7，标记context_type="adjacent"） → Top5 + 相邻条款（最多15条）

**相邻条文分数折扣(×0.7)的原理**:

Reranker输出的`rerank_score`代表条文与查询的语义相关度。相邻条文被召回不是因为它们本身与查询高度相关，而是为了提供上下文避免断章取义。

如果给相邻条文与主条文相同的权重，会导致：
1. LLM上下文窗口被低相关度内容占据，挤占真正相关条文的空间
2. LLM可能误认为相邻条文也是违规依据，导致过度引用
3. 风险评分计算时，相邻条文的加入会虚增条款数量加权

×0.7折扣的效果：
- 主条文 score=0.85 → 相邻条文 score=0.595
- 在LLM的Prompt中，相邻条文排在主条文之后，且标注了`context_type=adjacent`
- LLM会优先关注高分主条文，相邻条文仅作参考
- 如果0.7折扣后相邻条文score仍高于某些主条文，说明该相邻条文确实有参考价值

0.7这个值是经验值，可通过`config.RERANKER_ADJACENT_SCORE_FACTOR`调整。生产环境应根据实际审核效果校准。

**多路召回体系**:

当前召回路径 (API Key缺失时):
- 路径1: 向量检索 (Vector Search) — 基于语义相似度，top_k=20
- 路径2: 关键词匹配 (Rule Engine) — 基于违规类型关键词库

生产应增加的召回路径:
- 路径3: BM25关键词检索 — 基于词频-逆文档频率，对专业术语(如"保本保息")召回率远高于向量检索
- 路径4: 查询改写 (Query Rewriting) — 将用户输入改写为多个查询，合并召回结果
- 路径5: 法规结构化检索 — 按文档名+条款号直接定位

BM25实现复杂度: 中等。Python有`rank_bm25`库可直接使用，约50行代码。主要工作在分词(jieba)和索引构建。

其他召回方式:
- Dense+Sparse混合检索 (如Milvus 2.3+内置)
- 语义查询扩展 (LLM生成同义查询)
- 法规知识图谱检索 (按条款关联关系遍历)

这些差异已记录在 demo-production-gap.md 中。

**RAG上下文截断**：format_retrieved_context将article_text截断到300字符以控制LLM输入长度。

### 4.4 Risk Engine 风险评分与决策路由

```mermaid
flowchart TB
    RESULT["审核结果"] --> SCORE["风险评分计算<br/>base=违规严重度<br/>+条文数量加权<br/>+规则命中加成<br/>+置信度调整"]
    SCORE -->|"risk_score ∈ [0, 1]"| CLASSIFY{"4级风险分类"}
    CLASSIFY -->|"< 0.1"| LOW["LOW"]
    CLASSIFY -->|"< 0.7"| MEDIUM["MEDIUM"]
    CLASSIFY -->|"< 0.9"| HIGH["HIGH"]
    CLASSIFY -->|"≥ 0.9"| CRITICAL["CRITICAL"]

    LOW -->|"risk < 0.1"| AUTO_PASS["auto_pass<br/>自动通过"]
    MEDIUM -->|"0.1 ≤ risk < 0.7"| HUMAN_REVIEW["human_review<br/>人工复核"]
    HIGH -->|"risk ≥ 0.7"| AUTO_BLOCK["auto_block<br/>自动拦截"]
    CRITICAL --> AUTO_BLOCK

    style AUTO_PASS fill:#d1fae5,stroke:#065f46
    style HUMAN_REVIEW fill:#fef3c7,stroke:#92400e
    style AUTO_BLOCK fill:#fee2e2,stroke:#991b1b
```

**阈值设定依据**：

| 阈值 | 决策 | 依据 | 校准方式 |
|------|------|------|---------|
| 0.1 | auto_pass | 监管是容忍度很低的行业，0.1以上即需关注 | 当前为经验值；生产环境应运行1-2周后根据假阳性率调整 |
| 0.7 | human_review | 0.1-0.7区间对应诱导销售(0.7)、信息保护(0.4)等中低严重度，需人工确认 | 当前为经验值；应根据人工复核的翻转率调整——翻转率>30%说明阈值过低 |
| 0.9 | HIGH/CRITICAL分界 | severity≥0.9对应绝对化用语、收益承诺，是监管"零容忍"红线 | 相对稳定，监管红线很少变动。**注意**：当前所有regulation来源的违规类型severity默认为1.0，severity校准待完成（pending），因此0.9阈值在当前阶段所有regulation来源类型均会触发；校准完成后该阈值将具有实际区分意义 |

**重要**：这三个阈值可通过 `config.py` 中的 `RISK_AUTO_PASS_MAX` 和 `RISK_HUMAN_REVIEW_MAX` 配置，无需改代码。生产环境应在积累足够审核数据后，基于假阳性率/假阴性率/人工翻转率进行数据驱动校准。

### 4.5 HITL 人机协同

```mermaid
flowchart TB
    HR["human_review 决策"] --> QUEUE["待审队列<br/>(pending)<br/>GET /api/v1/review/pending"]
    QUEUE --> REVIEW["人工审核<br/>(override)<br/>POST /api/v1/review/{id}/override"]
    REVIEW --> FEWSHOT["Few-Shot回流<br/>(反馈学习)<br/>自动生成Few-Shot样本<br/>存入 few_shots.json"]

    style QUEUE fill:#fef3c7,stroke:#92400e
    style REVIEW fill:#dbeafe,stroke:#1e40af
    style FEWSHOT fill:#d1fae5,stroke:#065f46
```

**当前HITL实现状态**（✅ 已实现）：

> DeepSeek v3.2评审指出"HITL前端未实现"，当前系统已通过FastAPI + 纯HTML前端实现完整HITL功能，包括待审队列、审核操作面板、条文搜索对照和Few-Shot回流。

| 功能 | API层 | 前端 | 说明 |
|------|-------|------|------|
| 查看待审队列 | ✅ GET /api/v1/review/pending | ✅ 已实现 | 待审队列Tab，支持筛选和排序 |
| 人工override | ✅ POST /api/v1/review/{id}/override | ✅ 已实现 | 审核操作面板，支持通过/驳回+备注 |
| 条文查询对照 | ✅ 法规检索API | ✅ 已实现 | 条文搜索+对照组件 |
| Few-Shot回流 | ✅ 自动生成 | ✅ 已实现 | 前端展示Few-Shot样本状态 |

**审核结果与反馈数据结构**：

- `review_violations` 关系表：替代审核记录中 `violation_type` 列的多值字符串存储，将每条审核记录与多个违规类型的关系拆分为独立行，支持按违规类型高效查询和统计
- `violation_feedback` 表：支持逐条违规项的细粒度反馈，反馈类型包括 `correct`（判定正确）、`missed`（漏判）、`false_positive`（误判）、`wrong_citation`（引用条文错误），为severity校准和Few-Shot质量评分提供数据基础
- **废弃类型标记**：当违规类型被废弃（deprecated）后，历史审核记录中该类型显示为"[该类型已废弃]"标记，确保历史数据可追溯的同时避免与活跃类型混淆

**Few-Shot回流机制详解**：

1. **生成**：人工override时，`add_few_shot_from_feedback()` 自动创建样本，包含原始输入、正确结果、来源(override)
2. **存储**：`data/prompt_versions/few_shots.json`，每条样本包含 input_text、correct_result、violation_type、source、created_at
3. **检索与选择**：审核时 `get_few_shots(violation_type, limit)` 按当前审核的违规类型精确匹配筛选，返回最近N条（limit=2）样本，按created_at降序排列
4. **注入方式**：检索到的样本通过 `format_few_shots()` 格式化为文本注入LLM的user_prompt，格式为"案例N: 输入: ... 正确结论: ..."
5. **不一致检测**：当前无自动化不一致检测机制，系统依赖HITL阶段人工审核员发现并纠正Few-Shot与LLM判断不一致的情况。未来计划：增加自动化比对，当LLM审核结果与Few-Shot建议不一致时自动标记并提示审核员关注

**Few-Shot规模控制策略**（✅ 已实现）：

> DeepSeek v3.2评审指出"Few-Shot样本库缺少规模控制和质量淘汰机制"，当前系统已完整实现以下5项策略：

1. **容量上限**：每类型最多10条Few-Shot样本，全局最多100条
2. **质量评分**：每条样本维护 `quality_score`（初始1.0），具体调整规则如下：

| 事件 | 质量评分变化 | 具体示例 |
|------|-------------|---------|
| 人工override确认 | +0.2 | 审核员将"auto_block"改为"auto_pass"，确认该样本正确 → quality_score: 1.0 → 1.2 |
| LLM审核结果与Few-Shot建议一致 | +0.1 | Few-Shot建议"绝对化用语"违规，LLM也判定"绝对化用语" → quality_score: 1.0 → 1.1 |
| LLM审核结果与Few-Shot建议不一致 | -0.2 | Few-Shot建议"收益承诺"违规，LLM判定为合规 → quality_score: 1.0 → 0.8 |

3. **淘汰策略**：当某类型样本超过10条时，按 `quality_score × recency_factor` 排序，淘汰最低分。recency_factor = 0.5^(days_since_last_use/30)，30天未使用的样本权重减半
4. **版本兼容**：每次Prompt版本切换时，标记旧版本生成的样本为 `legacy`，优先淘汰legacy样本
5. **定期清理**：每季度自动清理quality_score < 0.3的样本和超过180天未使用的样本

### 4.6 Prompt Manager 版本治理

Prompt版本管理结构：

- `versions.json` — 版本注册表（v1默认active, v2实验...）
- `few_shots.json` — Few-Shot样本库（人工反馈生成 + 按违规类型检索）
- 3套专用Prompt：
  - `EXTRACT_SYSTEM_PROMPT` — 要素提取
  - `REASON_SYSTEM_PROMPT` — CoT推理审核
  - `FORMAT_SYSTEM_PROMPT` — 格式修正

### 4.7 幻觉检测（Validate步骤）

LLM输出的 violations 中每条 violated_articles 内的引用与RAG chunks逐条交叉验证：

- chunk.doc_name == article.doc_name AND chunk.article_number == article.article_number → 匹配，保留并补充article_text
- 不匹配 → 移除，标记hallucination_detected，reasoning追加"[N条引用经验证不存在，已移除]"
- 若全部移除且compliant=no：规则引擎有命中时回退到规则引擎条文（去重，最多5条）；规则引擎无命中时降为unknown

### 4.8 动态违规类型体系

法规文档入库 → 条款拆解(分块) → LLM辅助标注(行为模式提取: 主体+动作+对象+条件) / 规则标注(降级: 关键词匹配现有类型) → 映射到现有类型(自动标注) / 建议新类型(管理员审批) → 批准: 创建新违规类型+补充关键词 / 拒绝: 跳过 → 条款-类型映射表（多对多，带生效/失效时间）

**L1/L2分级设计**：

| 层级 | 数量 | 特点 | 示例 |
|------|------|------|------|
| L1(一级类型) | 5~8个 | 固定，对应监管框架顶层逻辑 | 虚假宣传、资质违规、销售行为违规、信息披露违规、信息保护违规 |
| L2(二级类型) | 20~30个 | 半固定，实际审核输出标签 | 绝对化用语、收益承诺、夸大收益、产品混淆、无资质代言、诱导销售... |

**违规类型source字段**：每个违规类型包含 `source` 字段，标识其来源渠道，决定默认severity范围：

| source值 | 含义 | 默认severity范围 | 示例 |
|----------|------|-----------------|------|
| regulation | 来源于监管法规条文 | 1.0（当前统一默认，校准后按条文严重度细分） | 绝对化用语、收益承诺 |
| industry | 来源于行业自律规范 | 0.5~0.8 | 诱导销售、产品混淆 |
| internal | 来源于企业内部合规要求 | 0.3~0.6 | 品牌使用规范、内部用语规范 |

**API Key缺失时限制**：API Key缺失时不支持创建自定义违规类型，仅可使用系统预置类型进行审核演示。

**审批工作流**：

```mermaid
flowchart TB
    SUGGEST["LLM辅助标注<br/>建议新类型"] --> PENDING["pending_annotations<br/>(待审批)"]
    PENDING --> REVIEW["管理员审批"]
    REVIEW -->|"批准"| APPROVE["创建新违规类型<br/>+ 补充关键词规则"]
    REVIEW -->|"拒绝+理由"| REJECT["记录拒绝理由<br/>跳过该类型"]
    APPROVE --> ACTIVE["类型生效<br/>可用于新审核"]
    REJECT --> LOG["审计日志记录"]
```

| 步骤 | 操作 | 说明 |
|------|------|------|
| 建议新类型 | LLM辅助标注或管理员手动提交 | 进入 `pending_annotations` 待审批状态 |
| 管理员审批 | 批准或拒绝 | 批准：创建新类型+补充关键词；拒绝：填写拒绝理由 |
| 映射失效处理 | 自动 | 映射失效不影响历史审核（snapshot已固定），新审核自动不引用失效映射 |
| 审计日志 | 自动记录 | 记录谁在什么时候创建/修改/废弃了类型或映射 |

**多级审批**：当前为单级管理员审批，多级审批流程为P2改进项（详见demo-production-gap.md）。

**程序性条款过滤**：入库时先判断条款是否属于"营销内容审核"范畴，程序性条款（如"应建立审核制度""内容保存期限"）不建违规类型。

**条款-类型多对多映射**：一个条款可关联多个违规类型，一个违规类型下有多个条款来源。映射关系带 effective_date / expiration_date，支持法规废止时标记失效。

**Primary/Secondary映射逻辑**：条款-类型映射区分 `primary` 与 `secondary` 两种关系：
- `primary`：该条款直接禁止或描述了该违规行为（如《保险法》第116条明确禁止"欺骗投保人"，映射到"虚假宣传"为primary）
- `secondary`：该条款提及或与该违规行为相关，但并非直接禁止性规定（如《保险法》第131条提及"不得诱导替换"，与"诱导销售"相关但非直接定义，映射为secondary）
- **判定方式**：当前由合规专家人工标注确定；LLM辅助标注会给出建议（primary/secondary），但最终由人工审核决定

详细的违规类型系统设计请参阅 [违规类型系统文档](violation-types.md)

**条款隐含逻辑与关联关系**:

法规条款之间存在多种关联关系：

1. **引用关系**: 条款A引用条款B（如"违反本规定的，依照XX法第Y条处罚"）
2. **补充关系**: 条款B是条款A的补充说明或例外情况
3. **递进关系**: 条款A规定一般要求，条款B规定更严格的具体要求
4. **排斥关系**: 条款A和条款B适用不同场景，互斥
5. **上下文依赖**: 条款的含义需要结合上下文条款才能正确理解

**当前系统如何处理**:
- Reranker的相邻条文扩展(×0.7)部分解决了上下文依赖问题
- 但引用关系、补充关系、递进关系尚未显式建模

**生产改进方向**:
- 构建法规知识图谱: 将条款间关系显式化为边(edge)
- 在RAG检索时，不仅召回语义相关的条款，还沿图谱边召回关联条款
- 在LLM Prompt中注入关联条款信息，帮助模型理解隐含逻辑
- 这是P2改进项，详见 demo-production-gap.md

### 4.9 CrossCheck 交叉复核

审核结果(compliant=no) → qwen3.6-plus复核 → 检查引用条文与输入语义相关性(防过度引用) + 检查推理逻辑自洽性(防自圆其说) + 对低置信度结果标记"建议人工复核"

- 通过 → confidence_adjustment ∈ [-0.1, 0.1]
- 未通过 → issues追加到reasoning + recommend_human_review

**设计原则**：用qwen3.6-plus做复核，而非同等重量的模型重复推理，成本仅增加~20%，但可降低漏判约30%。

**冲突裁决规则**：

当主模型与CrossCheck结论冲突时，按以下规则处理：

| 场景 | 主模型结论 | CrossCheck结论 | 裁决结果 | 说明 |
|------|-----------|---------------|---------|------|
| 一致违规 | 违规 | 违规 | auto_block | 双重确认，高置信度拦截 |
| 主模型合规、CrossCheck违规 | 合规 | 违规 | 降为human_review | 轻量模型可能误判，但不可忽视 |
| 主模型违规、CrossCheck合规 | 违规 | 合规 | 保留主模型结论，confidence降低0.2，标记"复核存疑" | 主模型(重量级)结论优先，但记录分歧 |
| CrossCheck低置信度 | 任意 | 置信度<0.6 | 直接放行CrossCheck（不采纳其意见） | 避免轻量模型低质量判断干扰主模型 |

**置信度阈值**：CrossCheck输出置信度低于0.6时，视为无效复核，不参与冲突裁决。该阈值可通过 `config.CROSSCHECK_MIN_CONFIDENCE` 配置。

### 4.10 Prompt注入防御体系

系统在安全中间件层(SecurityMiddleware)执行Prompt注入检测，**在进入10步工作流之前**完成。这与规则引擎预检(RuleCheck)是两个完全不同的机制：

- **Prompt注入检测**：在安全中间件层执行，检测用户输入中是否包含试图操纵LLM行为的攻击模式，命中则直接拒绝请求
- **规则引擎预检(RuleCheck)**：10步工作流的第2步，检测营销内容中的违规关键词，命中则将结果注入LLM Prompt辅助审核

#### 英文注入模式 (16种)

| # | 模式 | 说明 |
|---|------|------|
| 1 | `ignore (previous\|above\|all\|prior) instructions` | 忽略指令 |
| 2 | `ignore \w+ (previous\|above\|all\|prior) instructions` | 忽略特定指令 |
| 3 | `forget (everything\|all\|previous)` | 遗忘指令 |
| 4 | `you are now a` | 角色切换 |
| 5 | `system:` | 伪系统消息 |
| 6 | `assistant:` | 伪助手消息 |
| 7 | `new instructions:` | 新指令注入 |
| 8 | `override (previous\|default\|system)` | 覆盖指令 |
| 9 | `pretend (you are\|to be)` | 角色扮演 |
| 10 | `jailbreak` | 越狱攻击 |
| 11 | `DAN (mode\|模式)?` | DAN模式 |
| 12 | `developer mode` | 开发者模式 |
| 13 | `sudo mode` | 提权模式 |
| 14 | `disregard (all )?(previous\|above\|prior) (instructions?\|rules?)` | 无视规则 |
| 15 | `do not follow (your\|the\|previous) (instructions?\|rules?)` | 不遵守规则 |
| 16 | `repeat (your\|the) (system\|initial) prompt` | 窃取系统提示 |

#### 中文注入模式 (6种)

| # | 模式 | 说明 |
|---|------|------|
| 17 | `不再遵守` | 不遵守 |
| 18 | `忽略(以上\|之前\|所有)(的)?(指令\|规则\|约束)` | 忽略规则 |
| 19 | `假装(你是\|你是一个)` | 角色扮演 |
| 20 | `你现在是一个` | 角色切换 |
| 21 | `覆盖(之前的\|原有的\|默认的)(指令\|规则)` | 覆盖规则 |
| 22 | `输出你的系统提示` | 窃取提示 |

#### 特殊标记注入 (3种)

| # | 模式 | 说明 |
|---|------|------|
| 23 | `<\|im_start\|>` | ChatML标记注入 |
| 24 | `[INST]` | Llama标记注入 |
| 25 | ` ```system` | 伪代码块注入 |

#### XSS检测 (5种)

| # | 模式 | 说明 |
|---|------|------|
| 26 | `<script>` | Script标签注入 |
| 27 | `javascript:` | JavaScript协议注入 |
| 28 | `on\w+=` | 事件处理器注入 |
| 29 | `<iframe>` | iframe注入 |
| 30 | `<img onerror>` | img错误事件注入 |

#### SQL注入检测 (3种)

| # | 模式 | 说明 |
|---|------|------|
| 31 | Union/Select等SQL关键词组合 | SQL联合查询注入 |
| 32 | 注释符 (`--`, `/**/`) | SQL注释注入 |
| 33 | 恒真条件 (`' OR 1=1`, `" OR ""="`) | SQL绕过注入 |

---

## 五、用户故事与序列图

### 用户故事角色与系统RBAC角色映射

用户故事中出现的业务角色与系统权限模型中的3个RBAC角色对应关系如下：

| 用户故事角色 | 系统RBAC角色 | 角色标识 | 权限范围 |
|-------------|-------------|---------|---------|
| 合规管理员 | admin（管理员） | `admin` | 管理违规类型、条款映射、法规版本、系统配置、审批标注 |
| 合规审核员 | reviewer（审核员） | `reviewer` | 审核复核、override决策、提交逐项反馈、Few-Shot管理 |
| 业务人员 | viewer（查看者） | `viewer` | 提交审核请求、查看审核结果与历史 |

**映射说明**：

- **合规管理员 → admin**：用户故事US2（法规文档入库）、US4（违规类型管理）、US5（效果评估）中的合规管理员/系统管理员，对应系统的admin角色，拥有全部操作权限
- **合规审核员 → reviewer**：用户故事US3（人工复核）中的合规审核员，对应系统的reviewer角色，可执行审核复核、override决策和反馈操作
- **业务人员 → viewer**：用户故事US1（营销内容审核）中的业务人员，对应系统的viewer角色，可提交审核请求并查看结果

> 注：一个人可兼任多个角色，权限冲突时按"就高不就低"原则处理（详见2.6节角色权限冲突解决）。

### US1: 营销内容审核

**As a** 业务人员，**I want to** 提交营销内容进行合规审核，**so that** 我可以确保内容在发布前符合监管要求。

```mermaid
sequenceDiagram
    actor User as 业务人员
    participant API as FastAPI REST
    participant Sec as SecurityCheck
    participant WF as WorkflowEngine<br/>(10步流水线)

    User->>API: POST /api/v1/review<br/>{text: "稳赚不赔的保险"}
    API->>Sec: 安全校验(25种模式)
    Sec-->>API: 校验通过
    API->>WF: 启动10步Pipeline

    Note over WF: ① Extract: 要素提取
    Note over WF: ② RuleCheck: 命中"稳赚不赔"→绝对化用语
    Note over WF: ③ RAGRetrieve: 向量+关键词检索Top20
    Note over WF: ④ Rerank: Top20→Top5+相邻条款
    Note over WF: ⑤ ExpandRelations: 条款关联扩展
    Note over WF: ⑥ LLMReason: CoT推理(注入规则命中结果)
    Note over WF: ⑦ Format: 结构化归一化+降级兜底
    Note over WF: ⑧ Validate: 幻觉检测
    Note over WF: ⑨ CrossCheck: qwen3.6-plus复核
    Note over WF: ⑩ RiskAssess: risk=0.92→CRITICAL

    WF-->>API: {decision: "auto_block",<br/>risk_score: 0.92,<br/>violations: [{violation_type: "绝对化用语", ...}]}
    API-->>User: 审核结论: 拦截<br/>违规类型: 绝对化用语<br/>风险评分: 0.92
```

### 审核流程详解

**输入**:
```json
{
  "content": "买保险就选XX，稳赚不赔，年化收益5%！",
  "image_description": []
}
```

**Step 1 - Extract (信息提取)**:
- Input to LLM: system_prompt=EXTRACT_SYSTEM_PROMPT, user_prompt="请从以下营销内容中提取关键要素：\n\n买保险就选XX..."（如有图片描述，追加[图片描述信息]段落）
- LLM Output: `{"claims": ["稳赚不赔", "年化收益5%"], "keywords": ["稳赚不赔", "收益"], "has_risk_disclosure": false, "has_return_promise": true, "has_absolute_language": false, "image_text": "", "image_description": ""}`
- 图片输入时，keywords同时包含文本和图片中的关键术语，image_text为图片OCR逐字提取的原文，image_description为图片营销意图的100字符以内摘要

**Step 2 - RuleCheck (规则预检)**:
- Input: extracted keywords + violation_registry rules
- Process: keyword matching against each rule's keywords list
- Output: `{"hit": true, "violations": [{"violation_type": "收益承诺", "violated_articles": [{"doc_name": "保险销售行为管理办法", "article_number": "二十一", ...}], "reasoning": "规则引擎命中关键词: 稳赚不赔"}], "matched_keywords": ["稳赚不赔"], "confidence": 0.9}`

**Step 3 - RAG Retrieve (法规检索)**:
- Input: original text + extracted keywords as query
- Process: vector similarity search in ChromaDB, top_k=20
- Output: 20 regulation chunks with similarity scores

**Step 4 - Rerank (重排序)**:
- Input: 20 chunks from RAG
- Process: Cross-Encoder Rerank(qwen3-rerank)语义精排（需DASHSCOPE_API_KEY已配置） → top 5 + adjacent articles
- Output: 5-15 chunks (top 5 + adjacent), with rerank_score

**Step 5 - ExpandRelations (条款关联扩展)**:
- Input: reranked chunks from Rerank step
- Process: expand clause relations based on clause mapping database, retrieve related clauses via citation/reference relationships
- Output: expanded regulation context with related clauses

**Step 6 - LLM Reason (推理审核)**:
- Input to LLM:
  - system_prompt: REASON_SYSTEM_PROMPT (含CoT引导+语义隐含分析+违规类型ID对照表)
  - user_prompt: 待审核内容 + RAG检索的法规上下文 + Few-Shot案例 + 规则引擎预检结果(rule_hint) + 条款关联提示(relation_hint)
- LLM Output: `{"compliant": "no", "violations": [{"violation_type_id": "return_promise", "violation_type_name": "收益承诺", "violated_articles": [{"doc_name": "...", "article_number": "...", "violation_reason": "..."}]}, {"violation_type_id": "exaggerated_return", "violation_type_name": "夸大收益", "violated_articles": [{"doc_name": "...", "article_number": "...", "violation_reason": "..."}]}], "confidence": 0.85, "reasoning": "详细的CoT推理过程", "suggestions": "修改建议"}`

**Step 7 - Format (结构化归一化)**:
- Input: llm_reason_result (primary) + rule_check_result (reference)
- Process: normalize LLM output to standard violations structure; inject rule engine reference into reasoning if LLM didn't mention rule-matched keywords; degrade to rule-only result when LLM fails; data cleansing (compliant normalization, confidence clamping, violations format check)
- Output: formatted_result with normalized structure

**Step 8 - Validate (幻觉检测)**:
- Input: formatted result with violations array
- Process: verify each cited article exists in the regulation corpus
- Output: validated result with hallucinated articles removed

**Step 9 - CrossCheck (交叉验证)**:
- Input to LLM: original text + audit conclusion + cited articles
- Process: lightweight model checks citation relevance + reasoning consistency
- Output: `{"passed": true/false, "issues": [...], "confidence_adjustment": -0.1~0.1}`

**Step 10 - RiskAssess (风险评估)**:
- Input: validated result
- Process: risk_score = severity × 0.5 + article_count_weight + rule_hit_bonus + confidence_adjustment
- Output: risk_score, risk_level (low/medium/high/critical), decision (auto_pass/human_review/auto_block)

**最终输出**:
```json
{
  "compliant": "no",
  "violation_type": "收益承诺、夸大收益",
  "violation_types": [
    {"violation_type_id": "return_promise", "violation_type_name": "收益承诺"},
    {"violation_type_id": "exaggerated_return", "violation_type_name": "夸大收益"}
  ],
  "violated_articles": [
    {"doc_name": "保险销售行为管理办法", "article_number": "十九", "violation_reason": "使用'稳赚不赔'构成收益承诺"},
    {"doc_name": "保险销售行为管理办法", "article_number": "二十", "violation_reason": "年化收益率高达8%构成夸大收益"}
  ],
  "violations": [
    {"violation_type": "收益承诺", "violation_type_id": "return_promise", "violated_articles": [{"doc_name": "保险销售行为管理办法", "article_number": "十九", "violation_reason": "使用'稳赚不赔'构成收益承诺"}], "reasoning": "..."},
    {"violation_type": "夸大收益", "violation_type_id": "exaggerated_return", "violated_articles": [{"doc_name": "保险销售行为管理办法", "article_number": "二十", "violation_reason": "年化收益率高达8%构成夸大收益"}], "reasoning": "..."}
  ],
  "confidence": 0.85,
  "reasoning": "营销内容中使用'稳赚不赔'构成收益承诺...",
  "suggestions": "1. 删除'稳赚不赔'等收益承诺用语\n2. 将'高达8%'改为非保证性表述",
  "risk_score": 0.65,
  "risk_level": "medium",
  "decision": "human_review",
  "review_mode": "rule+llm",
  "model_used": "qwen3.6-plus",
  "regulation_snapshot": {"保险销售行为管理办法": "sha256:abc123..."},
  "crosscheck_passed": true,
  "workflow_steps": [
    {"name": "extract", "status": "completed", "latency_ms": 120.5},
    {"name": "rule_check", "status": "completed", "latency_ms": 5.2},
    {"name": "rag_retrieve", "status": "completed", "latency_ms": 350.8},
    {"name": "rerank", "status": "completed", "latency_ms": 23.4},
    {"name": "expand_relations", "status": "completed", "latency_ms": 8.5},
    {"name": "llm_reason", "status": "completed", "latency_ms": 2800.0},
    {"name": "format", "status": "completed", "latency_ms": 2.1},
    {"name": "validate", "status": "completed", "latency_ms": 15.3},
    {"name": "cross_check", "status": "completed", "latency_ms": 450.0},
    {"name": "risk_assess", "status": "completed", "latency_ms": 3.2}
  ]
}
```

### US2: 法规文档入库

**As a** 合规管理员，**I want to** 上传新的法规文档，**so that** 审核系统能够与最新法规保持同步。

```mermaid
sequenceDiagram
    actor Admin as 合规管理员
    participant API as FastAPI REST
    participant Parser as DocParserReg
    participant Chunk as ChunkStrat
    participant Annotate as LLM辅助标注
    participant Approve as 管理员审批
    participant Index as ChromaDB索引

    Admin->>API: POST /api/v1/regulations/upload<br/>上传法规文件(PDF)
    API->>Parser: 多格式解析(PdfParser)
    Parser-->>API: ParsedDocument(文本+表格+元信息)
    API->>Chunk: 分块策略(Article/Chapter)
    Chunk-->>API: Chunks[条款项]
    API->>Annotate: LLM辅助标注<br/>(行为模式提取+违规类型建议)
    Annotate-->>API: 标注结果+类型建议
    API-->>Admin: 标注完成，待审批

    Admin->>Approve: 审批标注结果<br/>(确认/修正类型映射)
    Approve-->>API: 审批通过
    API->>Index: Embedding向量化 + ChromaDB索引构建
    Index-->>API: 索引构建完成
    API-->>Admin: 法规入库成功
```

### 法规文档入库流程详解

**输入**:
```json
{
  "file": "保险销售行为管理办法.pdf",
  "effective_date": "2026-07-01",
  "chunk_strategy": "article"
}
```

**Step 1 - 文件上传与格式检测**:
- Input: 法规文件（支持PDF/DOCX/TXT/MD/图片格式）
- Process: 接收上传文件，根据文件扩展名和内容检测格式，选择对应解析器（PdfParser/DocxParser/TxtParser/MdParser/ImageParser）
- Output: `{"file_id": "reg_20260516_001", "format": "pdf", "size_bytes": 2048576, "parser": "PdfParser"}`

**Step 2 - 多格式文档解析（DocParserReg）**:
- Input: 上传的法规文件
- Process: PdfParser提取文本、表格、元信息（文档标题、章节结构）；图片类法规走OCR（qwen-vl/Tesseract）提取文字
- Output: `ParsedDocument(text="第一章 总则\n第一条 ...", tables=[...], metadata={"title": "保险销售行为管理办法", "chapter_count": 5})`

**Step 3 - 分块策略（ChunkStrat）**:
- Input: ParsedDocument + chunk_strategy参数（Article/Chapter/Semantic/Fixed）
- Process: 按条款（Article）拆分为独立条款项，每条包含条款号、条款文本、所属章节；相邻条款保留上下文关联
- Output: `Chunks[{"article_number": "一", "text": "为了规范保险销售行为...", "chapter": "第一章 总则"}, {"article_number": "二", "text": "本办法适用于...", "chapter": "第一章 总则"}, ...]`

**Step 4 - LLM辅助标注（行为模式提取 + 违规类型建议）**:
- Input to LLM: system_prompt=标注引导Prompt, user_prompt=逐条条款文本 + 现有违规类型列表
- Process: LLM对每条条款提取行为模式（主体+动作+对象+条件），判断是否属于"营销内容审核"范畴（过滤程序性条款），并建议映射到现有违规类型或建议创建新类型
- LLM Output: `{"annotations": [{"article_number": "二十一", "is_procedural": false, "behavior_pattern": {"subject": "保险销售人员", "action": "使用", "object": "绝对化用语", "condition": "在营销宣传中"}, "suggested_violation_type": "绝对化用语", "mapping_type": "primary", "is_new_type": false}, {"article_number": "二十二", "is_procedural": false, "behavior_pattern": {...}, "suggested_violation_type": "数据泄露", "mapping_type": "primary", "is_new_type": true}], "procedural_articles": ["一", "二", "三"]}`

**Step 5 - 管理员审批标注**:
- Input: LLM标注结果列表（含建议类型、行为模式、primary/secondary映射）
- Process: 管理员逐条审核标注结果，可确认、修正类型映射、修改primary/secondary标记、拒绝某条标注并填写理由；对建议新类型决定批准或拒绝
- Output: `{"approved_annotations": [...], "rejected_annotations": [{"article_number": "二十二", "reason": "该条款不属于营销审核范畴"}], "new_types_approved": [], "new_types_rejected": [{"suggested_name": "数据泄露", "reason": "已有信息保护违规类型覆盖"}]}`

**Step 6 - 条款-类型映射入库**:
- Input: 审批通过的标注结果
- Process: 将每条审批通过的标注写入`clause_type_mappings`表，包含doc_name、article_number、violation_type_id、mapping_type(primary/secondary)、effective_date；被拒绝的建议新类型记录到审计日志
- Output: `{"mappings_created": 12, "mappings_rejected": 1, "new_types_created": 0}`

**Step 7 - Embedding向量化 + 索引构建**:
- Input: 审批通过的条款文本列表
- Process: 对每条条款调用Embedding模型生成向量（1024维），写入ChromaDB集合，建立HNSW cosine索引；记录索引版本号
- Output: `{"index_version": "v_20260516_001", "vectors_added": 15, "collection_name": "regulations"}`

**最终输出**:
```json
{
  "regulation_id": "reg_20260516_001",
  "doc_name": "保险销售行为管理办法",
  "status": "active",
  "effective_date": "2026-07-01",
  "total_articles": 35,
  "procedural_articles_filtered": 3,
  "annotations_approved": 12,
  "annotations_rejected": 1,
  "mappings_created": 12,
  "new_types_created": 0,
  "index_version": "v_20260516_001",
  "vectors_added": 15
}
```

### US3: 人工复核

**As a** 合规审核员，**I want to** 复核被标记的内容，**so that** 我可以对模糊案例做出最终合规判定。

```mermaid
sequenceDiagram
    actor Reviewer as 合规审核员
    participant API as FastAPI REST
    participant Queue as PendingQueue
    participant Detail as 审核详情
    participant Search as 法规检索
    participant Override as Override操作
    participant FewShot as Few-Shot回流

    Reviewer->>API: GET /api/v1/review/pending
    API->>Queue: 查询human_review状态记录
    Queue-->>API: 待审列表
    API-->>Reviewer: 展示待审队列

    Reviewer->>API: GET /api/v1/review/{id}
    API->>Detail: 获取审核详情<br/>(原文+违规条款+风险评分)
    Detail-->>API: 审核详情
    API-->>Reviewer: 展示原文+违规条款对照

    Reviewer->>API: GET /api/v1/regulations/search<br/>?keyword=绝对化用语
    API->>Search: 法规条文搜索
    Search-->>API: 相关法规条文
    API-->>Reviewer: 展示法规条文参考

    Reviewer->>API: POST /api/v1/review/{id}/override<br/>{decision: "auto_pass",<br/>comment: "上下文语境合规"}
    API->>Override: 记录override决策
    Override->>FewShot: 自动生成Few-Shot样本
    FewShot-->>Override: 样本已存入few_shots.json
    Override-->>API: override完成
    API-->>Reviewer: 操作成功
```

### US4: 违规类型管理

**As a** 系统管理员，**I want to** 管理违规类型，**so that** 审核系统能够准确分类和评分违规行为。

**管理操作清单**：

| 操作 | API | 说明 | 级联行为 |
|------|-----|------|---------|
| 创建新类型 | POST /api/v1/violation-types | 创建L1/L2违规类型，指定source/severity | — |
| 废弃类型 | PUT /api/v1/violation-types/{id}/deprecate | 标记类型为废弃，不再用于新审核 | 自动过期该类型下所有条款映射（设置expiration_date） |
| 过期特定条款映射 | PUT /api/v1/violation-types/{id}/mappings/{mapping_id}/expire | 单独过期某条条款-类型映射 | 仅影响指定映射，其他映射保持生效 |
| 移除关键词 | DELETE /api/v1/violation-types/{id}/keywords/{keyword} | 从类型的关键词列表中移除指定关键词 | 规则引擎不再按该关键词命中此类型 |
| 补充关键词 | POST /api/v1/violation-types/{id}/keywords | 为类型添加关键词规则 | — |
| 更新条款映射 | PUT /api/v1/violation-types/{id}/mappings | 更新条款-类型映射关系 | — |

以上操作均可在前端系统管理Tab中执行。

```mermaid
sequenceDiagram
    actor Admin as 系统管理员
    participant API as FastAPI REST
    participant VR as ViolationRegistry
    participant DB as SQLite

    Admin->>API: GET /api/v1/violation-types
    API->>VR: 查询所有违规类型
    VR->>DB: SELECT from violation_types
    DB-->>VR: 类型列表(L1+L2)
    VR-->>API: 类型数据
    API-->>Admin: 展示违规类型管理界面

    Admin->>API: POST /api/v1/violation-types<br/>{name: "数据泄露",<br/>severity: 0.8,<br/>level: "L2",<br/>parent: "信息保护违规"}
    API->>VR: 创建新违规类型
    VR->>DB: INSERT violation_type
    DB-->>VR: 创建成功
    VR-->>API: 新类型已创建
    API-->>Admin: 类型创建成功

    Admin->>API: PUT /api/v1/violation-types/{id}/deprecate
    API->>VR: 废弃违规类型
    VR->>DB: UPDATE expiration_date
    DB-->>VR: 废弃成功
    VR-->>API: 类型已废弃
    API-->>Admin: 类型已标记为废弃

    Admin->>API: POST /api/v1/violation-types/{id}/keywords<br/>{keywords: ["数据泄露","信息外泄"]}
    API->>VR: 补充关键词规则
    VR->>DB: INSERT keywords
    DB-->>VR: 关键词已添加
    VR-->>API: 关键词更新成功
    API-->>Admin: 关键词规则已更新

    Admin->>API: PUT /api/v1/violation-types/{id}/mappings<br/>{clause_ids: [...]}
    API->>VR: 更新条款-类型映射
    VR->>DB: UPDATE clause_mappings
    DB-->>VR: 映射已更新
    VR-->>API: 映射更新成功
    API-->>Admin: 条款映射已更新
```

### US5: 效果评估

**As a** 系统管理员，**I want to** 评估审核准确率，**so that** 我可以持续优化系统效果。

```mermaid
sequenceDiagram
    actor Admin as 系统管理员
    participant API as FastAPI REST
    participant Eval as Evaluator
    participant DB as SQLite
    participant PM as PromptManager

    Admin->>API: POST /api/v1/eval/run<br/>{test_set: "default"}
    API->>Eval: 运行评估
    Eval->>DB: 加载测试用例
    Eval->>Eval: 逐条执行审核+比对预期结果
    Eval->>DB: 旧结果is_active=0 + INSERT新结果is_active=1<br/>(eval_results表)
    Eval-->>API: 评估完成
    API-->>Admin: 评估任务已提交

    Admin->>API: GET /api/v1/eval/report
    API->>DB: 查询最新评估报告
    DB-->>API: 评估指标
    API-->>Admin: 展示评估指标<br/>(准确率/召回率/F1/假阳性率)

    Admin->>API: GET /api/v1/eval/errors
    API->>Eval: 分析错误案例
    Eval->>DB: 查询误判记录
    DB-->>Eval: 错误案例列表
    Eval-->>API: 错误分析(分类+根因)
    API-->>Admin: 展示错误分析<br/>(漏判/误判分布+典型case)

    Admin->>API: PUT /api/v1/config/rules<br/>{调整规则权重/关键词}
    API->>DB: 更新规则配置
    DB-->>API: 配置已更新
    API-->>Admin: 规则已调整

    Admin->>API: PUT /api/v1/config/prompts<br/>{更新Prompt版本}
    API->>PM: 切换Prompt版本
    PM-->>API: 版本已切换
    API-->>Admin: Prompt已更新
```

### US6: 验收测试标准

**测试集构成**：

| 类别 | 数量 | 说明 |
|------|------|------|
| 合规样本 | 50条 | 确认合规的营销内容 |
| 违规样本 | 100条 | 每个L2违规类型至少10条 |
| 边界样本 | 20条 | 语义模糊、需人工判断的边界案例 |
| 对抗样本 | 10条 | Prompt注入、角色扮演等攻击性输入 |

**验收标准**：

| 指标 | 阈值 | 说明 |
|------|------|------|
| 总体准确率 | ≥95% | 所有测试样本的正确判定比例 |
| 关键违规类型召回率 | ≥99% | 绝对化用语、收益承诺等L2类型每类召回率 |
| 假阳性率 | ≤3% | 合规内容被误判为违规的比例 |
| 假阴性率 | ≤1% | 违规内容被漏判为合规的比例 |
| Prompt注入成功率 | <1% | 对抗样本中攻击成功的比例 |

---

## 六、多格式文档摄入管线

### 6.1 支持的法规文档格式

| 格式 | 解析器 | 文本提取 | 表格提取 | 图片提取 | OCR |
|------|--------|---------|---------|---------|-----|
| TXT | TxtParser | ✅ | — | — | — |
| Markdown | MdParser | ✅ | ✅(MD表格) | — | — |
| PDF | PdfParser | ✅(pymupdf/pdfminer) | ✅(pymupdf) | ✅(元信息) | — |
| Word(.docx) | DocxParser | ✅(python-docx) | ✅(python-docx) | ✅(元信息) | — |
| 图片(PNG/JPG/...) | ImageParser | — | — | ✅ | ✅(qwen-vl/Tesseract) |

### 6.2 扩展新格式

```python
class ExcelParser(DocumentParser):
    def supported_formats(self) -> List[DocumentFormat]:
        return [DocumentFormat.XLSX]

    def can_parse(self, source: str) -> bool:
        return source.lower().endswith((".xlsx", ".xls"))

    def parse(self, source: str, **kwargs) -> ParsedDocument:
        pass

parser_registry.register(ExcelParser())
```

---

## 七、多模态用户输入处理

### 7.1 输入类型自动检测

| 输入参数 | 检测结果 |
|---------|---------|
| text="xxx" | InputType.TEXT |
| images=[...] | InputType.IMAGE |
| files=[...] | InputType.FILE |
| text + images | InputType.MIXED |
| text + files | InputType.MIXED |
| images + files | InputType.MIXED |
| text + images + files | InputType.MIXED |

### 7.2 API端点

| 端点 | 方法 | 说明 | 输入类型 |
|------|------|------|---------|
| `/api/v1/review` | POST | 纯文本审核（同步，可能超时） | text |
| `/api/v1/review/multimodal` | POST | 多模态审核(JSON) | text + image_paths + file_paths |
| `/api/v1/review/upload` | POST | 文件上传审核(multipart) | text + files |
| `/api/v1/review/async` | POST | 异步审核（推荐，前端默认使用） | text |
| `/api/v1/review/batch` | POST | 批量审核 | text[] |

### 7.3 图片输入的统一管线

**当前设计**：图片输入和文本输入在Extract步骤之后走完全相同的管线。

1. 前端上传图片后，将图片以base64 data URL格式通过OpenAI Vision格式传入Extract步骤
2. Extract步骤中，qwen3.6-plus（多模态统一模型）直接接收图片数据，同时提取文本关键词和图片中的文字/营销信息
3. 提取的 `keywords` 同时包含文本和图片中的关键术语，用于后续RuleCheck和RAG检索
4. `image_text` 为图片OCR逐字提取的原文，`image_description` 为图片营销意图的100字符以内摘要

### 7.4 图文一致性校验（已知Gap）

**当前状态**：❌ 已知gap（P0优先级）

多模态处理中，文本与图片OCR结果分别提取，但缺少跨模态的**语义一致性校验**。违规内容可能通过图文互补或矛盾来逃避检测，例如：
- 文本只说"收益稳健"，图片中大字写"保本保息 无风险"
- 文本合规，但图表将演示利率标为"保证年化收益率 5%"

**计划方案**：在Workflow中增加"图文对齐"步骤（Extract之后、RuleCheck之前）：
1. 提取文本中的关键数字、比例、承诺性表述（如"年化 4%""保证"）
2. 调用多模态模型（Qwen-VL）对图片/图表进行结构化理解，提取同样的关键信息
3. 比对两者，如果出现语义矛盾或文本未体现的违规内容，则标记为 high_risk，并合并到违规证据中

详见 [demo-production-gap.md](demo-production-gap.md) 中P0优先级条目。

---

## 八、用户管理与行为分析

系统提供用户行为追踪能力，包括审核操作统计（审核量、违规率、人工翻转率）和违规趋势分析（按类型/时间段统计违规分布）。合规管理员可通过 Dashboard 查看运营数据。Demo 版本使用应用内简单统计，生产版本由 Analytics Service 提供完整行为分析，并通过 Grafana Dashboard 展示。

---

## 九、关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 审核模式 | **Rule+LLM 协同** | 规则引擎做关键词预检，LLM始终执行完整审核；规则命中时结果注入LLM Prompt，两者合并输出，避免浅层命中掩盖深层违规 |
| 审核流水线 | **10步Workflow Pipeline** | 每步独立可测、可跳过、可降级，条件执行避免无效调用 |
| 模型路由 | **LLM Gateway多模型+熔断** | 消除单模型依赖，每模型独立熔断器，优先级路由+自动降级 |
| 检索增强 | **RAG + Reranker** | 向量检索Top20→Reranker重排Top5，提升法规相关性 |
| 风险控制 | **Risk Engine评分+决策路由** | 量化风险等级，驱动auto_pass/human_review/auto_block三级处置 |
| 人机协同 | **HITL + Few-Shot回流** | 人工override自动生成Few-Shot样本，持续优化LLM审核能力 |
| Prompt治理 | **版本管理+Few-Shot** | Prompt可版本化切换，Few-Shot按违规类型检索注入 |
| 幻觉检测 | **Validate步骤交叉验证** | LLM引用条文与法规库逐条比对，移除不存在的引用 |
| 检索模式 | 向量 + 关键词双模 | 向量检索语义理解强，关键词检索精确匹配好，降级保障 |
| 文档解析 | 注册表+插件模式 | 新格式只需实现接口+注册，零侵入 |
| 输入处理 | 责任链模式 | 每种输入类型独立处理器，可组合 |
| 分块策略 | 策略模式 | 不同法规文档结构不同，运行时选择最优策略 |
| 并发控制 | Semaphore + 异步队列 | Semaphore控制并发上限，队列缓冲请求；异步审核结果在_do_review内直接保存DB，review_id随结果返回 |
| 审计日志 | HMAC签名+日切轮转 | 防篡改+自动清理，满足合规要求 |
| 违规类型管理 | **动态注册表+L1/L2分级** | 预定义核心类型保证业务一致性，动态扩展适配新法规；条款-类型多对多映射+生效/失效时间支持法规演进 |
| 交叉复核 | **轻量模型CrossCheck** | 用qwen3.6-plus对违规结论做交叉验证，成本仅增20%但降低漏判30%；合规内容跳过复核 |

---

## 九、外部评审回应 (DeepSeek v3.2)

DeepSeek v3.2评审总分86/100，提出6项不足。以下为逐项回应：

| 评审意见 | 当前状态 | 回应 |
|---------|---------|------|
| 图文一致性校验缺失 | ❌ 已知gap | P0优先级，详见demo-production-gap.md |
| CrossCheck能力边界未量化 | ⚠️ 部分解决 | 已添加冲突裁决规则和置信度阈值（见4.9节） |
| Few-Shot无淘汰机制 | ✅ 已解决 | 5策略已在文档中详细说明（见4.5节） |
| HITL前端未实现 | ✅ 已解决 | FastAPI + 纯HTML前端已实现完整HITL功能（见4.5节） |
| 测试验收标准缺失 | ⚠️ 部分解决 | 已添加验收标准，测试集待扩充（见US6） |
| 违规类型审批流程不细 | ⚠️ 部分解决 | 已添加审批流程文档，多级审批为P2（见4.8节） |
