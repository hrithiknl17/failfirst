"""Run the generated test against a real local build before a human sees it.

On failure, retry generation once with the evidence (pytest output + the DOM
at the moment of failure) fed back in. Still failing -> UNVERIFIED, not posted.
"""
from .runner import RunResult, run_test
from .verify import MAX_GENERATIONS, Attempt, VerificationResult, verify

__all__ = ["MAX_GENERATIONS", "Attempt", "RunResult", "VerificationResult", "run_test", "verify"]
