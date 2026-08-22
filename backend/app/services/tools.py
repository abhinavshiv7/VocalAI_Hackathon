from __future__ import annotations

import asyncio
import json
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from ..database import Target
from ..schemas import ToolRequest
from .failures import failure_controller


@dataclass
class NormalizedEvidence:
    source: str
    target: str
    observation: str
    severity: str
    kind: str = "OBSERVATION"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    status: str
    summary: str
    latency_ms: int
    evidence: list[NormalizedEvidence]
    error_type: str | None = None


class SecurityTool:
    name: str
    description: str
    executable: str

    def command(self, request: ToolRequest, target: Target) -> list[str]:
        raise NotImplementedError

    def normalize(self, stdout: str, request: ToolRequest, target: Target) -> list[NormalizedEvidence]:
        raise NotImplementedError

    async def execute(self, request: ToolRequest, target: Target, timeout: float) -> ToolResult:
        started = time.perf_counter()
        if failure_controller.matches("tool", self.name):
            return self._failure(started, "TOOL_UNAVAILABLE", "Demo failure injection blocked this tool")
        try:
            process = await asyncio.create_subprocess_exec(
                *self.command(request, target),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except TimeoutError:
                process.kill()
                await process.communicate()
                return self._failure(started, "TOOL_TIMEOUT", f"{self.name} exceeded {timeout:.0f}s")
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
            if process.returncode != 0 or not stdout.strip():
                return self._failure(
                    started,
                    "TOOL_FAILED",
                    stderr or f"{self.name} returned no usable output",
                )
            evidence = self.normalize(stdout, request, target)
            if not evidence:
                return self._failure(started, "TOOL_FAILED", "Tool output contained no normalizable evidence")
            return ToolResult(
                status="SUCCEEDED",
                summary=f"{self.name} produced {len(evidence)} normalized evidence item(s)",
                latency_ms=int((time.perf_counter() - started) * 1000),
                evidence=evidence,
            )
        except FileNotFoundError:
            return self._failure(started, "TOOL_UNAVAILABLE", f"{self.executable} is not installed")
        except (ET.ParseError, json.JSONDecodeError, ValueError) as exc:
            return self._failure(started, "TOOL_FAILED", f"Could not normalize output: {exc}")
        except Exception as exc:  # the tool boundary must never crash the investigation
            return self._failure(started, "TOOL_FAILED", str(exc))

    def _failure(self, started: float, error_type: str, message: str) -> ToolResult:
        return ToolResult(
            status="FAILED",
            summary=message[:500],
            latency_ms=int((time.perf_counter() - started) * 1000),
            error_type=error_type,
            evidence=[
                NormalizedEvidence(
                    source=self.name,
                    target="authorized-target",
                    observation=message[:500],
                    severity="info",
                    kind=error_type,
                    raw={"error": error_type},
                )
            ],
        )


class NmapDiscoveryTool(SecurityTool):
    name = "network_discovery"
    description = "Read-only TCP service discovery using nmap XML output"
    executable = "nmap"

    def command(self, request: ToolRequest, target: Target) -> list[str]:
        return [
            self.executable,
            "-Pn",
            "-p",
            str(target.port),
            "-sT",
            "--host-timeout",
            "6s",
            "-oX",
            "-",
            target.host,
        ]

    def normalize(self, stdout: str, request: ToolRequest, target: Target) -> list[NormalizedEvidence]:
        root = ET.fromstring(stdout)
        evidence: list[NormalizedEvidence] = []
        for port in root.findall(".//port"):
            state = port.find("state")
            service = port.find("service")
            port_id = port.attrib.get("portid", "unknown")
            state_name = state.attrib.get("state", "unknown") if state is not None else "unknown"
            service_name = service.attrib.get("name", "unknown") if service is not None else "unknown"
            evidence.append(
                NormalizedEvidence(
                    source=self.name,
                    target=target.id,
                    observation=f"TCP port {port_id} is {state_name}; service fingerprint: {service_name}",
                    severity="info" if state_name == "open" else "low",
                    raw={"port": port_id, "state": state_name, "service": service_name},
                )
            )
        return evidence


class HttpxInspectionTool(SecurityTool):
    name = "web_inspection"
    description = "Read-only HTTP probing using ProjectDiscovery httpx JSON output"
    executable = "httpx"
    expected_headers = [
        "content-security-policy",
        "x-frame-options",
        "x-content-type-options",
    ]

    def command(self, request: ToolRequest, target: Target) -> list[str]:
        return [
            self.executable,
            "-u",
            f"{target.base_url.rstrip('/')}{request.path}",
            "-json",
            "-include-response",
            "-silent",
            "-timeout",
            "5",
            "-retries",
            "0",
            "-no-stdin",
            "-duc",
        ]

    def normalize(self, stdout: str, request: ToolRequest, target: Target) -> list[NormalizedEvidence]:
        record = json.loads(next(line for line in stdout.splitlines() if line.strip()))
        status = int(record.get("status_code", 0))
        headers = {str(k).lower(): str(v) for k, v in (record.get("header") or record.get("headers") or {}).items()}
        missing = [name for name in self.expected_headers if name not in headers]
        evidence = [
            NormalizedEvidence(
                source=self.name,
                target=target.id,
                observation=f"{request.path} returned HTTP {status}",
                severity="info" if status in {401, 403} else "medium",
                raw={"path": request.path, "status_code": status},
            )
        ]
        if headers:
            evidence.append(
                NormalizedEvidence(
                    source=self.name,
                    target=target.id,
                    observation=f"Observed response headers: {', '.join(sorted(headers))}",
                    severity="info",
                    kind="RESPONSE_HEADERS_OBSERVED",
                    raw={"path": request.path, "header_names": sorted(headers)},
                )
            )
        if status in {401, 403}:
            evidence.append(
                NormalizedEvidence(
                    source=self.name,
                    target=target.id,
                    observation=f"Access control observed: unauthenticated request was denied with HTTP {status}",
                    severity="info",
                    kind="AUTH_CONTROL_OBSERVED",
                    raw={"path": request.path, "status_code": status},
                )
            )
        if request.path == "/admin":
            exposed = status == 200 and "www-authenticate" not in headers
            evidence.append(
                NormalizedEvidence(
                    source=self.name,
                    target=target.id,
                    observation=(
                        "Administrative endpoint is reachable without an authentication challenge"
                        if exposed
                        else "Administrative endpoint did not demonstrate unauthenticated exposure"
                    ),
                    severity="high" if exposed else "info",
                    kind="ADMIN_EXPOSURE" if exposed else "AUTH_CONTROL_OBSERVED",
                    raw={"path": request.path, "status_code": status, "auth_challenge": "www-authenticate" in headers},
                )
            )
        if missing:
            evidence.append(
                NormalizedEvidence(
                    source=self.name,
                    target=target.id,
                    observation=f"Missing response security headers: {', '.join(missing)}",
                    severity="medium",
                    kind="MISSING_SECURITY_HEADERS",
                    raw={"path": request.path, "missing_headers": missing},
                )
            )
        return evidence


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, SecurityTool] = {
            "network_discovery": NmapDiscoveryTool(),
            "web_inspection": HttpxInspectionTool(),
        }

    def get(self, name: str) -> SecurityTool:
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools[name]

    def describe(self) -> list[dict[str, str]]:
        return [{"name": tool.name, "description": tool.description} for tool in self._tools.values()]


tool_registry = ToolRegistry()
