import os
import sys
import unittest
from unittest.mock import patch

import check_requires

class TestCheckReqs(unittest.TestCase):
    def test_normal_run(self):
        # Mock glob to return a fake file
        with patch('glob.glob', return_value=['fake_file.py']):
            with patch('builtins.open',Mock()):
                # Also mock os.path.isfile to return True
                with patch('os.path.isfile', return_value=True):
                    # Capture the printed output
                    with patch('sys.stdout', new_callable=io.StringIO) as stdout:
                        check_requires.main()
                        output = stdout.value.getvalue()
                        self.assertIn('Inspected 1 files successfully.', output)

    def test_zero_files(self):
        # Mock glob to return an empty list
        with patch('glob.glob', return_value=[]):
            # Capture the exit code and output
            with patch('sys.stdout', new_callable=io.StringIO) as stdout:
            with patch('sys.stderr', new_callable=io.StringIO) as stderr:
                with self.assertRaises(SystemExit):
                    check_requires.main()
                self.assertEqual(stdout.getvalue(), '')
                selfassertIn('No files matched pattern:', stderr.getvalue())

    def test_existing_failure(self):
        # Simulate a file with invalid content
        with patch('glob.glob', return_value=['invalid_file.py']):
            with patch('builtins.open', side_effect=FileNotFoundError):
                with self.assertRaises(SystemExit):
                    check_requires.main()
