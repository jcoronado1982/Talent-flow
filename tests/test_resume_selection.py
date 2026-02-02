import os
import sys
import json

# Add project root to path
sys.path.append(os.getcwd())

from src.app.bots.apply.resume_manager import ResumeManager
from src.config.settings import Settings

def test_resume_selection():
    # Mock config
    with open("config/profile_config.json", "r") as f:
        config = json.load(f)
    
    # Mock browser (not used by get_resume_filename)
    manager = ResumeManager(None, config)
    
    test_cases = [
        {
            "role": "Full Stack Developer",
            "desc": "React and Next.js applications with complex state management. JavaScript and TypeScript expertise.",
            "lang": "en",
            "expected_not": "CV_L_J_ES_Jesus_Coronado.pdf" # Java Leader
        },
        {
            "role": "Java Backend Engineer",
            "desc": "Microservices with Spring Boot and Java 17.",
            "lang": "en",
            "expected": "CV_D_J_EN_Jesus_Coronado.pdf"
        },
        {
            "role": "Technical Lead",
            "desc": "Leading a team of developers and architecting Python systems.",
            "lang": "en",
            "expected": "CV_L_P_EN_Jesus_Coronado.pdf"
        },
        {
            "role": "Fullstack Engineer",
            "desc": "Experiencia sólida en Python y Django y manejo avanzado de PostgreSQL.",
            "lang": "en",
            "expected": "CV_D_P_ES_Jesus_Coronado.pdf"
        },
        {
            "role": "Software Engineer",
            "desc": "Senior Software Engineer to work hands-on helping them ship, package, and migrate Windows applications. Strong Windows engineering background, debugging with tools such as ProcMon, WinDbg, Fiddler, and strong C# skills with the ability to read C++. Experience with MSIX, WebView2.",
            "lang": "en",
            "expected": "CV_D_C_EN_Jesus_Coronado.pdf"
        }
    ]
    
    print("🚀 Starting Resume Selection Tests...")
    
    all_passed = True
    for i, tc in enumerate(test_cases):
        print(f"\nTest Case {i+1}: {tc['role']}")
        result_path = manager.get_resume_filename(tc['role'], tc['desc'], tc['lang'])
        result_file = os.path.basename(result_path)
        print(f"   Result: {result_file}")
        
        if "expected" in tc:
            if result_file == tc["expected"]:
                print("   ✅ PASS")
            else:
                print(f"   ❌ FAIL: Expected {tc['expected']}, got {result_file}")
                all_passed = False
        
        if "expected_not" in tc:
            if result_file != tc["expected_not"]:
                print(f"   ✅ PASS: Correctly avoided {tc['expected_not']}")
            else:
                print(f"   ❌ FAIL: Erroneously selected {tc['expected_not']}")
                all_passed = False
                
    if all_passed:
        print("\n✨ ALL TESTS PASSED!")
    else:
        print("\n💥 SOME TESTS FAILED.")

if __name__ == "__main__":
    test_resume_selection()
