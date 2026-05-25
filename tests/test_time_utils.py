import unittest

from time_utils import TAIPEI_TZ, taipei_datetime_str, taipei_now


class TimeUtilsTest(unittest.TestCase):
    def test_taipei_now_uses_taipei_timezone(self):
        self.assertEqual(taipei_now().tzinfo, TAIPEI_TZ)

    def test_taipei_datetime_str_format(self):
        value = taipei_datetime_str()
        self.assertRegex(value, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")


if __name__ == "__main__":
    unittest.main()
