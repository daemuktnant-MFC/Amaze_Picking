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

# --- IMPORT LIBRARY กล้องตัวพิเศษ ---
try:
    from streamlit_back_camera_input import back_camera_input
except ImportError:
    st.error("⚠️ กรุณาเพิ่ม 'streamlit-back-camera-input' ในไฟล์ requirements.txt")
    st.stop()

# --- CONFIGURATION ---
MAIN_FOLDER_ID = '1FHfyzzTzkK5PaKx6oQeFxTbLEq-Tmii7'
SHEET_ID = '1jNlztb3vfG0c8sw_bMTuA9GEqircx_uVE7uywd5dR2I'
THAI_TZ = pytz.timezone('Asia/Bangkok')

# --- PAGE CONFIG & CSS ---
st.set_page_config(page_title="Smart Picking (Pro)", page_icon="📦")

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
    </style>
""", unsafe_allow_html=True)

# --- HELPER & AUTH FUNCTIONS ---
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

def log_to_history(order_id, product_id, location, img_count, user_name):
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
        row_data = [timestamp, order_id, product_id, location, img_count, "Success", user_name]
        
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
    # ไม่ล้าง user_name

# --- UI LOGIC ---
if 'order_val' not in st.session_state: st.session_state.order_val = ""
if 'prod_val' not in st.session_state: st.session_state.prod_val = ""
if 'loc_val' not in st.session_state: st.session_state.loc_val = ""
if 'photo_gallery' not in st.session_state: st.session_state.photo_gallery = []
if 'cam_counter' not in st.session_state: st.session_state.cam_counter = 0
if 'user_name' not in st.session_state: st.session_state.user_name = ""

st.title("📦 ระบบเบิกสินค้า")
df_items = load_sheet_data()

# --- 0. USER INPUT (SCAN & MANUAL) ---
st.markdown("##### 👤 ผู้เบิกสินค้า:")

if not st.session_state.user_name:
    # 1. กล้องสแกนบัตร (อยู่บน)
    cam_key_user = f"cam_user_{st.session_state.cam_counter}"
    scan_user = back_camera_input("แตะเพื่อสแกนบัตรพนักงาน", key=cam_key_user)
    if scan_user:
        res = decode(Image.open(scan_user))
        if res:
            st.session_state.user_name = res[0].data.decode("utf-8")
            st.rerun()

    # 2. ช่องพิมพ์ชื่อ (อยู่ล่าง)
    manual_user = st.text_input("หรือพิมพ์ชื่อ/รหัสพนักงาน", key="input_user_manual").strip()
    if manual_order := manual_user: # walrus operator for cleaner check
        st.session_state.user_name = manual_user
        st.rerun()

    # หยุดระบบถ้ายังไม่มี user
    st.warning("⚠️ กรุณาระบุชื่อ/สแกนบัตรผู้เบิกสินค้าก่อนเริ่มงาน")
    st.stop() 

else:
    # ถ้ามี User แล้ว โชว์ชื่อและปุ่มเปลี่ยนคน
    col_u1, col_u2 = st.columns([3, 1])
    with col_u1:
        st.success(f"👤 พนักงาน: **{st.session_state.user_name}**")
    with col_u2:
        if st.button("เปลี่ยนคน", use_container_width=True):
            st.session_state.user_name = ""
            st.rerun()

st.divider()

# 1. ORDER
st.markdown("#### 1. Order ID")
if not st.session_state.order_val:
    cam_key = f"cam_order_{st.session_state.cam_counter}"
    scan_order = back_camera_input("แตะเพื่อเปิดกล้องสแกน Order", key=cam_key)
    if scan_order:
        res = decode(Image.open(scan_order))
        if res:
            st.session_state.order_val = res[0].data.decode("utf-8").upper()
            st.rerun()
    manual_order = st.text_input("หรือพิมพ์ Order ID", key="input_order_manual").strip().upper()
    if manual_order:
        st.session_state.order_val = manual_order
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
        cam_key_prod = f"cam_prod_{st.session_state.cam_counter}"
        scan_prod = back_camera_input("แตะเพื่อเปิดกล้องสแกนสินค้า", key=cam_key_prod)
        if scan_prod:
            res_p = decode(Image.open(scan_prod))
            if res_p:
                st.session_state.prod_val = res_p[0].data.decode("utf-8")
                st.rerun()
        manual_prod = st.text_input("หรือพิมพ์ Barcode สินค้า", key="input_prod_manual").strip()
        if manual_prod:
            st.session_state.prod_val = manual_prod
            st.rerun()
    else:
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
        
        if st.button("✏️ สแกนสินค้าใหม่"):
            st.session_state.prod_val = ""
            st.session_state.loc_val = "" 
            st.rerun()

        # 3. LOCATION
        if prod_found and target_loc_str:
            st.markdown("---")
            st.markdown(f"#### 3. ยืนยัน Location")
            if not st.session_state.loc_val:
                cam_key_loc = f"cam_loc_{st.session_state.cam_counter}"
                scan_loc = back_camera_input("แตะเพื่อเปิดกล้องสแกน Location", key=cam_key_loc)
                if scan_loc:
                    res_l = decode(Image.open(scan_loc))
                    if res_l:
                        st.session_state.loc_val = res_l[0].data.decode("utf-8").upper()
                        st.rerun()
                manual_loc = st.text_input("หรือสแกน/พิมพ์ Location", key="input_loc_manual").strip().upper()
                if manual_loc:
                    st.session_state.loc_val = manual_loc
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
                    if st.button("สแกน Location ใหม่"):
                        st.session_state.loc_val = ""
                        st.rerun()

                # 4. PACKING & UPLOAD
                if valid_loc:
                    st.markdown("---")
                    st.markdown(f"#### 4. ถ่ายรูปปิดกล่อง ({len(st.session_state.photo_gallery)}/5)")
                    
                    if len(st.session_state.photo_gallery) < 5:
                        pack_key = f"cam_pack_{st.session_state.cam_counter}"
                        pack_img = back_camera_input("แตะเพื่อถ่ายรูปสินค้า", key=pack_key)
                        if pack_img:
                            st.session_state.photo_gallery.append(pack_img.getvalue())
                            st.session_state.cam_counter += 1
                            st.rerun()
                    else:
                        st.info("📷 ครบ 5 รูปแล้ว")

                    if st.session_state.photo_gallery:
                        st.markdown("##### รายการรูปที่รออัปโหลด:")
                        cols = st.columns(5)
                        for idx, img_data in enumerate(st.session_state.photo_gallery):
                            with cols[idx]:
                                st.image(img_data, caption=f"รูป {idx+1}", use_column_width=True)
                                if st.button("🗑️", key=f"del_{idx}"):
                                    st.session_state.photo_gallery.pop(idx)
                                    st.rerun()

                    if len(st.session_state.photo_gallery) > 0:
                        st.markdown("---")
                        upload_placeholder = st.empty()
                        
                        if upload_placeholder.button(f"☁️ Upload {len(st.session_state.photo_gallery)} รูป", type="primary", use_container_width=True):
                            upload_placeholder.empty()
                            
                            with st.spinner("กำลังอัปโหลด... ห้ามปิดหน้านี้"):
                                srv = authenticate_drive()
                                if srv:
                                    target_fid, folder_name = prepare_destination_folder(srv, st.session_state.order_val)
                                    ts_str = datetime.now(THAI_TZ).strftime("%H%M%S")
                                    
                                    for i, img_bytes in enumerate(st.session_state.photo_gallery):
                                        fn = f"{st.session_state.order_val}_{st.session_state.prod_val}_LOC-{st.session_state.loc_val}_{ts_str}_Img{i+1}.jpg"
                                        upload_photo(srv, img_bytes, fn, target_fid)
                                    
                                    log_to_history(
                                        st.session_state.order_val,
                                        st.session_state.prod_val,
                                        st.session_state.loc_val,
                                        len(st.session_state.photo_gallery),
                                        st.session_state.user_name
                                    )
                                    
                                    st.balloons()
                                    st.success(f"✅ บันทึกสำเร็จ! โดย: {st.session_state.user_name}")
                                    time.sleep(2)
                                    reset_all_data()
                                    st.rerun()

st.markdown("---")
if st.button("🔄 เริ่มใหม่ทั้งหมด", type="secondary", use_container_width=True):
    reset_all_data()
    st.rerun()
