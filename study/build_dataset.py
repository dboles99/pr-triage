"""Collect the study dataset. See pr_triage/study.py."""
import sys

from pr_triage.study import main

sys.exit(main(["build", *sys.argv[1:]]))
