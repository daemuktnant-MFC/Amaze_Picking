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
import pytz 

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
THAI_TZ = pytz.timezone('Asia/Bangkok') 

# --- HELPER: GET THAI TIME ---
def get_thai_time():
    return datetime.now(THAI_TZ)

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

def save_log_batch(picker_name, picker_id, order_id, picked_items, file_id):
    try:
        creds = get_credentials()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        
        try:
            worksheet = sh.worksheet(LOG_SHEET_NAME)
        except:
            worksheet = sh.add_worksheet(title=LOG_SHEET_NAME, rows="1000", cols="20")
            worksheet.append_row([
                "Timestamp", "Picker Name", "Order ID", "Barcode", "Product Name", "Location", 
                "Pick Qty", "User ID", "Image Link (Col I)"
            ])
            
        timestamp = get_thai_time().strftime("%Y-%m-%d %H:%M:%S")
        image_link = f"https://drive.google.com/open?id={file_id}"
        
        rows_to_append = []
        for item in picked_items:
            row = [
                timestamp,
                picker_name,   
                order_id,      
                item['barcode'],
                item['name'],
                item['location'],
                item['qty'],
                picker_id,     
                image_link     
            ]
            rows_to_append.append(row)
        
        worksheet.append_rows(rows_to_append)
        print(f"Batch Log saved: {len(rows_to_append)} rows.")
    except Exception as e:
        st.warning(f"⚠️ บันทึก Log ไม่สำเร็จ: {e}")

# ==============================================================================
# 🔒 CRITICAL SECTION: FOLDER STRUCTURE (LOCKED)
# ==============================================================================
def get_target_folder_structure(service, order_id, main_parent_id):
    # 1. Folder วันที่ (Timezone Thai)
    date_folder_name = get_thai_time().strftime("%d-%m-%Y")
    
    q_date = f"name = '{date_folder_name}' and '{main_parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    res_date = service.files().list(q=q_date, fields="files(id)").execute()
    files_date = res_date.get('files', [])
    
    if files_date:
        date_folder_id = files_date[0]['id']
    else:
        meta_date = {'name': date_folder_name, 'parents': [main_parent_id], 'mimeType': 'application/vnd.google-apps.folder'}
        date_folder = service.files().create(body=meta_date, fields='id').execute()
        date_folder_id = date_folder.get('id')
        
    # 2. Folder Order_HH-MM (Timezone Thai)
    time_suffix = get_thai_time().strftime("%H-%M")
    order_folder_name = f"{order_id}_{time_suffix}"
    
    meta_order = {'name': order_folder_name, 'parents': [date_folder_id], 'mimeType': 'application/vnd.google-apps.folder'}
    order_folder = service.files().create(body=meta_order, fields='id').execute()
    
    return order_folder.get('id')
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

# --- STATE MANAGEMENT ---
def add_to_cart():
    if st.session_state.prod_val and st.session_state.loc_val:
        item = {
            "barcode": st.session_state.prod_val,
            "name": st.session_state.prod_display_name,
            "location": st.session_state.loc_val,
            "qty": st.session_state.pick_qty
        }
        st.session_state.cart_items.append(item)
        
        st.session_state.prod_val = ""
        st.session_state.loc_val = ""
        st.session_state.prod_display_name = ""
        st.session_state.pick_qty = 1
        st.session_state.cam_counter += 1
        st.success("✅ เพิ่มลงรายการแล้ว")
        time.sleep(0.5)
        st.rerun()

def finish_picking_mode():
    if not st.session_state.cart_items:
        st.error("⚠️ ยังไม่มีสินค้าในรายการ")
    else:
        st.session_state.app_mode = "PACKING"
        st.rerun()

def reset_all_data():
    st.session_state.order_val = ""
    st.session_state.prod_val = ""
    st.session_state.loc_val = ""
    st.session_state.prod_display_name = ""
    st.session_state.photo_gallery = []
    st.session_state.pick_qty = 1
    st.session_state.cam_counter += 1
    st.session_state.cart_items = [] 
    st.session_state.app_mode = "PICKING" 

def logout_user():
    st.session_state.current_user_name = ""
    st.session_state.current_user_id = ""
    reset_all_data()
    st.rerun()

# --- UI SETUP ---
st.set_page_config(page_title="Smart Picking System", page_icon="📦")

# === CSS INJECTION: ปรับขนาดกล้อง & ซ่อน Footer ===
st.markdown("""
<style>
/* 1. บังคับขยาย iframe ของ back_camera_input ให้สูงขึ้น */
iframe[title="streamlit_back_camera_input.back_camera_input"] {
    min-height: 450px !important;  
    transform: scale(1.1); 
    transform-origin: top center;
    margin-bottom: 20px;
}

/* 2. ซ่อนเมนู Hamburger (ขวาบน) และ Footer (ขวาล่าง) */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

/* ซ่อนแถบสีรุ้งด้านบนสุด */
[data-testid="stDecoration"] {display: none;}
</style>
""", unsafe_allow_html=True)
# ================================================

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

# --- PART 1: LOGIN ---
if not st.session_state.current_user_name:
    st.title("🔐 Login พนักงาน")
    st.info("กรุณาสแกนรหัสพนักงาน")
    
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

# --- PART 2: MAIN SYSTEM ---
else:
    c1, c2 = st.columns([3, 1])
    with c1:
        st.title("📦 ระบบเบิกสินค้า")
        st.caption(f"👤: **{st.session_state.current_user_name}** | Mode: {st.session_state.app_mode}")
    with c2:
        if st.button("Logout", type="secondary"): logout_user()

    df_items = load_sheet_data(0)

    # 1. ORDER
    if not st.session_state.order_val:
        st.markdown("#### 1. Order ID")
        col1, col2 = st.columns([3, 1])
        manual_order = col1.text_input("พิมพ์ Order ID", key="input_order_manual").strip().upper()
        if manual_order:
            st.session_state.order_val = manual_order
            st.rerun()
        
        scan_order = back_camera_input("แตะเพื่อสแกน Order", key=f"cam_order_{st.session_state.cam_counter}")
        if scan_order:
            res = decode(Image.open(scan_order))
            if res:
                st.session_state.order_val = res[0].data.decode("utf-8").upper()
                st.rerun()
    else:
        st.success(f"📦 Order: **{st.session_state.order_val}**")

    # ==========================
    # MODE A: PICKING (หยิบของ)
    # ==========================
    if st.session_state.order_val and st.session_state.app_mode == "PICKING":
        st.markdown("---")
        st.markdown("#### 2. หยิบสินค้า (เพิ่มลงรายการ)")
        
        # Scan Product
        if not st.session_state.prod_val:
            col1, col2 = st.columns([3, 1])
            manual_prod = col1.text_input("พิมพ์ Barcode", key="input_prod_manual").strip()
            if manual_prod:
                st.session_state.prod_val = manual_prod
                st.rerun()

            scan_prod = back_camera_input("แตะเพื่อสแกนสินค้า", key=f"cam_prod_{st.session_state.cam_counter}")
            if scan_prod:
                res_p = decode(Image.open(scan_prod))
                if res_p:
                    st.session_state.prod_val = res_p[0].data.decode("utf-8")
                    st.rerun()
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
                        brand = str(row.iloc[3]) 
                        var_name = str(row.iloc[5])
                        st.session_state.prod_display_name = f"{brand} {var_name}"
                    except:
                        st.session_state.prod_display_name = "Unknown Product"

                    target_loc_str = f"{str(row.get('Zone', '')).strip()}-{str(row.get('Location', '')).strip()}"
                    
                    st.info(f"✅ สินค้า: **{st.session_state.prod_display_name}**")
                    st.warning(f"📍 เป้าหมายเก็บ: **{target_loc_str}**")
                else:
                    st.error(f"❌ ไม่พบ Barcode: {st.session_state.prod_val}")
                    if st.button("สแกนใหม่"):
                        st.session_state.prod_val = ""
                        st.rerun()

            if prod_found and target_loc_str:
                if not st.session_state.loc_val:
                    manual_loc = st.text_input("Scan/พิมพ์ Location", key="input_loc").strip().upper()
                    if manual_loc:
                        st.session_state.loc_val = manual_loc
                        st.rerun()
                    
                    scan_loc = back_camera_input("แตะสแกน Location", key=f"cam_loc_{st.session_state.cam_counter}")
                    if scan_loc:
                        res_l = decode(Image.open(scan_loc))
                        if res_l:
                            st.session_state.loc_val = res_l[0].data.decode("utf-8").upper()
                            st.rerun()
                else:
                    valid_loc = False
                    if st.session_state.loc_val in target_loc_str:
                        st.success(f"✅ Location ถูกต้อง: {st.session_state.loc_val}")
                        valid_loc = True
                    else:
                        st.error(f"❌ ผิดตำแหน่ง ({st.session_state.loc_val})")
                        if st.button("แก้ Location"):
                            st.session_state.loc_val = ""
                            st.rerun()
                    
                    if valid_loc:
                        st.markdown(f"**จำนวนที่หยิบ (Qty)**")
                        st.session_state.pick_qty = st.number_input("ระบุจำนวน", min_value=1, value=1, step=1, label_visibility="collapsed")
                        
                        col_btn1, col_btn2 = st.columns(2)
                        if col_btn1.button("➕ เพิ่มลงรายการ", type="primary", use_container_width=True):
                            add_to_cart()
                        if col_btn2.button("❌ ยกเลิก", use_container_width=True):
                            st.session_state.prod_val = ""
                            st.session_state.loc_val = ""
                            st.rerun()

        st.markdown("---")
        st.markdown(f"🛒 **รายการที่หยิบแล้ว ({len(st.session_state.cart_items)} รายการ)**")
        
        if st.session_state.cart_items:
            cart_df = pd.DataFrame(st.session_state.cart_items)
            cart_df.columns = ["Barcode", "สินค้า", "Location", "Qty"]
            st.dataframe(cart_df, use_container_width=True, hide_index=True)
            
            if st.button("✅ หยิบครบแล้ว / ไปถ่ายรูป", type="primary", use_container_width=True):
                finish_picking_mode()

    # ==========================
    # MODE B: PACKING (ถ่ายรูป & Upload)
    # ==========================
    elif st.session_state.order_val and st.session_state.app_mode == "PACKING":
        st.markdown("---")
        st.markdown("#### 3. ถ่ายรูปยืนยัน (Pack)")
        
        st.info(f"📦 Order: {st.session_state.order_val} | ทั้งหมด {len(st.session_state.cart_items)} รายการ")
        st.table(pd.DataFrame(st.session_state.cart_items)[['name', 'qty']]) 
        
        st.markdown(f"**ถ่ายรูปสินค้าในกล่อง ({len(st.session_state.photo_gallery)}/5)**")
        
        if st.session_state.photo_gallery:
            cols = st.columns(5)
            for idx, img_data in enumerate(st.session_state.photo_gallery):
                with cols[idx]:
                    st.image(img_data, use_column_width=True)
                    if st.button("🗑️", key=f"del_{idx}"):
                        st.session_state.photo_gallery.pop(idx)
                        st.rerun()
        
        if len(st.session_state.photo_gallery) < 5:
            pack_img = back_camera_input("แตะเพื่อถ่ายรูป", key=f"cam_pack_{st.session_state.cam_counter}")
            if pack_img:
                img_pil = Image.open(pack_img)
                # Convert RGBA to RGB (Fix OSError)
                if img_pil.mode in ('RGBA', 'P'):
                    img_pil = img_pil.convert('RGB')
                
                buf = io.BytesIO()
                img_pil.save(buf, format='JPEG')
                st.session_state.photo_gallery.append(buf.getvalue())
                st.session_state.cam_counter += 1
                st.rerun()

        if len(st.session_state.photo_gallery) > 0:
            st.markdown("---")
            if st.button(f"☁️ ยืนยันปิดงาน Order นี้ (Upload)", type="primary", use_container_width=True):
                with st.spinner("กำลังสร้าง Folder และอัปโหลด..."):
                    srv = authenticate_drive()
                    if srv:
                        # 1. สร้าง Folder (ใช้เวลาไทย)
                        target_fid = get_target_folder_structure(srv, st.session_state.order_val, MAIN_FOLDER_ID)
                        
                        # 2. Upload (ชื่อไฟล์ใช้เวลาไทย)
                        ts = get_thai_time().strftime("%Y%m%d_%H%M%S")
                        first_file_id = ""
                        for i, img_bytes in enumerate(st.session_state.photo_gallery):
                            fn = f"{st.session_state.order_val}_PACK_{ts}_Img{i+1}.jpg"
                            upl_id = upload_photo(srv, img_bytes, fn, target_fid)
                            if i == 0: first_file_id = upl_id
                        
                        # 3. Log (User ลง Col H)
                        save_log_batch(
                            st.session_state.current_user_name, # Col B
                            st.session_state.current_user_id,   # Col H (ที่ขอเพิ่ม)
                            st.session_state.order_val,
                            st.session_state.cart_items, 
                            first_file_id 
                        )
                        
                        st.balloons()
                        st.success("✅ ปิดงานสำเร็จ! กำลังรีเซ็ต...")
                        time.sleep(2)
                        reset_all_data() 
                        st.rerun()
        
        if st.button("🔙 กลับไปหยิบเพิ่ม"):
            st.session_state.app_mode = "PICKING"
            st.rerun()

    st.markdown("---")
    if st.button("🔄 ยกเลิก / เริ่มใหม่ทั้งหมด", type="secondary"):
        reset_all_data()
        st.rerun()
