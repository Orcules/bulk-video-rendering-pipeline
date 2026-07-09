#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Sheets management - the pipeline's single source of truth
"""

import logging
import gspread
from google.oauth2.service_account import Credentials
import config
import time
from typing import List, Dict, Optional


logger = logging.getLogger(__name__)


class SheetsManager:
    """Google Sheets manager - the single source of truth"""
    
    def __init__(self):
        self._connect_to_sheets()
        self._map_columns()
        
    def _connect_to_sheets(self):
        """Connect to Google Sheets"""
        try:
            scope = [
                'https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive'
            ]
            
            creds = Credentials.from_service_account_file(
                'service_account.json', 
                scopes=scope
            )
            
            self.client = gspread.authorize(creds)
            self.sheet = self.client.open_by_key(config.GOOGLE_SHEET_ID).sheet1
            
            logger.info("Connected to Google Sheets")
            
        except Exception as e:
            logger.error(f"Google Sheets connection error: {e}")
            raise
    
    def _map_columns(self):
        """Map the sheet columns"""
        try:
            self.headers = self.sheet.row_values(1)
            self.column_map = {}
            
            for i, header in enumerate(self.headers):
                self.column_map[header] = i + 1  # Google Sheets is 1-indexed
                
            logger.info(f"Mapped {len(self.headers)} columns")
            
            # Key columns
            self.zapcap_task_col = self.column_map.get('ZapCap Task ID')
            self.final_video_col = self.column_map.get('Final Video url')
            self.status_col = self.column_map.get('Status')
            self.name_col = self.column_map.get('Name')
            
        except Exception as e:
            logger.error(f"Column mapping error: {e}")
            raise
    
    def get_all_rows(self) -> List[Dict]:
        """Read all rows from the sheet"""
        try:
            all_values = self.sheet.get_all_values()
            
            if not all_values or len(all_values) <= 1:
                logger.warning("Sheet has no data")
                return []
            
            rows = []
            
            for i, row_values in enumerate(all_values[1:], start=2):  # start=2: row 1 is the header
                row_data = {
                    'row_number': i,
                    'raw_data': row_values
                }
                
                # Map values by column name
                for j, value in enumerate(row_values):
                    if j < len(self.headers):
                        column_name = self.headers[j]
                        row_data[self._normalize_column_name(column_name)] = value.strip()
                
                rows.append(row_data)
            
            logger.info(f"Loaded {len(rows)} rows from the sheet")
            return rows
            
        except Exception as e:
            logger.error(f"Sheet read error: {e}")
            return []
    
    def get_incomplete_rows(self) -> List[Dict]:
        """Read incomplete rows (no Final Video URL yet)"""
        all_rows = self.get_all_rows()
        
        incomplete_rows = [
            row for row in all_rows 
            if not row.get('final_video_url', '').strip()
        ]
        
        logger.info(f"Found {len(incomplete_rows)} incomplete rows out of {len(all_rows)}")
        return incomplete_rows
    
    def get_pending_zapcap_tasks(self) -> List[Dict]:
        """Read pending ZapCap tasks (Task ID present but no Final Video)"""
        all_rows = self.get_all_rows()
        
        pending_tasks = []
        
        for row in all_rows:
            zapcap_task_id = row.get('zapcap_task_id', '').strip()
            final_video_url = row.get('final_video_url', '').strip()
            
            # Task ID present but no Final Video = pending task
            if zapcap_task_id and not final_video_url:
                pending_tasks.append(row)
        
        logger.info(f"Found {len(pending_tasks)} pending ZapCap tasks")
        return pending_tasks
    
    def update_zapcap_task_id(self, row_number: int, task_id: str):
        """Update the ZapCap Task ID"""
        if not self.zapcap_task_col:
            logger.warning("'ZapCap Task ID' column not found")
            return False
            
        try:
            self.sheet.update_cell(row_number, self.zapcap_task_col, task_id)
            logger.info(f"Updated Task ID on row {row_number}: {task_id[:12]}...")
            time.sleep(0.2)  # avoid rate limiting
            return True
            
        except Exception as e:
            logger.error(f"Task ID update error: {e}")
            return False
    
    def update_final_video_url(self, row_number: int, video_url: str):
        """Update the Final Video URL"""
        if not self.final_video_col:
            logger.warning("'Final Video url' column not found")
            return False
            
        try:
            self.sheet.update_cell(row_number, self.final_video_col, video_url)
            logger.info(f"Updated Video URL on row {row_number}")
            time.sleep(0.2)
            return True
            
        except Exception as e:
            logger.error(f"Video URL update error: {e}")
            return False
    
    def update_status(self, row_number: int, status: str):
        """Update the status column"""
        if not self.status_col:
            return  # a Status column is optional
            
        try:
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            status_with_time = f"{timestamp} - {status}"
            
            self.sheet.update_cell(row_number, self.status_col, status_with_time)
            time.sleep(0.2)
            
        except Exception as e:
            logger.warning(f"Status update error: {e}")
    
    def clear_zapcap_task_id(self, row_number: int, reason: str = ""):
        """Clear the ZapCap Task ID (on failure)"""
        if not self.zapcap_task_col:
            return False
            
        try:
            self.sheet.update_cell(row_number, self.zapcap_task_col, "")
            
            if reason:
                self.update_status(row_number, f"ZapCap task cleared - {reason}")
            
            logger.info(f"Cleared Task ID on row {row_number}")
            time.sleep(0.2)
            return True
            
        except Exception as e:
            logger.error(f"Task ID clear error: {e}")
            return False
    
    def complete_row(self, row_number: int, video_url: str):
        """Complete a row - set the Video URL and clear the Task ID"""
        try:
            # Set the Final Video URL
            self.update_final_video_url(row_number, video_url)
            
            # Clear the ZapCap Task ID
            if self.zapcap_task_col:
                self.sheet.update_cell(row_number, self.zapcap_task_col, "")
                time.sleep(0.2)
            
            # Update status
            self.update_status(row_number, "Completed successfully")
            
            logger.info(f"Row {row_number} completed!")
            return True
            
        except Exception as e:
            logger.error(f"Error completing row {row_number}: {e}")
            return False
    
    def get_row_by_number(self, row_number: int) -> Optional[Dict]:
        """Read a specific row by number"""
        try:
            row_values = self.sheet.row_values(row_number)
            
            if not row_values:
                return None
            
            row_data = {
                'row_number': row_number,
                'raw_data': row_values
            }
            
            # Map values
            for j, value in enumerate(row_values):
                if j < len(self.headers):
                    column_name = self.headers[j]
                    row_data[self._normalize_column_name(column_name)] = value.strip()
            
            return row_data
            
        except Exception as e:
            logger.error(f"Error reading row {row_number}: {e}")
            return None
    
    def _normalize_column_name(self, column_name: str) -> str:
        """Normalize a column name for Python use"""
        return (column_name.lower()
                .replace(' ', '_')
                .replace('?', '')
                .replace('/', '_')
                .replace('-', '_'))
    
    def get_column_mapping(self) -> Dict[str, int]:
        """Return the column map"""
        return self.column_map.copy()
    
    def refresh_connection(self):
        """Refresh the sheet connection"""
        try:
            self._connect_to_sheets()
            self._map_columns()
            logger.info("Sheet connection refreshed")
            
        except Exception as e:
            logger.error(f"Connection refresh error: {e}")
            raise 