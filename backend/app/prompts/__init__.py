"""Versioned system instructions used only by hosted-model mode."""

from .critic import CRITIC_SYSTEM_PROMPT
from .investigator import INVESTIGATOR_SYSTEM_PROMPT

__all__ = ["CRITIC_SYSTEM_PROMPT", "INVESTIGATOR_SYSTEM_PROMPT"]
