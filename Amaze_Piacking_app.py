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

# --- CSS HACK: ปรับขนาดกล้อง ---
st.markdown("""
<style>
/* บังคับขยาย iframe ของ back_camera_input ให้สูงขึ้น */
iframe[title="streamlit_back_camera_input.back_camera_input"] {
    min-height: 250px !important; 
    transform: scale(1.1); 
    transform-origin: top center;
    margin-bottom: 20px;
}
/* ปรับแต่งตารางให้ดูง่ายขึ้น */
div[data-testid="stDataFrame"] {
    width: 100%;
}
</style>
""", unsafe_allow_html=True)
# ==================================

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

# NOTE: save_log_to_sheet เดิมถูกออกแบบมาเพื่อรับรายการเดียว
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
            user_col, # Column H: User ID
            image_link
        ]
        worksheet.append_row(row_data)
    except Exception as e:
        st.warning(f"⚠️ บันทึก Log ไม่สำเร็จ: {e}")

# --- TIME HELPER (UTC+7) ---
def get_thai_time():
    return (datetime.utcnow() + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S")
def get_thai_date_str():
    return (datetime.utcnow() + timedelta(hours=7)).strftime("%d-%m-%Y")
def get_thai_time_suffix():
    return (datetime.utcnow() + timedelta(hours=7)).strftime("%H-%M")
def get_thai_ts_filename():
    return (datetime.utcnow() + timedelta(hours=7)).strftime("%Y%m%d_%H%M%S")

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
        
        if isinstance(file_obj, bytes):
            media_body = io.BytesIO(file_obj)
        else:
            media_body = file_obj
            
        media = MediaIoBaseUpload(
            media_body, 
            mimetype='image/jpeg', 
            chunksize=1024*1024, 
            resumable=True
        )
        
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file.get('id')
    except Exception as e:
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
    st.session_state.picking_phase = 'scan'
    st.session_state.temp_login_user = None # Ensure temp login is cleared
    # Clear Rider-specific states
    if 'target_rider_folder_id' in st.session_state: del st.session_state.target_rider_folder_id
    if 'target_rider_folder_name' in st.session_state: del st.session_state.target_rider_folder_name
    reset_for_next_item()

def logout_user():
    st.session_state.current_user_name = ""
    st.session_state.current_user_id = ""
    reset_all_data()
    st.rerun()

# --- UI SETUP ---
st.set_page_config(page_title="Smart Picking System", page_icon="📦")

# 🚩 Initialize ALL necessary session state variables robustly
def init_session_state():
    # *FIX*: กำหนดค่าเริ่มต้นให้กับตัวแปรหลักทั้งหมดอย่างชัดเจน
    if 'current_user_name' not in st.session_state: st.session_state.current_user_name = ""
    if 'current_user_id' not in st.session_state: st.session_state.current_user_id = ""
    if 'app_mode' not in st.session_state: st.session_state.app_mode = "PICKING"
    
    # ตัวแปรอื่นๆ
    if 'order_val' not in st.session_state: st.session_state.order_val = ""
    if 'prod_val' not in st.session_state: st.session_state.prod_val = ""
    if 'loc_val' not in st.session_state: st.session_state.loc_val = ""
    if 'prod_display_name' not in st.session_state: st.session_state.prod_display_name = ""
    if 'photo_gallery' not in st.session_state: st.session_state.photo_gallery = []
    if 'cam_counter' not in st.session_state: st.session_state.cam_counter = 0
    if 'pick_qty' not in st.session_state: st.session_state.pick_qty = 1
    if 'rider_photo' not in st.session_state: st.session_state.rider_photo = None
    if 'current_order_items' not in st.session_state: st.session_state.current_order_items = []
    if 'picking_phase' not in st.session_state: st.session_state.picking_phase = 'scan' 
    if 'temp_login_user' not in st.session_state: st.session_state.temp_login_user = None
    if 'last_user_input' not in st.session_state: st.session_state.last_user_input = ""
    
init_session_state()

# --- PART 1: LOGIN ---
if not st.session_state.current_user_name:
    st.title("🔐 Login พนักงาน")
    df_users = load_sheet_data(USER_SHEET_NAME)

    if st.session_state.temp_login_user is None:
        st.info("กรุณาสแกนรหัสพนักงาน")
        
        col1, col2 = st.columns([3, 1])
        
        # FIX: ใช้ value=st.session_state.last_user_input ในการควบคุมและล้างค่า
        manual_user_key = "input_user_manual_step1"
        manual_user = col1.text_input("พิมพ์รหัสพนักงาน", key=manual_user_key, value=st.session_state.last_user_input).strip()
        
        cam_key_user = f"cam_user_{st.session_state.cam_counter}"
        scan_user = back_camera_input("แตะเพื่อสแกนบัตรพนักงาน", key=cam_key_user)
        
        user_input_val = None
        if manual_user: user_input_val = manual_user
        elif scan_user:
            res_u = decode(Image.open(scan_user))
            if res_u: user_input_val = res_u[0].data.decode("utf-8")
        
        # ตรวจสอบ ID ที่เพิ่งเข้ามา
        if user_input_val:
            # *CRITICAL FIX*: ล้างค่า Manual Input ใน Session State เพื่อเคลียร์ช่องพิมพ์
            st.session_state.last_user_input = "" 
            
            if not df_users.empty and len(df_users.columns) >= 3:
                # Col A = ID, Col B = Pass, Col C = Name
                match = df_users[df_users.iloc[:, 0].astype(str) == str(user_input_val)]
                if not match.empty:
                    # Found User -> Go to Password step
                    st.session_state.temp_login_user = {
                        'id': str(user_input_val),
                        'pass': str(match.iloc[0, 1]).strip(), 
                        'name': match.iloc[0, 2]
                    }
                    st.rerun()
                else:
                    st.error(f"❌ ไม่พบรหัสพนักงาน: {user_input_val}")
            else:
                st.warning("⚠️ โหลดข้อมูลพนักงานไม่ได้ หรือ Sheet User มีคอลัมน์ไม่ครบ")

    # STEP 2: Verify Password
    else:
        user_info = st.session_state.temp_login_user
        st.info(f"👤 พนักงาน: **{user_info['name']}** ({user_info['id']})")
        
        # Use a new key for password input to prevent confusion with other text inputs
        password_input = st.text_input("🔑 กรุณากรอกรหัสผ่าน", type="password", key="login_pass_input").strip()
        
        c1, c2 = st.columns([1, 1])
        with c1:
            if st.button("✅ ยืนยัน Login", type="primary", use_container_width=True):
                if password_input == user_info['pass']:
                    st.session_state.current_user_id = user_info['id']
                    st.session_state.current_user_name = user_info['name']
                    st.session_state.temp_login_user = None
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
    # --- START SIDEBAR LOGIC ---
    with st.sidebar:
        st.write(f"👤 **{st.session_state.current_user_name}**")
        st.divider()
        
        # กำหนด Option และค่าปัจจุบันสำหรับการแสดงผล
        mode_options = {
            "📦 แผนกแพ็คสินค้า": "PICKING",
            "🛵 ส่งงาน Rider": "DELIVERY"
        }
        
        # ปรับค่าเริ่มต้นของ Radio ให้ตรงกับ app_mode
        current_sidebar_mode = "📦 แผนกแพ็คสินค้า"
        if st.session_state.app_mode == "DELIVERY":
             current_sidebar_mode = "🛵 ส่งงาน Rider"
        
        # ตรวจสอบว่าโหมดปัจจุบันเป็นโหมดที่ต้องถูกล็อกหรือไม่
        is_in_packing_flow = st.session_state.picking_phase == 'pack' and st.session_state.order_val
        
        selected_mode_display = st.radio(
            "เลือกโหมดทำงาน:",
            options=list(mode_options.keys()),
            index=list(mode_options.keys()).index(current_sidebar_mode),
            key="sidebar_mode_selector_radio",
            disabled=is_in_packing_flow # ล็อกการเลือกโหมดอื่นเมื่ออยู่ใน PACKING
        )
        
        # Logic เปลี่ยน app_mode เมื่อมีการเลือกใน Sidebar
        new_app_mode = mode_options[selected_mode_display]
        
        # FIX: แก้ไข Logic การสลับโหมดให้ถูกต้อง
        if new_app_mode != st.session_state.app_mode and not is_in_packing_flow:
            st.session_state.app_mode = new_app_mode
            st.session_state.photo_gallery = [] # Clear gallery when switching mode
            st.rerun()
        
        # แสดงคำเตือนถ้าพยายามสลับโหมดขณะอยู่ใน PACKING
        if is_in_packing_flow:
            st.warning("⚠️ กรุณายืนยัน Upload ในหน้าหลักก่อนเปลี่ยนโหมด")
            
        st.divider()
        if st.button("Logout", type="secondary"): logout_user()

    # --- END SIDEBAR LOGIC ---
    
    # --- MAIN CONTENT ---
    st.title("📦 ระบบเบิกสินค้า")
    st.caption(f"👤: **{st.session_state.current_user_name}** | Mode: {current_sidebar_mode}")
    
    # *ADVICE FOR MOBILE USERS*
    if not st.session_state.order_val and st.session_state.app_mode == "PICKING":
        st.info("💡 **ผู้ใช้มือถือ:** แตะที่ปุ่ม `>>` หรือ `☰` ที่มุมบนซ้ายเพื่อเลือกโหมดทำงานอื่น (Delivery) หรือ Logout")

    df_items = load_sheet_data(0)

    # =====================================================
    # MODE 1: PACKING FLOW
    # =====================================================
    if st.session_state.app_mode == "PICKING":
        
        # -----------------------------------------------
        # PHASE 1 & 2 LOGIC (SAME AS BEFORE)
        # -----------------------------------------------
        
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

        # PHASE 1: SCANNING (สแกนของจนครบ)
        if st.session_state.order_val and st.session_state.picking_phase == 'scan':
            st.markdown("---")
            st.markdown("#### 2. เพิ่มรายการสินค้า (Scan & Add)")
            
            # Input
            if not st.session_state.prod_val:
                col1, col2 = st.columns([3, 1])
                manual_prod = col1.text_input("พิมพ์ Barcode", key="input_prod_manual").strip()
                if manual_prod: st.session_state.prod_val = manual_prod; st.rerun()
                
                scan_prod = back_camera_input("แตะเพื่อสแกนสินค้า", key=f"cam_prod_{st.session_state.cam_counter}")
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
                                reset_for_next_item(); st.rerun()
                            else:
                                pass # Wait for user action
                        else:
                            st.error(f"❌ ผิดตำแหน่ง ({st.session_state.loc_val})")
                            if st.button("แก้ Location"): st.session_state.loc_val = ""; st.rerun()

            # BASKET & CONFIRM BUTTON
            if st.session_state.current_order_items:
                st.markdown("---")
                st.markdown(f"### 🛒 ตะกร้าสินค้า ({len(st.session_state.current_order_items)} รายการ)")
                st.dataframe(pd.DataFrame(st.session_state.current_order_items), use_container_width=True)
                
                # FIX: ปุ่มนี้จะเปลี่ยน picking_phase เป็น 'pack'
                if st.button("✅ ยืนยันรายการครบแล้ว (ไปถ่ายรูป)", type="primary", use_container_width=True):
                    st.session_state.picking_phase = 'pack'
                    st.rerun()

        # PHASE 2: PACKING (ถ่ายรูป & Upload)
        elif st.session_state.order_val and st.session_state.picking_phase == 'pack':
            st.success(f"📦 Order: **{st.session_state.order_val}** (ยืนยันแล้ว)")
            
            st.info("รายการสินค้าที่จะแพ็ค:")
            st.dataframe(pd.DataFrame(st.session_state.current_order_items), use_container_width=True)
            
            st.markdown("#### 3. ถ่ายรูปปิดกล่อง (รวมทุกชิ้น)")
            
            if st.session_state.photo_gallery:
                cols = st.columns(5)
                for idx, img in enumerate(st.session_state.photo_gallery):
                    with cols[idx]:
                        st.image(img, use_column_width=True)
                        if st.button("🗑️", key=f"del_{idx}"): st.session_state.photo_gallery.pop(idx); st.rerun()
            
            if len(st.session_state.photo_gallery) < 5:
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
                    st.session_state.photo_gallery = []
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
                                
                                st.balloons(); st.success("✅ บันทึกครบทุกรายการเรียบร้อย!"); time.sleep(2)
                                reset_all_data(); st.rerun()

    # =====================================================
    # MODE 2: RIDER HANDOVER 
    # =====================================================
    elif st.session_state.app_mode == "DELIVERY":
        st.title("🏍️ ส่งงาน Rider")
        st.info("ถ่ายรูปเพิ่มเติมเพื่อส่งให้ Rider (จะบันทึกลง Folder เดิม)")

        # 1. SCAN ORDER
        st.markdown("#### 1. สแกน Order ที่จะส่ง")
        col_r1, col_r2 = st.columns([3, 1])
        man_rider_ord = col_r1.text_input("พิมพ์ Order ID", key="rider_ord_man").strip().upper()
        
        current_rider_order = ""
        if man_rider_ord: 
            current_rider_order = man_rider_ord
        
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
                        if st.button("สแกน Order ใหม่"): st.session_state.order_val = ""; st.rerun()

        # 2. ถ่ายรูป Rider
        if st.session_state.get('target_rider_folder_id') and st.session_state.order_val:
            st.markdown("---")
            st.markdown(f"#### 2. ถ่ายรูปส่งมอบ ({st.session_state.target_rider_folder_name})")
            
            # Use rider_photo state to hold the image data
            if st.session_state.rider_photo is None:
                rider_img_input = back_camera_input("ถ่ายรูปส่งมอบ", key=f"rider_cam_act_{st.session_state.cam_counter}")
                
                if rider_img_input:
                    img_pil = Image.open(rider_img_input)
                    if img_pil.mode in ("RGBA", "P"): img_pil = img_pil.convert("RGB")
                    buf = io.BytesIO(); img_pil.save(buf, format='JPEG')
                    
                    st.session_state.rider_photo = buf.getvalue() # Store the bytes
                    st.rerun()

            if st.session_state.rider_photo is not None:
                st.image(st.session_state.rider_photo, caption="รูปที่จะส่ง", width=300)
                
                col_upload, col_clear = st.columns([2, 1])
                
                with col_clear:
                    if st.button("🗑️ ซ่อน/ถ่ายใหม่", type="secondary", use_container_width=True):
                        st.session_state.rider_photo = None
                        st.session_state.cam_counter += 1
                        st.rerun()

                with col_upload:
                    if st.button("🚀 ยืนยันส่งรูปนี้", type="primary", use_container_width=True):
                        with st.spinner("Uploading and Logging..."):
                            srv = authenticate_drive()
                            ts = get_thai_ts_filename()
                            fn = f"RIDER_{st.session_state.order_val}_{ts}.jpg"
                            
                            # Upload (Pass bytes object)
                            uid = upload_photo(srv, st.session_state.rider_photo, fn, st.session_state.target_rider_folder_id)
                            
                            # Log data matching the required format
                            save_log_to_sheet(
                                st.session_state.current_user_name,
                                st.session_state.order_val,
                                st.session_state.order_val,         # Barcode (ใช้ Order ID)
                                "Delivery Confirmation",            # Product Name
                                "Rider Handover",                   # Location
                                1,                                  # Pick Qty
                                st.session_state.current_user_id,   # User ID
                                uid                                 # Image Link ID
                            )

                            st.success("บันทึกรูป Rider และ Log สำเร็จ!")
                            time.sleep(1.5)
                            reset_all_data(); st.rerun()

# --- END MAIN SYSTEM ---
