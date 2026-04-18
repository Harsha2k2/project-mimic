from pathlib import Path
import subprocess
import sys


def test_flaky_detection_script_updates_quarantine_file(tmp_path) -> None:
    pass1 = tmp_path / "pass1.xml"
    pass2 = tmp_path / "pass2.xml"
    output = tmp_path / "flaky.txt"

    pass1.write_text(
        """
<testsuite>
  <testcase classname="tests.sample" name="test_a" />
  <testcase classname="tests.sample" name="test_b"><failure /></testcase>
</testsuite>
""".strip(),
        encoding="utf-8",
    )
    pass2.write_text(
        """
<testsuite>
  <testcase classname="tests.sample" name="test_a" />
  <testcase classname="tests.sample" name="test_b" />
</testsuite>
""".strip(),
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "tools/flaky/detect_flaky.py",
            str(pass1),
            str(pass2),
            str(output),
        ],
        check=True,
    )

    content = output.read_text(encoding="utf-8")
    assert "tests.sample::test_b" in content
