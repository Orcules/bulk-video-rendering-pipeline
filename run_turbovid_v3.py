#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Entry point for the TurboVid V3 pipeline
"""

import sys
import os

# Add the current directory to PATH
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from turbovid_v3 import main
    
    if __name__ == "__main__":
        main()
        
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("🔧 Make sure all required files exist:")
    print("   - turbovid_v3.py")
    print("   - sheets_manager.py")
    print("   - zapcap_manager.py")
    print("   - animation_manager.py")
    print("   - video_creator.py")
    print("   - config.py")
    print("   - service_account.json")
    
except Exception as e:
    print(f"❌ Unexpected error: {e}")
    import traceback
    traceback.print_exc() 