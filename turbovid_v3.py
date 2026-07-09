#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TurboVid V3 - a new, simple video creation system
Principles: Google Sheets as the single source of truth, modular architecture, clean code
"""

import sys
import time
import logging
import traceback
from datetime import datetime
from sheets_manager import SheetsManager
from video_creator import VideoCreator
from zapcap_manager import ZapCapManager
from animation_manager import AnimationManager
import config


class TurboVidV3:
    """New TurboVid system - simple and efficient"""
    
    def __init__(self):
        print(self._get_banner())
        self.sheets = SheetsManager()
        self.video_creator = VideoCreator()
        self.zapcap = ZapCapManager()
        self.animation = AnimationManager()
        
        # Wire up the modules
        self.zapcap.set_sheets_manager(self.sheets)
        self.animation.set_sheets_manager(self.sheets)
        
    def _get_banner(self):
        """System banner"""
        return """
╔═══════════════════════════════════════════════════════════════╗
║                  TURBO VID V3 - CLEAN EDITION                 ║
║                 Rebuilt video creation system                 ║
║                                                               ║
║  * Google Sheets as the single source of truth                ║
║  * Simple, modular architecture                               ║
║  * Improved performance and error handling                    ║
╚═══════════════════════════════════════════════════════════════╝
        """
    
    def run(self):
        """Main entry point"""
        try:
            self._show_menu()
            choice = self._get_user_choice()
            self._execute_choice(choice)
            
        except KeyboardInterrupt:
            print("\n\n⚠️  Process interrupted by the user")
        except Exception as e:
            print(f"\n❌ General error: {e}")
            traceback.print_exc()
    
    def _show_menu(self):
        """Display the options menu"""
        print("""
🎬 Choose an action:

1️⃣  Full processing - create all videos and animations
2️⃣  Check status of existing tasks
3️⃣  Create new videos only
4️⃣  Animate images only
5️⃣  Fast mode - incomplete rows only
6️⃣  Clean failed tasks
0️⃣  Exit

💡 The new system uses only Google Sheets - no complex JSON files!
        """)
    
    def _get_user_choice(self):
        """Get the user's choice"""
        while True:
            choice = input("Enter an action number: ").strip()
            if choice in ['0', '1', '2', '3', '4', '5', '6']:
                return choice
            print("❌ Invalid choice. Please enter a number between 0-6")
    
    def _execute_choice(self, choice):
        """Execute the selected action"""
        if choice == '0':
            print("👋 Goodbye!")
            return
            
        elif choice == '1':
            self._full_process()
            
        elif choice == '2':
            self._check_status()
            
        elif choice == '3':
            self._create_videos_only()
            
        elif choice == '4':
            self._animate_images_only()
            
        elif choice == '5':
            self._fast_mode()
            
        elif choice == '6':
            self._clean_failed_tasks()
    
    def _full_process(self):
        """Full processing - create all videos and animations"""
        print("\n🚀 Starting full processing...")
        
        if not self._confirm_action("start full processing"):
            return
            
        # Step 1: Clean failed tasks
        print("\n📝 Step 1: Cleaning failed tasks...")
        self.zapcap.clean_failed_tasks()
        
        # Step 2: Read data from the sheet
        print("\n📊 Step 2: Reading data from the sheet...")
        rows = self.sheets.get_all_rows()
        
        if not rows:
            print("❌ No data found in the sheet")
            return
            
        print(f"✅ Loaded {len(rows)} rows from the sheet")
        
        # Step 3: Create videos
        print("\n🎬 Step 3: Creating videos...")
        self._process_videos(rows)
        
        # Step 4: Animate images
        print("\n🎨 Step 4: Animating images...")
        self._process_animations(rows)
        
        # Step 5: Monitor tasks
        print("\n⏳ Step 5: Monitoring tasks...")
        self.zapcap.monitor_all_pending_tasks()
        
        print("\n🎉 Full processing completed!")
    
    def _check_status(self):
        """Check status of existing tasks"""
        print("\n🔍 Checking status of existing tasks...")
        
        # Check ZapCap tasks
        print("\n📹 Checking ZapCap tasks...")
        self.zapcap.monitor_all_pending_tasks()
        
        # Check animation tasks
        print("\n🎨 Checking animation tasks...")
        self.animation.check_all_pending_animations()
        
        print("\n✅ Status check completed!")
    
    def _create_videos_only(self):
        """Create videos only"""
        print("\n🎬 Creating videos only...")
        
        if not self._confirm_action("create videos"):
            return
            
        rows = self.sheets.get_all_rows()
        self._process_videos(rows)
        
        print("\n✅ Video creation completed!")
    
    def _animate_images_only(self):
        """Animate images only"""
        print("\n🎨 Animating images only...")
        
        if not self._confirm_action("animate images"):
            return
            
        rows = self.sheets.get_all_rows()
        self._process_animations(rows)
        
        print("\n✅ Image animation completed!")
    
    def _fast_mode(self):
        """Fast mode - incomplete rows only"""
        print("\n⚡ Fast mode - processing incomplete rows only...")
        
        if not self._confirm_action("start fast mode"):
            return
            
        # Find incomplete rows
        incomplete_rows = self.sheets.get_incomplete_rows()
        
        if not incomplete_rows:
            print("🎉 All rows are already completed!")
            return
            
        print(f"📊 Found {len(incomplete_rows)} incomplete rows")
        
        # Process only the incomplete rows
        self._process_videos(incomplete_rows)
        self._process_animations(incomplete_rows)
        self.zapcap.monitor_all_pending_tasks()
        
        print("\n🎉 Fast mode completed!")
    
    def _clean_failed_tasks(self):
        """Clean failed tasks"""
        print("\n🧹 Cleaning failed tasks...")
        
        if not self._confirm_action("clean failed tasks"):
            return
            
        cleaned_count = self.zapcap.clean_failed_tasks()
        print(f"✅ {cleaned_count} tasks cleaned successfully!")
    
    def _process_videos(self, rows):
        """Process video creation"""
        video_rows = [row for row in rows if not row.get('final_video_url')]
        
        if not video_rows:
            print("ℹ️  All rows already have a final video")
            return
            
        print(f"🎬 Creating {len(video_rows)} videos...")
        
        for row in video_rows:
            try:
                print(f"\n🎬 Processing row {row['row_number']}: {row.get('name', 'unnamed')}")
                
                # Create a video with ZapCap
                task_id = self.zapcap.create_video(row)
                
                if task_id:
                    print(f"✅ Video submitted to ZapCap: {task_id}")
                    # Update Task ID in the sheet
                    self.sheets.update_zapcap_task_id(row['row_number'], task_id)
                else:
                    print("❌ Failed to submit to ZapCap")
                    
                time.sleep(2)  # Short pause between requests
                
            except Exception as e:
                print(f"❌ Error processing row {row['row_number']}: {e}")
                continue
    
    def _process_animations(self, rows):
        """Process image animation"""
        animation_rows = [row for row in rows if self._needs_animation(row)]
        
        if not animation_rows:
            print("ℹ️  No rows require animation")
            return
            
        print(f"🎨 Animating {len(animation_rows)} images...")
        
        for row in animation_rows:
            try:
                print(f"\n🎨 Animating row {row['row_number']}: {row.get('name', 'unnamed')}")
                
                # Animate the images
                success = self.animation.animate_row(row)
                
                if success:
                    print(f"✅ Images animated successfully")
                else:
                    print("❌ Failed to animate images")
                    
                time.sleep(2)
                
            except Exception as e:
                print(f"❌ Error animating row {row['row_number']}: {e}")
                continue
    
    def _needs_animation(self, row):
        """Check whether the row requires animation"""
        animate_value = str(row.get('animate_images', '')).upper()
        return 'KLING' in animate_value or 'MINIMAX' in animate_value
    
    def _confirm_action(self, action_name):
        """Ask the user for confirmation"""
        while True:
            confirm = input(f"\n❓ Are you sure you want to {action_name}? (yes/no): ").strip().lower()
            if confirm in ['yes', 'y']:
                return True
            elif confirm in ['no', 'n']:
                print("❌ Action cancelled")
                return False
            else:
                print("❌ Please enter 'yes' or 'no'")


def main():
    """Main entry point"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    app = TurboVidV3()
    app.run()


if __name__ == "__main__":
    main() 