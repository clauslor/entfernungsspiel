import os

# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
# IMPORTANT: This application stores all game state in-process (GameRoom).
# Multiple workers would each have their own isolated state, so WebSocket
# connections on different workers would not see the same games.
# Keep workers=1 unless you migrate to a shared state backend (e.g. Redis).
workers = 1
worker_class = "uvicorn.workers.UvicornWorker"

# ---------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------
bind = f"{os.getenv('HOST', '0.0.0.0')}:{os.getenv('PORT', '9000')}"

# ---------------------------------------------------------------------------
# Timeouts
# ---------------------------------------------------------------------------
# WebSocket connections are long-lived; a low timeout would kill active games.
timeout = 120
graceful_timeout = 30
keepalive = 65

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
accesslog = "-"   # stdout
errorlog = "-"    # stderr
loglevel = os.getenv("LOG_LEVEL", "info").lower()

# ---------------------------------------------------------------------------
# Process name (visible in ps/top)
# ---------------------------------------------------------------------------
proc_name = "entfernungsspiel"
