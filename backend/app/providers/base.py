from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ProviderRequest:
    job_id: str
    model_path: Path
    furniture_path: Path
    scene_path: Path
    composition_id: str
    composition_path: Path | None
    width: int
    height: int
    output_count: int
    extra_paths: tuple[Path, ...] = ()
    guidance: str | None = None


@dataclass(slots=True)
class ProviderOutput:
    path: Path
    metadata: dict[str, object]


class GenerationProvider(ABC):
    @abstractmethod
    async def submit_job(self, request: ProviderRequest) -> str: ...

    @abstractmethod
    async def get_outputs(self, request: ProviderRequest) -> list[ProviderOutput]: ...

    @abstractmethod
    async def cancel_job(self, provider_job_id: str) -> None: ...

    @abstractmethod
    def get_capabilities(self) -> dict[str, object]: ...
