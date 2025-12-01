import streamlit as st
import pandas as pd
import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from datetime import datetime
from PIL import Image
from pyzbar.pyzbar import decode
from google.oauth2.credentials import Credentials
import requests

# --- CONFIGURATION ---
MAIN_FOLDER_ID = '1FHfyzzTzkK5PaKx6oQeFxTbLEq-Tmii7'
SHEET_ID = '1jNlztb3vfG0c8sw_bMTuA9GEqircx_uVE7uywd5dR2I'

# --- HELPER: GET CREDENTIALS ---
def get_credentials(scopes=None): # scopes ไม่จำเป็นแล้วสำหรับ refresh token แต่ใส่ไว้กัน error
    try:
        # ดึงค่าจาก Secrets
        info = st.secrets["oauth"]
        
        # สร้าง Credentials จาก Refresh Token
        creds = Credentials(
            None, # token (access token ชั่วคราว เดี๋ยว library เจนใหม่ให้เอง)
            refresh_token=info["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=info["client_id"],
            client_secret=info["client_secret"]
        )
        return creds
    except Exception as e:
        st.error(f"❌ Login ไม่ได้: {e}")
        return None

# --- FUNCTION: GOOGLE SHEET ---
@st.cache_data(ttl=600)
def load_sheet_data():
    try:
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        
        creds = get_credentials(scopes)
        if not creds: return pd.DataFrame() # จบการทำงานถ้าไม่มีกุญแจ
        
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
        # st.error(f"❌ อ่าน Google Sheet ไม่ได้: {e}") # ปิด error นี้ไว้ก่อนถ้าไม่อยากให้รก
        print(f"Sheet Error: {e}")
        return pd.DataFrame()

# --- FUNCTION: GOOGLE DRIVE ---
def authenticate_drive():
    try:
        scopes = ['https://www.googleapis.com/auth/drive']
        creds = get_credentials(scopes)
        return build('drive', 'v3', credentials=creds)
    except Exception as e:
        st.error(f"Error Drive: {e}")
        return None

def create_or_get_order_folder(service, order_id, parent_id):
    query = f"name = '{order_id}' and '{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])
    if files: return files[0]['id']
    else:
        file_metadata = {'name': order_id, 'parents': [parent_id], 'mimeType': 'application/vnd.google-apps.folder'}
        folder = service.files().create(body=file_metadata, fields='id').execute()
        return folder.get('id')

def upload_photo(service, file_obj, filename, folder_id):
    try:
        file_metadata = {'name': filename, 'parents': [folder_id]}
        media = MediaIoBaseUpload(file_obj, mimetype='image/jpeg')
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return file.get('id')
    except Exception as e:
        # สั่งให้ Print รายละเอียด Error ออกมาทางหน้าจอเลย
        st.error(f"🔴 เกิดข้อผิดพลาดในการอัปโหลด: {e}")
        # ถ้ามีรายละเอียดเพิ่มเติมจาก Google ให้โชว์ด้วย
        if hasattr(e, 'content'):
            st.code(e.content.decode('utf-8')) # แสดง JSON error เต็มๆ
        raise e # ส่ง error ต่อให้โปรแกรมหยุดทำงานตามปกติ

# --- UI SETUP ---
st.set_page_config(page_title="Smart Picking w/ Sheet", page_icon="📊")

if 'order_val' not in st.session_state: st.session_state.order_val = ""
if 'prod_val' not in st.session_state: st.session_state.prod_val = ""
if 'loc_val' not in st.session_state: st.session_state.loc_val = ""

st.title("📊 ระบบเบิกสินค้า (Cloud Ready)")

# โหลดข้อมูล
df_items = load_sheet_data()

# 1. ORDER
st.markdown("#### 1. Order ID")
col_o1, col_o2 = st.columns([4, 1])
with col_o2:
    use_cam_order = st.checkbox("📷", key="tog_order")

if use_cam_order:
    scan_order = st.camera_input("Scan Order", key="cam_order")
    if scan_order:
        res = decode(Image.open(scan_order))
        if res:
            st.session_state.order_val = res[0].data.decode("utf-8").upper()
            st.rerun()

order_input = col_o1.text_input("Scan/พิมพ์ Order ID", value=st.session_state.order_val, key="input_order").strip().upper()

# 2. PRODUCT
if order_input:
    st.session_state.order_val = order_input
    st.markdown("---")
    st.markdown("#### 2. Scan สินค้า")

    col_p1, col_p2 = st.columns([4, 1])
    with col_p2:
        use_cam_prod = st.checkbox("📷", key="tog_prod")
    
    if use_cam_prod:
        scan_prod = st.camera_input("Scan Product", key="cam_prod")
        if scan_prod:
            res_p = decode(Image.open(scan_prod))
            if res_p:
                st.session_state.prod_val = res_p[0].data.decode("utf-8")
                st.rerun()

    prod_input = col_p1.text_input("Scan Barcode สินค้า", value=st.session_state.prod_val, key="input_prod").strip()

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
             st.warning("⚠️ กำลังเชื่อมต่อฐานข้อมูล...")

    # 3. LOCATION
    if prod_input and target_loc_str:
        st.markdown("---")
        st.markdown(f"#### 3. ยืนยัน Location: `{target_loc_str}`")
        
        col_l1, col_l2 = st.columns([4, 1])
        with col_l2:
            use_cam_loc = st.checkbox("📷", key="tog_loc")
            
        if use_cam_loc:
            scan_loc = st.camera_input("Scan Location", key="cam_loc")
            if scan_loc:
                res_l = decode(Image.open(scan_loc))
                if res_l:
                    st.session_state.loc_val = res_l[0].data.decode("utf-8").upper()
                    st.rerun()

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
                st.error(f"❌ ผิดตำแหน่ง")

        # 4. PACK
        if valid_loc:
            st.markdown("---")
            final_img = st.camera_input("ถ่ายรูปปิดกล่อง", key="cam_final")
            
            if final_img:
                if st.button("☁️ Upload", type="primary"):
                    with st.spinner("Uploading..."):
                        srv = authenticate_drive()
                        if srv:
                            fid = create_or_get_order_folder(srv, order_input, MAIN_FOLDER_ID)
                            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                            fn = f"{order_input}_{prod_input}_LOC-{loc_input_val}_{ts}.jpg"
                            upload_photo(srv, final_img, fn, fid)
                            st.balloons()
                            st.success("บันทึกเรียบร้อย!")
                            st.session_state.prod_val = ""
                            st.session_state.loc_val = ""
                            st.rerun()


