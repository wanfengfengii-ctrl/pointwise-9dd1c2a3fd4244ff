"""Run the original regression together with the mixture business checks."""
import sys
import unittest

import mix_fixture


def main():
    suite = unittest.defaultTestLoader.discover('tests', top_level_dir='.')
    if not suite.countTestCases():
        print('No tests discovered in tests/', file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    successful = result.testsRun > 0 and result.wasSuccessful()
    try:
        mix_fixture.main()
    except AssertionError as exc:
        print(f'MIXTURE FIXTURE MISMATCH: {exc}', file=sys.stderr)
        successful = False
    print(f'MIXTURE VERIFY result={"PASS" if successful else "FAIL"}')
    return 0 if successful else 1


if __name__ == '__main__':
    raise SystemExit(main())
