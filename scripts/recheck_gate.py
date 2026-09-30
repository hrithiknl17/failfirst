"""Re-run the full verification gate on an existing test file, against fresh builds.

Uses the production ``verify()`` with a generator that always returns the given
file, and no retry — so this is exactly the check a new test must pass:
safety check, pass on the PR build, fail on the base build, stability gate.

    python scripts/recheck_gate.py --repo ../liquid-financial-sandbox \
        --base master --head demo/hub-log-button --test out/demo_hub-log-button/test_x.py
"""
import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "action" / "src"))

from context import build, checkout, merge_base, resolve_sha, serve  # noqa: E402
from generation import GeneratedTest  # noqa: E402
from verification import verify  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--test", required=True, help="test file to re-verify")
    args = parser.parse_args()

    code = Path(args.test).read_text(encoding="utf-8")
    head_tree = checkout(args.repo, resolve_sha(args.repo, args.head))
    base_tree = checkout(args.repo, merge_base(args.repo, args.base, args.head))
    build(args.repo, head_tree)
    build(args.repo, base_tree)

    with serve(head_tree) as head_url, serve(base_tree) as base_url, tempfile.TemporaryDirectory() as work:
        result = verify(
            lambda feedback: GeneratedTest(code, "recheck"),
            head_url=head_url, base_url=base_url, workdir=Path(work), max_generations=1,
        )
    attempt = result.attempts[-1]
    print(f"{args.head}: {result.status.upper()}")
    print(f"  first runs: PR build {attempt.head.outcome if attempt.head else '-'}, "
          f"base build {attempt.base.outcome if attempt.base else '-'}")
    print(f"  {result.reason}")
    return 0 if result.status == "verified" else 1


if __name__ == "__main__":
    sys.exit(main())
