"""LLM provider adapters for the cv_skill package.

Each adapter implements the :class:`adapters._base.LLMAdapter` Protocol.
Adapters are intentionally kept outside the ``src/cv_skill/`` package tree so
that their provider SDK dependencies remain truly optional and are never
imported by the core package.
"""
