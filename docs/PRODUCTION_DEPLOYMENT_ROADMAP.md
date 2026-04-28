# Next Month: Production Deployment Roadmap

**Target Completion**: May 22, 2026  
**Status**: Planning Phase  
**Scope**: 5 core deployment phases

---

## Overview

Transform the RLHF/DPO system from "works in test" to "ready for production", with persistent storage, background workers, monitoring, and safe deployment strategy.

**Total Effort**: 40-80 hours  
**Team**: Backend (2-3 engineers) + DevOps (1 engineer) + ML Ops (1 engineer)

## Execution Priority Update (April 22, 2026)

- Prioritize worker and queue readiness checks early because the latest end-to-end run stayed in `queued` for 120s.
- Keep Phase 1 tightly scoped: persistence correctness first; no feature expansion until persistence gates pass.
- Treat queue-readiness work in Phase 1 as a minimal unblocker preflight, not full Phase 2 delivery.

---

## Phase 1: Database Persistence (1-2 days)

**Goal**: Replace in-memory registries with persistent database storage and prove restart-safe correctness before any expansion

**Phase 1 Scope Guardrails**:

- Allowed: schema, persistence functions, crash/restart correctness tests, minimal queue-readiness preflight.
- Not allowed: monitoring/dashboard expansion, rollout logic, non-persistence refactors.
- Exit only when all persistence gates pass.

### Step 1.1: Create Migration

Create file: `migrations/versions/001_add_rlhf_tables.py`

```python
"""Add RLHF/DPO job tables"""
from alembic import op
import sqlalchemy as sa

revision = '001_rlhf_tables'
down_revision = None

def upgrade():
    op.create_table(
        'dpo_jobs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('base_model', sa.String(255), nullable=False),
        sa.Column('adapter_name', sa.String(255), nullable=False),
        sa.Column('dataset_path', sa.String(512), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, default='queued'),
        sa.Column('metrics', sa.JSON, nullable=True),
        sa.Column('adapter_path', sa.String(512), nullable=True),
        sa.Column('error', sa.JSON, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Index('idx_status', 'status'),
        sa.Index('idx_created', 'created_at'),
    )
    
    op.create_table(
        'rlhf_jobs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('base_model', sa.String(255), nullable=False),
        sa.Column('adapter_name', sa.String(255), nullable=False),
        sa.Column('dataset_path', sa.String(512), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, default='queued'),
        sa.Column('rounds_completed', sa.Integer, nullable=False, default=0),
        sa.Column('reward_model_path', sa.String(512), nullable=True),
        sa.Column('metrics', sa.JSON, nullable=True),
        sa.Column('adapter_path', sa.String(512), nullable=True),
        sa.Column('error', sa.JSON, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Index('idx_status', 'status'),
        sa.Index('idx_created', 'created_at'),
    )

def downgrade():
    op.drop_table('rlhf_jobs')
    op.drop_table('dpo_jobs')
```

### Step 1.2: Run Migration

```bash
cd /path/to/nexus-ai
source .venv/bin/activate
alembic upgrade head
```

**Verification**:
```bash
# Check tables exist
sqlite3 nexus.db ".tables"
# Should show: dpo_jobs, rlhf_jobs
```

### Step 1.3: Update Database Layer

Modify: `src/db.py`

```python
from datetime import datetime
from sqlalchemy import select
from src.db import Base, engine, SessionLocal

# Add to src/db.py after existing imports
from sqlalchemy import Column, String, DateTime, JSON, Integer
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class DPOJob(Base):
    """Persistent DPO training job record"""
    __tablename__ = 'dpo_jobs'
    
    id = Column(String(36), primary_key=True)
    base_model = Column(String(255), nullable=False)
    adapter_name = Column(String(255), nullable=False)
    dataset_path = Column(String(512), nullable=False)
    status = Column(String(50), nullable=False, default='queued')
    metrics = Column(JSON, nullable=True)
    adapter_path = Column(String(512), nullable=True)
    error = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)

class RLHFJob(Base):
    """Persistent RLHF training job record"""
    __tablename__ = 'rlhf_jobs'
    
    id = Column(String(36), primary_key=True)
    base_model = Column(String(255), nullable=False)
    adapter_name = Column(String(255), nullable=False)
    dataset_path = Column(String(512), nullable=False)
    status = Column(String(50), nullable=False, default='queued')
    rounds_completed = Column(Integer, nullable=False, default=0)
    reward_model_path = Column(String(512), nullable=True)
    metrics = Column(JSON, nullable=True)
    adapter_path = Column(String(512), nullable=True)
    error = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)

# Persistence functions
def save_dpo_job(job_dict):
    """Persist DPO job to database"""
    session = SessionLocal()
    try:
        db_job = DPOJob(
            id=job_dict['id'],
            base_model=job_dict['base_model'],
            adapter_name=job_dict['adapter_name'],
            dataset_path=job_dict['dataset_path'],
            status=job_dict['status'],
            metrics=job_dict.get('metrics'),
            adapter_path=job_dict.get('adapter_path'),
            error=job_dict.get('error'),
            created_at=job_dict['created_at'],
            completed_at=job_dict.get('completed_at'),
        )
        session.add(db_job)
        session.commit()
    finally:
        session.close()

def get_dpo_job_by_id(job_id):
    """Retrieve DPO job from database"""
    session = SessionLocal()
    try:
        return session.query(DPOJob).filter(DPOJob.id == job_id).first()
    finally:
        session.close()

def get_queued_dpo_jobs(limit=10):
    """Get next batch of queued DPO jobs for worker"""
    session = SessionLocal()
    try:
        return session.query(DPOJob).filter(
            DPOJob.status == 'queued'
        ).limit(limit).all()
    finally:
        session.close()
```

### Step 1.4: Persistence Correctness Gates (Mandatory)

Run and pass all of the following before Phase 2:

```bash
# 1) Baseline persistence tests
PYTHONPATH=. pytest tests/test_rlhf_dpo.py -v

# 2) Restart durability check (manual or scripted)
# Submit job -> restart API process -> verify job still retrievable with same status/metadata

# 3) Failure payload check
# Force one failed training run and verify persisted error payload is actionable
```

Acceptance criteria:

- Job records survive service restart with intact status and metadata.
- Status transitions (`queued -> running -> completed|failed`) are persisted atomically.
- Failed jobs persist machine-readable error details sufficient for retry triage.

### Step 1.5: Early Worker/Queue Readiness Preflight (Minimal Unblocker)

Why now: latest pipeline run remained `queued` for 120s, which is a Phase 2 slip risk if left unvalidated.

Do only these checks in Phase 1:

- Confirm a worker process can start in target environment and poll queued jobs.
- Confirm one queued DPO job is claimed (`queued -> running`) when worker is active.
- Confirm queue poll interval and basic retry/backoff settings are sane.

Do not expand into full Phase 2 implementation here. This is readiness validation only.

---

## Phase 2: Background Worker (2-3 days)

**Goal**: Implement async job execution without blocking API

**Entry Gate for Phase 2**:

- Phase 1 persistence correctness gates are fully green.
- Phase 1 queue-readiness preflight has proven at least one `queued -> running` transition.

### Step 2.1: Create Worker Script

Create file: `scripts/rlhf_worker.py`

```python
#!/usr/bin/env python3
"""Background worker for RLHF/DPO job execution"""
import os
import time
import logging
import argparse
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(message)s'
)
logger = logging.getLogger('rlhf_worker')

def process_dpo_jobs(worker_id=0, batch_size=1, poll_interval=30):
    """Main worker loop for DPO job processing"""
    from src.db import get_queued_dpo_jobs, save_dpo_job
    from src.rlhf_dpo import run_dpo_training
    
    logger.info(f"Worker {worker_id} started | batch_size={batch_size} poll_interval={poll_interval}s")
    
    while True:
        try:
            # Fetch next batch of queued jobs
            jobs = get_queued_dpo_jobs(limit=batch_size)
            
            if not jobs:
                logger.debug(f"No queued jobs, sleeping {poll_interval}s")
                time.sleep(poll_interval)
                continue
            
            for job_db in jobs:
                try:
                    logger.info(f"Processing job {job_db.id} | model={job_db.base_model} | adapter={job_db.adapter_name}")
                    
                    # Convert DB record to dict
                    job_dict = {
                        'id': job_db.id,
                        'base_model': job_db.base_model,
                        'adapter_name': job_db.adapter_name,
                        'dataset_path': job_db.dataset_path,
                        'status': 'running',
                        'metrics': {},
                        'created_at': job_db.created_at,
                    }
                    
                    # Update status to running
                    job_dict['status'] = 'running'
                    save_dpo_job(job_dict)
                    
                    # Execute training
                    result = run_dpo_training(job_dict)
                    
                    # Update with results
                    job_dict.update({
                        'status': 'completed',
                        'metrics': result.get('metrics', {}),
                        'adapter_path': result.get('adapter_path'),
                        'completed_at': datetime.utcnow(),
                    })
                    save_dpo_job(job_dict)
                    
                    logger.info(f"✓ Job {job_db.id} completed | metrics={result.get('metrics')}")
                    
                except Exception as e:
                    logger.error(f"✗ Job {job_db.id} failed: {e}", exc_info=True)
                    job_dict['status'] = 'failed'
                    job_dict['error'] = {'message': str(e)}
                    job_dict['completed_at'] = datetime.utcnow()
                    save_dpo_job(job_dict)
                    
        except Exception as e:
            logger.error(f"Worker {worker_id} error: {e}", exc_info=True)
            time.sleep(10)  # Backoff on error

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='RLHF/DPO Background Worker')
    parser.add_argument('--worker-id', type=int, default=0, help='Worker ID')
    parser.add_argument('--batch-size', type=int, default=1, help='Jobs per batch')
    parser.add_argument('--poll-interval', type=int, default=30, help='Poll interval in seconds')
    args = parser.parse_args()
    
    process_dpo_jobs(
        worker_id=args.worker_id,
        batch_size=args.batch_size,
        poll_interval=args.poll_interval,
    )
```

### Step 2.2: Deploy Worker

**Option A: Systemd Service**

Create file: `/etc/systemd/system/nexus-rlhf-worker.service`

```ini
[Unit]
Description=Nexus AI RLHF/DPO Background Worker
After=network.target

[Service]
Type=simple
User=nexus
WorkingDirectory=/opt/nexus-ai
ExecStart=/opt/nexus-ai/.venv/bin/python scripts/rlhf_worker.py --worker-id=0
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable nexus-rlhf-worker
sudo systemctl start nexus-rlhf-worker
sudo systemctl status nexus-rlhf-worker
```

**Option B: Docker Container**

Add to `docker-compose.prod.yml`:

```yaml
services:
  nexus-api:
    # ... existing config ...
    
  nexus-rlhf-worker:
    image: nexus-ai:latest
    command: python scripts/rlhf_worker.py --worker-id=0 --batch-size=1
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/nexus
      - OLLAMA_BASE_URL=http://ollama:11434
    depends_on:
      - nexus-api
    restart: always
    volumes:
      - ./adapters:/mnt/adapters
```

### Step 2.3: Test Worker

```bash
# Start worker in background
PYTHONPATH=. python scripts/rlhf_worker.py --poll-interval=5 &

# Submit a job via API
curl -X POST http://localhost:8000/v1/rlhf/dpo/job \
  -H "Content-Type: application/json" \
  -d '{
    "base_model": "meta-llama/Llama-2-7b",
    "dataset_path": "/tmp/nexus_*.jsonl",
    "adapter_name": "worker_test"
  }'

# Monitor job status
curl http://localhost:8000/v1/rlhf/dpo/jobs?status=running

# Should transition: queued → running → completed
```

---

## Phase 3: Monitoring & Observability (1-2 days)

**Goal**: Track job health, quality metrics, and system performance

### Step 3.1: Add Prometheus Metrics

Modify: `src/routes/rlhf.py`

```python
from prometheus_client import Counter, Histogram, Gauge
import time

# Metrics
dpo_jobs_total = Counter(
    'nexus_dpo_jobs_total',
    'Total DPO jobs created',
    ['status']
)

dpo_job_duration = Histogram(
    'nexus_dpo_job_duration_seconds',
    'DPO job execution time'
)

dpo_jobs_queued = Gauge(
    'nexus_dpo_jobs_queued',
    'Number of queued DPO jobs'
)

# Add to DPO job creation endpoint
@router.post("/dpo/job")
async def create_dpo_job(request: DPOJobCreateRequest):
    job_id = create_dpo_job(...)
    dpo_jobs_total.labels(status='queued').inc()
    dpo_jobs_queued.set(len(list_dpo_jobs()))
    return {"job_id": job_id, ...}

# Add to job completion
def update_job_status(job_id, new_status):
    # ... update logic ...
    if new_status == 'completed':
        dpo_jobs_total.labels(status='completed').inc()
        dpo_job_duration.observe(job.elapsed_time)
    elif new_status == 'failed':
        dpo_jobs_total.labels(status='failed').inc()
```

### Step 3.2: Alerting Rules

Create file: `config/prometheus_rules.yml`

```yaml
groups:
  - name: nexus_rlhf_alerts
    rules:
      - alert: DPOJobStuck
        expr: nexus_dpo_jobs_queued > 5
        for: 1h
        annotations:
          summary: "DPO job queue backlog > 5"
      
      - alert: DPOJobFailureRate
        expr: rate(nexus_dpo_jobs_total{status="failed"}[5m]) > 0.1
        annotations:
          summary: "DPO job failure rate > 10%"
      
      - alert: DPOJobSlowExecution
        expr: nexus_dpo_job_duration_seconds > 3600
        annotations:
          summary: "DPO job took > 1 hour"
```

---

## Phase 4: Staged Rollout (1-2 days)

**Goal**: Safely deploy trained adapters with traffic splitting

### Step 4.1: Adapter Registry

Modify: `src/lora.py`

```python
class AdapterVersion:
    def __init__(self, name, adapter_path, base_model, quality_score=None, traffic_weight=0.0):
        self.name = name
        self.adapter_path = adapter_path
        self.base_model = base_model
        self.quality_score = quality_score
        self.traffic_weight = traffic_weight

# Adapter registry with traffic splitting
adapter_registry = {
    'baseline': AdapterVersion('baseline', '/path/to/baseline', 'llama-7b', traffic_weight=1.0),
    'dpo_v1': AdapterVersion('dpo_v1', '/path/to/dpo_v1', 'llama-7b', traffic_weight=0.0),
}

def select_adapter():
    """Route traffic based on adapter weights"""
    import random
    r = random.random()
    cumulative = 0.0
    for name, adapter in adapter_registry.items():
        cumulative += adapter.traffic_weight
        if r <= cumulative:
            return adapter
    return adapter_registry['baseline']
```

### Step 4.2: Staged Promotion Script

Create file: `scripts/promote_adapter.py`

```python
#!/usr/bin/env python3
"""Promote DPO adapter through staged deployment"""
import argparse
import logging

logger = logging.getLogger('adapter_promoter')

def promote_adapter(adapter_name, quality_threshold=0.95):
    """
    Promote adapter through stages:
    0% → 5% → 25% → 50% → 100%
    """
    from src.lora import adapter_registry
    
    adapter = adapter_registry.get(adapter_name)
    if not adapter:
        logger.error(f"Adapter {adapter_name} not found")
        return False
    
    # Check quality gate
    if adapter.quality_score < quality_threshold:
        logger.warning(f"Quality score {adapter.quality_score} < threshold {quality_threshold}")
        return False
    
    # Stage 1: 5% traffic
    logger.info(f"Promoting {adapter_name} to 5% traffic")
    adapter.traffic_weight = 0.05
    time.sleep(3600)  # Monitor for 1 hour
    
    # Stage 2: 25% traffic
    logger.info(f"Promoting {adapter_name} to 25% traffic")
    adapter.traffic_weight = 0.25
    time.sleep(3600)  # Monitor for 1 hour
    
    # Stage 3: 50% traffic
    logger.info(f"Promoting {adapter_name} to 50% traffic")
    adapter.traffic_weight = 0.50
    time.sleep(3600)  # Monitor for 1 hour
    
    # Stage 4: 100% traffic
    logger.info(f"Promoting {adapter_name} to 100% traffic")
    adapter.traffic_weight = 1.0
    
    logger.info(f"✓ {adapter_name} fully promoted")
    return True

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('adapter_name')
    parser.add_argument('--quality-threshold', type=float, default=0.95)
    args = parser.parse_args()
    
    promote_adapter(args.adapter_name, args.quality_threshold)
```

### Step 4.3: Rollback Plan

```bash
# Quick rollback to baseline
ADAPTER=dpo_v1 python scripts/promote_adapter.py --quality-threshold=0.0

# This resets dpo_v1 traffic weight to 0
# Baseline automatically handles all traffic
```

---

## Phase 5: Operational Safety (1 day)

**Goal**: Automation, governance, and long-term sustainability

### Step 5.1: Eval-Gated Deployment

Modify: `src/rlhf_dpo.py`

```python
def evaluate_adapter(adapter_path, eval_dataset_path, baseline_path=None):
    """Evaluate adapter quality vs baseline"""
    from src.evals import run_eval_suite
    
    # Run evaluation
    metrics = run_eval_suite(adapter_path, eval_dataset_path)
    
    # Compare vs baseline
    if baseline_path:
        baseline_metrics = run_eval_suite(baseline_path, eval_dataset_path)
        improvement = (metrics['score'] - baseline_metrics['score']) / baseline_metrics['score']
        
        if improvement < 0.02:  # Require 2% improvement
            return {'status': 'rejected', 'improvement': improvement}
        return {'status': 'approved', 'improvement': improvement, 'metrics': metrics}
    
    return {'status': 'approved', 'metrics': metrics}

def maybe_promote_adapter(job_id):
    """Promote only if quality improves"""
    job = get_dpo_job(job_id)
    
    if job.status != 'completed':
        return False
    
    # Evaluate
    eval_result = evaluate_adapter(
        job.adapter_path,
        '/path/to/eval_dataset.jsonl'
    )
    
    if eval_result['status'] == 'approved':
        logger.info(f"Job {job_id} approved for deployment")
        return True
    else:
        logger.info(f"Job {job_id} rejected: improvement only {eval_result['improvement']:.1%}")
        return False
```

### Step 5.2: Scheduled Retraining

Create file: `scripts/scheduled_retrainer.py`

```python
#!/usr/bin/env python3
"""Periodic retraining on latest feedback"""
import schedule
import logging
from datetime import datetime, timedelta
from src.db import get_newest_feedback

logger = logging.getLogger('retrainer')

def retrain_on_schedule():
    """Retrain every Monday at 2 AM"""
    from src.lora import export_feedback_dataset
    from src.rlhf_dpo import prepare_dpo_dataset, create_dpo_job
    
    # Get feedback from last 7 days
    feedback = get_newest_feedback(days=7)
    
    if len(feedback) < 100:
        logger.info(f"Not enough feedback ({len(feedback)} < 100), skipping retrain")
        return
    
    logger.info(f"Starting scheduled retrain with {len(feedback)} pairs")
    
    # Prepare dataset
    dataset_path = prepare_dpo_dataset(feedback)
    
    # Create job
    job = create_dpo_job(
        base_model='meta-llama/Llama-2-7b',
        dataset_path=dataset_path,
        adapter_name=f"scheduled_dpo_{datetime.utcnow().strftime('%Y%m%d')}"
    )
    
    logger.info(f"Scheduled retrain job created: {job.id}")

# Schedule for every Monday at 2 AM
schedule.every().monday.at("02:00").do(retrain_on_schedule)

while True:
    schedule.run_pending()
    time.sleep(60)
```

---

## Phase 6: Deployment Checklist

Before going live, verify:

- [ ] **Database**: Migrations applied, tables verified
- [ ] **Worker**: Successfully processes jobs end-to-end
- [ ] **Monitoring**: Metrics collected, alerts configured
- [ ] **Staging**: Full pipeline tested on staging environment
- [ ] **Documentation**: Team trained on new procedures
- [ ] **Rollback**: Quick rollback procedure tested
- [ ] **Automation**: Scheduled retraining operational
- [ ] **Governance**: Quality gates enforced

---

## Deployment Timeline

| Week | Phase | Deliverable | Status |
|------|-------|-------------|--------|
| Week 1 | Database & Worker | Persistent jobs, background processing | In Progress |
| Week 2 | Monitoring & Rollout | Metrics, alerts, staged deployment | Blocked on Week 1 |
| Week 3 | Operations & Safety | Auto-retraining, eval-gated deployment | Blocked on Week 2 |
| Week 4 | Go-Live | Production deployment | Ready if above complete |

---

## Go/No-Go Decision (End of Month)

**Go** to production if:
- ✅ All tests passing (unit + integration + staging)
- ✅ Worker processes 10+ jobs successfully
- ✅ Monitoring operational with <5% false alarm rate
- ✅ Rollback tested and proven
- ✅ Team trained and confident

**No-Go** triggers:
- ❌ Quality metrics regressed
- ❌ > 20% job failure rate
- ❌ Adapter loading errors in prod test
- ❌ Team concerns about readiness

---

## Resources & Support

- **Documentation**: See `docs/RLHF_DPO_GUIDE.md`
- **Examples**: `examples/rlhf_dpo_workflows.py`
- **Tests**: `tests/test_rlhf_dpo.py`
- **Slack**: #nexus-ai-team for discussions
- **On-call**: Escalate critical issues to architecture team

---

**Created**: April 22, 2026  
**Last Updated**: April 22, 2026  
**Owner**: ML Ops Team
