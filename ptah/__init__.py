"""PTAH - the Olympos software-engineering agent kernel.

Public surface:

    Agent, RunResult            the reasoning-action loop
    Conversation, Store         event-sourced persistent sessions
    LLM, ScriptedLLM            provider-agnostic brains
    ToolRegistry, tools.*       audited action surface
    RiskAnalyzer, Policy        security classification + confirmation
    load_skills                 keyword-triggered knowledge cards
    condense                    bounded history
"""

from ptah.content import VERSION as __version__  # noqa: F401
from ptah.backend import BackendRouter, HealthAwareBackendRouter  # noqa: F401
from ptah.deployment import (deployment_readiness,
                             validate_deployment)  # noqa: F401

__all__ = ["__version__", "BackendRouter", "HealthAwareBackendRouter",
           "deployment_readiness", "validate_deployment"]
