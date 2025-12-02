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

# --- IMPORT LIBRARY กล้อง ---
try:
    from streamlit_back_camera_input import back_camera_input
except ImportError:
    st.error("⚠️ ต้องเพิ่ม 'streamlit-back-camera-input' ใน requirements.txt")
    st.stop()

# --- CONFIGURATION ---
MAIN_FOLDER_ID = '1FHfyzzTzkK5PaKx6oQeFxTbLEq-Tmii7'
SHEET_ID = '1jNlztb3vfG0c8sw_bMTuA9GEqircx_uVE7uywd5dR2I'
LOG_SHEET_NAME = 'Logs'

# --- AUTHENTICATION ---
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

# --- GOOGLE SERVICES ---
@st.cache_data(ttl=600)
def load_sheet_data():
    try:
        creds = get_credentials()
        if not creds: return pd.DataFrame()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        worksheet = sh.get_worksheet(0)
        
        rows = worksheet.get_all_values()
        if len(rows) > 1:
            headers = rows[0]
            data = rows[1:]
            df = pd.DataFrame(data, columns=headers)
            if 'Barcode' in df.columns:
                df['Barcode'] = df['Barcode'].astype(str).str.replace(r'\.0$', '', regex=True)
            return df
        return pd.DataFrame()
    except Exception as e:
        print(f"Sheet Error: {e}")
        return pd.DataFrame()

# --- ฟังก์ชันบันทึก Log (เพิ่ม Pick Qty) ---
def save_log_to_sheet(order_id, barcode, prod_name, location, pick_qty, user_id, user_name, file_id):
    try:
        creds = get_credentials()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        
        try:
            worksheet = sh.worksheet(LOG_SHEET_NAME)
        except:
            # สร้าง Sheet ใหม่พร้อม Header (เพิ่ม Pick Qty)
            worksheet = sh.add_worksheet(title=LOG_SHEET_NAME, rows="1000", cols="10")
            worksheet.append_row(["Timestamp", "Order ID", "Barcode", "Product Name", "Location", "Pick Qty", "User ID", "Name", "Image ID"])
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # บันทึกข้อมูล
        worksheet.append_row([
            timestamp, 
            order_id, 
            barcode, 
            prod_name, 
            location, 
            pick_qty,   # เพิ่ม Pick Qty
            user_id,
            user_name,
            file_id
        ])
        print("Log saved.")
    except Exception as e:
        st.warning(f"⚠️ บันทึก Log ไม่สำเร็จ: {e}")

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

def reset_all_data():
    st.session_state.order_val = ""
    st.session_state.prod_val = ""
    st.session_state.loc_val = ""
    st.session_state.prod_display_name = ""
    st.session_state.current_pick_qty = "" # Reset Qty
    st.session_state.photo_gallery = []
    st.session_state.cam_counter += 1

# --- UI SETUP ---
st.set_page_config(page_title="Smart Picking (Pro Max)", page_icon="📦")

# Init Session State
if 'order_val' not in st.session_state: st.session_state.order_val = ""
if 'prod_val' not in st.session_state: st.session_state.prod_val = ""
if 'loc_val' not in st.session_state: st.session_state.loc_val = ""
if 'prod_display_name' not in st.session_state: st.session_state.prod_display_name = ""
if 'current_pick_qty' not in st.session_state: st.session_state.current_pick_qty = ""
if 'photo_gallery' not in st.session_state: st.session_state.photo_gallery = []
if 'cam_counter' not in st.session_state: st.session_state.cam_counter = 0

# --- SIDEBAR: ข้อมูลพนักงาน (เพิ่มสแกน) ---
with st.sidebar:
    st.title("👤 ข้อมูลพนักงาน")
    
    # Checkbox เปิดกล้องสำหรับ User ID
    use_cam_user = st.checkbox("📷 สแกนรหัสพนักงาน", key="tog_user_scan")
    
    if use_cam_user:
        # กล้องสแกน User ID
        scan_user = back_camera_input("สแกนบัตรพนักงาน", key="cam_user_input")
        if scan_user:
            res_u = decode(Image.open(scan_user))
            if res_u:
                # บันทึกค่าลง Session State ของ text_input
                st.session_state.user_id_input = res_u[0].data.decode("utf-8")
                st.rerun()

    # ช่องกรอกข้อมูล (จะอัปเดตอัตโนมัติถ้าสแกนผ่านกล้อง)
    user_id = st.text_input("รหัสพนักงาน (User ID)", key="user_id_input").strip()
    user_name = st.text_input("ชื่อ-นามสกุล (Name)", key="user_name_input").strip()
    
    if user_id and user_name:
        st.success(f"Logon: {user_name}")
    else:
        st.warning("🔴 กรุณาระบุตัวตน")

# --- MAIN CONTENT ---
st.title("📦 ระบบเบิกสินค้า")
df_items = load_sheet_data()

# 1. ORDER
st.markdown("#### 1. Order ID")
if not st.session_state.order_val:
    col1, col2 = st.columns([3, 1])
    manual_order = col1.text_input("พิมพ์ Order ID", key="input_order_manual").strip().upper()
    if manual_order:
        st.session_state.order_val = manual_order
        st.rerun()
    
    cam_key = f"cam_order_{st.session_state.cam_counter}"
    scan_order = back_camera_input("แตะเพื่อสแกน Order", key=cam_key)
    if scan_order:
        res = decode(Image.open(scan_order))
        if res:
            st.session_state.order_val = res[0].data.decode("utf-8").upper()
            st.rerun()
else:
    st.success(f"📦 Order: **{st.session_state.order_val}**")
    if st.button("✏️ แก้ไข Order"):
        st.session_state.order_val = ""
        st.rerun()

# 2. PRODUCT
if st.session_state.order_val:
    st.markdown("---")
    st.markdown("#### 2. Scan สินค้า")
    
    if not st.session_state.prod_val:
        col1, col2 = st.columns([3, 1])
        manual_prod = col1.text_input("พิมพ์ Barcode", key="input_prod_manual").strip()
        if manual_prod:
            st.session_state.prod_val = manual_prod
            st.rerun()

        cam_key_prod = f"cam_prod_{st.session_state.cam_counter}"
        scan_prod = back_camera_input("แตะเพื่อสแกนสินค้า", key=cam_key_prod)
        if scan_prod:
            res_p = decode(Image.open(scan_prod))
            if res_p:
                st.session_state.prod_val = res_p[0].data.decode("utf-8")
                st.rerun()
    else:
        target_loc_str = None
        prod_found = False
        pick_qty_val = "-"
        
        if not df_items.empty:
            match = df_items[df_items['Barcode'] == st.session_state.prod_val]
            if not match.empty:
                prod_found = True
                row = match.iloc[0]
                
                try:
                    brand_name = str(row.iloc[3]) 
                    variant_name = str(row.iloc[5])
                    full_prod_name = f"{brand_name} {variant_name}"
                    
                    # ดึงจำนวนที่ต้องหยิบ (QTY) - เช็คชื่อ Column ว่าเป็น 'QTY' หรือ 'Qty' หรือ Index 8
                    # เพื่อความชัวร์ ใช้ .get ถ้ามีหัวตาราง หรือ iloc ถ้าฟิกตำแหน่ง
                    pick_qty_val = str(row.get('QTY', row.get('Qty', row.iloc[8] if len(row) > 8 else '-')))
                except:
                    full_prod_name = "Error reading data"
                    pick_qty_val = "-"

                st.session_state.prod_display_name = full_prod_name
                st.session_state.current_pick_qty = pick_qty_val
                
                zone_val = str(row.get('Zone', '')).strip()
                loc_val = str(row.get('Location', '')).strip()
                target_loc_str = f"{zone_val}-{loc_val}"
                
                # แสดงผลข้อมูล
                st.success(f"✅ สินค้า: **{full_prod_name}**")
                
                c_info1, c_info2 = st.columns(2)
                with c_info1:
                    st.warning(f"📍 Location: **{target_loc_str}**")
                with c_info2:
                    st.info(f"🔢 จำนวนที่ต้องหยิบ: **{pick_qty_val}**")
                    
            else:
                st.error(f"❌ ไม่พบ Barcode: {st.session_state.prod_val}")
        else:
             st.warning("⚠️ Loading Data...")

        if st.button("✏️ สแกนใหม่"):
            st.session_state.prod_val = ""
            st.session_state.loc_val = ""
            st.session_state.current_pick_qty = ""
            st.rerun()

        # 3. LOCATION
        if prod_found and target_loc_str:
            st.markdown("---")
            st.markdown(f"#### 3. ยืนยัน Location")
            
            if not st.session_state.loc_val:
                manual_loc = st.text_input("Scan/พิมพ์ Location", key="input_loc_manual").strip().upper()
                if manual_loc:
                    st.session_state.loc_val = manual_loc
                    st.rerun()
                cam_key_loc = f"cam_loc_{st.session_state.cam_counter}"
                scan_loc = back_camera_input("แตะเพื่อสแกน Location", key=cam_key_loc)
                if scan_loc:
                    res_l = decode(Image.open(scan_loc))
                    if res_l:
                        st.session_state.loc_val = res_l[0].data.decode("utf-8").upper()
                        st.rerun()
            else:
                valid_loc = False
                if st.session_state.loc_val == target_loc_str:
                    st.success(f"✅ Location ถูกต้อง: {st.session_state.loc_val}")
                    valid_loc = True
                elif st.session_state.loc_val in target_loc_str:
                    st.warning(f"⚠️ ใกล้เคียง: {st.session_state.loc_val}")
                    valid_loc = True
                else:
                    st.error(f"❌ ผิดตำแหน่ง ({st.session_state.loc_val})")
                    if st.button("แก้ Location"):
                        st.session_state.loc_val = ""
                        st.rerun()

                # 4. PACK & UPLOAD
                if valid_loc:
                    st.markdown("---")
                    st.markdown(f"#### 4. ถ่ายรูป ({len(st.session_state.photo_gallery)}/5)")
                    
                    if st.session_state.photo_gallery:
                        cols = st.columns(5)
                        for idx, img_data in enumerate(st.session_state.photo_gallery):
                            with cols[idx]:
                                st.image(img_data, use_column_width=True)
                                if st.button("🗑️", key=f"del_{idx}"):
                                    st.session_state.photo_gallery.pop(idx)
                                    st.rerun()
                    
                    if len(st.session_state.photo_gallery) < 5:
                        pack_img = st.camera_input("ถ่ายรูปสินค้า", key=f"cam_pack_{st.session_state.cam_counter}")
                        if pack_img:
                            st.session_state.photo_gallery.append(pack_img.getvalue())
                            st.session_state.cam_counter += 1
                            st.rerun()

                    if len(st.session_state.photo_gallery) > 0:
                        st.markdown("---")
                        # ปุ่ม Upload
                        if st.button(f"☁️ Upload & Save Log", type="primary", use_container_width=True):
                            if not user_id or not user_name:
                                st.error("🚨 กรุณาระบุ 'รหัสพนักงาน' และ 'ชื่อ' ที่เมนูซ้ายมือก่อน")
                            else:
                                with st.spinner("กำลังบันทึกข้อมูล..."):
                                    srv = authenticate_drive()
                                    if srv:
                                        fid = create_or_get_order_folder(srv, st.session_state.order_val, MAIN_FOLDER_ID)
                                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                                        
                                        first_file_id = "" 
                                        
                                        for i, img_bytes in enumerate(st.session_state.photo_gallery):
                                            fn = f"{st.session_state.order_val}_{st.session_state.prod_val}_LOC-{st.session_state.loc_val}_{ts}_Img{i+1}.jpg"
                                            upl_id = upload_photo(srv, img_bytes, fn, fid)
                                            if i == 0: first_file_id = upl_id 
                                        
                                        # บันทึก Log พร้อม Pick Qty
                                        save_log_to_sheet(
                                            st.session_state.order_val,
                                            st.session_state.prod_val,
                                            st.session_state.prod_display_name,
                                            st.session_state.loc_val,
                                            st.session_state.current_pick_qty, # ค่า QTY ที่ดึงมา
                                            user_id,
                                            user_name,
                                            first_file_id
                                        )
                                        
                                        st.balloons()
                                        st.success("บันทึกเสร็จสิ้น!")
                                        time.sleep(2)
                                        reset_all_data()
                                        st.rerun()

st.markdown("---")
if st.button("🔄 เริ่มใหม่ทั้งหมด", type="secondary", use_container_width=True):
    reset_all_data()
    st.rerun()
