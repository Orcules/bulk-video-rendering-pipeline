import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# API Keys
ELEVEN_LABS_API_KEY = os.getenv("ELEVEN_LABS_API_KEY")
ZAPCAP_API_KEY = os.getenv("ZAPCAP_API_KEY")
ZAPCAP_WEBHOOK_SECRET = os.getenv("ZAPCAP_WEBHOOK_SECRET")
KLING_API_KEY = os.getenv("KLING_API_KEY")
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY")

# Google Sheets Configuration
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SERVICE_ACCOUNT_EMAIL = os.getenv("SERVICE_ACCOUNT_EMAIL")
SERVICE_ACCOUNT_KEY = os.getenv("SERVICE_ACCOUNT_KEY")

# Google Cloud Storage
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "turbovid-videos")

# Sheet Column Names
COLUMNS = {
    "SCRIPT": "Script",
    "FINAL_VIDEO_URL": "Final Video url",
    "VOICE": "Voice",
    "VO_GENDER": "VO Gender",
    "ZOOM": "Zoom in?",
    "SIZE": "Size",
    "ZAPCAP_TEMPLATE": "ZapCap Template"
} 