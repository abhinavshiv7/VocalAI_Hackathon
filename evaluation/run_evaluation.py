import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.services.evaluation import run_evaluation  # noqa: E402


async def main() -> None:
    summary = await run_evaluation(get_settings())
    output_dir = ROOT / "evaluation" / "results"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "latest.json"
    output_file.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    print(json.dumps(summary.model_dump(exclude={"results"}), indent=2))
    if summary.success_rate < 100 or summary.graceful_failure_rate < 100:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())

