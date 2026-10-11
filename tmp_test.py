#!/usr/bin/env python3
"""Quick test to verify the check_requires module works."""

import sys

# Add the scripts directory to the path so we can import check_requires
sys.path.insert(0, ".")

import check_requires


def test_basic_functionality():
    """Test that the module can be imported and basic functions work."""
    # Test that we can call load_resource_keys without error
    keys = check_requires.load_resource_keys()
    print(f"Loaded {len(keys)} resource keys")
    return True


if __name__ == "__main__":
    test_basic_functionality()
    print("Basic test passed!")
