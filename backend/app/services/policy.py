from dataclasses import dataclass
from urllib.parse import urlparse

from ..database import Investigation, Target
from ..schemas import ToolRequest
from .knowledge import approved_web_paths


class PolicyViolation(ValueError):
    pass


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str


class PolicyEngine:
    allowed_operations = {"read_only"}

    def authorize(
        self,
        request: ToolRequest,
        target: Target | None,
        investigation: Investigation,
        max_tool_calls: int,
    ) -> PolicyDecision:
        if target is None or not target.authorized:
            raise PolicyViolation("UNAUTHORIZED_TARGET: target is not on the explicit allowlist")
        if request.target_id != target.id:
            raise PolicyViolation("SCOPE_MISMATCH: request target does not match investigation")
        if request.tool not in target.allowed_tools:
            raise PolicyViolation("TOOL_NOT_ALLOWED: tool is outside the target policy")
        if request.operation not in self.allowed_operations:
            raise PolicyViolation("OPERATION_NOT_ALLOWED: only read-only operations are permitted")
        if request.scope != "authorized":
            raise PolicyViolation("SCOPE_NOT_AUTHORIZED")
        if request.tool == "network_discovery" and request.path != "/":
            raise PolicyViolation("DISCOVERY_PATH_NOT_ALLOWED: discovery is target-wide and has no route path")
        approved_paths = set(getattr(target, "approved_paths", None) or approved_web_paths(target.id))
        if request.tool == "web_inspection" and request.path not in approved_paths:
            raise PolicyViolation("PATH_NOT_ALLOWED: web inspection path is outside approved target knowledge")
        if investigation.tool_calls >= max_tool_calls:
            raise PolicyViolation("TOOL_BUDGET_EXCEEDED")
        parsed = urlparse(target.base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname != target.host:
            raise PolicyViolation("TARGET_CONFIG_INVALID: base URL escapes the allowlisted host")
        return PolicyDecision(True, "Target, tool, operation, scope, and budget approved")
