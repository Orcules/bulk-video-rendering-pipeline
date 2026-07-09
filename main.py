from video_processor import VideoProcessor
import time
import sys
import traceback
import config
import gspread
from google.oauth2.service_account import Credentials
import json
import requests

def print_banner():
    """Print the program banner"""
    print("\n" + "=" * 60)
    print("               TURBO VIDEO CREATOR - v2.0")
    print("               (Fixed Version)")
    print("=" * 60)
    print("\nAutomated marketing product-video creation tool")
    print("=" * 60 + "\n")

def auto_clean_expired_zapcap_tasks():
    """Auto-clean ZapCap tasks older than two hours"""
    try:
        import re
        from datetime import datetime, timedelta
        
        print("🧹 Checking for ZapCap tasks older than 2 hours...")
        
        # Connect to the sheet
        SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        
        with open('service_account.json', 'r') as f:
            service_account_info = json.load(f)
        
        creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(config.GOOGLE_SHEET_ID).sheet1
        
        # Read the header row
        headers = sheet.row_values(1)
        zapcap_task_col = None
        status_col = None
        
        for i, header in enumerate(headers):
            if header == "ZapCap Task ID":
                zapcap_task_col = i + 1
            elif header == "Status":
                status_col = i + 1
        
        if not zapcap_task_col or not status_col:
            print("ℹ️  ZapCap Task ID / Status columns not found - skipping cleanup")
            return
        
        # Read all data
        all_values = sheet.get_all_values()
        if len(all_values) <= 1:
            print("ℹ️  Sheet has no data - skipping cleanup")
            return
        
        expired_tasks = []
        TASK_EXPIRY_HOURS = 2
        
        # Check every row that has a ZapCap Task ID
        for row_num in range(2, len(all_values) + 1):
            if row_num - 1 >= len(all_values):
                break
                
            row_data = all_values[row_num - 1]
            
            if len(row_data) < max(zapcap_task_col, status_col):
                continue
                
            task_id = row_data[zapcap_task_col - 1].strip()
            status_text = row_data[status_col - 1].strip()
            
            if not task_id:
                continue
            
            # Extract the timestamp from the status text
            timestamp_pattern = r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})'
            match = re.search(timestamp_pattern, status_text)
            
            if match:
                try:
                    timestamp_str = match.group(1)
                    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                    
                    # Check whether the task expired
                    now = datetime.now()
                    expiry_time = timestamp + timedelta(hours=TASK_EXPIRY_HOURS)
                    
                    if now > expiry_time:
                        age_hours = (now - timestamp).total_seconds() / 3600
                        expired_tasks.append({
                            'row_num': row_num,
                            'task_id': task_id,
                            'age_hours': age_hours
                        })
                        
                except ValueError:
                    continue
        
        # Clear the expired tasks
        if expired_tasks:
            print(f"🗑️  Clearing {len(expired_tasks)} expired tasks...")
            
            for task in expired_tasks:
                print(f"   🗑️  Clearing row {task['row_num']}: Task {task['task_id'][:12]}... (age: {task['age_hours']:.1f}h)")
                
                # Clear the ZapCap Task ID
                sheet.update_cell(task['row_num'], zapcap_task_col, "")
                
                # Update status
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                status_message = f"{timestamp} - Old ZapCap task auto-cleaned - ready for new submission"
                sheet.update_cell(task['row_num'], status_col, status_message)
                
                time.sleep(0.2)  # small pause to avoid rate limiting
                
            print(f"✅ Cleared {len(expired_tasks)} stale tasks")
        else:
            print("✅ No stale tasks to clear")
            
    except Exception as e:
        print(f"❌ Auto-cleanup error: {e}")
        # Never abort the run because cleanup failed

def main():
    try:
        print_banner()
        
        processor = VideoProcessor(config=config)
        
        choice = None
        if len(sys.argv) > 1:
            choice_arg = sys.argv[1]
            if choice_arg in ['1', '2', '3', '4', '5', '6']:
                choice = choice_arg
                print(f"Choice taken from the command-line argument: {choice}")
            else:
                print(f"Invalid command-line argument: {choice_arg}. Showing the menu.")

        if choice is None:
            print("Choose an action:")
            print("1. Full processing (create videos + animate images)")
            print("2. ZapCap video creation only")
            print("3. Image animation only") 
            print("4. Check status of existing tasks")
            print("5. Fast mode - process incomplete rows only")
            print("6. Exit")
            print("\n💡 Note: options 1, 2, 4, 5 auto-clean stale ZapCap tasks (older than 2 hours) before running")
            choice = input("\nEnter the action number: ")
        
        print(f"\nSelected: {choice}")
        
        if choice == '1':
            print("\nAre you sure you want to process ALL data? (yes/no): ")
            confirmation = input()
            
            if confirmation.lower() != 'yes':
                print("Cancelled.")
                return
                
            print("\nStarting processing...")
            print("Press Ctrl+C at any point to stop\n")
            
            # Clean stale tasks before processing
            auto_clean_expired_zapcap_tasks()
            
            processor.run(
                process_mode="all",  # regular full-processing mode
                start_row=2, # Start from the beginning (after headers)
                end_row=None, # Process until the end
                specific_rows=None # Process all rows instead of specific ones
            )
            
        elif choice == '2':
            print("\nAre you sure you want to create videos? (yes/no): ")
            confirmation = input()
            
            if confirmation.lower() != 'yes':
                print("Cancelled.")
                return
            
            # Clean stale tasks before processing
            auto_clean_expired_zapcap_tasks()
                
            try:
                all_values = processor.sheet.get_all_values()
                if not all_values:
                    print("No data found in the sheet.")
                    return
                headers = all_values[0]
                
                sheet_rows_data = []
                for i_row, row_values in enumerate(all_values[1:], start=2):
                    row_dict = {'original_row_index': i_row}
                    for j_col, cell_value in enumerate(row_values):
                        if j_col < len(headers):
                            row_dict[headers[j_col]] = cell_value
                    sheet_rows_data.append(row_dict)
            
                processor.rows = sheet_rows_data
                print(f"Loaded {len(processor.rows)} rows from the sheet")
            except Exception as e_sheet_read:
                print(f"Error reading sheet data for choice '{choice}': {e_sheet_read}")
                return
            
            rows_to_process_for_zapcap = [r for r in processor.rows if not r.get(config.COLUMNS.get('FINAL_VIDEO_URL', 'Final Video url'))]
            
            if not rows_to_process_for_zapcap:
                print("No rows to process - every row already has a final video!")
                return
                
            print(f"Found {len(rows_to_process_for_zapcap)} rows for ZapCap processing")
            
            processor._process_zapcap_batch(rows_to_process_for_zapcap) 
            
            print("\nVideo creation finished!")
            
        elif choice == '3':
            print("\nAre you sure you want to animate images? (yes/no): ")
            confirmation = input()
            
            if confirmation.lower() != 'yes':
                print("Cancelled.")
                return
                
            print("\nLoading data from the sheet...")
            try:
                all_values = processor.sheet.get_all_values()
                if not all_values:
                    print("No data found in the sheet.")
                    return
                headers = all_values[0]
                
                sheet_rows_data = []
                for i_row, row_values in enumerate(all_values[1:], start=2):
                    row_dict = {'original_row_index': i_row}
                    for j_col, cell_value in enumerate(row_values):
                        if j_col < len(headers):
                            row_dict[headers[j_col]] = cell_value
                    sheet_rows_data.append(row_dict)
                
                processor.rows = sheet_rows_data
                print(f"Loaded {len(processor.rows)} rows from the sheet")
            except Exception as e_sheet_read:
                print(f"Error reading sheet data for choice '{choice}': {e_sheet_read}")
                return

            animate_column_name = config.COLUMNS.get('ANIMATE_IMAGES', 'Animate the images?')
            # Filter rows that need animation (only KLING or MINIMAX)
            rows_with_animation = []
            for row in processor.rows:
                animate_val = str(row.get(animate_column_name, '')).strip()
                needs_animation = (
                    'KLING' in animate_val.upper() or
                    'MINIMAX' in animate_val.upper()
                )
                if needs_animation:
                    rows_with_animation.append(row)
            
            if not rows_with_animation:
                print("No rows marked for animation (or the 'Animate the images?' column is empty/'no')!")
                return
                
            print(f"Found {len(rows_with_animation)} rows to animate")
            
            processor.animate_images_batch(rows_with_animation)
            
            print("\nImage animation finished!")
            
        elif choice == '4':
            print("\nChecking status of existing tasks...")
            
            # Clean stale tasks before the status check
            auto_clean_expired_zapcap_tasks()
            
            import os
            import json
            
            active_tasks_file = "active_tasks.json"
            if not os.path.exists(active_tasks_file):
                print("No active tasks found (active_tasks.json is missing)!")
                return
                
            try:
                with open(active_tasks_file, 'r') as f:
                    tasks = json.load(f)
                    
                if not tasks:
                    print("No active tasks in the file.")
                    return
                    
                print(f"Found {len(tasks)} active tasks in the file.")
                
                animation_tasks_from_file = [t for t in tasks if 'column' in t and ('service' in t or '_animation_type' in t)]

                if animation_tasks_from_file:
                    print(f"\nChecking status of {len(animation_tasks_from_file)} animation tasks from file...")
                    processor.wait_for_animations(animation_tasks_from_file)
                else:
                    print("No animation tasks to check from file.")
                
                if processor.tasks_for_final_monitoring: # Check the list used by pipeline
                    print(f"\nChecking status of {len(processor.tasks_for_final_monitoring)} internal ZapCap tasks from the current run...")
                    processor.monitor_tasks_batch(processor.tasks_for_final_monitoring) # Monitor tasks collected by workers in current run
                    processor.tasks_for_final_monitoring.clear()
                elif hasattr(processor, 'pending_zapcap_tasks') and processor.pending_zapcap_tasks: # Fallback for older pending tasks if any
                    print(f"\nChecking status of {len(processor.pending_zapcap_tasks)} older ZapCap tasks...")
                    processor.monitor_tasks_batch(processor.pending_zapcap_tasks)
                    processor.pending_zapcap_tasks.clear()
                else:
                    print("No internal ZapCap tasks to track from current or previous runs.")
                
            except Exception as e:
                print(f"Task status check error: {str(e)}")
            
        elif choice == '5':
            print("\nSelected: fast mode - incomplete rows only")
            print("\nThis mode processes only incomplete rows (no Final Video URL)")
            print("Are you sure you want to start? (yes/no):")
            confirm = input().strip().lower()
            if confirm in ['yes', 'y']:
                print("\nStarting fast processing...")
                print("Press Ctrl+C at any point to stop\n")
                
                # Clean stale tasks before processing
                auto_clean_expired_zapcap_tasks()
                
                # Fast mode: pre-filter incomplete rows
                print("Scanning for incomplete rows...")
                try:
                    all_values = processor.sheet.get_all_values()
                    if not all_values:
                        print("No data found in the sheet.")
                        return
                    
                    headers = all_values[0]
                    
                    # Find incomplete rows
                    incomplete_rows = []
                    final_video_col_index = None
                    
                    # Locate the Final Video URL column index
                    for i, header in enumerate(headers):
                        if header == "Final Video url":
                            final_video_col_index = i
                            break
                    
                    if final_video_col_index is None:
                        print("'Final Video url' column not found in the sheet")
                        return
                    
                    # Check each row
                    for row_idx, row_values in enumerate(all_values[1:], start=2):
                        if row_idx < len(row_values) and final_video_col_index < len(row_values):
                            final_video_url = row_values[final_video_col_index].strip()
                            if not final_video_url:  # incomplete row
                                incomplete_rows.append(row_idx)
                    
                    if not incomplete_rows:
                        print("All rows are already complete! Nothing to process.")
                        return
                        
                    print(f"Found {len(incomplete_rows)} incomplete rows out of {len(all_values)-1}")
                    print(f"Rows to process: {incomplete_rows[:10]}{'...' if len(incomplete_rows) > 10 else ''}")
                    
                    # Process only the incomplete rows
                    processor.run(
                        process_mode="all",
                        start_row=2,
                        end_row=None,
                        specific_rows=incomplete_rows
                    )
                    
                except Exception as e:
                    print(f"Fast-mode error: {e}")
                    traceback.print_exc()
            else:
                print("Cancelled.")
            
        elif choice == '6':
            print("Exiting...")
            return
            
        else:
            print("Invalid choice!")
            
        print("\nProcess completed successfully!")
        
    except KeyboardInterrupt:
        print("\n\nProcess interrupted by the user.")
    except Exception as e:
        print(f"\nAn error occurred: {str(e)}")
        print("\nError details:")
        traceback.print_exc()

if __name__ == "__main__":
    main() 