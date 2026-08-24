"""PTAH - the Yggdrasil software-engineering agent kernel.

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

__all__ = ["__version__"]
