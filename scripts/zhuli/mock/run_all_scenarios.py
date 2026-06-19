"""Run all scenarios + aggregate report.

Usage:
  PYTHONPATH=scripts python -m zhuli.mock.run_all_scenarios

Output:
  docs/主力大課程/mock_test_results/_summary_<timestamp>.md
"""
from __future__ import annotations
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from zhuli.mock.test_runner import SCENARIOS, run_scenario


def main():
    output_dir = REPO / "docs" / "主力大課程" / "mock_test_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = output_dir / f"_summary_{timestamp}.md"

    lines = [
        f"# Mock Test Summary — {timestamp}",
        "",
        f"- Scenarios run: {len(SCENARIOS)}",
        "",
        "## Per-scenario results",
        "",
        "| Scenario | Date | Tickers | Expected | Status |",
        "|---|---|---|---|---|",
    ]
    total_expected = 0
    total_pass = 0
    for name, cfg in SCENARIOS.items():
        print(f"\n=== {name} ===")
        rc = run_scenario(name, output_dir)
        n_exp = sum(len(v) for v in cfg.get('expected_triggers', {}).values())
        total_expected += n_exp
        status = '✅' if rc == 0 else '❌'
        if rc == 0:
            total_pass += 1
        lines.append(f"| {name} | {cfg['date']} | {','.join(cfg['tickers'])} | {n_exp} | {status} |")

    lines.append("")
    lines.append(f"## Aggregate")
    lines.append(f"- Scenarios passed: {total_pass} / {len(SCENARIOS)}")
    lines.append(f"- Total expected triggers: {total_expected}")
    lines.append("")
    lines.append("## Detail reports")
    for name, cfg in SCENARIOS.items():
        lines.append(f"- [{name}](./{name}_{cfg['date']}.md)")
    summary_path.write_text("\n".join(lines))
    print(f"\n📄 Summary: {summary_path}")


if __name__ == "__main__":
    main()
