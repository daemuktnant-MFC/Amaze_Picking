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

def authenticate_drive():
    try:
        creds = get_credentials()
        if creds: return build('drive', 'v3', credentials=creds)
        return None
    except Exception as e:
        st.error(f"Error Drive: {e}")
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
            
            for col in df.columns:
                if 'Barcode' in col or 'ID' in col: 
                    df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True)
            return df
        return pd.DataFrame()
    except Exception as e:
        print(f"Sheet Error ({sheet_name}): {e}")
        return pd.DataFrame()

def save_log_to_sheet(picker_name, order_id, barcode, prod_name, location, pick_qty, file_id):
    try:
        creds = get_credentials()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        
        try:
            worksheet = sh.worksheet(LOG_SHEET_NAME)
        except:
            worksheet = sh.add_worksheet(title=LOG_SHEET_NAME, rows="1000", cols="20")
            # Header
            worksheet.append_row([
                "Timestamp", "Picker Name", "Order ID", "Barcode", "Product Name", "Location", 
                "Pick Qty", "Reserved", "Image Link (Col I)"
            ])
            
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # สร้าง Link รูปภาพ
        image_link = f"https://drive.google.com/open?id={file_id}"
        
        # จัดเรียงข้อมูลลง Column A ถึง I (9 ช่อง)
        # G = Pick Qty, I = Image Link
        row_data = [
            timestamp, 
            picker_name, 
            order_id, 
            barcode, 
            prod_name, 
            location, 
            pick_qty, # Col G
            "",       # Col H (Reserved)
            image_link # Col I
        ]
        
        worksheet.append_row(row_data)
        print("Log saved.")
    except Exception as e:
        st.warning(f"⚠️ บันทึก Log ไม่สำเร็จ: {e}")

# ==============================================================================
# 🔒 CRITICAL SECTION: FOLDER STRUCTURE (LOCKED)
# ==============================================================================
# Structure: Main > "dd-mm-yyyy" > "Order_HH-MM" > Images
# ==============================================================================
def get_target_folder_structure(service, order_id, main_parent_id):
    # 1. จัดการ Folder วันที่ (dd-mm-yyyy)
    date_folder_name = datetime.now().strftime("%d-%m-%Y")
    
    # ค้นหาว่ามี Folder วันนี้หรือยัง
    q_date = f"name = '{date_folder_name}' and '{main_parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    res_date = service.files().list(q=q_date, fields="files(id)").execute()
    files_date = res_date.get('files', [])
    
    if files_date:
        date_folder_id = files_date[0]['id']
    else:
        # สร้างใหม่ถ้ายังไม่มี
        meta_date = {
            'name': date_folder_name,
            'parents': [main_parent_id],
            'mimeType': 'application/vnd.google-apps.folder'
        }
        date_folder = service.files().create(body=meta_date, fields='id').execute()
        date_folder_id = date_folder.get('id')
        
    # 2. จัดการ Folder Order_HH-MM (ข้างใน Folder วันที่)
    time_suffix = datetime.now().strftime("%H-%M")
    order_folder_name = f"{order_id}_{time_suffix}"
    
    meta_order = {
        'name': order_folder_name,
        'parents': [date_folder_id], 
        'mimeType': 'application/vnd.google-apps.folder'
    }
    order_folder = service.files().create(body=meta_order, fields='id').execute()
    
    return order_folder.get('id')
# ==============================================================================
# END CRITICAL SECTION
# ==============================================================================

def upload_photo(service, file_obj, filename, folder_id):
    try:
        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(file_obj), mimetype='image/jpeg')
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file.get('id')
    except Exception as e:
        st.error(f"🔴 Upload Error: {e}")
        raise e

# --- RESET FUNCTIONS ---
def reset_for_next_item():
    """รีเซ็ตเฉพาะส่วนสินค้า เพื่อให้สแกนชิ้นต่อไปใน Order เดิมได้เลย"""
    st.session_state.prod_val = ""
    st.session_state.loc_val = ""
    st.session_state.prod_display_name = ""
    st.session_state.photo_gallery = []
    st.session_state.pick_qty = 1 # รีเซ็ตจำนวนกลับเป็น 1
    st.session_state.cam_counter += 1

def reset_all_data():
    """รีเซ็ตทั้งหมดเพื่อเริ่ม Order ใหม่"""
    st.session_state.order_val = ""
    reset_for_next_item()

def logout_user():
    st.session_state.current_user_name = ""
    st.session_state.current_user_id = ""
    reset_all_data()
    st.rerun()

# --- UI SETUP ---
st.set_page_config(page_title="Smart Picking System", page_icon="📦")

if 'current_user_name' not in st.session_state: st.session_state.current_user_name = ""
if 'current_user_id' not in st.session_state: st.session_state.current_user_id = ""
if 'order_val' not in st.session_state: st.session_state.order_val = ""
if 'prod_val' not in st.session_state: st.session_state.prod_val = ""
if 'loc_val' not in st.session_state: st.session_state.loc_val = ""
if 'prod_display_name' not in st.session_state: st.session_state.prod_display_name = ""
if 'photo_gallery' not in st.session_state: st.session_state.photo_gallery = []
if 'cam_counter' not in st.session_state: st.session_state.cam_counter = 0
if 'pick_qty' not in st.session_state: st.session_state.pick_qty = 1 # Default qty

# --- PART 1: LOGIN ---
if not st.session_state.current_user_name:
    st.title("🔐 Login พนักงาน")
    st.info(f"กรุณาสแกนรหัสพนักงาน")
    
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
                st.toast(f"ยินดีต้อนรับคุณ {found_name} 👋", icon="✅")
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"❌ ไม่พบรหัสพนักงาน: {user_input_val}")
        else:
            st.warning("⚠️ โหลดข้อมูลพนักงานไม่ได้")

# --- PART 2: SYSTEM ---
else:
    c1, c2 = st.columns([3, 1])
    with c1:
        st.title("📦 ระบบเบิกสินค้า")
        st.caption(f"👤 ผู้ใช้งาน: **{st.session_state.current_user_name}**")
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
        # แสดง Order ปัจจุบัน และปุ่มเปลี่ยน Order
        col_ord_1, col_ord_2 = st.columns([3, 1])
        with col_ord_1:
            st.success(f"📦 Order: **{st.session_state.order_val}**")
        with col_ord_2:
            if st.button("เปลี่ยน Order / จบงาน", type="secondary"):
                reset_all_data()
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
                    try:
                        brand_name = str(row.iloc[3]) 
                        variant_name = str(row.iloc[5])
                        full_prod_name = f"{brand_name} {variant_name}"
                    except:
                        full_prod_name = "Error reading columns"

                    st.session_state.prod_display_name = full_prod_name
                    zone_val = str(row.get('Zone', '')).strip()
                    loc_val = str(row.get('Location', '')).strip()
                    target_loc_str = f"{zone_val}-{loc_val}"
                    
                    st.success(f"✅ พบข้อมูล: **{full_prod_name}**")
                    st.warning(f"📍 เป้าหมายเก็บ: **{target_loc_str}**")
                else:
                    st.error(f"❌ ไม่พบ Barcode: {st.session_state.prod_val}")
            else:
                 st.warning("⚠️ Loading Data...")

            if st.button("✏️ สแกนสินค้าใหม่ (ตัวนี้ผิด)"):
                reset_for_next_item()
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

                    # 4. PICK QUANTITY (เพิ่มส่วนนี้)
                    if valid_loc:
                        st.markdown("---")
                        st.markdown(f"#### 4. จำนวนที่หยิบ (Pick Qty)")
                        st.session_state.pick_qty = st.number_input("ระบุจำนวน", min_value=1, value=1, step=1)

                        # 5. PACK / PHOTO
                        st.markdown("---")
                        st.markdown(f"#### 5. ถ่ายรูป ({len(st.session_state.photo_gallery)}/5)")
                        
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
                            if st.button(f"☁️ บันทึกรายการนี้ (Upload)", type="primary", use_container_width=True):
                                with st.spinner("กำลังบันทึกข้อมูล..."):
                                    srv = authenticate_drive()
                                    if srv:
                                        # ล็อค Logic การสร้าง Folder ห้ามแก้
                                        target_fid = get_target_folder_structure(srv, st.session_state.order_val, MAIN_FOLDER_ID)
                                        
                                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                                        first_file_id = "" 
                                        
                                        for i, img_bytes in enumerate(st.session_state.photo_gallery):
                                            fn = f"{st.session_state.order_val}_{st.session_state.prod_val}_LOC-{st.session_state.loc_val}_{ts}_Img{i+1}.jpg"
                                            upl_id = upload_photo(srv, img_bytes, fn, target_fid)
                                            if i == 0: first_file_id = upl_id 
                                        
                                        # บันทึก Log รวมถึง Pick Qty (Column G)
                                        save_log_to_sheet(
                                            st.session_state.current_user_name,
                                            st.session_state.order_val,
                                            st.session_state.prod_val,
                                            st.session_state.prod_display_name,
                                            st.session_state.loc_val,
                                            st.session_state.pick_qty, # ส่งค่า Pick Qty ไปบันทึก
                                            first_file_id
                                        )
                                        
                                        st.balloons()
                                        st.success(f"บันทึกสินค้า {st.session_state.prod_display_name} เรียบร้อย!")
                                        time.sleep(1.5)
                                        
                                        # สำคัญ: Reset แค่ Item เพื่อให้สแกนชิ้นต่อไปใน Order เดิม
                                        reset_for_next_item()
                                        st.rerun()
