# 部署指南

> 版本: v3.2 | 更新日期: 2026-05-16 16:18 | 受众: 运维工程师、DevOps

---

## 一、Demo部署（单机）

### 1.1 最低要求

| 资源 | 规格 |
|------|------|
| CPU | 2核 |
| 内存 | 4GB |
| 磁盘 | 20GB |
| Python | 3.10+ |
| 网络 | 需访问百炼API（可选） |

### 1.2 部署步骤

```bash
# 1. 克隆项目
git clone <repo_url>
cd insurance-review

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 可选：安装多格式支持
pip install pymupdf python-docx    # PDF/Word
pip install pytesseract Pillow     # 图片OCR（还需安装Tesseract引擎）

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 DASHSCOPE_API_KEY（可选）

# 6. 启动服务
python api_server.py
# 访问 http://localhost:7861
# API文档 http://localhost:7861/docs
```

### 1.3 环境变量配置

```bash
# 必需
DASHSCOPE_API_KEY=sk-xxx          # 百炼API Key

# 可选（有默认值）
LLM_MODEL=qwen3.5-35b-a3b               # LLM模型
EMBEDDING_MODEL=text-embedding-v3  # Embedding模型
SERVER_PORT=7861                   # API服务端口
MAX_INPUT_LENGTH=10000             # 最大输入长度
REVIEW_MAX_CONCURRENT=10           # 最大并发审核数
API_KEY_EXPIRE_DAYS=90             # API Key过期天数
CORS_ORIGINS=http://localhost:7861 # CORS白名单
```

---

## 二、生产部署（Docker）

### 2.1 Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

# Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir pymupdf python-docx

# 应用代码
COPY . .

# 数据目录
RUN mkdir -p /app/data/regulations /app/data/vector_store \
    /app/data/db_backups /app/data/audit_logs /app/data/uploads \
    /app/data/prompt_versions /app/data/violation_types

EXPOSE 7861

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:7861/health || exit 1

# 启动API服务
CMD ["python", "api_server.py"]
```

### 2.2 docker-compose.yml

```yaml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "7861:7861"
    environment:
      - DASHSCOPE_API_KEY=${DASHSCOPE_API_KEY}
      - SERVER_PORT=7861
      - REVIEW_MAX_CONCURRENT=20
      - TASK_QUEUE_MAX_WORKERS=8
    volumes:
      - ./data:/app/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:7861/health"]
      interval: 30s
      timeout: 5s
      retries: 3
```

### 2.3 启动

```bash
# 启动
docker-compose up -d

# 查看日志
docker-compose logs -f api

# 健康检查
curl http://localhost:7861/health
```

---

## 三、生产部署（Kubernetes）

### 3.1 架构

```
                    ┌─────────────┐
                    │   Ingress   │
                    │  (Nginx/TLS)│
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐┌──────────┐┌──────────┐
        │ API Pod 1││ API Pod 2││ API Pod 3│
        │ (FastAPI) ││ (FastAPI) ││ (FastAPI) │
        └────┬─────┘└────┬─────┘└────┬─────┘
             │           │           │
    ┌────────┼───────────┼───────────┼────────┐
    │        ▼           ▼           ▼        │
    │  ┌──────────┐ ┌──────────┐ ┌─────────┐ │
    │  │PostgreSQL│ │  Milvus  │ │  Redis  │ │
    │  │  (RDS)   │ │(分布式)  │ │(Cluster)│ │
    │  └──────────┘ └──────────┘ └─────────┘ │
    │            数据层 (StatefulSet)          │
    └─────────────────────────────────────────┘
```

### 3.2 关键配置

```yaml
# HPA配置
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: insurance-review-api
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: insurance-review-api
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

---

## 四、监控配置

### 4.1 Prometheus

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'insurance-review'
    scrape_interval: 15s
    static_configs:
      - targets: ['api:7861']
    metrics_path: /metrics
```

### 4.2 关键告警规则

```yaml
groups:
  - name: insurance-review
    rules:
      - alert: HighErrorRate
        expr: rate(review_total{status="error"}[5m]) > 0.1
        for: 2m
        labels:
          severity: critical

      - alert: HighLatency
        expr: histogram_quantile(0.95, review_duration_seconds_bucket) > 10
        for: 5m
        labels:
          severity: warning

      - alert: CircuitBreakerOpen
        expr: circuit_breaker_state{state="open"} == 1
        for: 0m
        labels:
          severity: critical
```

---

## 五、备份与恢复

### 5.1 自动备份

- SQLite数据库：每次关闭时自动备份，保留最近7份
- 审计日志：日切+90天轮转
- Prompt版本：`data/prompt_versions/` 目录（versions.json + few_shots.json）
- 违规类型数据：`data/violation_types/` 目录（violation_types.json + clause_mappings.json + pending_annotations.json）
- 向量索引：需手动触发 `POST /api/v1/regulations/reindex`

### 5.2 手动备份

```bash
# 触发备份
curl -X POST http://localhost:7861/api/v1/backup \
  -H "X-API-Key: YOUR_ADMIN_KEY"

# 备份文件位于 data/db_backups/
```

### 5.3 恢复

```bash
# 1. 停止服务
# 2. 替换 data/insurance_review.db 为备份文件
# 3. 重建向量索引
curl -X POST http://localhost:7861/api/v1/regulations/reindex \
  -H "X-API-Key: YOUR_ADMIN_KEY"
```

---

## 六、安全加固清单

| 项目 | Demo | 生产 | 说明 |
|------|------|------|------|
| HTTPS | — | ✅ | Nginx + Let's Encrypt |
| WAF | — | ✅ | 阿里云WAF / ModSecurity |
| 数据加密 | — | ✅ | TDE / 字段加密 |
| 密钥管理 | .env | ✅ | KMS / Vault |
| CSRF防护 | — | ✅ | CSRF Token |
| 日志审计 | ✅ | ✅ | ELK / Loki |
| 网络隔离 | — | ✅ | VPC + 安全组 |
| 容器安全 | — | ✅ | 镜像扫描 + 非root运行 |
