"""Run the generated test against a real local build before a human sees it.

Contract (built in step 5): on selector failure, retry generation once with
the DOM snapshot fed back in. Still failing -> result is UNVERIFIED and the
test is not posted.
"""
