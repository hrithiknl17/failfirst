"""Gather what generation needs to write a grounded test.

Contract (built in step 5):
- existing tests that touch the changed files, so style and fixtures match
- an ARIA snapshot + role/name/test-id locator list captured from the PR's
  build running locally — the only selectors generation is allowed to use
"""
