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

# --- 3. GOOGLE SERVICES ---
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

def create_or_get_order_folder(service, order_id, parent_id):
    date_prefix = datetime.now().strftime("%d-%m-%Y")
    folder_name = f"{date_prefix}_{order_id}"
    query = f"name = '{folder_name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    if files: return files[0]['id']
    else:
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

# CSS ปรับแต่งสำหรับมือถือ (ปุ่มใหญ่, ซ่อน padding)
st.markdown("""
<style>
    .stButton button { width: 100%; height: 3.5rem; font-size: 1.2rem; }
    .block-container { padding-top: 1rem; padding-bottom: 2rem; }
    [data-testid="stExpander"] { background-color: #f0f2f6; border-radius: 10px; }
    div[data-testid="stMetricValue"] { font-size: 1.2rem; }
</style>
""", unsafe_allow_html=True)

# Init State
if 'order_val' not in st.session_state: st.session_state.order_val = ""
if 'prod_val' not in st.session_state: st.session_state.prod_val = ""
if 'loc_val' not in st.session_state: st.session_state.loc_val = ""
if 'input_order' not in st.session_state: st.session_state.input_order = ""
if 'input_prod' not in st.session_state: st.session_state.input_prod = ""
if 'input_loc' not in st.session_state: st.session_state.input_loc = ""
if 'photo_gallery' not in st.session_state: st.session_state.photo_gallery = []
if 'cam_id' not in st.session_state: st.session_state.cam_id = 0 # Counter เพื่อรีเซ็ตกล้อง

df_items = load_sheet_data()

# --- LOGIC: กำหนดสถานะปัจจุบัน (Current Step) ---
# 1 = Scan Order, 2 = Scan Product, 3 = Verify Location, 4 = Pack
current_step = 1
step_title = "1. สแกน Order ID"
target_loc_str = None

if st.session_state.order_val:
    current_step = 2
    step_title = "2. สแกน Barcode สินค้า"
    
    if st.session_state.prod_val:
        # เช็คข้อมูลสินค้าเพื่อหา Location เป้าหมาย
        if not df_items.empty:
            match = df_items[df_items['Barcode'] == st.session_state.prod_val]
            if not match.empty:
                row = match.iloc[0]
                target_loc_str = f"{str(row.get('Zone', '')).strip()}-{str(row.get('Location', '')).strip()}"
                
                if st.session_state.loc_val:
                    # ถ้าสแกน Loc แล้ว เช็คว่าถูกไหม
                    if st.session_state.loc_val == target_loc_str or st.session_state.loc_val in target_loc_str:
                         current_step = 4
                         step_title = f"4. ถ่ายรูปแพ็คสินค้า ({len(st.session_state.photo_gallery)}/5)"
                    else:
                         current_step = 3 # ผิด ให้สแกนใหม่
                         step_title = "3. สแกน Location (ข้อมูลผิด)"
                else:
                    current_step = 3
                    step_title = f"3. ยืนยัน Location: {target_loc_str}"
            else:
                st.error("❌ ไม่พบข้อมูลสินค้าใน Sheet")
                # ค้างอยู่ที่ Step 2 เพื่อให้สแกนใหม่
    

# --- 📱 MAIN UI: TOP SECTION (กล้องจุดเดียว) ---
st.title("📱 Smart Picking")

# ส่วนแสดงกล้อง (Universal Scanner)
# จะแสดงกล้องตลอดเวลา แต่เปลี่ยน Key ไปเรื่อยๆ เพื่อรีเฟรช และเปลี่ยน Label ตาม Step
cam_label = f"📸 กล้อง: {step_title}"
if current_step == 4: cam_label = "📸 ถ่ายรูปสินค้าลงกล่อง"

# ใช้ Container ครอบเพื่อให้ดูเป็นสัดส่วน
with st.container():
    st.info(f"👉 ขั้นตอนปัจจุบัน: **{step_title}**")
    
    # กล้อง (ถ้าครบ 5 รูปในขั้นตอนแพ็ค จะซ่อนกล้อง)
    show_cam = True
    if current_step == 4 and len(st.session_state.photo_gallery) >= 5:
        show_cam = False
        st.success("✅ ถ่ายครบ 5 รูปแล้ว")

    if show_cam:
        img_file = st.camera_input(cam_label, key=f"cam_{st.session_state.cam_id}")
        
        if img_file:
            # --- PROCESS LOGIC ---
            if current_step < 4:
                # โหมดอ่าน Barcode
                code = read_barcode_from_image(img_file)
                if code:
                    code = code.upper()
                    if current_step == 1:
                        st.session_state.order_val = code
                        st.session_state.input_order = code
                    elif current_step == 2:
                        st.session_state.prod_val = code
                        st.session_state.input_prod = code
                    elif current_step == 3:
                        st.session_state.loc_val = code
                        st.session_state.input_loc = code
                    
                    st.toast(f"✅ อ่านค่า: {code}")
                    st.session_state.cam_id += 1 # รีเซ็ตกล้อง
                    st.rerun()
                else:
                    st.warning("⚠️ อ่าน Barcode ไม่ได้ ถ่ายใหม่ครับ")
            
            else:
                # โหมดถ่ายรูป (Packing)
                st.session_state.photo_gallery.append(img_file.getvalue())
                st.toast(f"บันทึกรูปที่ {len(st.session_state.photo_gallery)}")
                st.session_state.cam_id += 1 # รีเซ็ตกล้อง
                st.rerun()

# --- 📊 MIDDLE SECTION: STATUS DASHBOARD ---
st.markdown("---")
col1, col2, col3 = st.columns(3)
col1.metric("Order", st.session_state.order_val if st.session_state.order_val else "-")
col2.metric("Product", "✅" if st.session_state.prod_val else "-")
col3.metric("Location", "✅" if current_step == 4 else "-")

if target_loc_str and current_step >= 3:
    if current_step == 3 and st.session_state.loc_val:
        st.error(f"❌ ตำแหน่งผิด! (Scan: {st.session_state.loc_val} vs Target: {target_loc_str})")
    elif current_step == 3:
        st.info(f"📍 เป้าหมาย: **{target_loc_str}**")

# --- 🖼️ GALLERY & UPLOAD (สำหรับ Step 4) ---
if current_step == 4:
    if st.session_state.photo_gallery:
        st.write("Gallery:")
        g_cols = st.columns(5)
        for i, img in enumerate(st.session_state.photo_gallery):
            with g_cols[i]:
                st.image(img, use_column_width=True)
                if st.button("ลบ", key=f"del_{i}"):
                    st.session_state.photo_gallery.pop(i)
                    st.rerun()
    
    if st.session_state.photo_gallery:
        if st.button(f"☁️ Upload {len(st.session_state.photo_gallery)} รูป", type="primary"):
             with st.spinner("Uploading..."):
                srv = authenticate_drive()
                if srv:
                    fid = create_or_get_order_folder(srv, st.session_state.order_val, MAIN_FOLDER_ID)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    for i, b in enumerate(st.session_state.photo_gallery):
                        fn = f"{st.session_state.order_val}_{st.session_state.prod_val}_LOC-{target_loc_str}_{ts}_Img{i+1}.jpg"
                        upload_photo(srv, b, fn, fid)
                    
                    st.balloons()
                    st.success("บันทึกสำเร็จ!")
                    time.sleep(2)
                    # Reset
                    st.session_state.order_val = ""
                    st.session_state.prod_val = ""
                    st.session_state.loc_val = ""
                    st.session_state.input_order = ""
                    st.session_state.input_prod = ""
                    st.session_state.input_loc = ""
                    st.session_state.photo_gallery = []
                    st.session_state.cam_id += 1
                    st.rerun()

# --- ✏️ BOTTOM SECTION: MANUAL INPUT (EXPANDER) ---
# ส่วนนี้ซ่อนไว้ ถ้ากล้องพังค่อยกดเปิดมาพิมพ์
with st.expander("📝 กรอกข้อมูลเอง (Manual Input)"):
    st.text_input("1. Order ID", key="input_order", on_change=sync_input_state, args=("input_order", "order_val"))
    if st.session_state.order_val:
        st.text_input("2. Product Barcode", key="input_prod", on_change=sync_input_state, args=("input_prod", "prod_val"))
    if st.session_state.prod_val:
        st.text_input("3. Location Barcode", key="input_loc", on_change=sync_input_state, args=("input_loc", "loc_val"))
        
    if st.button("Reset / เริ่มใหม่ทั้งหมด"):
        st.session_state.order_val = ""
        st.session_state.prod_val = ""
        st.session_state.loc_val = ""
        st.session_state.input_order = ""
        st.session_state.input_prod = ""
        st.session_state.input_loc = ""
        st.session_state.photo_gallery = []
        st.session_state.cam_id += 1
        st.rerun()
