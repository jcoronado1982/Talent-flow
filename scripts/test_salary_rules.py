import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.app.bots.apply.resume_manager import ResumeManager
from src.config.settings import Settings

def test():
    config = Settings.load_profile()
    # Mock browser
    manager = ResumeManager(None, config)
    
    test_cases = [
        ("Senior Java Developer", "en", "Expected: 2000"),
        ("Software Lead Architect", "en", "Expected: 4000"),
        ("Full Stack Developer", "es", "Expected: 7000000"),
        ("Líder de Proyectos", "es", "Expected: 8000000"),
        ("Frontend Developer", "en", "Expected: 2000 (Full Stack rule fallback)"),
        ("Unknown Role", "pt", "Expected: 7000000 (Default)"),
    ]
    
    print("\n--- Testing Salary Resolution Rules ---")
    for role, lang, expected in test_cases:
        val, curr = manager.get_salary_expectation(role, lang)
        print(f"Role: {role:30} | Lang: {lang} -> Result: {val} {curr} ({expected})")

if __name__ == "__main__":
    test()
