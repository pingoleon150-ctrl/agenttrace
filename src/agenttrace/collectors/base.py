from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from agenttrace.models import Observation


class Collector(ABC):
    @abstractmethod
    async def collect(self) -> AsyncIterator[Observation]:
        """Yield public observations without bypassing authentication or access controls."""
        raise NotImplementedError
