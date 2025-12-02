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

# --- IMPORT LIBRARY กล้องตัวพิเศษ (ใช้งานทั้งแอป) ---
try:
    from streamlit_back_camera_input import back_camera_input
except ImportError:
    st.error("⚠️ กรุณาเพิ่ม 'streamlit-back-camera-input' ในไฟล์ requirements.txt")
    st.stop()

# --- CONFIGURATION ---
MAIN_FOLDER_ID = '1FHfyzzTzkK5PaKx6oQeFxTbLEq-Tmii7'
SHEET_ID = '1jNlztb3vfG0c8sw_bMTuA9GEqircx_uVE7uywd5dR2I'
THAI_TZ = pytz.timezone('Asia/Bangkok')

# --- PAGE CONFIG & CSS (UNCHANGED) ---
st.set_page_config(page_title="Smart Picking V2", page_icon="🛒")

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stButton>button {
        width: 100%;
        border-radius: 10px;
        height: 3em;
        font-weight: bold;
    }
    .stSuccess, .stInfo, .stWarning, .stError {
        padding: 1rem;
        border-radius: 10px;
    }
    .dataframe {font-size: 0.8rem !important;}
    </style>
""", unsafe_allow_html=True)

# --- HELPER & AUTH FUNCTIONS (UNCHANGED) ---
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
        return pd.DataFrame()

def check_user_login(scanned_id):
    try:
        creds = get_credentials()
        if not creds: return None, "Auth Error"
        
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        
        try:
            worksheet = sh.worksheet("User")
        except:
            return None, "ไม่พบ Tab ชื่อ 'User'"
            
        data = worksheet.get_all_records()
        df_users = pd.DataFrame(data)
        
        if 'USERNAME' in df_users.columns:
            df_users['USERNAME'] = df_users['USERNAME'].astype(str).str.strip()
        else:
            return None, "ไม่พบคอลัมน์ USERNAME"
            
        scanned_id = str(scanned_id).strip()
        match = df_users[df_users['USERNAME'] == scanned_id]
        
        if not match.empty:
            user_real_name = match.iloc[0].get('Name', 'Unknown')
            return user_real_name, None
        else:
            return None, "ไม่พบรหัสพนักงาน"
            
    except Exception as e:
        return None, f"Error: {e}"

# --- LOG FUNCTION UPDATED: เพิ่ม 'quantity' ในข้อมูลที่บันทึก
def log_to_history(cart_items, order_id, img_count, user_id, user_name):
    try:
        creds = get_credentials()
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        try:
            worksheet = sh.worksheet("History")
        except:
            st.warning("⚠️ ไม่พบ Sheet 'History'")
            return
            
        timestamp = datetime.now(THAI_TZ).strftime("%Y-%m-%d %H:%M:%S")
        
        for item in cart_items:
            # เพิ่ม item['quantity'] ใน row_data
            row_data = [
                timestamp, 
                order_id, 
                item['product_id'], 
                item['location'],   
                item['quantity'],  # <<<<< NEW: บันทึกจำนวน
                img_count,          
                "Success", 
                user_id,            
                user_name           
            ]
            # ตรวจสอบว่าคอลัมน์ใน Sheet 'History' ถูกตั้งค่าให้รับค่า Quantity แล้ว
            worksheet.append_row(row_data)
            
    except Exception as e:
        st.error(f"❌ Log Error: {e}")

def authenticate_drive():
    try:
        creds = get_credentials()
        if creds: return build('drive', 'v3', credentials=creds)
        return None
    except Exception as e:
        st.error(f"Error Drive: {e}")
        return None

def create_or_get_folder(service, folder_name, parent_id):
    query = f"name = '{folder_name}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    if files: return files[0]['id']
    else:
        file_metadata = {'name': folder_name, 'parents': [parent_id], 'mimeType': 'application/vnd.google-apps.folder'}
        folder = service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')

def prepare_destination_folder(service, order_id):
    date_folder_name = datetime.now(THAI_TZ).strftime("%d-%m-%Y")
    date_folder_id = create_or_get_folder(service, date_folder_name, MAIN_FOLDER_ID)
    time_suffix = datetime.now(THAI_TZ).strftime("%H-%M")
    order_folder_name = f"{order_id}_{time_suffix}"
    final_folder_id = create_or_get_folder(service, order_folder_name, date_folder_id)
    return final_folder_id, order_folder_name

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
    st.session_state.photo_gallery = []
    st.session_state.cam_counter += 1
    st.session_state.picked_cart = [] 
    st.session_state.packing_mode = False 
    st.session_state.quantity = 1 # <<<<< NEW: รีเซ็ตจำนวน

# --- UI LOGIC ---
if 'order_val' not in st.session_state: st.session_state.order_val = ""
if 'prod_val' not in st.session_state: st.session_state.prod_val = ""
if 'loc_val' not in st.session_state: st.session_state.loc_val = ""
if 'photo_gallery' not in st.session_state: st.session_state.photo_gallery = []
if 'cam_counter' not in st.session_state: st.session_state.cam_counter = 0
if 'user_name' not in st.session_state: st.session_state.user_name = ""
if 'user_id_raw' not in st.session_state: st.session_state.user_id_raw = "" 
if 'picked_cart' not in st.session_state: st.session_state.picked_cart = []
if 'packing_mode' not in st.session_state: st.session_state.packing_mode = False
if 'quantity' not in st.session_state: st.session_state.quantity = 1 # <<<<< NEW: เพิ่มตัวแปรสำหรับจำนวน

st.title("🛒 ระบบเบิกสินค้า V2.0")
df_items = load_sheet_data()

# 0. LOGIN SECTION (UNCHANGED)
st.markdown("##### 👤 ผู้เบิกสินค้า:")

if not st.session_state.user_name:
    
    # --- CAMERA INPUT ---
    cam_key_user = f"cam_user_{st.session_state.cam_counter}"
    scan_user = back_camera_input("แตะเพื่อสแกนบัตรพนักงาน", key=cam_key_user)
    
    temp_user_id = None
    
    # 1. Processing from Camera (Auto-trigger)
    if scan_user:
        res = decode(Image.open(scan_user))
        if res: temp_user_id = res[0].data.decode("utf-8").strip()
        
    # 2. Manual Input
    manual_user_input = st.text_input("หรือพิมพ์รหัสพนักงาน", key="input_user_manual").strip()

    # 3. Processing from Manual Input (Auto-trigger when pressing Enter/Losing focus)
    if manual_user_input and not temp_user_id:
        temp_user_id = manual_user_input
        
    # --- VALIDATION AND LOGIN ---
    if temp_user_id:
        with st.spinner(f"กำลังตรวจสอบรหัส: {temp_user_id}..."):
            real_name, error_msg = check_user_login(temp_user_id)
            
            if real_name:
                st.session_state.user_name = real_name
                st.session_state.user_id_raw = temp_user_id
                st.rerun()
            else:
                st.error(f"❌ {error_msg}")

    st.warning("⚠️ กรุณาสแกนบัตรหรือใส่รหัสพนักงานเพื่อเข้าสู่ระบบ")
    st.stop() 

else:
    # Login Success
    col_u1, col_u2 = st.columns([3, 1])
    with col_u1:
        st.success(f"👤 สวัสดีครับ: **{st.session_state.user_name}**")
    with col_u2:
        if st.button("เปลี่ยนคน", use_container_width=True):
            st.session_state.user_name = ""
            st.session_state.user_id_raw = ""
            st.rerun()

st.divider()

# 1. ORDER ID (UNCHANGED)
st.markdown("#### 1. Order ID")
if not st.session_state.order_val:
    # --- CAMERA INPUT ---
    cam_key = f"cam_order_{st.session_state.cam_counter}"
    scan_order = back_camera_input("แตะเพื่อเปิดกล้องสแกน Order", key=cam_key)
    if scan_order:
        res = decode(Image.open(scan_order))
        if res:
            st.session_state.order_val = res[0].data.decode("utf-8").upper()
            st.rerun()
            
    # --- MANUAL INPUT ---
    manual_order = st.text_input("หรือพิมพ์ Order ID", key="input_order_manual").strip().upper()
    
    # Auto-trigger when manual input is entered
    if manual_order:
        st.session_state.order_val = manual_order
        st.rerun()
    
else:
    st.info(f"📦 กำลังเบิกออเดอร์: **{st.session_state.order_val}**")
    if not st.session_state.packing_mode:
        if st.button("⚠️ ยกเลิก/เปลี่ยน Order"):
            reset_all_data()
            st.rerun()

# --- LOGIC SEPARATOR: PICKING vs PACKING ---
if st.session_state.order_val and not st.session_state.packing_mode:
    # >>>>> MODE 1: PICKING <<<<<
    st.markdown("---")
    st.markdown(f"#### 2. หยิบสินค้า (รายการที่ {len(st.session_state.picked_cart) + 1})")
    
    # 2.1 SCAN PRODUCT (UNCHANGED)
    if not st.session_state.prod_val:
        cam_key_prod = f"cam_prod_{st.session_state.cam_counter}"
        scan_prod = back_camera_input("แตะเพื่อสแกนสินค้า", key=cam_key_prod)
        if scan_prod:
            res_p = decode(Image.open(scan_prod))
            if res_p:
                st.session_state.prod_val = res_p[0].data.decode("utf-8")
                st.rerun()
        
        manual_prod = st.text_input("หรือพิมพ์ Barcode สินค้า", key="input_prod_manual").strip()
        
        # Auto-trigger when manual input is entered
        if manual_prod:
            st.session_state.prod_val = manual_prod
            st.rerun()
            
    else:
        # 2.2 VERIFY & LOCATION (UNCHANGED)
        target_loc_str = None
        prod_found = False
        prod_name_disp = ""
        
        if not df_items.empty:
            match = df_items[df_items['Barcode'] == st.session_state.prod_val]
            if not match.empty:
                prod_found = True
                row = match.iloc[0]
                zone_val = str(row.get('Zone', '')).strip()
                loc_val = str(row.get('Location', '')).strip()
                target_loc_str = f"{zone_val}-{loc_val}"
                prod_name_disp = row.get('Product Name (1 Variant Name1 ( Variant Name2 ( Quotation name', 'Unknown')
                
                st.success(f"✅ สินค้า: {prod_name_disp}")
                st.warning(f"📍 ไปที่ Location: **{target_loc_str}**")
            else:
                st.error(f"❌ ไม่พบ Barcode: {st.session_state.prod_val}")
                if st.button("สแกนใหม่"):
                    st.session_state.prod_val = ""
                    st.session_state.quantity = 1 # <<<<< NEW: รีเซ็ตจำนวน
                    st.rerun()
        
        # 2.3 CONFIRM LOCATION (UNCHANGED)
        if prod_found and target_loc_str:
            if not st.session_state.loc_val:
                cam_key_loc = f"cam_loc_{st.session_state.cam_counter}"
                scan_loc = back_camera_input("แตะเพื่อสแกน Location ยืนยัน", key=cam_key_loc)
                if scan_loc:
                    res_l = decode(Image.open(scan_loc))
                    if res_l:
                        st.session_state.loc_val = res_l[0].data.decode("utf-8").upper()
                        st.rerun()
                
                manual_loc = st.text_input("หรือพิมพ์ Location", key="input_loc_manual").strip().upper()

                # Auto-trigger when manual input is entered
                if manual_loc:
                    st.session_state.loc_val = manual_loc
                    st.rerun()

            else:
                valid_loc = False
                if st.session_state.loc_val in target_loc_str:
                    st.success(f"✅ ถูกต้อง! ({st.session_state.loc_val})")
                    valid_loc = True
                else:
                    st.error(f"❌ ผิดตำแหน่ง ({st.session_state.loc_val})")
                    if st.button("สแกน Location ใหม่"):
                        st.session_state.loc_val = ""
                        st.rerun()
                
                # 2.4 QUANTITY INPUT & ADD TO CART
                if valid_loc:
                    st.markdown("---")
                    
                    # <<<<< NEW: กล่องใส่จำนวนสินค้า
                    st.session_state.quantity = st.number_input(
                        "จำนวนสินค้าที่หยิบ (ชิ้น)", 
                        min_value=1, 
                        value=st.session_state.quantity, 
                        step=1, 
                        key="input_quantity"
                    )

                    if st.session_state.quantity > 0:
                        if st.button(f"📥 ยืนยันหยิบ {st.session_state.quantity} ชิ้น", type="primary", use_container_width=True):
                            item_data = {
                                "product_id": st.session_state.prod_val,
                                "product_name": prod_name_disp,
                                "location": st.session_state.loc_val,
                                "quantity": st.session_state.quantity, # <<<<< NEW: บันทึกจำนวน
                                "time": datetime.now(THAI_TZ).strftime("%H:%M:%S")
                            }
                            st.session_state.picked_cart.append(item_data)
                            
                            # รีเซ็ตค่าเพื่อเริ่มหยิบรายการถัดไป
                            st.session_state.prod_val = ""
                            st.session_state.loc_val = ""
                            st.session_state.quantity = 1 # <<<<< NEW: ตั้งจำนวนเริ่มต้นใหม่
                            st.session_state.cam_counter += 1
                            
                            st.toast(f"หยิบใส่ตะกร้าแล้ว ({len(st.session_state.picked_cart)} รายการ)")
                            time.sleep(0.5)
                            st.rerun()
                    else:
                         st.warning("กรุณากรอกจำนวนสินค้า")


    # --- SHOW CART & PROCEED BUTTON ---
    if st.session_state.picked_cart:
        st.divider()
        st.markdown(f"##### 🛒 รายการที่หยิบแล้ว ({len(st.session_state.picked_cart)} รายการ)")
        df_cart = pd.DataFrame(st.session_state.picked_cart)
        # แสดงคอลัมน์ Quantity ในตาราง
        st.dataframe(df_cart[['product_id', 'quantity', 'location', 'product_name']], use_container_width=True, hide_index=True)
        
        st.divider()
        col_act1, col_act2 = st.columns(2)
        with col_act2:
            if st.button("📦 ไปขั้นตอนแพ็คสินค้า ➡️", type="primary", use_container_width=True):
                st.session_state.packing_mode = True
                st.rerun()

elif st.session_state.order_val and st.session_state.packing_mode:
    # >>>>> MODE 2: PACKING (UNCHANGED) <<<<<
    st.markdown("---")
    st.info("✅ หยิบครบแล้ว เข้าสู่ขั้นตอนแพ็คสินค้า")
    st.markdown(f"#### 3. ถ่ายรูปปิดกล่อง ({len(st.session_state.photo_gallery)}/5)")
    
    # 3.1 CAMERA (ใช้ back_camera_input เพื่อให้กล้องหลังทำงาน)
    if len(st.session_state.photo_gallery) < 5:
        pack_key = f"cam_pack_{st.session_state.cam_counter}"
        pack_img = back_camera_input("แตะเพื่อถ่ายรูปกล่องสินค้า", key=pack_key)
        
        # --- NEW BUTTON: ถ่ายรูป (Visual Cue) ---
        if st.button("📸 ถ่ายรูป", key='btn_take_photo', use_container_width=True):
            st.info("💡 กรุณาแตะที่กล้องด้านบนเพื่อเปิดกล้อง และกด 'Capture' ภายใน Browser/App กล้องของมือถือ")
        
        if pack_img:
            st.session_state.photo_gallery.append(pack_img.getvalue())
            st.session_state.cam_counter += 1
            st.rerun()
    else:
        st.info("📷 ครบ 5 รูปแล้ว")

    # 3.2 GALLERY
    if st.session_state.photo_gallery:
        st.markdown("##### รายการรูปที่รออัปโหลด:")
        cols = st.columns(5)
        for idx, img_data in enumerate(st.session_state.photo_gallery):
            with cols[idx]:
                st.image(img_data, caption=f"รูป {idx+1}", use_column_width=True)
                if st.button("🗑️", key=f"del_{idx}"):
                    st.session_state.photo_gallery.pop(idx)
                    st.rerun()

    # 3.3 UPLOAD (FINAL STEP)
    if len(st.session_state.photo_gallery) > 0:
        st.markdown("---")
        upload_placeholder = st.empty()
        
        if upload_placeholder.button(f"☁️ บันทึกงานและอัปโหลด", type="primary", use_container_width=True):
            upload_placeholder.empty()
            
            with st.spinner("กำลังอัปโหลด... ห้ามปิดหน้านี้"):
                srv = authenticate_drive()
                if srv:
                    target_fid, folder_name = prepare_destination_folder(srv, st.session_state.order_val)
                    ts_str = datetime.now(THAI_TZ).strftime("%H%M%S")
                    
                    for i, img_bytes in enumerate(st.session_state.photo_gallery):
                        fn = f"{st.session_state.order_val}_PACKED_{ts_str}_Img{i+1}.jpg"
                        upload_photo(srv, img_bytes, fn, target_fid)
                    
                    # เรียกใช้ฟังก์ชัน Log ที่ถูกปรับปรุงแล้ว
                    log_to_history(
                        st.session_state.picked_cart,
                        st.session_state.order_val,
                        len(st.session_state.photo_gallery),
                        st.session_state.user_id_raw,
                        st.session_state.user_name
                    )
                    
                    st.balloons()
                    st.success(f"✅ บันทึกสำเร็จ! โดย: {st.session_state.user_name}")
                    time.sleep(2)
                    reset_all_data()
                    st.rerun()

st.markdown("---")
if st.button("🔄 ยกเลิกทั้งหมด (Reset)", type="secondary", use_container_width=True):
    reset_all_data()
    st.rerun()
