#!/usr/bin/env python3
import sys

import pytest

sys.exit(pytest.main(["-v", "tests/test_md_links.py::test_json_output_clean_tree"]))
