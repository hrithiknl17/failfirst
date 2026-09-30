import pytest

from pipeline import generated_test_filename, suggested_test_path


@pytest.mark.parametrize("head, expected", [
    ("failfirst/demo-saved-label", "test_failfirst_demo_saved_label.py"),  # was test_failfirst_failfirst_...
    ("FailFirst/Demo", "test_failfirst_demo.py"),
    ("demo/percent-zero", "test_failfirst_demo_percent_zero.py"),
    ("feature/failfirst/x", "test_failfirst_feature_failfirst_x.py"),  # only a leading prefix is stripped
    ("failfirst-demo", "test_failfirst_failfirst_demo.py"),  # not the "failfirst/" prefix
    ("failfirst/", "test_failfirst_change.py"),
    ("", "test_failfirst_change.py"),
])
def test_generated_test_filename(head, expected):
    assert generated_test_filename(head) == expected


def test_suggested_path_uses_the_clean_name():
    assert suggested_test_path("failfirst/demo-saved-label") == "e2e/test_failfirst_demo_saved_label.py"
