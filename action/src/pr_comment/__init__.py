"""Post the verified test to the PR as a suggested file with a pass/fail badge.

Contract (built after step 7): only VERIFIED tests are posted as code;
UNVERIFIED results post a short failure note instead, never the test body.
"""
