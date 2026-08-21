# Prior-art comparison

Research date: 21 August 2026. This comparison uses vendor descriptions and narrows SentinelLoop's claim deliberately.

| Product | What it does | How SentinelLoop differs |
|---|---|---|
| [Pentera](https://pentera.io/pentera-platform/) | Enterprise adversarial exposure validation across internal, external, cloud, and hybrid estates, including attack execution, prioritization, remediation workflows, and revalidation. | SentinelLoop is not an enterprise adversarial-testing engine. It is a small, inspectable reference implementation centered on hypothesis/evidence separation, an independent critic, model/schema failure ceilings, and reproducible evaluation inside a scripted lab. |
| [Horizon3.ai NodeZero](https://horizon3.ai/nodezero/) | Autonomous pentesting that discovers and safely exploits weaknesses, chains attack paths, guides remediation, and verifies fixes across broad production environments. | SentinelLoop performs observation-only checks with exactly two adapters and no exploitation or lateral movement. Its distinctive demonstration is the two-role disagreement path and explicit refusal to validate when either role or evidence source fails. |
| [XBOW](https://xbow.com/blog/what-is-ai-pentesting) | Autonomous AI penetration testing focused on discovering reproducible, exploitable application vulnerabilities at machine speed, with mitigation and retesting. | SentinelLoop does not claim comparable offensive capability. It exposes the orchestration internals—policy decisions, normalized evidence, confidence changes, critic contradictions, budget counters, and injected failures—as the product surface for teaching and controlled validation. |

## Meaningful differentiation

The adjacent products compete on breadth, exploitability, attack paths, and enterprise scale. SentinelLoop's MVP is intentionally narrower: it makes **epistemic safety** visible. A hypothesis is not a finding; tool failure is evidence about uncertainty; and the second role has authority to reject or cap confidence. The evaluator includes false-positive, contradictory-evidence, malformed-output, and model-outage cases as first-class acceptance criteria.

This is a hackathon prototype and prior-art-informed systems demonstration—not a claim that the underlying category or autonomous security testing is novel.

