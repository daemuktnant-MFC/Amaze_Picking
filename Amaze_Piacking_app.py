import streamlit as st
import pandas as pd
import gspread
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from datetime import datetime, timedelta
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

# --- CSS HACK: ขยายความสูงกล้อง 50% ---
st.markdown(
    """
    <style>
    /* ขยายความสูงของ iframe ที่รันกล้อง (ปรับค่า min-height ให้สูงขึ้น) */
    iframe[title="streamlit_back_camera_input.back_camera_input"] {
        min-height: 300px !important; 
        height: 150% !important;
    }
    /* ปรับแต่งตารางให้ดูง่ายขึ้น */
    div[data-testid="stDataFrame"] {
        width: 100%;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# --- CONFIGURATION ---
MAIN_FOLDER_ID = '1FHfyzzTzkK5PaKx6oQeFxTbLEq-Tmii7'
SHEET_ID = '1jNlztb3vfG0c8sw_bMTuA9GEqircx_uVE7uywd5dR2I'
LOG_SHEET_NAME = 'Logs'
RIDER_SHEET_NAME = 'Rider_Logs'
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
            
            # Cleaning Columns
            df.columns = df.columns.str.strip()
            for col in df.columns:
                if 'barcode' in col.lower() or 'id' in col.lower(): 
                    df[col] = df[col].astype(str).str.replace(r'\.0$', '', regex=True)
            
            if 'Barcode' not in df.columns:
                for col in df.columns:
                    if col.lower() == 'barcode':
                        df.rename(columns={col: 'Barcode'}, inplace=True)
                        break
                        
            return df
        return pd.DataFrame()
    except Exception as e:
        return pd.DataFrame()

# --- TIME HELPER (UTC+7) ---
def get_thai_time():
    return (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S")
def get_thai_date_str():
    return (datetime.utcnow() + timedelta(hours=7)).strftime("%d-%m-%Y")
def get_thai_time_suffix():
    return (datetime.utcnow() + timedelta(hours=7)).strftime("%H-%M")
def get_thai_ts_filename():
    return (datetime.utcnow() + timedelta(hours=7)).strftime("%Y%m%d_%H%M%S")

def save_log_to_sheet(picker_name, order_id, barcode, prod_name, location, pick_qty, user_col, file_id):
    try:
        creds = get_credentials()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        try:
            worksheet = sh.worksheet(LOG_SHEET_NAME)
        except:
            worksheet = sh.add_worksheet(title=LOG_SHEET_NAME, rows="1000", cols="20")
            worksheet.append_row(["Timestamp", "Picker Name", "Order ID", "Barcode", "Product Name", "Location", "Pick Qty", "User", "Image Link (Col I)"])
            
        timestamp = get_thai_time()
        image_link = f"https://drive.google.com/open?id={file_id}"
        
        # Row Data
        row_data = [
            timestamp, 
            picker_name, 
            order_id, 
            barcode, 
            prod_name, 
            location, 
            pick_qty, 
            user_col, # Column H
            image_link
        ]
        worksheet.append_row(row_data)
    except Exception as e:
        st.warning(f"⚠️ บันทึก Log ไม่สำเร็จ: {e}")

def save_rider_log(picker_name, order_id, file_id, folder_name):
    try:
        creds = get_credentials()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        try:
            worksheet = sh.worksheet(RIDER_SHEET_NAME)
        except:
            worksheet = sh.add_worksheet(title=RIDER_SHEET_NAME, rows="1000", cols="10")
            worksheet.append_row(["Timestamp", "User Name", "Order ID", "Folder Name", "Rider Image Link"])
            
        timestamp = get_thai_time()
        image_link = f"https://drive.google.com/open?id={file_id}"
        worksheet.append_row([timestamp, picker_name, order_id, folder_name, image_link])
    except Exception as e:
        st.warning(f"⚠️ บันทึก Rider Log ไม่สำเร็จ: {e}")

# ==============================================================================
# 🔒 CRITICAL SECTION: FOLDER STRUCTURE (LOCKED)
# ==============================================================================
def get_target_folder_structure(service, order_id, main_parent_id):
    date_folder_name = get_thai_date_str()
    
    q_date = f"name = '{date_folder_name}' and '{main_parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    res_date = service.files().list(q=q_date, fields="files(id)").execute()
    files_date = res_date.get('files', [])
    
    if files_date:
        date_folder_id = files_date[0]['id']
    else:
        meta_date = {'name': date_folder_name, 'parents': [main_parent_id], 'mimeType': 'application/vnd.google-apps.folder'}
        date_folder = service.files().create(body=meta_date, fields='id').execute()
        date_folder_id = date_folder.get('id')
        
    time_suffix = get_thai_time_suffix()
    order_folder_name = f"{order_id}_{time_suffix}"
    
    meta_order = {'name': order_folder_name, 'parents': [date_folder_id], 'mimeType': 'application/vnd.google-apps.folder'}
    order_folder = service.files().create(body=meta_order, fields='id').execute()
    
    return order_folder.get('id')
# ==============================================================================
# END CRITICAL SECTION
# ==============================================================================

def find_existing_order_folder(service, order_id, main_parent_id):
    date_folder_name = get_thai_date_str()
    q_date = f"name = '{date_folder_name}' and '{main_parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    res_date = service.files().list(q=q_date, fields="files(id)").execute()
    files_date = res_date.get('files', [])
    
    if not files_date:
        return None, "ไม่พบ Folder วันที่ของวันนี้ (ยังไม่มีการเปิดบิลวันนี้)"
    
    date_folder_id = files_date[0]['id']
    q_order = f"'{date_folder_id}' in parents and name contains '{order_id}_' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    res_order = service.files().list(q=q_order, fields="files(id, name)", orderBy="createdTime desc").execute()
    files_order = res_order.get('files', [])
    
    if files_order:
        return files_order[0]['id'], files_order[0]['name']
    else:
        return None, f"ไม่พบ Folder ของ Order: {order_id} ในวันนี้"

def upload_photo(service, file_obj, filename, folder_id):
    try:
        file_metadata = {'name': filename, 'parents': [folder_id]}
        
        # 💡 การแก้ไข: ตรวจสอบว่าเป็น bytes object หรือไม่
        if isinstance(file_obj, bytes):
            # ถ้าเป็น bytes object ดิบ ให้แปลงเป็น io.BytesIO (File-like object)
            media_body = io.BytesIO(file_obj)
        else:
            # ถ้าเป็น File-like Object อยู่แล้ว (เช่น UploadedFile จาก Rider Mode), ใช้ได้เลย
            media_body = file_obj
            
        # สร้าง MediaIoBaseUpload จากวัตถุที่เป็น File-like object
        # Google API ต้องการให้วัตถุที่นี่มีเมธอด .seek()
        media = MediaIoBaseUpload(
            media_body, 
            mimetype='image/jpeg', 
            chunksize=1024*1024, 
            resumable=True
        )
        
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file.get('id')
    except Exception as e:
        # st.error(f"🔴 Upload Error: {e}") # (Redacted for brevity, keep for debugging)
        raise e

# --- RESET FUNCTIONS ---
def reset_for_next_item():
    st.session_state.prod_val = ""
    st.session_state.loc_val = ""
    st.session_state.prod_display_name = ""
    st.session_state.pick_qty = 1 
    st.session_state.cam_counter += 1

def reset_all_data():
    st.session_state.order_val = ""
    st.session_state.current_order_items = []
    st.session_state.photo_gallery = [] 
    st.session_state.rider_photo = None
    st.session_state.picking_phase = 'scan' # Reset กลับไปเฟสแรก
    reset_for_next_item()

def logout_user():
    st.session_state.current_user_name = ""
    st.session_state.current_user_id = ""
    reset_all_data()
    st.rerun()

# --- UI SETUP ---
st.set_page_config(page_title="Smart Picking System", page_icon="📦")

# Init Session State
if 'current_user_name' not in st.session_state: st.session_state.current_user_name = ""
if 'current_user_id' not in st.session_state: st.session_state.current_user_id = ""
if 'order_val' not in st.session_state: st.session_state.order_val = ""
if 'prod_val' not in st.session_state: st.session_state.prod_val = ""
if 'loc_val' not in st.session_state: st.session_state.loc_val = ""
if 'prod_display_name' not in st.session_state: st.session_state.prod_display_name = ""
if 'photo_gallery' not in st.session_state: st.session_state.photo_gallery = []
if 'cam_counter' not in st.session_state: st.session_state.cam_counter = 0
if 'pick_qty' not in st.session_state: st.session_state.pick_qty = 1 
if 'cart_items' not in st.session_state: st.session_state.cart_items = [] 
if 'app_mode' not in st.session_state: st.session_state.app_mode = "PICKING" 
if 'temp_login_user' not in st.session_state: st.session_state.temp_login_user = None

# --- LOGIN ---
if not st.session_state.current_user_name:
    st.title("🔐 Login พนักงาน")
    df_users = load_sheet_data(USER_SHEET_NAME)

    # STEP 1: Scan/Input User ID (จะแสดงก็ต่อเมื่อยังไม่มี Temp User)
    if st.session_state.temp_login_user is None:
        st.info("กรุณาสแกนรหัสพนักงาน")
        
        col1, col2 = st.columns([3, 1])
        manual_user = col1.text_input("พิมพ์รหัสพนักงาน", key="input_user_manual").strip()
        cam_key_user = f"cam_user_{st.session_state.cam_counter}"
        scan_user = back_camera_input("แตะเพื่อสแกนบัตรพนักงาน", key=cam_key_user)
        
        user_input_val = None
        if manual_user: user_input_val = manual_user
        elif scan_user:
            res_u = decode(Image.open(scan_user))
            if res_u: user_input_val = res_u[0].data.decode("utf-8")
        
        # ตรวจสอบ ID ที่เพิ่งเข้ามา
        if user_input_val:
            # *CRITICAL FIX*: ล้างค่า Manual Input เพื่อป้องกันการวนลูป
            col1.text_input("พิมพ์รหัสพนักงาน", value="", key="input_user_manual_cleared").strip() 
            
            if not df_users.empty:
                # Col A = ID, Col B = Pass, Col C = Name
                match = df_users[df_users.iloc[:, 0].astype(str) == str(user_input_val)]
                if not match.empty:
                    # พบ User -> เก็บลง Temp แล้วไปหน้า Password (ยังไม่ Login)
                    st.session_state.temp_login_user = {
                        'id': str(user_input_val),
                        'pass': str(match.iloc[0, 1]).strip(), # Password (Column B)
                        'name': match.iloc[0, 2]               # Name (Column C)
                    }
                    st.rerun()
                else:
                    st.error(f"❌ ไม่พบรหัสพนักงาน: {user_input_val}")
            else:
                st.warning("⚠️ โหลดข้อมูลพนักงานไม่ได้")

    # STEP 2: Verify Password (จะแสดงเมื่อมี Temp User)
    else:
        user_info = st.session_state.temp_login_user
        st.info(f"👤 พนักงาน: **{user_info['name']}** ({user_info['id']})")
        
        password_input = st.text_input("🔑 กรุณากรอกรหัสผ่าน", type="password", key="login_pass_input").strip()
        
        c1, c2 = st.columns([1, 1])
        with c1:
            if st.button("✅ ยืนยัน Login", type="primary", use_container_width=True):
                # ตรวจสอบ Password
                if password_input == user_info['pass']:
                    st.session_state.current_user_id = user_info['id']
                    st.session_state.current_user_name = user_info['name']
                    st.session_state.temp_login_user = None # เคลียร์ Temp
                    st.toast(f"ยินดีต้อนรับคุณ {user_info['name']} 👋", icon="✅")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("❌ รหัสผ่านไม่ถูกต้อง")
        
        with c2:
            if st.button("⬅️ เปลี่ยน User", use_container_width=True):
                st.session_state.temp_login_user = None
                st.rerun()

else:
    # --- LOGGED IN ---
    with st.sidebar:
        st.write(f"👤 **{st.session_state.current_user_name}**")
        mode = st.radio("เลือกโหมดทำงาน:", ["📦 แผนกแพ็คสินค้า", "🏍️ ส่งงาน Rider"])
        st.divider()
        if st.button("Logout", type="secondary"):
            logout_user()

    # =====================================================
    # MODE 1: PACKING (SPLIT PHASE: SCAN -> PACK)
    # =====================================================
    if mode == "📦 แผนกแพ็คสินค้า":
        st.title("📦 ระบบเบิก-แพ็คสินค้า")
        
        df_items = load_sheet_data(0)
        if not df_items.empty and 'Barcode' not in df_items.columns:
            st.error("❌ ไม่พบคอลัมน์ 'Barcode' ใน Sheet!")
            st.stop()

        # -----------------------------------------------
        # PHASE 1: SCANNING (สแกนของจนครบ)
        # -----------------------------------------------
        if st.session_state.picking_phase == 'scan':
            # 1. ORDER
            st.markdown("#### 1. Order ID")
            if not st.session_state.order_val:
                col1, col2 = st.columns([3, 1])
                manual_order = col1.text_input("พิมพ์ Order ID", key="pack_order_man").strip().upper()
                if manual_order:
                    st.session_state.order_val = manual_order
                    st.rerun()
                
                scan_order = back_camera_input("แตะเพื่อสแกน Order", key=f"pack_cam_{st.session_state.cam_counter}")
                if scan_order:
                    res = decode(Image.open(scan_order))
                    if res:
                        st.session_state.order_val = res[0].data.decode("utf-8").upper()
                        st.rerun()
            else:
                c1, c2 = st.columns([3, 1])
                with c1: st.success(f"📦 Order: **{st.session_state.order_val}**")
                with c2: 
                    if st.button("เปลี่ยน Order"): reset_all_data(); st.rerun()

            # 2. SCAN ITEMS LOOP
            if st.session_state.order_val:
                st.markdown("---")
                st.markdown("#### 2. เพิ่มรายการสินค้า (Scan & Add)")
                
                # Input
                if not st.session_state.prod_val:
                    col1, col2 = st.columns([3, 1])
                    manual_prod = col1.text_input("พิมพ์ Barcode", key="pack_prod_man").strip()
                    if manual_prod: st.session_state.prod_val = manual_prod; st.rerun()
                    
                    # กล้อง Scan (ที่ขยาย 50% แล้วด้วย CSS ด้านบน)
                    scan_prod = back_camera_input("แตะเพื่อสแกนสินค้า", key=f"prod_cam_{st.session_state.cam_counter}")
                    if scan_prod:
                        res_p = decode(Image.open(scan_prod))
                        if res_p: st.session_state.prod_val = res_p[0].data.decode("utf-8"); st.rerun()
                else:
                    # Verify
                    target_loc_str = None
                    prod_found = False
                    if not df_items.empty:
                        match = df_items[df_items['Barcode'] == st.session_state.prod_val]
                        if not match.empty:
                            prod_found = True
                            row = match.iloc[0]
                            try:
                                brand = str(row.iloc[3]); variant = str(row.iloc[5])
                                full_name = f"{brand} {variant}"
                            except: full_name = "Error Name"
                            st.session_state.prod_display_name = full_name
                            target_loc_str = f"{str(row.get('Zone','')).strip()}-{str(row.get('Location','')).strip()}"
                            st.success(f"✅ **{full_name}**"); st.warning(f"📍 เป้าหมาย: **{target_loc_str}**")
                        else: st.error("❌ ไม่พบ Barcode")
                    else: st.warning("⚠️ Loading Data...")
                    
                    if st.button("❌ สแกนใหม่"): reset_for_next_item(); st.rerun()

                    # Location & Qty
                    if prod_found and target_loc_str:
                        st.markdown("---")
                        st.markdown("##### ยืนยัน Location")
                        if not st.session_state.loc_val:
                            man_loc = st.text_input("Scan/พิมพ์ Location", key="loc_man").strip().upper()
                            if man_loc: st.session_state.loc_val = man_loc; st.rerun()
                            scan_loc = back_camera_input("แตะเพื่อสแกน Location", key=f"loc_cam_{st.session_state.cam_counter}")
                            if scan_loc:
                                res_l = decode(Image.open(scan_loc))
                                if res_l: st.session_state.loc_val = res_l[0].data.decode("utf-8").upper(); st.rerun()
                        else:
                            if st.session_state.loc_val == target_loc_str or st.session_state.loc_val in target_loc_str:
                                st.success(f"✅ ถูกต้อง: {st.session_state.loc_val}")
                                st.markdown("##### ระบุจำนวน")
                                st.session_state.pick_qty = st.number_input("จำนวน (Qty)", min_value=1, value=1)
                                
                                st.markdown("---")
                                if st.button("➕ เพิ่มลงตะกร้า", type="primary", use_container_width=True):
                                    new_item = {
                                        "Barcode": st.session_state.prod_val,
                                        "Product Name": st.session_state.prod_display_name,
                                        "Location": st.session_state.loc_val,
                                        "Qty": st.session_state.pick_qty
                                    }
                                    st.session_state.current_order_items.append(new_item)
                                    st.toast(f"เพิ่ม {st.session_state.prod_display_name} แล้ว!", icon="🛒")
                                    reset_for_next_item()
                                    st.rerun()
                            else:
                                st.error(f"❌ ผิดตำแหน่ง ({st.session_state.loc_val})")
                                if st.button("แก้ Location"): st.session_state.loc_val = ""; st.rerun()

                # BASKET & CONFIRM BUTTON
                if st.session_state.current_order_items:
                    st.markdown("---")
                    st.markdown(f"### 🛒 ตะกร้าสินค้า ({len(st.session_state.current_order_items)} รายการ)")
                    st.dataframe(pd.DataFrame(st.session_state.current_order_items), use_container_width=True)
                    
                    # ปุ่มเปลี่ยนไป Phase 2
                    if st.button("✅ ยืนยันรายการครบแล้ว (ไปถ่ายรูป)", type="primary", use_container_width=True):
                        st.session_state.picking_phase = 'pack'
                        st.rerun()

        # -----------------------------------------------
        # PHASE 2: PACKING (ถ่ายรูป & Upload)
        # -----------------------------------------------
        elif st.session_state.picking_phase == 'pack':
            st.success(f"📦 Order: **{st.session_state.order_val}** (ยืนยันแล้ว)")
            
            # Show Basket (Read only)
            st.info("รายการสินค้าที่จะแพ็ค:")
            st.dataframe(pd.DataFrame(st.session_state.current_order_items), use_container_width=True)
            
            st.markdown("#### 4. ถ่ายรูปปิดกล่อง (รวมทุกชิ้น)")
            
            if st.session_state.photo_gallery:
                cols = st.columns(5)
                for idx, img in enumerate(st.session_state.photo_gallery):
                    with cols[idx]:
                        st.image(img, use_column_width=True)
                        if st.button("🗑️", key=f"del_{idx}"): st.session_state.photo_gallery.pop(idx); st.rerun()
            
            if len(st.session_state.photo_gallery) < 5:
                # กล้องถ่ายรูปแพ็ค (CSS Apply here too)
                pack_img = back_camera_input("ถ่ายรูปสินค้ากองรวม (กล้องหลัง)", key=f"pack_cam_fin_{st.session_state.cam_counter}")
                if pack_img:
                    img_pil = Image.open(pack_img)
                    if img_pil.mode in ("RGBA", "P"): img_pil = img_pil.convert("RGB")
                    buf = io.BytesIO(); img_pil.save(buf, format='JPEG')
                    st.session_state.photo_gallery.append(buf.getvalue())
                    st.session_state.cam_counter += 1; st.rerun()
            
            col_b1, col_b2 = st.columns([1, 1])
            with col_b1:
                if st.button("⬅️ กลับไปแก้ไขรายการ"):
                    st.session_state.picking_phase = 'scan'
                    st.rerun()
            with col_b2:
                if len(st.session_state.photo_gallery) > 0:
                    if st.button("☁️ ยืนยัน Upload ทั้งหมด", type="primary", use_container_width=True):
                        with st.spinner("กำลังบันทึกข้อมูล..."):
                            srv = authenticate_drive()
                            if srv:
                                fid = get_target_folder_structure(srv, st.session_state.order_val, MAIN_FOLDER_ID)
                                ts = get_thai_ts_filename()
                                first_id = ""
                                
                                for i, b in enumerate(st.session_state.photo_gallery):
                                    fn = f"{st.session_state.order_val}_PACKED_{ts}_Img{i+1}.jpg"
                                    uid = upload_photo(srv, b, fn, fid)
                                    if i==0: first_id = uid 
                                
                                # Loop Save Logs
                                for item in st.session_state.current_order_items:
                                    save_log_to_sheet(
                                        st.session_state.current_user_name,
                                        st.session_state.order_val,
                                        item['Barcode'],
                                        item['Product Name'],
                                        item['Location'],
                                        item['Qty'],
                                        st.session_state.current_user_id,
                                        first_id
                                    )
                                
                                st.balloons()
                                st.success("✅ บันทึกครบทุกรายการเรียบร้อย!")
                                time.sleep(2)
                                reset_all_data() 
                                st.rerun()

    # =====================================================
    # MODE 2: RIDER HANDOVER (เหมือนเดิม)
    # =====================================================
    elif mode == "🏍️ ส่งงาน Rider":
        st.title("🏍️ ส่งงาน Rider")
        st.info("ถ่ายรูปเพิ่มเติมเพื่อส่งให้ Rider (จะบันทึกลง Folder เดิม)")

        # 1. SCAN ORDER
        st.markdown("#### 1. สแกน Order ที่จะส่ง")
        col_r1, col_r2 = st.columns([3, 1])
        man_rider_ord = col_r1.text_input("พิมพ์ Order ID", key="rider_ord_man").strip().upper()

        # กล้อง Scan Order
        scan_rider_ord = back_camera_input("แตะเพื่อสแกน Order", key=f"rider_cam_ord_{st.session_state.cam_counter}")
        
        current_rider_order = ""
        if man_rider_ord: current_rider_order = man_rider_ord
        elif scan_rider_ord:
            res = decode(Image.open(scan_rider_ord))
            if res: current_rider_order = res[0].data.decode("utf-8").upper()

        if current_rider_order:
            st.session_state.order_val = current_rider_order
            
            with st.spinner(f"🔍 กำลังหา Folder ของ {current_rider_order}..."):
                srv = authenticate_drive()
                if srv:
                    folder_id, folder_name = find_existing_order_folder(srv, current_rider_order, MAIN_FOLDER_ID)
                    
                    if folder_id:
                        st.success(f"✅ เจอ Folder: **{folder_name}**")
                        st.session_state.target_rider_folder_id = folder_id
                        st.session_state.target_rider_folder_name = folder_name
                    else:
                        st.error(f"❌ {folder_name}")
                        st.session_state.target_rider_folder_id = None

        # 2. ถ่ายรูป Rider
        if st.session_state.get('target_rider_folder_id') and st.session_state.order_val:
            st.markdown("---")
            st.markdown(f"#### 2. ถ่ายรูปส่งมอบ ({st.session_state.target_rider_folder_name})")
            
            rider_img_input = back_camera_input("ถ่ายรูปส่งมอบ", key=f"rider_cam_act_{st.session_state.cam_counter}")
            
            if rider_img_input:
                st.image(rider_img_input, caption="รูปที่จะส่ง", width=300)
                if st.button("🚀 ยืนยันส่งรูปนี้", type="primary"):
                    with st.spinner("Uploading..."):
                        srv = authenticate_drive()
                        ts = get_thai_ts_filename()
                        fn = f"RIDER_{st.session_state.order_val}_{ts}.jpg"
                        
                        uid = upload_photo(srv, rider_img_input, fn, st.session_state.target_rider_folder_id)
                        
                        save_rider_log(st.session_state.current_user_name, st.session_state.order_val, uid, st.session_state.target_rider_folder_name)
                        
                        st.success("บันทึกรูป Rider สำเร็จ!")
                        time.sleep(1.5)
                        st.session_state.order_val = ""
                        st.session_state.target_rider_folder_id = None
                        st.session_state.cam_counter += 1
                        st.rerun()
