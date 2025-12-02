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
USER_SHEET_NAME = 'User'

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
def load_sheet_data(sheet_name=0):
    try:
        creds = get_credentials()
        if not creds: return pd.DataFrame()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        
        if isinstance(sheet_name, int):
            worksheet = sh.get_worksheet(sheet_name)
        else:
            worksheet = sh.worksheet(sheet_name)

        rows = worksheet.get_all_values()
        if len(rows) > 1:
            headers = rows[0]
            data = rows[1:]
            df = pd.DataFrame(data, columns=headers)
            
            # Clean Data
            for col in df.columns:
                if 'Barcode' in col or 'ID' in col: 
                    df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True)
            return df
        return pd.DataFrame()
    except Exception as e:
        print(f"Sheet Error ({sheet_name}): {e}")
        return pd.DataFrame()

# --- FOLDER MANAGEMENT ---
def create_folder_structure(service, order_id, parent_id):
    # 1. Folder Date (DD-MM-YYYY)
    date_folder_name = datetime.now().strftime("%d-%m-%Y")
    query_date = f"name = '{date_folder_name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query_date, fields="files(id)").execute()
    files = results.get('files', [])
    
    if files:
        date_folder_id = files[0]['id']
    else:
        file_metadata = {'name': date_folder_name, 'parents': [parent_id], 'mimeType': 'application/vnd.google-apps.folder'}
        folder = service.files().create(body=file_metadata, fields='id').execute()
        date_folder_id = folder.get('id')

    # 2. Folder Order (Order_HH-MM)
    time_suffix = datetime.now().strftime("%H-%M")
    sub_folder_name = f"{order_id}_{time_suffix}"
    
    file_metadata_sub = {
        'name': sub_folder_name, 
        'parents': [date_folder_id], 
        'mimeType': 'application/vnd.google-apps.folder'
    }
    sub_folder = service.files().create(body=file_metadata_sub, fields='id, webViewLink').execute()
    
    return sub_folder.get('id'), sub_folder.get('webViewLink')

def upload_photo(service, file_obj, filename, folder_id):
    try:
        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(file_obj), mimetype='image/jpeg')
        service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    except Exception as e:
        st.error(f"🔴 Upload Error: {e}")
        raise e

# --- LOGGING (แก้ไขบันทึก Pick Qty จริง) ---
def save_log_to_sheet(timestamp, order_id, barcode, prod_name, location, actual_qty, user_id, user_name, folder_link):
    try:
        creds = get_credentials()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        
        try:
            worksheet = sh.worksheet(LOG_SHEET_NAME)
        except:
            worksheet = sh.add_worksheet(title=LOG_SHEET_NAME, rows="1000", cols="10")
            worksheet.append_row(["Timestamp", "Order ID", "Barcode", "Product Name", "Location", "Pick Qty", "User ID", "Name", "Images File"])
            
        row_data = [
            timestamp,      # A
            order_id,       # B
            barcode,        # C
            prod_name,      # D
            location,       # E
            str(actual_qty),# F (บันทึกค่าจริงที่กรอก)
            user_id,        # G
            user_name,      # H
            folder_link     # I
        ]
        
        worksheet.append_row(row_data)
        print("Log saved successfully.")
    except Exception as e:
        st.warning(f"⚠️ บันทึก Log ไม่สำเร็จ: {e}")

def reset_all_data():
    st.session_state.order_val = ""
    st.session_state.prod_val = ""
    st.session_state.loc_val = ""
    st.session_state.prod_display_name = ""
    st.session_state.master_qty = 0    # Reset ค่า Target
    st.session_state.actual_qty = 0    # Reset ค่าจริง
    st.session_state.photo_gallery = []
    st.session_state.cam_counter += 1

def logout_user():
    st.session_state.current_user_name = ""
    st.session_state.current_user_id = ""
    reset_all_data()
    st.rerun()

# --- UI SETUP ---
st.set_page_config(page_title="Smart Picking (Edit Qty)", page_icon="📦")

# Init Session State
if 'current_user_name' not in st.session_state: st.session_state.current_user_name = ""
if 'current_user_id' not in st.session_state: st.session_state.current_user_id = ""
if 'order_val' not in st.session_state: st.session_state.order_val = ""
if 'prod_val' not in st.session_state: st.session_state.prod_val = ""
if 'loc_val' not in st.session_state: st.session_state.loc_val = ""
if 'prod_display_name' not in st.session_state: st.session_state.prod_display_name = ""
if 'master_qty' not in st.session_state: st.session_state.master_qty = 0 # จำนวนจากระบบ
if 'actual_qty' not in st.session_state: st.session_state.actual_qty = 0 # จำนวนหยิบจริง
if 'photo_gallery' not in st.session_state: st.session_state.photo_gallery = []
if 'cam_counter' not in st.session_state: st.session_state.cam_counter = 0

# --- PART 1: LOGIN ---
if not st.session_state.current_user_name:
    st.title("🔐 Login พนักงาน")
    df_users = load_sheet_data(USER_SHEET_NAME)
    
    col1, col2 = st.columns([3, 1])
    manual_user = col1.text_input("พิมพ์รหัสพนักงาน", key="input_user_manual").strip()
    
    cam_key_user = f"cam_user_{st.session_state.cam_counter}"
    scan_user = back_camera_input("แตะเพื่อสแกนบัตรพนักงาน", key=cam_key_user)
    
    user_input_val = None
    if manual_user: user_input_val = manual_user
    elif scan_user:
        res_u = decode(Image.open(scan_user))
        if res_u: user_input_val = res_u[0].data.decode("utf-8")
    
    if user_input_val:
        if not df_users.empty:
            match = df_users[df_users.iloc[:, 0].astype(str) == str(user_input_val)]
            if not match.empty:
                found_name = match.iloc[0, 2]
                st.session_state.current_user_id = user_input_val
                st.session_state.current_user_name = found_name
                st.toast(f"ยินดีต้อนรับ {found_name}", icon="✅")
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"❌ ไม่พบรหัส: {user_input_val}")
        else:
            st.warning("⚠️ โหลดข้อมูลพนักงานไม่ได้")

# --- PART 2: OPERATION ---
else:
    c1, c2 = st.columns([3, 1])
    with c1:
        st.caption(f"👤: **{st.session_state.current_user_name}** ({st.session_state.current_user_id})")
    with c2:
        if st.button("Logout", type="secondary"):
            logout_user()

    df_items = load_sheet_data(0)

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
            
            if not df_items.empty:
                match = df_items[df_items['Barcode'] == st.session_state.prod_val]
                if not match.empty:
                    prod_found = True
                    row = match.iloc[0]
                    
                    # ข้อมูลสินค้า
                    try:
                        brand_name = str(row.iloc[3]) 
                        variant_name = str(row.iloc[5])
                        full_prod_name = f"{brand_name} {variant_name}"
                        
                        # ดึง QTY จาก Master
                        master_qty_str = str(row.get('QTY', row.iloc[8])).strip()
                        # พยายามแปลงเป็น int
                        try:
                            master_qty_int = int(float(master_qty_str))
                        except:
                            master_qty_int = 1 # ถ้าแปลงไม่ได้ให้ default เป็น 1
                            
                    except:
                        full_prod_name = "Error reading"
                        master_qty_int = 1

                    st.session_state.prod_display_name = full_prod_name
                    st.session_state.master_qty = master_qty_int # เก็บไว้เทียบ
                    
                    # ถ้ายังไม่ได้กำหนดค่าจริง ให้เริ่มต้นเท่ากับ Master
                    if st.session_state.actual_qty == 0:
                        st.session_state.actual_qty = master_qty_int

                    zone_val = str(row.get('Zone', '')).strip()
                    loc_val = str(row.get('Location', '')).strip()
                    target_loc_str = f"{zone_val}-{loc_val}"
                    
                    # แสดงผล
                    st.success(f"✅ {full_prod_name}")
                    
                    c_info1, c_info2 = st.columns(2)
                    c_info1.warning(f"📍 เป้าหมาย: **{target_loc_str}**")
                    c_info2.info(f"🔢 ต้องหยิบ: **{st.session_state.master_qty}**")
                    
                    # --- ส่วนกรอกจำนวนหยิบจริง ---
                    st.markdown("👇 **ระบุจำนวนที่หยิบจริง (Actual Qty)**")
                    actual_input = st.number_input("จำนวนที่หยิบได้จริง", min_value=1, value=st.session_state.actual_qty, key="num_input_actual")
                    # อัปเดตค่าเข้า Session State
                    st.session_state.actual_qty = actual_input
                    
                else:
                    st.error(f"❌ ไม่พบ Barcode: {st.session_state.prod_val}")
            else:
                 st.warning("⚠️ Loading Data...")

            if st.button("✏️ สแกนใหม่"):
                st.session_state.prod_val = ""
                st.session_state.loc_val = ""
                st.session_state.actual_qty = 0 # reset
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
                        st.success(f"✅ ถูกต้อง: {st.session_state.loc_val}")
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
                            # แสดงสรุปก่อนบันทึก
                            st.caption(f"กำลังจะบันทึกยอดหยิบจริง: **{st.session_state.actual_qty}** ชิ้น")
                            
                            if st.button(f"☁️ Upload & Save Log", type="primary", use_container_width=True):
                                with st.spinner("กำลังบันทึกข้อมูล..."):
                                    srv = authenticate_drive()
                                    if srv:
                                        folder_id, folder_link = create_folder_structure(srv, st.session_state.order_val, MAIN_FOLDER_ID)
                                        
                                        ts_name = datetime.now().strftime("%Y%m%d_%H%M%S")
                                        for i, img_bytes in enumerate(st.session_state.photo_gallery):
                                            fn = f"Img{i+1}_{st.session_state.order_val}_{ts_name}.jpg"
                                            upload_photo(srv, img_bytes, fn, folder_id)
                                        
                                        timestamp_log = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                        # ส่ง st.session_state.actual_qty ไปบันทึก
                                        save_log_to_sheet(
                                            timestamp=timestamp_log,
                                            order_id=st.session_state.order_val,
                                            barcode=st.session_state.prod_val,
                                            prod_name=st.session_state.prod_display_name,
                                            location=st.session_state.loc_val,
                                            actual_qty=st.session_state.actual_qty, # ใช้ค่าจริง
                                            user_id=st.session_state.current_user_id,
                                            user_name=st.session_state.current_user_name,
                                            folder_link=folder_link
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
