import contextlib
import io
import unittest

from pr_triage.cli import main


class CliTests(unittest.TestCase):
    def test_version_prints_package_version(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--version"])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), "pr-triage 0.1.0\n")

    def test_unknown_command_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as e:
            main(["nope"])
        self.assertEqual(e.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
