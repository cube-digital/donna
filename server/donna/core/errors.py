from dataclasses import dataclass, field
from typing import Dict, Optional, Set


@dataclass
class StrategyErrorConfig:
    """Per-strategy validation configuration."""

    disallowed_substrings: Set[str] = field(default_factory=set)
    allow_html: bool = True
    allow_page_delimiters: bool = True
    reject_tracebacks_under: int = 600
    min_length: int = 0


@dataclass
class OCRErrorPolicy:
    """Global error policy with optional per-strategy overrides."""

    global_disallowed_substrings: Set[str] = field(default_factory=set)
    global_min_length: int = 0
    default_strategy: StrategyErrorConfig = field(default_factory=StrategyErrorConfig)
    strategy_overrides: Dict[str, StrategyErrorConfig] = field(default_factory=dict)

    def get_effective_config(self, strategy_name: Optional[str]) -> StrategyErrorConfig:
        if strategy_name and strategy_name in self.strategy_overrides:
            override = self.strategy_overrides[strategy_name]
            # Merge default and override (override takes precedence)
            merged = StrategyErrorConfig(
                disallowed_substrings=(
                    self.default_strategy.disallowed_substrings
                    | override.disallowed_substrings
                ),
                allow_html=override.allow_html,
                allow_page_delimiters=override.allow_page_delimiters,
                reject_tracebacks_under=override.reject_tracebacks_under,
                min_length=max(self.default_strategy.min_length, override.min_length),
            )
            return merged
        return self.default_strategy


def default_error_policy() -> OCRErrorPolicy:
    """Return a sensible default error policy."""
    global_blocklist = {
        "authenticationerror",
        "unauthorized",
        "incorrect api key",
        "api key provided",
        "status code 401",
        "status code 403",
        "http 401",
        "http 403",
        "401 unauthorized",
        "403 forbidden",
    }

    default_cfg = StrategyErrorConfig(
        disallowed_substrings=set(),
        allow_html=True,
        allow_page_delimiters=True,
        reject_tracebacks_under=600,
        min_length=0,
    )

    # Examples of custom overrides if needed later
    overrides: Dict[str, StrategyErrorConfig] = {}

    return OCRErrorPolicy(
        global_disallowed_substrings=global_blocklist,
        global_min_length=0,
        default_strategy=default_cfg,
        strategy_overrides=overrides,
    )


class NarrioException(Exception):
    pass


class ExternalServiceAPIError(NarrioException):
    """Exception to mark network communication errors"""

    def _init_(self, code, message):
        self.code = code
        super()._init_(message)


class ImproperlyConfigured(NarrioException):
    pass
