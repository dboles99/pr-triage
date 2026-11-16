"""Run the study. See pr_triage/study.py."""
import sys

from pr_triage.study import main

sys.exit(main(["run", *sys.argv[1:]]))
