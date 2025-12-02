import streamlit as st
from streamlit_back_camera_input import back_camera_input
import pandas as pd
import gspread
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from datetime import datetime
import pytz 
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

# ฟังก์ชันจัดการ Input: รับค่าเสร็จแล้วล้างช่องทิ้งทันที
def sync_input_state(key_name, val_name):
    if key_name in st.session_state and st.session_state[key_name]:
        # 1. ส่งค่าไปเก็บในตัวแปรหลัก
        st.session_state[val_name] = st.session_state[key_name]
        # 2. แจ้งเตือนแบบลอย (Toast) ว่ารับค่าแล้ว
        st.toast(f"✅ รับข้อมูล: {st.session_state[key_name]}")
        # 3. ล้างค่าในช่องกรอกให้ว่าง
        st.session_state[key_name] = ""

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

def log_to_history(order_id, prod_code, loc_code, img_count):
    try:
        creds = get_credentials()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        try:
            worksheet = sh.worksheet("History")
        except:
            worksheet = sh.add_worksheet(title="History", rows=1000, cols=10)
            worksheet.append_row(["Timestamp (Thai)", "Order ID", "Product Barcode", "Location", "Images Count", "Status"])

        tz_thai = pytz.timezone('Asia/Bangkok')
        now_str = datetime.now(tz_thai).strftime("%Y-%m-%d %H:%M:%S")
        worksheet.append_row([now_str, order_id, prod_code, loc_code, img_count, "Success"])
        return True
    except Exception as e:
        st.toast(f"⚠️ บันทึก History ไม่สำเร็จ: {e}", icon="⚠️") # Toast Error
        return False

def authenticate_drive():
    try:
        creds = get_credentials()
        if creds: return build('drive', 'v3', credentials=creds)
        return None
    except Exception as e:
        st.toast(f"Error Drive: {e}", icon="❌") # Toast Error
        return None

def get_or_create_folder(service, folder_name, parent_id):
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

# --- 4. APP SETUP ---
st.set_page_config(page_title="Mobile Picking", page_icon="📱", layout="centered")

# CSS: ปรับให้ Toast มองเห็นชัดขึ้น
st.markdown("""
<style>
    .stButton button { width: 100%; height: 3.5rem; font-size: 1.2rem; }
    .camera-hint { font-size: 0.8rem; color: #666; text-align: center; margin-bottom: 5px; }
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
if 'cam_id' not in st.session_state: st.session_state.cam_id = 0

df_items = load_sheet_data()

# --- LOGIC ---
current_step = 1
step_title = "1. สแกน Order ID"
target_loc_str = None

if st.session_state.order_val:
    current_step = 2
    step_title = "2. สแกน Barcode สินค้า"
    
    if st.session_state.prod_val:
        if not df_items.empty:
            match = df_items[df_items['Barcode'] == st.session_state.prod_val]
            if not match.empty:
                row = match.iloc[0]
                target_loc_str = f"{str(row.get('Zone', '')).strip()}-{str(row.get('Location', '')).strip()}"
                
                if st.session_state.loc_val:
                    if st.session_state.loc_val == target_loc_str or st.session_state.loc_val in target_loc_str:
                         current_step = 4
                         step_title = f"4. ถ่ายรูปแพ็ค ({len(st.session_state.photo_gallery)}/5)"
                    else:
                         current_step = 3
                         step_title = "3. สแกน Location (ผิด❌)"
                else:
                    current_step = 3
                    step_title = f"3. ยืนยัน Location: {target_loc_str}"
            else:
                st.toast("❌ ไม่พบข้อมูลสินค้าในระบบ", icon="❌") # Toast Error

# --- UI ---
st.title("📱 Smart Picking")

with st.container():
    st.info(f"👉 ขั้นตอน: **{step_title}**")
    
    # ส่วนกล้อง
    show_cam = True
    if current_step == 4 and len(st.session_state.photo_gallery) >= 5:
        show_cam = False
        st.toast("✅ ครบ 5 รูปแล้ว กด Upload ได้เลย", icon="🎉")

    if show_cam:
        image_file = back_camera_input(key=f"cam_{st.session_state.cam_id}")
        
        if image_file:
            if current_step < 4:
                code = read_barcode_from_image(image_file)
                if code:
                    code = code.upper()
                    if current_step == 1:
                        st.session_state.order_val = code
                    elif current_step == 2:
                        st.session_state.prod_val = code
                    elif current_step == 3:
                        st.session_state.loc_val = code
                    
                    st.toast(f"✅ สแกนสำเร็จ: {code}", icon="📸")
                    st.session_state.cam_id += 1
                    st.rerun()
                else:
                    st.toast("⚠️ อ่าน Barcode ไม่ได้ ลองขยับกล้อง", icon="⚠️")
            else:
                st.session_state.photo_gallery.append(image_file.getvalue())
                st.toast(f"📸 บันทึกรูปที่ {len(st.session_state.photo_gallery)}", icon="✅")
                st.session_state.cam_id += 1
                st.rerun()

# --- DASHBOARD ---
st.markdown("---")
c1, c2, c3 = st.columns(3)
c1.metric("Order", st.session_state.order_val if st.session_state.order_val else "-")
c2.metric("Product", "✅" if st.session_state.prod_val else "-")
c3.metric("Location", "✅" if current_step == 4 else "-")

if target_loc_str and current_step >= 3:
    if current_step == 3 and st.session_state.loc_val:
        st.toast(f"❌ ผิดตำแหน่ง! (Scan: {st.session_state.loc_val})", icon="🚫")
        st.error(f"❌ ผิดตำแหน่ง (คุณอยู่ที่: {st.session_state.loc_val})") # ยังคงโชว์ Error ตัวใหญ่ไว้นิดนึงเผื่อพลาด
    elif current_step == 3:
        st.info(f"📍 เป้าหมาย: **{target_loc_str}**")

# --- UPLOAD SECTION (แก้ไข: ซ่อนปุ่มเมื่อกด) ---
if current_step == 4:
    if st.session_state.photo_gallery:
        st.write("รูปที่ถ่ายแล้ว:")
        g_cols = st.columns(5)
        for i, img in enumerate(st.session_state.photo_gallery):
            with g_cols[i]:
                st.image(img, use_column_width=True)
                if st.button("ลบ", key=f"del_{i}"):
                    st.session_state.photo_gallery.pop(i)
                    st.rerun()
    
    if st.session_state.photo_gallery:
        # [NEW] สร้าง Placeholder เพื่อจัดการปุ่ม
        upload_placeholder = st.empty()
        
        # ถ้ากดปุ่ม (ปุ่มจะอยู่ใน Placeholder)
        if upload_placeholder.button(f"☁️ Upload {len(st.session_state.photo_gallery)} รูป", type="primary"):
             # 1. ซ่อนปุ่มทันที! ป้องกันกดซ้ำ
             upload_placeholder.empty()
             
             # 2. แสดงสถานะกำลังทำงาน
             status_msg = st.info("🚀 กำลังอัปโหลดข้อมูล กรุณารอสักครู่...")
             st.toast("กำลังเชื่อมต่อ Google Drive...", icon="⏳")

             with st.spinner("Uploading..."):
                srv = authenticate_drive()
                if srv:
                    # Drive Logic
                    tz_thai = pytz.timezone('Asia/Bangkok')
                    now_thai = datetime.now(tz_thai)
                    date_str = now_thai.strftime("%d-%m-%Y")
                    time_str = now_thai.strftime("%H_%M")
                    
                    date_folder_id = get_or_create_folder(srv, date_str, MAIN_FOLDER_ID)
                    sub_folder_name = f"{st.session_state.order_val}-{time_str}"
                    final_folder_id = get_or_create_folder(srv, sub_folder_name, date_folder_id)

                    for i, b in enumerate(st.session_state.photo_gallery):
                        fn = f"{sub_folder_name}_Img{i+1}.jpg"
                        upload_photo(srv, b, fn, final_folder_id)

                    # Sheet Logic
                    log_success = log_to_history(
                        st.session_state.order_val, 
                        st.session_state.prod_val, 
                        st.session_state.loc_val, 
                        len(st.session_state.photo_gallery)
                    )
                    
                    # สำเร็จ!
                    status_msg.empty() # ลบข้อความกำลังโหลด
                    st.balloons()
                    st.toast(f"✅ บันทึกสำเร็จ! ({sub_folder_name})", icon="🎉")
                    
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

# --- MANUAL INPUT (แก้ไข: Auto Clear) ---
with st.expander("📝 กรอกเอง / Upload รูป"):
    st.markdown("---")
    # ใช้ on_change=sync_input_state เพื่อรับค่าและล้างช่องทันที
    st.text_input("พิมพ์ Order ID", key="input_order", on_change=sync_input_state, args=("input_order", "order_val"))
    
    if st.session_state.order_val:
        st.text_input("พิมพ์ Product Barcode", key="input_prod", on_change=sync_input_state, args=("input_prod", "prod_val"))
    
    if st.session_state.prod_val:
        st.text_input("พิมพ์ Location", key="input_loc", on_change=sync_input_state, args=("input_loc", "loc_val"))
        
    if st.button("Reset / เริ่มใหม่"):
        st.session_state.order_val = ""
        st.session_state.prod_val = ""
        st.session_state.loc_val = ""
        st.session_state.input_order = ""
        st.session_state.input_prod = ""
        st.session_state.input_loc = ""
        st.session_state.photo_gallery = []
        st.session_state.cam_id += 1
        st.rerun()
