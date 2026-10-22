import unittest
from unittest.mock import patch
from collections import namedtuple
from typing_agent.download_model import check_space


class DownloadTests(unittest.TestCase):
    def test_no_download_when_disk_is_full(self):
        usage = namedtuple('usage', 'total used free')(1000, 990, 10)
        with patch('typing_agent.download_model.shutil.disk_usage', return_value=usage):
            with self.assertRaisesRegex(RuntimeError, 'Insufficient disk space'):
                check_space('models/example', 100)

    def test_enough_space(self):
        usage = namedtuple('usage', 'total used free')(1000, 10, 990)
        with patch('typing_agent.download_model.shutil.disk_usage', return_value=usage):
            check_space('models/example', 100)
