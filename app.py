# -*- coding: utf-8 -*-
import streamlit as st
import time
from video_processor import VideoProcessor
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Initialize session state for logs if not exists
if 'logs' not in st.session_state:
    st.session_state.logs = []

def add_log(message: str, status: str = 'info'):
    """Add a log message to the session state"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.logs.append({
        'timestamp': timestamp,
        'message': message,
        'status': status
    })
    # Keep only last 100 logs to prevent memory issues
    if len(st.session_state.logs) > 100:
        st.session_state.logs = st.session_state.logs[-100:]

def main():
    st.title("Video Processing Dashboard")
    
    # Create a container for logs
    log_container = st.container()
    
    # Create a container for the start button
    button_container = st.container()
    
    # Display logs
    with log_container:
        for log in st.session_state.logs:
            if log['status'] == 'info':
                st.info(f"{log['timestamp']} - {log['message']}")
            elif log['status'] == 'success':
                st.success(f"{log['timestamp']} - {log['message']}")
            elif log['status'] == 'error':
                st.error(f"{log['timestamp']} - {log['message']}")
    
    # Start button
    with button_container:
        if st.button("Start Processing"):
            try:
                # Initialize processor with custom logging functions
                processor = VideoProcessor()
                processor.print_info = lambda msg: add_log(msg, 'info')
                processor.print_success = lambda msg: add_log(msg, 'success')
                processor.print_error = lambda msg: add_log(msg, 'error')
                
                # Start processing
                processor.run(process_mode="all", start_row=2)
                
            except Exception as e:
                add_log(f"Error: {str(e)}", 'error')
                st.error(f"An error occurred: {str(e)}")

if __name__ == "__main__":
    # Set Streamlit page config to reduce updates
    st.set_page_config(
        page_title="Video Processing Dashboard",
        layout="wide",
        initial_sidebar_state="collapsed"
    )
    
    # Add custom CSS to reduce updates
    st.markdown("""
        <style>
        .stButton>button {
            width: 100%;
            margin-top: 1rem;
        }
        .stMarkdown {
            margin-bottom: 1rem;
        }
        </style>
    """, unsafe_allow_html=True)
    
    main() 