"""Allow `python -m harness [subcommand]` entry point."""

from harness.router import ModelRouter


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="harness")
    sub = parser.add_subparsers(dest="command", required=True)

    # python -m harness config
    sub.add_parser("config", help="Print the current model routing table")

    args = parser.parse_args()

    if args.command == "config":
        router = ModelRouter()
        print(router.pretty_print())


if __name__ == "__main__":
    main()
