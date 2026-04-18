import subprocess
import sys


def test_docs_validation_script_passes() -> None:
    subprocess.run([sys.executable, "tools/docs/validate_docs.py"], check=True)
