"""
Shared rules for timestamped directories under output/.

Folder base name: YYYY-MM-DD_26 v  (literal "_26 v"; space before "v").
Same-day collision:  YYYY-MM-DD_26 v (2), YYYY-MM-DD_26 v (3), ...
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

OUTPUT_SUFFIX = "_26 v"


def allocate_output_run_dir(project_root: Path, when: datetime | None = None) -> Path:
    """
    Return a Path under project_root/output/ that does not yet exist.
    Does not create the directory — callers mkdir after.
    """
    when = when or datetime.now()
    date_part = when.strftime("%Y-%m-%d")
    base_name = f"{date_part}{OUTPUT_SUFFIX}"
    out_root = project_root / "output"
    out_root.mkdir(parents=True, exist_ok=True)

    candidate = out_root / base_name
    if not candidate.exists():
        return candidate

    n = 2
    while True:
        name = f"{date_part}{OUTPUT_SUFFIX} ({n})"
        c = out_root / name
        if not c.exists():
            return c
        n += 1
