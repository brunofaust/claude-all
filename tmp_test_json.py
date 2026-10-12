import sys
import unittest

from tests.test_md_links import TestJsonOutput

# Create a test suite with the TestJsonOutput class
suite = unittest.TestLoader().loadTestsFromTestCase(TestJsonOutput)
runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
