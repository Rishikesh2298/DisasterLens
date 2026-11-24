import os
from typing import Callable, Literal, Type

from dl.vision.base import VisionAdapter

VisionMode = Literal["live", "cached", "mock"]
SUPPORTED_MODES: set[str] = {"live", "cached", "mock"}

# Registry mapping provider name (lowercase) to adapter factory or class
_ADAPTER_REGISTRY: dict[str, Type[VisionAdapter] | Callable[..., VisionAdapter]] = {}


def register_adapter(
    name: str,
) -> Callable[[Type[VisionAdapter] | Callable[..., VisionAdapter]], Type[VisionAdapter] | Callable[..., VisionAdapter]]:
    """
    Decorator to register a VisionAdapter implementation or factory function.

    Example:
        @register_adapter("gemini")
        class GeminiVisionAdapter(VisionAdapter):
            ...
    """
    def decorator(
        cls_or_factory: Type[VisionAdapter] | Callable[..., VisionAdapter]
    ) -> Type[VisionAdapter] | Callable[..., VisionAdapter]:
        key = name.strip().lower()
        _ADAPTER_REGISTRY[key] = cls_or_factory
        return cls_or_factory

    return decorator


def list_registered_providers() -> list[str]:
    """Return a sorted list of registered provider names."""
    return sorted(_ADAPTER_REGISTRY.keys())


def clear_registry() -> None:
    """Clear all registered adapters (useful for unit testing)."""
    _ADAPTER_REGISTRY.clear()


def get_adapter(
    provider: str | None = None,
    model: str | None = None,
    mode: str | None = None,
    **kwargs,
) -> VisionAdapter:
    """
    Factory function to retrieve a configured VisionAdapter instance.

    Reads configuration from environment variables if arguments are omitted:
    - VISION_MODE: 'live', 'cached', or 'mock' (default: 'mock')
    - VISION_PROVIDER: 'gemini', 'mock', etc. (default: 'gemini')
    - VISION_MODEL: e.g. 'gemini-1.5-pro' or 'oracle-mock' (default depends on provider)

    Args:
        provider: Provider name (e.g., 'gemini', 'mock').
        model: Model name/identifier.
        mode: Execution mode ('live', 'cached', 'mock').
        **kwargs: Additional provider-specific parameters (e.g. api_key, cache_dir).

    Returns:
        VisionAdapter: An initialized adapter conforming to the VisionAdapter interface.

    Raises:
        ValueError: If mode is unsupported or provider is unregistered.
    """
    # 1. Resolve and validate VISION_MODE
    resolved_mode = (mode or os.getenv("VISION_MODE", "mock")).strip().lower()
    if resolved_mode not in SUPPORTED_MODES:
        raise ValueError(
            f"Invalid VISION_MODE '{resolved_mode}'. Allowed modes are: {sorted(SUPPORTED_MODES)}"
        )

    # 2. Resolve VISION_PROVIDER
    if resolved_mode == "mock":
        resolved_provider = (provider or os.getenv("VISION_PROVIDER", "mock")).strip().lower()
    else:
        resolved_provider = (provider or os.getenv("VISION_PROVIDER", "gemini")).strip().lower()

    # 3. Resolve VISION_MODEL
    default_model = "oracle-mock" if resolved_mode == "mock" else "gemini-1.5-pro"
    resolved_model = (model or os.getenv("VISION_MODEL", default_model)).strip()

    # 4. Handle 'mock' mode
    if resolved_mode == "mock":
        if "mock" in _ADAPTER_REGISTRY:
            adapter = _ADAPTER_REGISTRY["mock"](model=resolved_model, **kwargs)
        else:
            # Lazy import to avoid circular dependency
            try:
                from dl.vision.mock import MockVisionAdapter
                adapter = MockVisionAdapter(model=resolved_model, **kwargs)
            except (ImportError, AttributeError) as err:
                raise NotImplementedError(
                    "Mock mode requested, but MockVisionAdapter is not yet implemented in dl.vision.mock"
                ) from err
        return adapter

    # 5. Handle 'live' and 'cached' modes
    # If provider is not yet in registry, attempt lazy import of standard built-in providers
    if resolved_provider not in _ADAPTER_REGISTRY:
        _try_lazy_load_provider(resolved_provider)

    if resolved_provider not in _ADAPTER_REGISTRY:
        available = list_registered_providers()
        raise ValueError(
            f"Unknown VISION_PROVIDER '{resolved_provider}'. "
            f"Available registered providers: {available if available else 'None'}. "
            f"Please register the provider or set a valid VISION_PROVIDER."
        )

    adapter_factory = _ADAPTER_REGISTRY[resolved_provider]
    adapter = adapter_factory(model=resolved_model, **kwargs)

    # 6. Wrap in cache layer if in 'cached' mode
    if resolved_mode == "cached":
        try:
            from dl.vision.cache import CachedVisionAdapter
            adapter = CachedVisionAdapter(inner_adapter=adapter, **kwargs)
        except (ImportError, AttributeError) as err:
            raise NotImplementedError(
                "Cached mode requested, but CachedVisionAdapter is not yet implemented in "
                "dl.vision.cache (scheduled for Day 3)."
            ) from err

    return adapter


def _try_lazy_load_provider(provider_name: str) -> None:
    """Attempt to import built-in providers to trigger their @register_adapter."""
    if provider_name == "gemini":
        try:
            import dl.vision.providers.gemini  # noqa: F401
        except (ImportError, AttributeError):
            pass
    elif provider_name in ("backup", "openai", "claude"):
        try:
            import dl.vision.providers.backup_adapter  # noqa: F401
        except (ImportError, AttributeError):
            pass
