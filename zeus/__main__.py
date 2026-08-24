"""ZEUS launcher: local console, hosted kernel, or self-test."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import content


def menu():
    print(f"""ZEUS v1.0 - workspace protection kernel

1) Status             (one-shot kernel summary)
2) Patrol once        (run a single protection cycle)
3) Build baseline     (integrity snapshot of protected roots)
4) Verify integrity   (compare disk against baseline)
5) Host server        (auto-patrol, JSON-lines on {content.SERVER_PORT})
6) Connect to host
7) Self-test          (verify_zeus suite)
0) Quit""")
    return input("choice: ").strip()


def main():
    if "--host" in sys.argv:
        import server
        server.main()
        return 0
    while True:
        choice = menu()
        if choice == "1":
            import cli
            return_code = cli.main()
            if return_code not in (0, 1):
                return 0
        elif choice == "2":
            import cli
            cli.cmd_patrol()
        elif choice == "3":
            import cli
            cli.cmd_baseline()
        elif choice == "4":
            import cli
            cli.cmd_verify()
        elif choice == "5":
            import server
            server.main()
        elif choice == "6":
            import cli
            sys.argv = ["cli", "--connect"]
            cli.main()
        elif choice == "7":
            import verify_zeus
            if not verify_zeus.main():
                return 1
        elif choice == "0":
            return 0


if __name__ == "__main__":
    sys.exit(main())
