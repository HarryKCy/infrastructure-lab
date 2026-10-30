import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from availability_probe import probe
from unittest.mock import patch, MagicMock
class ProbeTest(unittest.TestCase):
    def test_success(self):
        context=MagicMock();context.__enter__.return_value.status=200
        with patch('availability_probe.urlopen',return_value=context):self.assertTrue(probe('http://127.0.0.1/health')['ok'])
    def test_http_503(self):
        context=MagicMock();context.__enter__.return_value.status=503
        with patch('availability_probe.urlopen',return_value=context):self.assertFalse(probe('http://127.0.0.1/health')['ok'])
