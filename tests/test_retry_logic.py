
import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import time

# Add src to path
sys.path.append(os.getcwd())

from src.app.bots.search.manager import SearchBotManager

class TestRetryLogic(unittest.TestCase):
    @patch('src.app.bots.search.manager.Settings')
    @patch('src.app.bots.search.manager.db')
    @patch('src.app.bots.search.manager.SearchMonitor')
    @patch('src.app.bots.search.manager.JobAnalyzer')
    @patch('src.app.bots.search.manager.JobSearchBrowser')
    @patch('src.app.bots.search.manager.time.sleep')
    def test_retry_on_failure(self, mock_sleep, MockBrowser, MockBrain, MockMonitor, MockDB, MockSettings):
        # Setup Mocks
        mock_brain_instance = MockBrain.return_value
        # Simulate 2 Failures then 1 Success
        # First call: None (Simulate wrb.fr error)
        # Second call: Exception (Simulate timeout)
        # Third call: Success
        mock_brain_instance.analyze.side_effect = [None, Exception("Simulated Timeout"), {"match_percentage": 90}]
        
        manager = SearchBotManager(headless=True)
        # Verify brain is mocked
        self.assertEqual(manager.brain, mock_brain_instance)

        # Test Data - Description MUST be > 50 chars
        payload = "A very long description " * 10 
        details = {"description": payload, "date": "Today", "title": "Dev", "company": "TestCorp"}
        url = "http://test.com"

        # Run Method
        print("\n--- Starting Retry Test ---")
        manager.process_single_job(details, url, "Dev")
        print("--- End Retry Test ---")

        # Assertions
        # Should have called analyze 3 times
        self.assertEqual(mock_brain_instance.analyze.call_count, 3)
        manager.monitor.log.assert_any_call("✅ [FINALIZADO] Éxito: 90% de coincidencia.")

    @patch('src.app.bots.search.manager.Settings')
    @patch('src.app.bots.search.manager.db')
    @patch('src.app.bots.search.manager.SearchMonitor')
    @patch('src.app.bots.search.manager.JobAnalyzer')
    @patch('src.app.bots.search.manager.JobSearchBrowser')
    @patch('src.app.bots.search.manager.time.sleep')
    def test_all_retries_fail(self, mock_sleep, MockBrowser, MockBrain, MockMonitor, MockDB, MockSettings):
        mock_brain_instance = MockBrain.return_value
        # Simulate Persistent Failure (Always None)
        mock_brain_instance.analyze.return_value = None
        
        manager = SearchBotManager(headless=True)
        
        # Test Data - Description MUST be > 50 chars
        payload = "A very long description " * 10
        details = {"description": payload, "date": "Today", "title": "Dev", "company": "FailCorp"}
        url = "http://fail.com"

        print("\n--- Starting Persistent Failure Test ---")
        manager.process_single_job(details, url, "Dev")
        print("--- End Persistent Failure Test ---")

        # Should match retries configured (3)
        self.assertEqual(mock_brain_instance.analyze.call_count, 3)
        # Should log final error
        manager.monitor.log.assert_any_call("❌ [FINALIZADO] Error: Falló el análisis tras reintentos.")

if __name__ == '__main__':
    unittest.main()
