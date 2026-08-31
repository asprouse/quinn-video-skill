"""Command-line entry point.

Each pipeline stage is its own subcommand so a failed run can resume from the
middle instead of re-paying for narration and avatar rendering.
"""

from __future__ import annotations

import argparse
import sys

from .config import ConfigError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quinn-video",
        description="Turn a topic into a finished short-form educational video.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check the toolchain and credentials")
    group = doctor.add_mutually_exclusive_group()
    group.add_argument("--list-avatars", action="store_true", help="print pickable avatar ids")
    group.add_argument("--list-voices", action="store_true", help="print pickable voice ids")

    sub.add_parser("fonts", help="download the bundled caption typeface")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        if args.command == "doctor":
            from . import doctor

            if args.list_avatars:
                return doctor.list_avatars()
            if args.list_voices:
                return doctor.list_voices()
            return doctor.run()

        if args.command == "fonts":
            from .fonts import install

            return install()

    except ConfigError as exc:
        print(f"\n\033[31mconfiguration error\033[0m: {exc}\n", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
