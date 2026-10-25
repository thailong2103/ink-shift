"""Central registry for managing and discovering translation engines."""

from src.backend.engines.base import BaseTranslationEngine
from src.backend.logging import format_logfmt, get_logger

logger = get_logger("engine.registry")


class EngineNotFoundError(Exception):
    """Raised when an engine name is not found in the registry."""




class EngineRegistry:
    """Registry maintaining active translation engines and default fallbacks."""

    def __init__(self) -> None:
        self._engines: dict[str, BaseTranslationEngine] = {}
        self._default_engine_name: str | None = None

    def register(
        self, engine: BaseTranslationEngine, is_default: bool = False
    ) -> None:
        """Register a translation engine instance."""
        self._engines[engine.name] = engine
        if is_default or self._default_engine_name is None:
            self._default_engine_name = engine.name
        logger.debug(
            format_logfmt(
                "EngineRegistered",
                name=engine.name,
                is_default=bool(is_default or self._default_engine_name == engine.name),
            )
        )

    def get(self, name: str) -> BaseTranslationEngine:
        """Retrieve an engine by name or raise EngineNotFoundError."""
        if name not in self._engines:
            raise EngineNotFoundError(f"Engine '{name}' is not registered.")
        return self._engines[name]

    def get_default(self) -> BaseTranslationEngine:
        """Retrieve the default engine or raise EngineNotFoundError."""
        if (
            self._default_engine_name is None
            or self._default_engine_name not in self._engines
        ):
            raise EngineNotFoundError("No engines registered in registry.")
        return self._engines[self._default_engine_name]

    async def list_available(self) -> dict[str, bool]:
        """Return a mapping of engine names to their readiness status."""
        result: dict[str, bool] = {}
        for name, engine in self._engines.items():
            result[name] = await engine.is_available()
        return result
