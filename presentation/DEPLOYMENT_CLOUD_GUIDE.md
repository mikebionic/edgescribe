# edgescribe: Cloud Deployment Guide

Руководство по развертыванию edgescribe на сервере.

---

## Вариант 1: Минимальное развертывание (1-10 пользователей)

### Рекомендуемый сервер (AWS, GCP, Azure, Hetzner)

```
Процессор:    2 vCPU (Intel Xeon / AMD EPYC)
Оперативная память: 16 GB RAM
Диск:         100 GB SSD (40 GB для моделей + 60 GB буфер)
Операционная система: Ubuntu 22.04 LTS или Debian 12
Интернет:     100 Mbps (для загрузки моделей и клиентов)
```

### Стоимость примерно:
- **AWS EC2 t3.xlarge**: $0.16/час (~$120/месяц)
- **Google Cloud n2-standard-4**: $0.19/час (~$140/месяц)
- **Azure Standard_D4s_v3**: $0.20/час (~$150/месяц)
- **Hetzner CPX41**: €35/месяц (дешевле!)

### Пропускная способность

| Метрика | Значение | Примечание |
|---------|----------|-----------|
| Одновременных пользователей | 2-3 | Зависит от длины аудио |
| Очередь jobs | до 10 | Остальное ждёт в queue |
| Обработка в час | 2-3 часа аудио | На large-v3-turbo |
| Max одного файла | 2 часа | Больше нужны timeout |

### Архитектура
```
User browser
    ↓
Load Balancer / Nginx
    ↓
[Single VM - edgescribe service]
    ├─ FastAPI + static UI
    ├─ ThreadPoolExecutor (2 workers)
    └─ Storage (local SSD)
    ↓
Output files (download или S3)
```

---

## Вариант 2: Среднее развертывание (10-100 пользователей)

### Рекомендуемая инфраструктура

**Вариант A: Kubernetes на облаке**
```
Master Node:
├─ CPU: 4 vCPU
├─ RAM: 16 GB
└─ Disk: 50 GB

Worker Nodes (3x):
├─ CPU: 8 vCPU
├─ RAM: 32 GB каждый
└─ Disk: 200 GB SSD каждый

Shared Storage:
├─ Database: PostgreSQL (AWS RDS, 100 GB)
├─ Cache: Redis (AWS ElastiCache)
└─ Object Storage: AWS S3 или GCS
```

**Вариант B: Docker Compose на одном мощном сервере**
```
Процессор:    16 vCPU (Intel Xeon / AMD EPYC)
Оперативная память: 128 GB RAM (!)
Диск:         1 TB SSD (NVMe для speed)
OS:           Ubuntu 22.04 LTS
Network:      1 Gbps
```

### Стоимость:
- **Kubernetes (AWS EKS)**: $200-400/месяц
- **Docker Compose (high-end)**: $200-300/месяц (Hetzner AX161)
- **Google Cloud Run** (serverless): $0.0000667 за CPU-sec (~$50-100/месяц при 10-20 часов обработки)

### Пропускная способность

| Метрика | Kubernetes | Docker Compose |
|---------|-----------|-----------------|
| Одновременных jobs | 10-20 | 8-16 |
| Пиковая очередь | 50+ | 30-40 |
| Обработка в день | 20-40 часов аудио | 15-30 часов |
| Max одного файла | 5 часов | 3 часа |
| Connections | 100+ одновременно | 50-80 одновременно |

### Архитектура Kubernetes
```
[Ingress / Load Balancer]
    ↓
[Nginx Reverse Proxy]
    ↓
    ├─ [API Pods (3 replicas)]
    │  └─ FastAPI + static UI
    │
    ├─ [Worker Pods (5-10 replicas)]
    │  └─ Transcription processing
    │
    ├─ [Diarization Pods (2 replicas)]
    │  └─ Speaker identification
    │
    ├─ [PostgreSQL (managed RDS)]
    │  └─ Job tracking
    │
    ├─ [Redis (managed)]
    │  └─ Queue + cache
    │
    └─ [S3 / GCS]
       └─ Audio files + results
```

---

## Вариант 3: Enterprise развертывание (100-1000+ пользователей)

### Полная инфраструктура

```
┌─────────────────────────────────────────────────────┐
│ EDGE LOCATIONS (CDN for low latency)                │
│ ├─ Europe (Frankfurt)                               │
│ ├─ US East (Virginia)                               │
│ ├─ US West (Oregon)                                 │
│ ├─ Asia Pacific (Tokyo/Singapore)                   │
│ └─ Custom locations (on-premise)                    │
└─────────────────────────────────────────────────────┘
           ↓ (Global Load Balancer)
┌─────────────────────────────────────────────────────┐
│ MAIN ORCHESTRATION (Central Hub)                    │
│ ├─ Kubernetes Cluster (managed: GKE, EKS, AKS)     │
│ ├─ Auto-scaling (HPA based on CPU/RAM)             │
│ ├─ Multi-region replication                         │
│ └─ 24/7 monitoring + alerts                         │
└─────────────────────────────────────────────────────┘
           ↓
┌─────────────────────────────────────────────────────┐
│ STORAGE & DATABASES                                 │
│ ├─ PostgreSQL (primary + replicas)                  │
│ ├─ Redis Cluster (high availability)               │
│ ├─ S3 + CloudFront (audio distribution)            │
│ └─ Backup systems (daily snapshots)                │
└─────────────────────────────────────────────────────┘
           ↓
┌─────────────────────────────────────────────────────┐
│ PROCESSING WORKERS (Distributed)                    │
│ ├─ Transcription nodes (50-200)                     │
│ ├─ Diarization nodes (10-50)                        │
│ ├─ Post-processing nodes (5-20)                     │
│ └─ GPU nodes (optional, for speed)                  │
└─────────────────────────────────────────────────────┘
```

### Примерные затраты:

```
Infrastructure per month:
├─ GKE/EKS (master + workers): $2,000-5,000
├─ Storage (S3/GCS): $500-2,000
├─ Database (RDS/Cloud SQL): $1,000-3,000
├─ CDN/Load Balancer: $300-1,000
├─ Monitoring/Logging: $500-1,000
├─ Backup/DR: $300-500
└─ Network egress: $500-2,000

TOTAL: $5,100 - $14,500 per month
```

### Пропускная способность

| Метрика | Значение | При пике |
|---------|----------|----------|
| Одновременных jobs | 50-100 | до 200 |
| Дневной throughput | 200-500 часов аудио | до 1000 часов |
| Пиковая очередь | 500+ | 2000+ |
| Max одного файла | 10 часов | (split на chunks) |
| Connections одновременно | 500-1000 | до 5000 |
| API requests/sec | 100-500 | до 1000 |
| GB processed/day | 500-1000 | до 2000 |

---

## Как деплоить (пошагово)

### Шаг 1: Подготовка образа Docker

```dockerfile
# Dockerfile
FROM python:3.11-slim-bookworm

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')"

CMD ["python", "api.py", "--server.address=0.0.0.0", "--server.port=8000"]
```

### Шаг 2: Докеризация с Compose (для малого развертывания)

```yaml
# docker-compose.yml
version: '3.9'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: edgescribe
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: edgescribe
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  edgescribe-api:
    build: .
    ports:
      - "8000:8000"
    environment:
      REDIS_URL: redis://redis:6379
      DATABASE_URL: postgresql://edgescribe:${DB_PASSWORD}@postgres:5432/edgescribe
      WORKERS: 4
      MAX_QUEUE: 50
    depends_on:
      - redis
      - postgres
    volumes:
      - ./models:/app/models  # Кешируем модели
      - uploads:/app/uploads  # Загруженные файлы

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    depends_on:
      - edgescribe-api

volumes:
  redis_data:
  postgres_data:
  uploads:
```

### Шаг 3: Развертывание на Kubernetes

```yaml
# kubernetes/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: edgescribe-worker
spec:
  replicas: 5  # Auto-scale от 1 до 20
  selector:
    matchLabels:
      app: edgescribe
  template:
    metadata:
      labels:
        app: edgescribe
    spec:
      containers:
      - name: edgescribe
        image: your-registry/edgescribe:latest
        resources:
          requests:
            memory: "8Gi"
            cpu: "2"
          limits:
            memory: "16Gi"
            cpu: "4"
        volumeMounts:
        - name: models
          mountPath: /app/models
        - name: temp
          mountPath: /tmp
        env:
        - name: REDIS_URL
          valueFrom:
            configMapKeyRef:
              name: edgescribe-config
              key: redis_url
        ports:
        - containerPort: 8000
      volumes:
      - name: models
        persistentVolumeClaim:
          claimName: models-pvc
      - name: temp
        emptyDir:
          sizeLimit: 100Gi

---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: edgescribe-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: edgescribe-worker
  minReplicas: 2
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

### Шаг 4: Развертывание на облаке (примеры)

**AWS:**
```bash
# Используйте ECS или EKS
aws ecr create-repository --repository-name edgescribe
docker tag edgescribe:latest 123456789.dkr.ecr.us-east-1.amazonaws.com/edgescribe:latest
docker push 123456789.dkr.ecr.us-east-1.amazonaws.com/edgescribe:latest

# Deployment через CloudFormation или Terraform
terraform apply
```

**Google Cloud:**
```bash
# Используйте Cloud Run (serverless) или GKE
gcloud builds submit --tag gcr.io/my-project/edgescribe
gcloud run deploy edgescribe \
  --image gcr.io/my-project/edgescribe:latest \
  --platform managed \
  --region us-central1 \
  --memory 16Gi \
  --cpu 4 \
  --max-instances 20
```

**Azure:**
```bash
# Используйте AKS
az container registry create --resource-group mygroup --name myregistry --sku Basic
az aks create --resource-group mygroup --name myakcluster --node-count 3 --vm-set-type VirtualMachineScaleSets
az aks install-cli
kubectl apply -f kubernetes/deployment.yaml
```

---

## 📈 Тестирование производительности

### Нагрузочное тестирование (Load Testing)

```bash
# Используйте Apache JMeter или Locust

# locustfile.py
from locust import HttpUser, task, between

class TranscribeUser(HttpUser):
    wait_time = between(1, 5)

    @task
    def upload_audio(self):
        with open("test_audio.mp3", "rb") as f:
            self.client.post("/transcribe",
                files={"audio": f})

# Запуск:
locust -f locustfile.py -u 100 -r 10 -t 5m
```

### Мониторинг во время нагрузки

```bash
# Terminal 1: Мониторим CPU/RAM
watch -n 1 'docker stats --no-stream'

# Terminal 2: Мониторим очередь jobs
watch -n 1 'redis-cli LLEN edgescribe:queue'

# Terminal 3: Мониторим ошибки
tail -f /var/log/edgescribe.log | grep ERROR
```

### Результаты тестирования (примеры)

**На single VM (16GB, 4 CPU):**
```
Concurrent connections: 20
Queue size: ~50 jobs
Processing time (1 hour audio): 30 minutes
Throughput: 2 hours audio/hour wall-clock
Response time (API): 200-500ms
CPU usage: 80-95%
Memory usage: 12-14 GB
```

**На Kubernetes cluster (3 nodes, 8 CPU, 32 GB each):**
```
Concurrent connections: 100
Queue size: ~200 jobs
Processing time (1 hour audio): 15 minutes (parallel)
Throughput: 8-12 hours audio/hour wall-clock
Response time (API): 100-200ms
CPU usage: 60-80% (with autoscaling headroom)
Memory usage: 20-25 GB (of 96GB available)
```

---

## Security & Production Hardening

### SSL/TLS (обязательно)
```nginx
# nginx.conf
upstream edgescribe {
    server edgescribe-api:8000;
}

server {
    listen 443 ssl http2;
    server_name transcribe.yourdomain.com;

    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://edgescribe;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}

# Редирект HTTP на HTTPS
server {
    listen 80;
    server_name transcribe.yourdomain.com;
    return 301 https://$server_name$request_uri;
}
```

### Rate Limiting
```python
# fastapi app
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/transcribe")
@limiter.limit("10/minute")
async def transcribe(request: Request, ...):
    # 10 запросов в минуту per IP
    pass
```

### Аутентификация
```python
# API keys for users
@app.post("/transcribe")
async def transcribe(api_key: str = Header(...)):
    user = verify_api_key(api_key)
    if not user:
        raise HTTPException(status_code=401)
    # Process
```

---

## Мониторинг и Логирование

### Prometheus metrics
```python
from prometheus_client import Counter, Histogram, start_http_server

transcribe_requests = Counter(
    'transcribe_requests_total',
    'Total transcription requests'
)

transcribe_duration = Histogram(
    'transcribe_duration_seconds',
    'Transcription duration in seconds',
    buckets=[60, 300, 600, 1800, 3600]
)

queue_size = Gauge(
    'job_queue_size',
    'Current job queue size'
)
```

### ELK Stack (Elasticsearch, Logstash, Kibana)
```yaml
# docker-compose.yml addition
elasticsearch:
  image: docker.elastic.co/elasticsearch/elasticsearch:8.0.0
  environment:
    discovery.type: single-node

logstash:
  image: docker.elastic.co/logstash/logstash:8.0.0

kibana:
  image: docker.elastic.co/kibana/kibana:8.0.0
  ports:
    - "5601:5601"
```

---

## 🎯 Рекомендации по выбору конфигурации

### Для стартапа (0-100 пользователей):
```
✓ Используйте: Single VM или Docker Compose
✓ Сервер: 16GB RAM, 4 CPU (Hetzner CPX41)
✓ Стоимость: €35/месяц (~$40)
✓ Максимум users: 10-20 одновременно
```

### Для растущего бизнеса (100-1000 пользователей):
```
✓ Используйте: Kubernetes (GKE/EKS)
✓ Серверы: 3x8CPU/32GB nodes
✓ Стоимость: $2000-3000/месяц
✓ Максимум users: 100-200 одновременно
```

### Для enterprise (1000+ пользователей):
```
✓ Используйте: Multi-region Kubernetes
✓ Серверы: Auto-scaling 10-50 nodes
✓ Стоимость: $10,000+/месяц
✓ Максимум users: 1000+ одновременно
```

---

## 📝 Чек-лист развертывания

- [ ] Выбрана конфигурация сервера
- [ ] Dockerfile создан и тестирован
- [ ] Docker image собран и залит в registry
- [ ] Database (PostgreSQL) настроена
- [ ] Cache (Redis) настроена
- [ ] SSL/TLS сертификаты установлены
- [ ] Rate limiting настроен
- [ ] Аутентификация реализована
- [ ] Логирование и мониторинг настроены
- [ ] Backup и recovery план составлен
- [ ] Load testing проведено
- [ ] Security audit выполнен
- [ ] Документация написана
- [ ] Team обучена на production procedures

---

## 🚨 Типичные проблемы и решения

### Проблема: Out of Memory (OOM)
```
Решение:
1. Увеличьте RAM сервера
2. Обработайте большие файлы chunks'ами
3. Используйте smaller model (medium вместо large)
4. Установите memory limits в Kubernetes
```

### Проблема: Очередь растёт, jobs не обрабатываются
```
Решение:
1. Увеличьте количество worker pods/containers
2. Проверьте CPU/disk utilization
3. Оптимизируйте код (profile с py-spy)
4. Используйте GPU acceleration (если доступно)
```

### Проблема: Медленная сетевая скорость при загрузке файлов
```
Решение:
1. Используйте S3 presigned URLs (для больших файлов)
2. Chunked upload (по 5-10 MB chunks)
3. CloudFront CDN для распределения
4. Региональное развертывание (edge locations)
```

### Проблема: Модели не кешируются, долгая холодная загрузка
```
Решение:
1. Pre-download models в Docker image
2. Используйте persistent volumes для моделей
3. Multi-tier caching (local + S3)
4. Прогрев контейнеров перед production
```

---

## 📞 Support & Scaling Consultation

Если вам нужна помощь с deployment:
- Консультация по инфраструктуре: $200-500/час
- Полный setup под ключ: $5000-15000
- Ongoing support: $500-2000/месяц

---

**Итого:** Это полное руководство для масштабирования edgescribe от одного сервера до enterprise-level облачного решения.
