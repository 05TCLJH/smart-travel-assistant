"""运行行程生成计时基准，并保存结构化报告。"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from backend.core.paths import REPORTS_DIR, ensure_runtime_dirs
from backend.diagnostics.trip_benchmark import (
    DEFAULT_BENCHMARK_CASES,
    TimelineRecorder,
    aggregate_case_runs,
    summarize_result,
    summarize_segments,
)
from backend.services.travel_service import TravelService


def _load_cases(case_names: list[str], cases_file: str | None) -> list[dict[str, Any]]:
    if cases_file:
        raw = json.loads(Path(cases_file).read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("cases file must be a JSON array")
        cases = [dict(item) for item in raw if isinstance(item, dict)]
    else:
        cases = deepcopy(DEFAULT_BENCHMARK_CASES)

    if not case_names:
        return cases

    selected = []
    wanted = set(case_names)
    for case in cases:
        if str(case.get("name", "")).strip() in wanted:
            selected.append(case)
    missing = wanted - {str(case.get("name", "")).strip() for case in selected}
    if missing:
        raise ValueError(f"unknown benchmark case(s): {', '.join(sorted(missing))}")
    return selected


def _run_single_case(service: TravelService, case: dict[str, Any], run_index: int) -> dict[str, Any]:
    recorder = TimelineRecorder()
    trip_request = dict(case.get("trip_request") or {})
    persona = dict(case.get("persona") or {})
    run_label = "cold" if run_index == 0 else f"warm_{run_index}"

    def on_progress(event: dict[str, Any]) -> None:
        recorder.observe(event)

    started = perf_counter()
    try:
        result = service.generate(trip_request, persona, progress=on_progress)
        success = True
        error = ""
    except Exception as exc:
        result = {}
        success = False
        error = str(exc)
    elapsed = round(perf_counter() - started, 4)
    recorder.finalize()

    return {
        "run_label": run_label,
        "success": success,
        "error": error,
        "elapsed_s": elapsed,
        "result_summary": summarize_result(result) if success else {},
        "step_summary": summarize_segments(recorder.segments),
        "segments": [segment.__dict__ for segment in recorder.segments],
        "event_count": len(recorder.events),
    }


def _build_report(cases: list[dict[str, Any]], repeat: int) -> dict[str, Any]:
    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "repeat": repeat,
        "cases": [],
    }

    for case in cases:
        service = TravelService()
        runs = [_run_single_case(service, case, idx) for idx in range(repeat)]
        report["cases"].append(
            {
                "name": case.get("name"),
                "trip_request": case.get("trip_request"),
                "persona": case.get("persona"),
                "runs": runs,
                "aggregate": aggregate_case_runs(runs),
            }
        )

    all_runs = [run for case in report["cases"] for run in case["runs"]]
    report["overall"] = aggregate_case_runs(all_runs)
    return report


def _print_report(report: dict[str, Any]) -> None:
    print("=== Trip Generation Benchmark ===")
    print(f"generated_at: {report.get('generated_at')}")
    print(f"repeat: {report.get('repeat')}")
    overall = report.get("overall") or {}
    print(
        "overall:"
        f" success={overall.get('success_count')}/{overall.get('run_count')}"
        f" avg={overall.get('avg_elapsed_s')}s"
        f" min={overall.get('min_elapsed_s')}s"
        f" max={overall.get('max_elapsed_s')}s"
    )
    print()

    for case in report.get("cases", []):
        agg = case.get("aggregate") or {}
        print(f"[case] {case.get('name')}")
        print(
            f"  success={agg.get('success_count')}/{agg.get('run_count')}"
            f" avg={agg.get('avg_elapsed_s')}s"
            f" min={agg.get('min_elapsed_s')}s"
            f" max={agg.get('max_elapsed_s')}s"
        )
        for run in case.get("runs", []):
            result_summary = run.get("result_summary") or {}
            print(
                f"  - {run.get('run_label')}: elapsed={run.get('elapsed_s')}s"
                f" candidate_count={result_summary.get('candidate_count')}"
                f" planning_attempts={result_summary.get('planning_attempts')}"
                f" issues={len(result_summary.get('issues', []))}"
            )
        slow_steps = (agg.get("slowest_steps") or [])[:5]
        if slow_steps:
            print("  slowest_steps:")
            for row in slow_steps:
                print(
                    f"    * {row.get('step_id')}: avg={row.get('avg_duration_s')}s"
                    f" max={row.get('max_duration_s')}s"
                )
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark timed trip-generation cases")
    parser.add_argument("--case", dest="cases", action="append", default=[], help="case name to run; can be repeated")
    parser.add_argument("--cases-file", dest="cases_file", default=None, help="path to a JSON array of benchmark cases")
    parser.add_argument("--repeat", type=int, default=2, help="run each case N times; first run is cold, later runs are warm")
    parser.add_argument("--output", dest="output", default=None, help="path to save the JSON report")
    args = parser.parse_args()

    ensure_runtime_dirs()
    cases = _load_cases(args.cases, args.cases_file)
    report = _build_report(cases, max(1, int(args.repeat or 1)))

    output_path = Path(args.output) if args.output else REPORTS_DIR / f"trip_generation_benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    _print_report(report)
    print(f"report_saved: {output_path}")


if __name__ == "__main__":
    main()
