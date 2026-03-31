"""
Core pipeline orchestration logic.

This module is responsible for executing prepared pipelines end-to-end.
It does NOT handle CLI parsing or argument validation.

Execution flow:

1. Detect available solvers (Frama-C, Z3, cvc5, etc.)
2. Load and prepare pipeline configurations
3. Build runtime environment (LLM clients + solver configuration)
4. Execute each pipeline sequentially
5. Track runtime statistics and ETA
6. Generate an optional HTML report
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from spec2code.core.pipeline_executor import execute_pipeline_prepared
from spec2code.pipeline_modules.config_loader import load_and_prepare_configs
from spec2code.pipeline_modules.runtime import build_runtime
from spec2code.pipeline_modules.verify import initialize_solvers
from spec2code.gui.report import (
    find_latest_sample_output,
    render_last_run_report,
)

logger = logging.getLogger(__name__)


def _fmt_duration(seconds: float) -> str:
    """
    Format a duration in seconds into a human readable string.

    Examples:
        3s
        2m15s
        1h02m05s
    """
    if seconds < 0:
        seconds = 0.0

    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)

    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def run_pipeline(
    *,
    config_path: Path,
    open_report: bool = False,
) -> int:
    """
    Execute pipelines defined in the provided configuration file.

    Parameters
    ----------
    config_path:
        Path to the pipeline configuration file.

    open_report:
        If True, open the generated HTML report automatically in a browser.

    Returns
    -------
    int
        Exit code (0 for success).
    """

    start_all = time.perf_counter()

    # ------------------------------------------------------------
    # Validate configuration file
    # ------------------------------------------------------------
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    logger.info("Starting pipeline run")

    # ------------------------------------------------------------
    # Detect installed verification tools / solvers
    # ------------------------------------------------------------
    logger.info("Detecting solvers...")
    solvers = initialize_solvers()

    # ------------------------------------------------------------
    # Load and normalize configuration objects
    # ------------------------------------------------------------
    logger.info("Loading and preparing configs from %s", config_path)
    prepared = load_and_prepare_configs(str(config_path), solvers=solvers)

    # ------------------------------------------------------------
    # Determine which LLM providers are required
    # ------------------------------------------------------------
    llm_names = sorted({name for cfg in prepared for name in cfg.llms_used})

    logger.info("Building runtime for %d LLM(s)", len(llm_names))

    runtime = build_runtime(
        llm_names=llm_names,
        solvers=solvers,
    )

    # ------------------------------------------------------------
    # Execute pipelines sequentially
    # ------------------------------------------------------------
    total_pipelines = len(prepared)

    logger.info("Prepared %d pipeline(s). Running...", total_pipelines)

    pipeline_times: list[float] = []
    latest_output_json: str | None = None

    for i, pipeline_cfg in enumerate(prepared, start=1):

        logger.info(
            "(%d/%d) Executing pipeline: %s",
            i,
            total_pipelines,
            pipeline_cfg.name,
        )

        pipeline_start = time.perf_counter()

        execute_pipeline_prepared(
            pipeline_cfg,
            runtime=runtime,
        )

        pipeline_elapsed = time.perf_counter() - pipeline_start
        pipeline_times.append(pipeline_elapsed)

        # track newest output.json for report generation
        latest_output_json = (
            find_latest_sample_output(pipeline_cfg.output_folder)
            or latest_output_json
        )

        avg = sum(pipeline_times) / len(pipeline_times)
        remaining = avg * (total_pipelines - i)

        logger.info(
            "(%d/%d) Done: %s in %s | eta %s",
            i,
            total_pipelines,
            pipeline_cfg.name,
            _fmt_duration(pipeline_elapsed),
            _fmt_duration(remaining),
        )

    # ------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------
    total_elapsed = time.perf_counter() - start_all

    logger.info("All pipelines completed in %s", _fmt_duration(total_elapsed))

    # ------------------------------------------------------------
    # Generate HTML report
    # ------------------------------------------------------------
    if latest_output_json:
        render_last_run_report(
            latest_output_json=Path(latest_output_json),
            open_in_browser=open_report,
        )

    return 0
