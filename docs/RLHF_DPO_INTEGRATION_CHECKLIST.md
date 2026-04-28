# RLHF/DPO Integration Checklist

This checklist guides integration of the new RLHF/DPO modules into Nexus AI's main application.

## Pre-Integration Verification

- [ ] **Dependencies installed**
  ```bash
  pip install -r requirements.txt
  pip install transformers peft trl datasets torch bitsandbytes
  ```

- [ ] **Tests passing**
  ```bash
  pytest tests/test_rlhf_dpo.py -v
  ```

- [ ] **Examples runnable**
  ```bash
  python examples/rlhf_dpo_workflows.py
  ```

- [ ] **No import conflicts**
  ```bash
  python -c "from src.rlhf_dpo import prepare_dpo_dataset; print('✓')"
  python -c "from src.routes.rlhf import router; print('✓')"
  ```

---

## Phase 1: API Integration

### Step 1.1: Register Routes

**File**: `src/app.py`

Add after existing imports:
```python
from src.routes.rlhf import router as rlhf_router
```

Add after other route registrations:
```python
# Register RLHF/DPO routes
app.include_router(rlhf_router)
```

**Verification**:
```bash
curl http://localhost:8000/v1/rlhf/health
# Should return: {"status": "healthy", "dpo_jobs_queued": 0, ...}
```

### Step 1.2: Update API Documentation

**File**: `src/app.py`

Ensure OpenAPI tags are updated:
```python
tags_metadata = [
    {"name": "RLHF/DPO", "description": "RLHF and DPO training endpoints"},
    # ... other tags
]

app = FastAPI(openapi_tags=tags_metadata)
```

**Verification**: Visit `http://localhost:8000/docs` and see "RLHF/DPO" section.

### Step 1.3: Add Environment Variables

**File**: `.env` or `.env.local`

```bash
# RLHF/DPO configuration
ADAPTER_STORE_DIR=/tmp/nexus_adapters
RLHF_MAX_JOBS=5
RLHF_WORKER_ENABLED=false  # Enable after worker is running
```

---

## Phase 2: Database Persistence

### Step 2.1: Create Database Schema

**File**: `migrations/versions/[timestamp]_add_rlhf_dpo_tables.py`

```python
"""Add RLHF and DPO job tables."""

from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table(
        'dpo_jobs',
        sa.Column('job_id', sa.String(36), primary_key=True),
        sa.Column('base_model', sa.String(255), nullable=False),
        sa.Column('dataset_path', sa.String(255), nullable=False),
        sa.Column('adapter_name', sa.String(255), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),  # queued|running|completed|failed
        sa.Column('created_at', sa.String(30), nullable=False),
        sa.Column('completed_at', sa.String(30), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('metrics', sa.JSON(), nullable=True),
        sa.Column('adapter_path', sa.String(255), nullable=True),
    )

    op.create_table(
        'rlhf_jobs',
        sa.Column('job_id', sa.String(36), primary_key=True),
        sa.Column('base_model', sa.String(255), nullable=False),
        sa.Column('dataset_path', sa.String(255), nullable=False),
        sa.Column('adapter_name', sa.String(255), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('rounds_completed', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.String(30), nullable=False),
        sa.Column('completed_at', sa.String(30), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('metrics', sa.JSON(), nullable=True),
        sa.Column('adapter_path', sa.String(255), nullable=True),
        sa.Column('reward_model_path', sa.String(255), nullable=True),
    )

def downgrade():
    op.drop_table('dpo_jobs')
    op.drop_table('rlhf_jobs')
```

**Run migration**:
```bash
alembic upgrade head
```

### Step 2.2: Add DB Functions

**File**: `src/db.py`

Add functions to replace in-memory storage:

```python
def persist_dpo_job(job):
    """Save DPO job to database."""
    # Implementation using your DB abstraction

def get_dpo_job_from_db(job_id):
    """Load DPO job from database."""
    # Implementation

def list_dpo_jobs_from_db(status=None):
    """List DPO jobs from database."""
    # Implementation

# Similar for RLHF jobs
```

### Step 2.3: Update RLHF Module to Use DB

**File**: `src/rlhf_dpo.py`

Modify to use database instead of in-memory:

```python
def create_dpo_job(...):
    job = DPOJob(...)
    persist_dpo_job(job)  # Add this line
    return job
```

---

## Phase 3: Background Worker Setup

### Step 3.1: Create Worker Script

**File**: `scripts/rlhf_worker.py`

```python
#!/usr/bin/env python
"""Background worker for RLHF/DPO training jobs."""

import time
import logging
from src.rlhf_dpo import list_dpo_jobs, list_rlhf_jobs, run_dpo_training, run_rlhf_training

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    logger.info("RLHF/DPO Worker starting...")
    
    while True:
        try:
            # Process DPO jobs
            dpo_jobs = list_dpo_jobs(status="queued")
            for job in dpo_jobs[:1]:  # Process one at a time
                logger.info(f"Running DPO job: {job.job_id}")
                run_dpo_training(job)
            
            # Process RLHF jobs
            rlhf_jobs = list_rlhf_jobs(status="queued")
            for job in rlhf_jobs[:1]:
                logger.info(f"Running RLHF job: {job.job_id}")
                run_rlhf_training(job)
            
            time.sleep(30)  # Check queue every 30 seconds
        except Exception as e:
            logger.exception(f"Worker error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
```

### Step 3.2: Run Worker

```bash
# Start worker (in production, use systemd or supervisor)
python scripts/rlhf_worker.py &

# Or via Docker (add to docker-compose.yml):
# rlhf-worker:
#   build: .
#   command: python scripts/rlhf_worker.py
#   volumes:
#     - /tmp/nexus_adapters:/tmp/nexus_adapters
```

---

## Phase 4: Monitoring and Observability

### Step 4.1: Add Job Metrics Logging

**File**: `src/monitoring.py` (or similar)

```python
def log_job_event(event_type, job_id, job_type, status, metrics=None):
    """Log job events for monitoring."""
    logger.info(f"Job event: type={event_type} job_id={job_id} job_type={job_type} status={status}")
    # Send to telemetry/monitoring system

def track_job_completion(job):
    """Track job completion metrics."""
    log_job_event("completion", job.job_id, "dpo", job.status, metrics=job.metrics)
```

### Step 4.2: Add Health Checks

**File**: `src/routes/health.py` (or similar)

```python
@app.get("/health/rlhf")
def rlhf_health():
    """Check RLHF system health."""
    from src.rlhf_dpo import list_dpo_jobs, list_rlhf_jobs
    
    dpo_queued = len(list_dpo_jobs(status="queued"))
    dpo_running = len(list_dpo_jobs(status="running"))
    dpo_failed = len(list_dpo_jobs(status="failed"))
    
    return {
        "dpo": {
            "queued": dpo_queued,
            "running": dpo_running,
            "failed": dpo_failed,
        },
        # Similar for RLHF
    }
```

---

## Phase 5: Feedback Collection

### Step 5.1: Collect User Feedback

**File**: `src/feedback.py`

Integrate preference feedback collection:

```python
def collect_feedback(prompt, response_a, response_b, preferred):
    """Collect user preference feedback."""
    feedback = {
        "prompt": prompt,
        "response_a": response_a,
        "response_b": response_b,
        "preferred": preferred,
        "rating": get_user_rating(),
        "timestamp": datetime.now().isoformat(),
    }
    # Store in database
    save_feedback(feedback)
```

### Step 5.2: Export Feedback as Training Data

```python
def export_feedback_for_rlhf(min_rating=3, start_date=None):
    """Export collected feedback as RLHF training data."""
    # Query feedback from database
    # Convert to preference pairs format
    # Save to JSONL
```

---

## Phase 6: Testing and Validation

### Step 6.1: Run Integration Tests

```bash
# Test API endpoints
curl -X GET http://localhost:8000/v1/rlhf/health
curl -X GET http://localhost:8000/v1/rlhf/dpo/jobs

# Test job creation
curl -X POST http://localhost:8000/v1/rlhf/dpo/job \
  -H "Content-Type: application/json" \
  -d '{"base_model": "llama", "dataset_path": "/tmp/test.jsonl", "adapter_name": "test"}'
```

### Step 6.2: Validate Data Flow

```bash
# Create sample feedback
python examples/rlhf_dpo_workflows.py

# Check database
sqlite3 nexus.db "SELECT COUNT(*) FROM dpo_jobs;"

# Monitor worker
tail -f /var/log/nexus/rlhf_worker.log
```

### Step 6.3: Run Full Test Suite

```bash
pytest tests/test_rlhf_dpo.py -v
pytest tests/ -k rlhf -v
```

---

## Phase 7: Deployment

### Step 7.1: Update Docker

**File**: `docker-compose.yml`

```yaml
services:
  # ... existing services ...
  
  rlhf-worker:
    build: .
    command: python scripts/rlhf_worker.py
    environment:
      - ADAPTER_STORE_DIR=/tmp/nexus_adapters
      - DATABASE_URL=${DATABASE_URL}
    volumes:
      - /tmp/nexus_adapters:/tmp/nexus_adapters
      - ./logs:/var/log/nexus
    depends_on:
      - api
    restart: unless-stopped
```

### Step 7.2: Environment Configuration

**File**: `.env.production`

```bash
# RLHF/DPO
RLHF_WORKER_ENABLED=true
ADAPTER_STORE_DIR=/mnt/storage/adapters
RLHF_MAX_JOBS=2
RLHF_MAX_BATCH_SIZE=8
RLHF_GPU_DEVICES=0,1  # GPU IDs for training
```

### Step 7.3: Production Deployment

```bash
# Build and push
docker build -t nexus-ai:latest .
docker push nexus-ai:latest

# Deploy
kubectl apply -f deploy/k8s/rlhf-worker.yaml
# or
docker-compose -f docker-compose.prod.yml up -d rlhf-worker
```

---

## Phase 8: Monitoring (Post-Deployment)

### Step 8.1: Setup Monitoring Dashboard

Track:
- Job creation rate
- Job completion time
- Job failure rate
- Average training loss
- Adapter promotion rate

### Step 8.2: Alerts

Setup alerts for:
- Job failure rate > 10%
- Average job duration > 6 hours
- Queue depth > 50 jobs
- Worker restart loop

### Step 8.3: Logs

Aggregate logs from:
- API endpoint logs
- Worker process logs
- Training job logs
- Error/exception logs

---

## Troubleshooting During Integration

### Routes Not Found

```bash
# Verify registration in app.py
grep "rlhf_router" src/app.py

# Restart server
# GET /v1/rlhf/health should return 200 OK
```

### Jobs Not Processing

```bash
# Check worker is running
ps aux | grep rlhf_worker

# Check database connections
sqlite3 nexus.db "SELECT status, COUNT(*) FROM dpo_jobs GROUP BY status;"

# Check logs
tail -f logs/worker.log
```

### GPU Out of Memory

```bash
# Reduce batch size in config
config = {"per_device_batch_size": 2}

# Or reduce LoRA rank
config = {"lora_r": 8}
```

### Slow Training

```bash
# Check GPU usage
nvidia-smi

# Check disk I/O
iostat -x 1

# Profile training
python -m cProfile scripts/rlhf_worker.py
```

---

## Validation Checklist

### Pre-Launch

- [ ] All tests passing (`pytest tests/test_rlhf_dpo.py -v`)
- [ ] Examples runnable (`python examples/rlhf_dpo_workflows.py`)
- [ ] API endpoints accessible
- [ ] Database migrations applied
- [ ] Worker starts without errors
- [ ] Feedback collection working
- [ ] Monitoring dashboards set up

### Post-Launch

- [ ] Health check endpoint working
- [ ] Jobs appear in database
- [ ] Worker picks up queued jobs
- [ ] Training completes successfully
- [ ] Metrics logged correctly
- [ ] No console errors
- [ ] No database errors
- [ ] Performance meets SLA

---

## Rollback Plan

If issues arise:

1. **Stop worker**: `kill $(pgrep -f rlhf_worker)`
2. **Disable API routes**: Comment out `app.include_router(rlhf_router)` in `app.py`
3. **Check database**: Backup `nexus.db` before downgrade
4. **Rollback migration**: `alembic downgrade -1`
5. **Monitor**: Restart API and watch for errors
6. **Restore**: If critical, restore from backup

---

## Success Criteria

✅ **Integration Complete When:**

- All tests pass
- API endpoints return 200 OK
- Background worker processes jobs
- Database persists job history
- Feedback flows into training pipeline
- Adapters are saved and loadable
- Monitoring captures metrics
- No console errors or warnings

---

## Next Steps After Integration

1. **Collect User Feedback**: Enable preference pair collection in chat interface
2. **Run First DPO Training**: Create manual DPO job to verify pipeline
3. **Monitor Quality**: Track pre/post metrics on sample conversations
4. **Gradual Rollout**: Enable for 10% of users, track feedback
5. **Iterate**: Collect more data, retrain, improve iteratively

---

## Support

For issues during integration:

- **API Routes**: Check `src/routes/rlhf.py` for endpoint details
- **Examples**: Run `python examples/rlhf_dpo_workflows.py` for reference
- **Tests**: Use `tests/test_rlhf_dpo.py` as integration test template
- **Documentation**: See `docs/RLHF_DPO_GUIDE.md` for full reference
- **Logs**: Check logs in `logs/` directory for errors
