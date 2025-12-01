import streamlit as st
import pandas as pd
import gspread
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from datetime import datetime
from PIL import Image
from pyzbar.pyzbar import decode 
import io 
import time

# --- 1. CONFIGURATION ---
MAIN_FOLDER_ID = '1FHfyzzTzkK5PaKx6oQeFxTbLEq-Tmii7'
SHEET_ID = '1jNlztb3vfG0c8sw_bMTuA9GEqircx_uVE7uywd5dR2I'

# --- 2. HELPER FUNCTIONS ---
def read_barcode_from_image(img_file):
    if img_file is None: return None
    try:
        image = Image.open(img_file)
        decoded_objects = decode(image)
        if decoded_objects:
            return decoded_objects[0].data.decode("utf-8").strip()
        return None
    except Exception:
        return None

def get_credentials():
    try:
        if "oauth" in st.secrets:
            info = st.secrets["oauth"]
            return Credentials(
                None, refresh_token=info["refresh_token"],
                token_uri="https://oauth2.googleapis.com/token",
                client_id=info["client_id"], client_secret=info["client_secret"]
            )
        return None
    except Exception:
        return None

# --- 3. GOOGLE SERVICES (Drive & Sheets) ---
@st.cache_data(ttl=600)
def load_sheet_data():
    try:
        creds = get_credentials()
        if not creds: return pd.DataFrame()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        worksheet = sh.get_worksheet(0)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        if 'Barcode' in df.columns:
            try:
                df['Barcode'] = df['Barcode'].astype(str).str.replace(r'\.0$', '', regex=True)
            except:
                df['Barcode'] = df['Barcode'].astype(str)
        return df
    except Exception:
        return pd.DataFrame()

def authenticate_drive():
    try:
        creds = get_credentials()
        if creds: return build('drive', 'v3', credentials=creds)
        return None
    except Exception as e:
        st.error(f"Error Drive: {e}")
        return None

# 🔥 ฟังก์ชันสร้าง Folder แบบใหม่ (Generic)
def get_or_create_folder(service, folder_name, parent_id):
    # ค้นหาว่ามี Folder ชื่อนี้อยู่แล้วหรือไม่
    query = f"name = '{folder_name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    
    if files:
        return files[0]['id'] # ถ้ามี ให้ใช้ ID เดิม
    else:
        # ถ้าไม่มี ให้สร้างใหม่
        file_metadata = {'name': folder_name, 'parents': [parent_id], 'mimeType': 'application/vnd.google-apps.folder'}
        folder = service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')

def upload_photo(service, file_obj, filename, folder_id):
    file_metadata = {'name': filename, 'parents': [folder_id]}
    media = MediaIoBaseUpload(io.BytesIO(file_obj), mimetype='image/jpeg')
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    return file.get('id')

def sync_input_state(key_name, val_name):
    if key_name in st.session_state:
        st.session_state[val_name] = st.session_state[key_name]

# --- 4. APP SETUP ---
st.set_page_config(page_title="Mobile Picking", page_icon="📱", layout="centered")

st.markdown("""
<style>
    .stButton button { width: 100%; height: 3.5rem; font-size: 1.2rem; }
    .block-container { padding-top: 1rem; padding-bottom: 2rem; }
    [data-testid="stExpander"] { background-color: #f0f2f6; border-radius: 10px; }
    div[data-testid="stMetricValue"] { font-size: 1.2rem; }
    .camera-hint { font-size: 0.8rem; color: #666; text-align: center; margin-bottom: 5px; }
</style>
""", unsafe_allow_html=True)

# Init State
if 'order_val' not
