# Fix Summary

## Failure
- `tests/test_browser_integration.py::test_browse_action_keywords`
- Import failed because `server.ACTION_KEYWORDS` no longer existed.
- The test also expected a `browse` keyword bucket.

## Fix
- Restored `ACTION_KEYWORDS` in `server.py`.
- Added a `browse` bucket with the expected browsing phrases.
- Reused the same keyword buckets in `detect_action_fast()` so the tests and runtime stay aligned.

## Verification
- Full test suite passed: `35 passed`
- Command used: `.venv/bin/pytest -q`

