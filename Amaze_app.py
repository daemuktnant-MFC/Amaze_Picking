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

# --- 2. HELPER FUNCTIONS (Barcode & Auth) ---
def read_barcode_from_image(img_file):
    """ฟังก์ชันอ่าน Barcode จากรูปภาพ (แม่นยำกว่า)"""
    if img_file is None:
        return None
    try:
        image = Image.open(img_file)
        decoded_objects = decode(image)
        if decoded_objects:
            # คืนค่า Barcode แรกที่เจอ และแปลงเป็น string
            return decoded_objects[0].data.decode("utf-8").strip()
        return None
    except Exception as e:
        st.error(f"Error reading barcode: {e}")
        return None

def get_credentials():
    try:
        if "oauth" in st.secrets:
            info = st.secrets["oauth"]
            creds = Credentials(
                None,
                refresh_token=info["refresh_token"],
                token_uri="https://oauth2.googleapis.com/token",
                client_id=info["client_id"],
                client_secret=info["client_secret"]
            )
            return creds
        else:
            st.error("❌ ไม่พบข้อมูล [oauth] ใน Secrets")
            return None
    except Exception as e:
        st.error(f"❌ Error Credentials: {e}")
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
    except Exception as e:
        # print(f"Sheet Error: {e}") # Debug Only
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
    
    if files: 
        return files[0]['id']
    else:
        file_metadata = {'name': folder_name, 'parents': [parent_id], 'mimeType': 'application/vnd.google-apps.folder'}
        folder = service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')

def upload_photo(service, file_obj, filename, folder_id):
    try:
        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(file_obj), mimetype='image/jpeg')
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file.get('id')
    except Exception as e:
        st.error(f"🔴 Upload Error: {e}")
        raise e

# --- 4. UI SETUP ---
st.set_page_config(page_title="Smart Picking (Google)", page_icon="📦")

# Initialize State
if 'order_val' not in st.session_state: st.session_state.order_val = ""
if 'prod_val' not in st.session_state: st.session_state.prod_val = ""
if 'loc_val' not in st.session_state: st.session_state.loc_val = ""
if 'photo_gallery' not in st.session_state: st.session_state.photo_gallery = []
if 'cam_counter' not in st.session_state: st.session_state.cam_counter = 0

# Key สำหรับรีเซ็ตกล้องสแกน
if 'key_cam_order' not in st.session_state: st.session_state.key_cam_order = 0
if 'key_cam_prod' not in st.session_state: st.session_state.key_cam_prod = 0
if 'key_cam_loc' not in st.session_state: st.session_state.key_cam_loc = 0

st.title("📦 ระบบเบิกสินค้า (Google API)")

df_items = load_sheet_data()

# ==========================================
# 1. ORDER ID
# ==========================================
st.markdown("#### 1. Order ID")
col_o1, col_o2 = st.columns([4, 1])

# Checkbox เปิด/ปิดกล้อง
with col_o2:
    use_cam_order = st.checkbox("📷", key="tog_order")

# ส่วนแสดงกล้อง (ถ้าติ๊กถูก)
if use_cam_order:
    img_file = st.camera_input("ถ่าย Barcode Order", key=f"cam_o_{st.session_state.key_cam_order}")
    if img_file:
        res = read_barcode_from_image(img_file)
        if res:
            st.session_state.order_val = res.upper()
            st.session_state.key_cam_order += 1 # เปลี่ยน Key เพื่อรีเซ็ตกล้อง
            st.rerun()
        else:
            st.warning("อ่านไม่ได้ ถ่ายใหม่")

# กล่องข้อความ (รับค่าจาก State หรือพิมพ์เอง)
order_input = col_o1.text_input("Scan/พิมพ์ Order ID", value=st.session_state.order_val, key="input_order").strip().upper()

# ==========================================
# 2. PRODUCT SCAN
# ==========================================
if order_input:
    # Sync ค่ากลับไปที่ State เผื่อมีการพิมพ์แก้เอง
    st.session_state.order_val = order_input
    
    st.markdown("---")
    st.markdown("#### 2. Scan สินค้า")

    col_p1, col_p2 = st.columns([4, 1])
    with col_p2:
        use_cam_prod = st.checkbox("📷", key="tog_prod")
    
    if use_cam_prod:
        img_file_p = st.camera_input("ถ่าย Barcode สินค้า", key=f"cam_p_{st.session_state.key_cam_prod}")
        if img_file_p:
            res_p = read_barcode_from_image(img_file_p)
            if res_p:
                st.session_state.prod_val = res_p
                st.session_state.key_cam_prod += 1
                st.rerun()
            else:
                st.warning("อ่านไม่ได้ ถ่ายใหม่")

    prod_input = col_p1.text_input("Scan Barcode สินค้า", value=st.session_state.prod_val, key="input_prod").strip()

    # Logic ค้นหาใน Sheet
    target_loc_str = None
    if prod_input:
        if not df_items.empty:
            match = df_items[df_items['Barcode'] == prod_input]
            if not match.empty:
                row = match.iloc[0]
                zone_val = str(row.get('Zone', '')).strip()
                loc_val = str(row.get('Location', '')).strip()
                target_loc_str = f"{zone_val}-{loc_val}"
                prod_name = row.get('Product Name (1 Variant Name1 ( Variant Name2 ( Quotation name', 'Unknown') 
                
                st.success(f"✅ {prod_name}")
                st.info(f"📍 เป้าหมาย: **{target_loc_str}**")
            else:
                st.error(f"❌ ไม่พบ Barcode ใน Sheet")
        else:
             st.warning("⚠️ กำลังโหลดข้อมูล Sheet...")

    # ==========================================
    # 3. LOCATION VERIFY
    # ==========================================
    if prod_input and target_loc_str:
        st.markdown("---")
        st.markdown(f"#### 3. ยืนยัน Location: `{target_loc_str}`")
        
        col_l1, col_l2 = st.columns([4, 1])
        with col_l2:
            use_cam_loc = st.checkbox("📷", key="tog_loc")
            
        if use_cam_loc:
            img_file_l = st.camera_input("ถ่าย Barcode Location", key=f"cam_l_{st.session_state.key_cam_loc}")
            if img_file_l:
                res_l = read_barcode_from_image(img_file_l)
                if res_l:
                    st.session_state.loc_val = res_l.upper()
                    st.session_state.key_cam_loc += 1
                    st.rerun()
                else:
                    st.warning("อ่านไม่ได้ ถ่ายใหม่")

        loc_input_val = col_l1.text_input("Scan Location", value=st.session_state.loc_val, key="input_loc").strip().upper()
        
        valid_loc = False
        if loc_input_val:
            if loc_input_val == target_loc_str:
                st.success("✅ ถูกต้อง!")
                valid_loc = True
            elif loc_input_val in target_loc_str:
                st.warning(f"⚠️ ใกล้เคียง (ยอมรับได้)")
                valid_loc = True
            else:
                st.error(f"❌ ผิดตำแหน่ง (อยู่ที่: {loc_input_val})")

        # ==========================================
        # 4. PACKING & UPLOAD (Multi-Shot)
        # ==========================================
        if valid_loc:
            st.markdown("---")
            st.markdown(f"#### 4. ถ่ายรูปปิดกล่อง ({len(st.session_state.photo_gallery)}/5)")
            
            # Show Gallery
            if st.session_state.photo_gallery:
                cols = st.columns(5)
                for idx, img_data in enumerate(st.session_state.photo_gallery):
                    with cols[idx]:
                        st.image(img_data, caption=f"รูปที่ {idx+1}", use_column_width=True)
                        if st.button("🗑️ ลบ", key=f"del_btn_{idx}"):
                            st.session_state.photo_gallery.pop(idx)
                            st.rerun()
            
            # Camera Input (Pack)
            if len(st.session_state.photo_gallery) < 5:
                cam_key = f"cam_pack_{st.session_state.cam_counter}"
                pack_img = st.camera_input("ถ่ายรูปสินค้า", key=cam_key)
                
                if pack_img:
                    st.session_state.photo_gallery.append(pack_img.getvalue())
                    st.session_state.cam_counter += 1
                    st.rerun()
            else:
                st.info("📷 ครบ 5 รูปแล้ว")

            # Upload Button
            if len(st.session_state.photo_gallery) > 0:
                st.markdown("---")
                if st.button(f"☁️ Upload {len(st.session_state.photo_gallery)} รูป ขึ้น Drive", type="primary"):
                    with st.spinner("กำลังทยอยอัปโหลด..."):
                        srv = authenticate_drive()
                        if srv:
                            fid = create_or_get_order_folder(srv, order_input, MAIN_FOLDER_ID)
                            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                            
                            for i, img_bytes in enumerate(st.session_state.photo_gallery):
                                fn = f"{order_input}_{prod_input}_LOC-{loc_input_val}_{ts}_Img{i+1}.jpg"
                                upload_photo(srv, img_bytes, fn, fid)
                            
                            st.balloons()
                            st.success(f"บันทึกเรียบร้อย!")
                            
                            time.sleep(2) 
                            
                            # Reset All
                            st.session_state.order_val = "" # (จะเคลียร์ Order หรือไม่ แล้วแต่ Logic หน้างาน)
                            st.session_state.prod_val = ""
                            st.session_state.loc_val = ""
                            st.session_state.photo_gallery = [] 
                            st.session_state.cam_counter += 1
                            st.rerun()
