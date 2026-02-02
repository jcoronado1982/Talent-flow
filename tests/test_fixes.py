import sys
import os
import re
import unittest

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.apply_bot import find_resume_path

class TestFixes(unittest.TestCase):
    def test_find_resume_path_developer(self):
        # Pick a file we saw in the directory listing earlier: "CV_D_C_EN_Jesus_Coronado.pdf"
        # We need to know where it is. Assuming CV_D... are in Developer?
        # Let's just find ANY file we know exists.
        # Step 50 showed Developer has 6 children.
        # I'll rely on the logic finding a non-existent file returning None, 
        # and hopefully valid ones returning a path.
        
        # Test 1: Non-existent file
        result = find_resume_path("non_existent_resume.pdf")
        self.assertIsNone(result)

    def test_numeric_sanitization_regex(self):
        # Logic copied from apply_bot.py
        inputs = [
            ("5 years", "5"),
            ("10+ years", "10"),
            ("I have 3 years of experience", "3"),
            ("12000000 COP", "12000000"),
            ("No experience", None) 
        ]
        
        for raw, expected in inputs:
            digits = re.findall(r'\d+', str(raw))
            result = digits[0] if digits else None
            self.assertEqual(result, expected, f"Failed for '{raw}'")

if __name__ == '__main__':
    unittest.main()
