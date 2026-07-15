import json
import subprocess
import sys
from pathlib import Path


def test_fixture_evaluation_is_valid() -> None:
    repository = Path(__file__).parents[3]
    result = subprocess.run(
        [sys.executable, str(repository / "evaluations/run.py"), "--fixture-only"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout)["cases"] == 5

