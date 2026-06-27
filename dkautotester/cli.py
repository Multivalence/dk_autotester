"""Command-line entrypoint wiring the full pipeline.

    load manifest -> build image -> run batches -> parse protocol -> report

Exit codes:
    0  ran successfully (test pass/fail/partial status is in the report, not the exit code)
    2  configuration error (bad manifest)
    3  protocol violation (harness output did not follow the convention)
    4  docker build/run error
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace

from . import __version__
from .config import ConfigError, load_config
from .dockerfile import render_dockerfile
from .docker_runner import DockerError, build_image, chunk, run_batch
from .protocol import ProtocolError, parse_stream
from .report import Report


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dkautotester",
        description="Run a bash test harness against many git repos in isolated, batched containers.",
    )
    p.add_argument("-c", "--config", required=True, help="path to the manifest YAML")
    p.add_argument("-s", "--script", help="path to test script (overrides config's test_script)")
    p.add_argument("-o", "--output", default="results.json", help="path for the JSON report")
    p.add_argument("-t", "--tag", default="dkautotester:run", help="docker image tag to build")
    p.add_argument(
        "--print-dockerfile",
        action="store_true",
        help="render and print the generated Dockerfile, then exit (no docker required)",
    )
    p.add_argument(
        "--skip-build",
        action="store_true",
        help="reuse an existing image with --tag instead of building",
    )
    p.add_argument("--version", action="version", version=f"dkautotester {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    # Override test_script if --script is provided
    if args.script:
        script_path = os.path.abspath(args.script)
        if not os.path.isfile(script_path):
            print(f"config error: script not found: {script_path}", file=sys.stderr)
            return 2
        config = replace(config, test_script=script_path)

    if args.print_dockerfile:
        print(render_dockerfile(config))
        return 0

    try:
        if args.skip_build:
            image = args.tag
            print(f"Reusing image {image} (--skip-build)", file=sys.stderr)
        else:
            print(f"Building image {args.tag} ({len(config.repos)} repos)...", file=sys.stderr)
            image = build_image(config, tag=args.tag)
    except DockerError as exc:
        print(f"docker error: {exc}", file=sys.stderr)
        return 4

    batches = chunk(config.repos, config.batch_size)
    all_results = []

    try:
        for i, batch in enumerate(batches, start=1):
            names = [r.name for r in batch]
            print(
                f"Running batch {i}/{len(batches)} ({len(batch)} repos): {', '.join(names)}",
                file=sys.stderr,
            )
            run = run_batch(config, image, batch)
            if run.returncode != 0:
                # Container-level trouble; show stderr but still try to parse what we got.
                print(
                    f"  batch {i} container exited {run.returncode}; stderr tail:\n"
                    + "\n".join(run.stderr.strip().splitlines()[-10:]),
                    file=sys.stderr,
                )
            results = parse_stream(run.stdout, names)
            all_results.extend(results)
    except DockerError as exc:
        print(f"docker error: {exc}", file=sys.stderr)
        return 4
    except ProtocolError as exc:
        print(f"protocol violation, terminating: {exc}", file=sys.stderr)
        return 3

    report = Report(results=all_results, config=config)
    report.write_json(args.output)
    print(report.render_text())
    print(f"\nJSON report written to {args.output}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
