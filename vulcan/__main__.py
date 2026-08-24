"""Vulcan launcher: embedded console, hosted server, or self-test."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import content


def menu():
    print(f"""Vulcan v1.0 - building automation sandbox

1) Local console      (embedded world, manual ticks)
2) Host server        (auto-tick, JSON-lines on {content.SERVER_PORT})
3) Connect to host
4) Self-test          (verify_vulcan suite)
0) Quit""")
    return input("choice: ").strip()


def main():
    while True:
        choice = menu()
        if choice == "1":
            import cli
            cli.main()
        elif choice == "2":
            import server
            server.main()
        elif choice == "3":
            import cli
            sys.argv = ["cli", "--connect"]
            cli.main()
        elif choice == "4":
            import verify_vulcan
            ok = verify_vulcan.main()
            if not ok:
                return 1
        elif choice == "0":
            return 0


if __name__ == "__main__":
    sys.exit(main())
