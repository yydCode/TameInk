import os
from pathlib import Path

from app.infrastructure.jobs import DurableAgentQueue

workspace = Path(os.environ.get("TAME_INK_WORKSPACE", ".tame-ink-workspace"))
huey = DurableAgentQueue(workspace).huey
