"""Shared skeleton every track builds on (S0).

- `common.schema`: contract values, record shapes, run_id / timestamp / trace-hash helpers (spec 2.2, 2.3, 4.4-4.7)
- `common.tooling`: the tool interface between `loop` and `tools` (spec 4.2)
- `common.limits`: default limits the code enforces (spec 4.10 and the other 조정값, i.e. adjustable defaults)
- `common/fixtures/`: spec 4.7-format fake input (a fictional work) to develop against until the real data lands

Owned by the upper orchestrator. Tracks only read it; ask for changes with an orch.py `request`.
"""

from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
