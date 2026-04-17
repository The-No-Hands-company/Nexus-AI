"""
Gunicorn configuration for Nexus AI.

Usage:
    gunicorn main:app -c gunicorn.conf.py

Environment variables:
    PORT          HTTP port (default 8000)
    WEB_WORKERS   Uvicorn worker count (default: 2*CPU+1, capped at 8)
    WORKER_TIMEOUT  Worker timeout in seconds (default 120)
"""
import os
import multiprocessing

_cpu = multiprocessing.cpu_count()

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
workers = int(os.getenv("WEB_WORKERS", min(2 * _cpu + 1, 8)))
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
timeout = int(os.getenv("WORKER_TIMEOUT", "120"))
keepalive = 5
graceful_timeout = 30
max_requests = 1000
max_requests_jitter = 50

# Logging
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "nexus-ai"

# Security
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190
