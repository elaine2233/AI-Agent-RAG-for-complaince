# API参考文档

> 版本: v3.4 | 更新日期: 2026-05-18 17:40

---

## 一、认证

所有API端点（除 `/health`, `/ready`, `/metrics`, `/api/v1/regulations/formats` 外）需要API Key认证。

**请求头**：`X-API-Key: <your_api_key>`

**API Key获取**：系统初始化时自动创建admin用户，API Key在首次启动时输出到日志。

**DashScope API Key转发**：前端通过 `X-API-Key` 请求头传入的API Key，在认证通过后同时作为 DashScope API Key 使用。当用户提供的 Key 为有效的 DashScope API Key 时，系统将使用该 Key 调用 LLM 和 Embedding 服务，而非依赖服务端配置的 `DASHSCOPE_API_KEY`。这使得 Demo 模式下用户可使用自己的 DashScope Key 获得完整 LLM 和向量检索功能。

**API Key过期**：默认90天过期，可通过 `API_KEY_EXPIRE_DAYS` 环境变量配置。

**角色权限**：

| 角色 | 权限 |
|------|------|
| viewer | 查看审核历史、统计 |
| reviewer | viewer + 提交审核、反馈、查看告警、查看待审队列 |
| admin | reviewer + 上传法规、重建索引、备份、清理、管理Prompt版本 |

---

## 二、系统端点

### GET /health

健康检查（无需认证）

**响应**：
```json
{"status": "healthy", "version": "3.0"}
```

### GET /ready

就绪检查（无需认证）

**响应**：
```json
{"status": "ready"}
```

### GET /metrics

Prometheus指标端点（无需认证）

**响应**：`text/plain` Prometheus格式指标

### GET /api/v1/health/detail

详细健康检查（需认证）

**响应**：
```json
{
  "status": "healthy",
  "checks": {
    "database": {"status": "healthy"},
    "rag_engine": {"status": "healthy"},
    "llm_circuit": {"status": "healthy"},
    "task_queue": {"status": "healthy"}
  }
}
```

### GET /api/v1/alerts

获取活跃告警（需reviewer角色）

**响应**：
```json
{
  "active_alerts": [...],
  "new_fired": [...]
}
```

### GET /api/v1/llm-audit-logs

获取LLM审计日志（需认证）

**说明**：返回LLM调用和Rerank调用的审计日志记录，用于排查审核异常和追踪模型行为。日志按日期存储在 `data/llm_audit/` 目录下的JSONL文件中。**日志按时间戳降序排列（最新在前）**，支持按 `step_name`（llm_reason/crosscheck/rerank等）和 `review_id` 筛选。

**查询参数**：

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `date` | string | 否 | 指定日期，格式YYYYMMDD（如 `20260518`）。不指定则返回所有日期的日志 |
| `limit` | int | 否 | 返回记录数上限，默认50 |

**日志字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `timestamp` | string | 调用时间戳（ISO格式） |
| `model` | string | 模型名称（完整版本号，如 qwen3.6-flash） |
| `step_name` | string | 流水线步骤名：llm_reason（主推理）、crosscheck（交叉复核）、rerank（重排序）等 |
| `review_id` | int | 关联的审核记录ID |
| `user_prompt` | string | 用户输入/Prompt摘要 |
| `response` | string | 模型响应。rerank步骤显示重排结果（条款名+分数），其他步骤显示模型输出 |
| `latency_ms` | float | 调用耗时（毫秒） |
| `success` | bool | 是否成功 |

**响应**：
```json
{
  "logs": [
    {
      "timestamp": "2026-05-18T17:34:43.689220",
      "model": "qwen3.6-flash",
      "step_name": "llm_reason",
      "review_id": 68,
      "user_prompt": "...",
      "response": "...",
      "latency_ms": 2340.5,
      "success": true
    },
    {
      "timestamp": "2026-05-18T17:34:43.456789",
      "model": "qwen3-rerank",
      "step_name": "rerank",
      "review_id": 68,
      "user_prompt": "[Rerank] 对20条法规条款重排序: 互联网保险业务监管办法第十七条; ...",
      "response": "重排结果: 互联网保险业务监管办法第九条(score=0.4014); 互联网保险业务监管办法第十四条(score=0.397); ...",
      "latency_ms": 258.4,
      "success": true
    }
  ],
  "total": 50,
  "log_dir": "/path/to/data/llm_audit"
}
```

---

### POST /api/v1/test-connection

测试DashScope API连接（需认证）

**说明**：验证提供的API Key是否能成功连接DashScope服务。用于前端在配置API Key后验证连通性。

**请求头**：`X-API-Key: <your_api_key>`

**响应**：
```json
{
  "connected": true,
  "model": "qwen3.6-plus",
  "latency_ms": 230.5,
  "message": "DashScope API连接正常"
}
```

**错误响应**（连接失败）：
```json
{
  "connected": false,
  "model": "qwen3.6-plus",
  "latency_ms": 0,
  "message": "API Key无效或DashScope服务不可用"
}
```

### GET /api/v1/clause-mappings

获取条款-违规类型映射列表（需认证）

**说明**：返回系统中所有条款与违规类型的映射关系，包括映射类型（primary/secondary）和生效状态。映射数据从数据库持久化存储中读取。

**查询参数**：`violation_type_id`(可选，按违规类型筛选), `doc_name`(可选，按法规文档筛选)

**响应**：
```json
{
  "mappings": [
    {
      "mapping_id": 1,
      "doc_name": "保险销售行为管理办法",
      "article_number": "二十一",
      "violation_type_id": "absolute_language",
      "violation_type_name": "绝对化用语",
      "mapping_type": "primary",
      "effective_date": "2026-07-01",
      "expiration_date": null,
      "status": "active"
    }
  ],
  "total": 17
}
```

---

## 三、审核端点

### POST /api/v1/review

单条文本审核

**请求体**：
```json
{
  "content": "这款保险产品稳赚不赔",
  "image_descriptions": ["[图片: poster.jpg] 图片显示保本保息宣传语，100字以内营销意图摘要"]
}
```

**请求字段说明**：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `content` | string | 是 | 待审核的营销文本内容 |
| `image_descriptions` | array | 否 | 图片描述列表。每项为图片的文字提取结果或营销意图摘要，用于多模态审核。参与 input_hash 计算 |

**响应**：
```json
{
  "review_id": 1,
  "input_hash": "a1b2c3d4e5f6g7h8",
  "compliant": "no",
  "violations": [
    {
      "violation_type": "绝对化用语",
      "violated_articles": [
        {
          "doc_name": "保险销售行为管理办法",
          "article_number": "十八",
          "article_text": "...",
          "violation_reason": "使用绝对化用语（匹配: 稳赚不赔）"
        }
      ],
      "reasoning": "规则引擎命中关键词: 稳赚不赔，构成绝对化用语"
    }
  ],
  "confidence": 0.9,
  "risk_score": 0.75,
  "risk_level": "high",
  "decision": "auto_block",
  "review_mode": "rule",
  "model_used": "",
  "prompt_version": "",
  "workflow_steps": [
    {"name": "extract", "status": "completed", "latency_ms": 12.3},
    {"name": "rule_check", "status": "completed", "latency_ms": 5.1},
    {"name": "rag_retrieve", "status": "completed", "latency_ms": 45.2},
    {"name": "rerank", "status": "completed", "latency_ms": 23.4},
    {"name": "llm_reason", "status": "skipped", "latency_ms": 0},
    {"name": "format", "status": "completed", "latency_ms": 2.1},
    {"name": "validate", "status": "completed", "latency_ms": 8.7},
    {"name": "crosscheck", "status": "completed", "latency_ms": 15.6},
    {"name": "risk_assess", "status": "completed", "latency_ms": 3.2}
  ],
  "latency_ms": 1523.45
}
```

**响应字段说明**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `review_id` | int | 审核记录ID |
| `input_hash` | string | 输入内容哈希（SHA256前16位），包含文本和图片描述，用于识别重复审核 |
| `violations` | array | 违规项列表，每项包含 violation_type、violated_articles、reasoning |
| `risk_score` | float | 风险评分 [0, 1] |
| `risk_level` | string | 风险等级: low/medium/high/critical |
| `decision` | string | 处置决策: auto_pass/human_review/auto_block |
| `review_mode` | string | 审核模式: rule(规则命中)/llm(LLM推理)/security_block |
| `model_used` | string | 使用的LLM模型名（规则模式为空） |
| `prompt_version` | string | 使用的Prompt版本（规则模式为空） |
| `workflow_steps` | array | 10步流水线执行记录 |
| `regulation_snapshot` | dict | 审核时的法规版本快照（doc_name → content_hash） |
| `crosscheck_passed` | bool | CrossCheck复核是否通过 |

### POST /api/v1/review/multimodal

多模态审核（文本+图片路径+文件路径）

**请求体**：
```json
{
  "text": "这款保险产品收益稳定",
  "image_paths": ["/path/to/image.png"],
  "file_paths": ["/path/to/document.pdf"]
}
```

**响应**：同 `/api/v1/review`

### POST /api/v1/review/upload

文件上传审核（multipart/form-data）

**请求**：
```
POST /api/v1/review/upload
Content-Type: multipart/form-data

text=这款保险产品收益稳定
files=@document.pdf
files=@image.png
```

**响应**：同 `/api/v1/review`

### POST /api/v1/review/async

异步审核（提交后返回task_id，通过轮询获取结果）

**请求体**：同 `/api/v1/review`

**响应**：
```json
{
  "task_id": "task_abc123",
  "status": "pending",
  "message": "审核任务已提交，请通过 /api/v1/task/task_abc123 查询结果"
}
```

### GET /api/v1/task/{task_id}

查询异步任务状态

**响应**：
```json
{
  "task_id": "task_abc123",
  "status": "completed",
  "result": {
    "compliant": "no",
    "violations": [
      {
        "violation_type": "...",
        "violated_articles": [...],
        "reasoning": "..."
      }
    ],
    "risk_score": 0.75,
    "risk_level": "high",
    "decision": "auto_block",
    ...
  },
  "latency_ms": 1523.45
}
```

### GET /api/v1/task/stats

任务队列统计（需reviewer角色）

**响应**：
```json
{
  "task_queue": {
    "queue_size": 3,
    "max_queue_size": 100,
    "active_workers": 2,
    "max_workers": 4
  },
  "semaphore": {
    "current": 5,
    "max_concurrent": 10
  }
}
```

### POST /api/v1/review/batch

批量审核（最多50条）

**请求体**：
```json
{
  "items": [
    {"content": "比银行存款利息高多了"},
    {"content": "保险责任包括重大疾病保障"}
  ]
}
```

**响应**：
```json
{
  "total": 2,
  "results": [...],
  "total_latency_ms": 3245.67
}
```

### GET /api/v1/review/pending

获取待人工审核队列（需reviewer角色）

**说明**：返回 Risk Engine 判定为 `human_review` 的审核记录列表，供人工复核。

**响应**：
```json
{
  "pending_reviews": [
    {
      "review_id": 5,
      "content": "这款保险产品适合稳健型投资者",
      "compliant": "no",
      "violations": [
        {
          "violation_type": "产品混淆",
          "violated_articles": [...],
          "reasoning": "..."
        }
      ],
      "risk_score": 0.45,
      "risk_level": "medium",
      "decision": "human_review",
      "review_mode": "llm",
      "created_at": "2026-05-16 10:30:00"
    }
  ],
  "total": 1
}
```

### POST /api/v1/review/{review_id}/override

人工审核覆盖（需reviewer角色）

**说明**：人工对 `human_review` 状态的审核记录做出最终判定。覆盖结果自动生成 Few-Shot 样本回流到 PromptManager。

**请求体**：
```json
{
  "decision": "auto_pass",
  "comment": "实际合规内容，'稳健型投资者'为通用表述非混淆"
}
```

**响应**：
```json
{
  "message": "审核记录已更新",
  "review_id": 5,
  "original_decision": "human_review",
  "new_decision": "auto_pass",
  "few_shot_created": true,
  "few_shot_id": "a1b2c3d4e5f6"
}
```

---

## 四、法规端点

### GET /api/v1/regulations

获取法规列表（需认证）

### GET /api/v1/regulations/formats

获取支持的法规文档格式（无需认证）

**响应**：
```json
{"supported_formats": ["txt", "md", "pdf", "docx", "image"]}
```

### POST /api/v1/regulations/upload

上传法规文档（需admin角色，multipart/form-data）

**请求**：
```
POST /api/v1/regulations/upload
Content-Type: multipart/form-data

file=@新法规.pdf
```

**响应**：
```json
{
  "message": "法规文档已上传: 新法规.pdf",
  "filename": "新法规.pdf",
  "format": "pdf",
  "title": "新法规",
  "sections": 25,
  "tables": 3,
  "images": 2,
  "hint": "请调用 POST /api/v1/regulations/reindex 重建索引以生效"
}
```

### POST /api/v1/regulations/reindex

重建法规索引（需admin角色）

---

## 五点五、违规类型端点

### GET /api/v1/violation-types

获取违规类型列表（需认证）

**查询参数**：`level`(1或2), `parent_id`

**响应**：
```json
{
  "types": [
    {
      "id": "absolute_language",
      "name": "绝对化用语",
      "level": 2,
      "parent_id": "false_publicity",
      "severity": 0.9,
      "description": "使用绝对化、确定性用语进行保险营销宣传",
      "keywords": ["稳赚不赔", "保本保息", ...],
      "suggestions": "删除绝对化用语，替换为合规表述",
      "is_system": true,
      "status": "active"
    }
  ],
  "stats": {
    "total_types": 15,
    "l1_types": 5,
    "l2_types": 10,
    "system_types": 15,
    "custom_types": 0,
    "active_mappings": 17,
    "pending_annotations": 3
  }
}
```

### GET /api/v1/violation-types/{type_id}

获取违规类型详情（含关联条款）

### POST /api/v1/violation-types

创建违规类型（需admin角色）

> **注意**：Demo 模式下此端点不可用，调用将返回 403 错误。

**查询参数**：`name`, `level`(1/2), `parent_id`, `severity`, `description`, `keywords`(逗号分隔), `suggestions`, `source`("system"或"custom"，默认"custom")

### PUT /api/v1/violation-types/{type_id}

更新违规类型（需admin角色）

**查询参数**：`name`, `level`, `parent_id`, `severity`, `description`, `keywords`(逗号分隔), `suggestions`, `source`

### DELETE /api/v1/violation-types/{type_id}

废弃违规类型（需admin角色，同时失效所有条款映射）

### POST /api/v1/violation-types/{type_id}/keywords

添加关键词（需admin角色）

**查询参数**：`keyword`

### GET /api/v1/violation-types/annotations/pending

获取待审批的法规条文标注（需admin角色）

### POST /api/v1/violation-types/annotations/{annotation_id}/approve

审批标注（需admin角色）

**查询参数**：`type_id`(可选，指定映射到现有类型)

### POST /api/v1/violation-types/annotations/{annotation_id}/reject

拒绝标注（需admin角色）

### POST /api/v1/violation-types/{type_id}/deprecate

废弃违规类型（需admin角色，同时失效所有条款映射）

**说明**：将违规类型标记为 deprecated，同时将所有关联的条款映射标记为失效。已废弃类型不再出现在活跃类型列表中，但可通过 `is_type_deprecated()` 查询。

**响应**：
```json
{
  "message": "违规类型已废弃",
  "type_id": "old_type_id",
  "expired_mappings": 5
}
```

### POST /api/v1/violation-types/{type_id}/mappings/{mapping_id}/expire

失效单条条款映射（需admin角色）

**说明**：将指定条款映射标记为失效，不影响其他映射。

**响应**：
```json
{
  "message": "条款映射已失效",
  "type_id": "absolute_language",
  "mapping_id": 12
}
```

---

## 五点六、违规反馈端点

### POST /api/v1/review/{id}/violation-feedback

提交逐条违规反馈（需reviewer角色）

**说明**：用户对审核结果中的单条违规项提交反馈，支持精准标注某条违规判定是否正确。

**请求体**：
```json
{
  "violation_index": 0,
  "is_correct": false,
  "comment": "该表述实际合规"
}
```

**响应**：
```json
{
  "message": "违规反馈已提交",
  "review_id": 1,
  "violation_index": 0,
  "feedback_id": 42
}
```

### GET /api/v1/review/{id}/violation-feedback

获取某次审核的逐条违规反馈（需认证）

**响应**：
```json
{
  "review_id": 1,
  "feedbacks": [
    {
      "violation_index": 0,
      "is_correct": false,
      "comment": "该表述实际合规",
      "created_at": "2026-05-16 14:30:00"
    }
  ],
  "total": 1
}
```

### GET /api/v1/violation-feedback/stats

获取违规反馈统计（需认证）

**响应**：
```json
{
  "total_feedback": 120,
  "correct_rate": 0.85,
  "by_type": {
    "绝对化用语": {"total": 45, "correct_rate": 0.82},
    "收益承诺": {"total": 30, "correct_rate": 0.90}
  }
}
```

---

## 五、Prompt管理端点

### GET /api/v1/prompts/versions

获取Prompt版本列表（需admin角色）

**响应**：
```json
{
  "versions": [
    {
      "version": "v1",
      "description": "默认审核Prompt",
      "is_active": true,
      "created_at": "2026-05-16 09:00:00",
      "metrics": {}
    }
  ],
  "stats": {
    "total_versions": 1,
    "active_version": "v1",
    "total_few_shots": 3,
    "few_shot_sources": ["human_override"]
  }
}
```

### POST /api/v1/prompts/activate

激活指定Prompt版本（需admin角色）

**请求体**：
```json
{
  "version": "v2"
}
```

**响应**：
```json
{
  "message": "Prompt版本已切换",
  "active_version": "v2"
}
```

---

## 六、LLM管理端点

### GET /api/v1/llm/status

获取LLM模型状态（需reviewer角色）

**响应**：
```json
{
  "models": {
    "qwen3.6-plus": {
      "role": "primary",
      "provider": "dashscope",
      "circuit_state": "closed",
      "priority": 0
    },
    "qwen3.6-flash": {
      "role": "fallback",
      "provider": "dashscope",
      "circuit_state": "closed",
      "priority": 5,
      "note": "后备模型，主模型熔断时自动切换"
    }
  }
}
```

**circuit_state 说明**：
- `closed`：正常可用
- `open`：熔断中（失败次数超阈值，暂停调用）
- `half_open`：半开（试探性恢复调用）

---

## 七、数据端点

### GET /api/v1/reviews

审核历史列表（需认证）

**查询参数**：`page`, `page_size`, `compliant`, `start_date`, `end_date`

### GET /api/v1/reviews/{review_id}

审核详情（需认证，校验用户归属）

### POST /api/v1/feedback

提交审核反馈

**请求体**：
```json
{
  "review_id": 1,
  "is_correct": false,
  "comment": "实际是合规内容"
}
```

**说明**：如果 `is_correct=false`，系统自动从反馈中生成 Few-Shot 样本。

### GET /api/v1/feedback/stats

反馈统计（需认证）

### GET /api/v1/stats

系统统计（需认证）

---

## 八、管理端点

### POST /api/v1/backup

手动备份（需admin角色）

### POST /api/v1/cleanup

数据清理（需admin角色）

**查询参数**：`days`（默认365）

---

## 九、错误码

| 状态码 | 含义 | 场景 |
|--------|------|------|
| 400 | 请求错误 | 输入校验失败、文件格式不支持、Prompt版本不存在 |
| 401 | 未认证 | 缺少API Key或Key无效/过期 |
| 403 | 权限不足 | 角色权限不满足 |
| 404 | 资源不存在 | 审核记录/任务/Prompt版本不存在 |
| 429 | 请求过多 | 并发超限、限流触发 |
| 500 | 服务器错误 | 未预期异常 |

**错误响应格式**：
```json
{"detail": "错误描述"}
```
