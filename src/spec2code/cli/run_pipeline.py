"""
CLI entrypoint for running the spec2code pipeline.

This module is intentionally small and only responsible for:
    - parsing command line arguments
    - configuring logging
    - calling the core pipeline runner

All heavy logic lives in spec2code.core.runner.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from spec2code.core.runner import run_pipeline


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse command-line arguments.

    Users must provide a configuration file describing the pipeline run.
    The current loader expects JSON.
    """
    parser = argparse.ArgumentParser(
        prog="spec2code-run",
        description="Run one or more pipelines defined in a config file.",
    )

    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        required=True,
        help="Path to pipeline configuration file (JSON).",
    )

    parser.add_argument(
        "--no-open-report",
        dest="open_report",
        action="store_false",
        default=True,
        help="Do not open the generated HTML report in a browser after execution.",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Main CLI entrypoint.

    This function:
        1. configures logging
        2. parses CLI arguments
        3. invokes the pipeline runner
    """

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    args = parse_args(argv)

    return run_pipeline(
        config_path=args.config,
        open_report=args.open_report,
    )


if __name__ == "__main__":
    raise SystemExit(main())
