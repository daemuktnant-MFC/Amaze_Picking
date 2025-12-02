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

# --- IMPORT LIBRARY กล้องตัวพิเศษ (ช่วยเรื่องโฟกัส) ---
# ถ้ายังไม่แก้ requirements.txt จะ error บรรทัดนี้
try:
    from streamlit_back_camera_input import back_camera_input
except ImportError:
    st.error("⚠️ กรุณาเพิ่ม 'streamlit-back-camera-input' ในไฟล์ requirements.txt")
    st.stop()

# --- CONFIGURATION ---
MAIN_FOLDER_ID = '1FHfyzzTzkK5PaKx6oQeFxTbLEq-Tmii7'
SHEET_ID = '1jNlztb3vfG0c8sw_bMTuA9GEqircx_uVE7uywd5dR2I'

# --- HELPER & AUTH FUNCTIONS (คงเดิม) ---
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
        print(f"Sheet Error: {e}")
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
    try:
        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(file_obj), mimetype='image/jpeg')
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file.get('id')
    except Exception as e:
        st.error(f"🔴 Upload Error: {e}")
        raise e

# --- ฟังก์ชัน Reset (แก้ Error Session State) ---
def reset_all_data():
    st.session_state.order_val = ""
    st.session_state.prod_val = ""
    st.session_state.loc_val = ""
    st.session_state.photo_gallery = []
    st.session_state.cam_counter += 1
    # ไม่ต้องลบ key widget โดยตรง ปล่อยให้ Rerun จัดการ

# --- UI SETUP ---
st.set_page_config(page_title="Smart Picking (Pro)", page_icon="📦")

if 'order_val' not in st.session_state: st.session_state.order_val = ""
if 'prod_val' not in st.session_state: st.session_state.prod_val = ""
if 'loc_val' not in st.session_state: st.session_state.loc_val = ""
if 'photo_gallery' not in st.session_state: st.session_state.photo_gallery = []
if 'cam_counter' not in st.session_state: st.session_state.cam_counter = 0

st.title("📦 ระบบเบิกสินค้า (Auto Focus)")
df_items = load_sheet_data()

# ==========================================
# 1. ORDER ID
# ==========================================
st.markdown("#### 1. Order ID")

# ถ้ายังไม่มีข้อมูล Order -> โชว์ช่องกรอกและกล้อง
if not st.session_state.order_val:
    col1, col2 = st.columns([3, 1])
    
    # ช่องกรอก Manual (ใส่ on_change ไม่ได้ใน logic นี้ ใช้เช็คค่าเอา)
    manual_order = col1.text_input("พิมพ์ Order ID แล้วกด Enter", key="input_order_manual").strip().upper()
    if manual_order:
        st.session_state.order_val = manual_order
        st.rerun()

    # กล้อง (ใช้ back_camera_input เพื่อโฟกัส)
    # ใส่ key ให้เปลี่ยนไปเรื่อยๆ เพื่อรีเซ็ตกล้อง
    cam_key = f"cam_order_{st.session_state.cam_counter}"
    scan_order = back_camera_input("แตะเพื่อเปิดกล้องสแกน Order", key=cam_key)
    
    if scan_order:
        res = decode(Image.open(scan_order))
        if res:
            st.session_state.order_val = res[0].data.decode("utf-8").upper()
            st.rerun()

# ถ้ามีข้อมูล Order แล้ว -> โชว์ผลลัพธ์ และปุ่มแก้ไข (ซ่อนกล้อง)
else:
    st.success(f"📦 Order: **{st.session_state.order_val}**")
    if st.button("✏️ แก้ไข Order"):
        st.session_state.order_val = ""
        st.rerun()

# ==========================================
# 2. PRODUCT SCAN (จะโชว์เมื่อมี Order แล้ว)
# ==========================================
if st.session_state.order_val:
    st.markdown("---")
    st.markdown("#### 2. Scan สินค้า")
    
    # ถ้ายังไม่มีสินค้า -> โชว์กล้อง
    if not st.session_state.prod_val:
        col1, col2 = st.columns([3, 1])
        
        # ช่องกรอก Manual
        manual_prod = col1.text_input("พิมพ์ Barcode สินค้า แล้วกด Enter", key="input_prod_manual").strip()
        if manual_prod:
            st.session_state.prod_val = manual_prod
            st.rerun()

        # กล้อง
        cam_key_prod = f"cam_prod_{st.session_state.cam_counter}"
        scan_prod = back_camera_input("แตะเพื่อเปิดกล้องสแกนสินค้า", key=cam_key_prod)
        
        if scan_prod:
            res_p = decode(Image.open(scan_prod))
            if res_p:
                st.session_state.prod_val = res_p[0].data.decode("utf-8")
                st.rerun()
                
    # ถ้ามีสินค้าแล้ว -> โชว์รายละเอียด และไปขั้นตอนถัดไป
    else:
        # ตรวจสอบข้อมูลใน Sheet
        target_loc_str = None
        prod_found = False
        
        if not df_items.empty:
            match = df_items[df_items['Barcode'] == st.session_state.prod_val]
            if not match.empty:
                prod_found = True
                row = match.iloc[0]
                zone_val = str(row.get('Zone', '')).strip()
                loc_val = str(row.get('Location', '')).strip()
                target_loc_str = f"{zone_val}-{loc_val}"
                prod_name = row.get('Product Name (1 Variant Name1 ( Variant Name2 ( Quotation name', 'Unknown')
                
                st.info(f"✅ สินค้า: {prod_name}")
                st.warning(f"📍 เป้าหมายเก็บ: **{target_loc_str}**")
            else:
                st.error(f"❌ ไม่พบ Barcode: {st.session_state.prod_val}")
        else:
             st.warning("⚠️ กำลังโหลดฐานข้อมูลสินค้า...")

        # ปุ่มสแกนใหม่
        if st.button("✏️ สแกนสินค้าใหม่"):
            st.session_state.prod_val = ""
            st.session_state.loc_val = "" # ล้าง Location ด้วยถ้าเปลี่ยนสินค้า
            st.rerun()

        # ==========================================
        # 3. LOCATION VERIFY (โชว์เมื่อเจอสินค้าถูกต้อง)
        # ==========================================
        if prod_found and target_loc_str:
            st.markdown("---")
            st.markdown(f"#### 3. ยืนยัน Location")
            
            if not st.session_state.loc_val:
                manual_loc = st.text_input("สแกน/พิมพ์ Location", key="input_loc_manual").strip().upper()
                if manual_loc:
                    st.session_state.loc_val = manual_loc
                    st.rerun()
                    
                cam_key_loc = f"cam_loc_{st.session_state.cam_counter}"
                scan_loc = back_camera_input("แตะเพื่อเปิดกล้องสแกน Location", key=cam_key_loc)
                if scan_loc:
                    res_l = decode(Image.open(scan_loc))
                    if res_l:
                        st.session_state.loc_val = res_l[0].data.decode("utf-8").upper()
                        st.rerun()
            else:
                # ตรวจสอบความถูกต้อง
                valid_loc = False
                if st.session_state.loc_val == target_loc_str:
                    st.success(f"✅ Location ถูกต้อง: {st.session_state.loc_val}")
                    valid_loc = True
                elif st.session_state.loc_val in target_loc_str:
                    st.warning(f"⚠️ ใกล้เคียง: {st.session_state.loc_val} (ยอมรับได้)")
                    valid_loc = True
                else:
                    st.error(f"❌ ผิดตำแหน่ง (คุณอยู่ที่: {st.session_state.loc_val})")
                    if st.button("สแกน Location ใหม่"):
                        st.session_state.loc_val = ""
                        st.rerun()

                # ==========================================
                # 4. PACKING & UPLOAD
                # ==========================================
                if valid_loc:
                    st.markdown("---")
                    st.markdown(f"#### 4. ถ่ายรูปปิดกล่อง ({len(st.session_state.photo_gallery)}/5)")
                    
                    # Gallery
                    if st.session_state.photo_gallery:
                        cols = st.columns(5)
                        for idx, img_data in enumerate(st.session_state.photo_gallery):
                            with cols[idx]:
                                st.image(img_data, caption=f"รูป {idx+1}", use_column_width=True)
                                if st.button("🗑️", key=f"del_{idx}"):
                                    st.session_state.photo_gallery.pop(idx)
                                    st.rerun()
                    
                    # กล้องถ่ายรูป (ใช้ Camera ธรรมดาได้เพราะถ่ายภาพรวม ไม่ต้องมาโคร)
                    # หรือจะใช้ back_camera ก็ได้ถ้าอยากได้ชัดๆ
                    if len(st.session_state.photo_gallery) < 5:
                        pack_img = st.camera_input("ถ่ายรูปสินค้า", key=f"cam_pack_{st.session_state.cam_counter}")
                        if pack_img:
                            st.session_state.photo_gallery.append(pack_img.getvalue())
                            st.session_state.cam_counter += 1
                            st.rerun()

                    # ปุ่ม Upload
                    if len(st.session_state.photo_gallery) > 0:
                        st.markdown("---")
                        if st.button(f"☁️ Upload {len(st.session_state.photo_gallery)} รูป", type="primary", use_container_width=True):
                            with st.spinner("กำลังอัปโหลด..."):
                                srv = authenticate_drive()
                                if srv:
                                    fid = create_or_get_order_folder(srv, st.session_state.order_val, MAIN_FOLDER_ID)
                                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                                    
                                    for i, img_bytes in enumerate(st.session_state.photo_gallery):
                                        fn = f"{st.session_state.order_val}_{st.session_state.prod_val}_LOC-{st.session_state.loc_val}_{ts}_Img{i+1}.jpg"
                                        upload_photo(srv, img_bytes, fn, fid)
                                    
                                    st.balloons()
                                    st.success("บันทึกสำเร็จ!")
                                    time.sleep(2)
                                    reset_all_data()
                                    st.rerun()

# ปุ่ม Reset ล่างสุด
st.markdown("---")
if st.button("🔄 เริ่มใหม่ทั้งหมด", type="secondary", use_container_width=True):
    reset_all_data()
    st.rerun()
