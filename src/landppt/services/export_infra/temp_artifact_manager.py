"""
Temporary artifact lifecycle helpers for export workflows.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass


@dataclass
class TempArtifactManager:
    prefix: str
    path: str | None = None

    def create(self) -> str:
        if not self.path:
            self.path = tempfile.mkdtemp(prefix=self.prefix)
        return self.path

    def cleanup(self) -> None:
        if self.path:
            shutil.rmtree(self.path, ignore_errors=True)

