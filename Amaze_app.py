import streamlit as st
import pandas as pd
import gspread
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from datetime import datetime
from PIL import Image
from pyzbar.pyzbar import decode


# --- CONFIGURATION ---
MAIN_FOLDER_ID = '1FHfyzzTzkK5PaKx6oQeFxTbLEq-Tmii7'
SHEET_ID = '1jNlztb3vfG0c8sw_bMTuA9GEqircx_uVE7uywd5dR2I' # ID จาก URL รูปภาพของคุณ
CREDENTIALS_FILE = 'service_account.json'

# --- FUNCTION: เชื่อมต่อ GOOGLE SHEET (Master Data) ---
@st.cache_data(ttl=600)
def load_sheet_data():
    try:
        # --- วิธีใหม่ (ง่ายกว่า) ---
        # ไม่ต้องกำหนด scope เอง ให้ gspread จัดการให้
        gc = gspread.service_account(filename=CREDENTIALS_FILE)
        
        # เปิดไฟล์ Sheet
        sh = gc.open_by_key(SHEET_ID)
        worksheet = sh.get_worksheet(0) 
        
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        
        # แปลง Barcode เป็น Text (ถ้ามี column นี้)
        if 'Barcode' in df.columns:
            # ใช้ try-except ย่อยเผื่อกรณีข้อมูล Barcode บางช่องไม่ใช่ตัวเลข
            try:
                df['Barcode'] = df['Barcode'].astype(str).str.replace(r'\.0$', '', regex=True)
            except:
                df['Barcode'] = df['Barcode'].astype(str)
            
        return df
    except Exception as e:
        # สำคัญ: Print Error ออกมาดูที่ Terminal ด้วยเผื่อในเว็บอ่านยาก
        print(f"DEBUG ERROR: {e}") 
        st.error(f"❌ อ่าน Google Sheet ไม่ได้: {e}")
        return pd.DataFrame()

# --- FUNCTION: GOOGLE DRIVE ---
def authenticate_drive():
    try:
        #creds = service_account.Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=['https://www.googleapis.com/auth/drive'])
        key_dict = dict(st.secrets["gcp_service_account"])

        creds = service_account.Credentials.from_service_account_info(key_dict, scopes=['https://www.googleapis.com/auth/drive'])
        
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
    file_metadata = {'name': filename, 'parents': [folder_id]}
    media = MediaIoBaseUpload(file_obj, mimetype='image/jpeg')
    file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    return file.get('id')

# --- UI SETUP ---
st.set_page_config(page_title="Smart Picking w/ Sheet", page_icon="📊")

if 'order_val' not in st.session_state: st.session_state.order_val = ""
if 'prod_val' not in st.session_state: st.session_state.prod_val = ""
if 'loc_val' not in st.session_state: st.session_state.loc_val = ""

st.title("📊 ระบบเบิกสินค้า (Master Sheet)")

# โหลดข้อมูลจาก Google Sheet
df_items = load_sheet_data()

# ==========================================
# 1️⃣ STEP 1: ระบุ ORDER (เพื่อสร้าง Folder)
# ==========================================
st.markdown("#### 1. Order ID (สำหรับตั้งชื่อ Folder)")
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

# ==========================================
# 2️⃣ STEP 2: SCAN สินค้า -> ดึง LOCATION
# ==========================================
if order_input:
    st.session_state.order_val = order_input
    st.markdown("---")
    st.markdown("#### 2. Scan Barcode สินค้า (เพื่อดึง Location)")

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

    # LOGIC: เช็คสินค้ากับ Google Sheet
    target_loc_str = None # ตัวแปรเก็บ Location เป้าหมาย
    
    if prod_input:
        if not df_items.empty:
            # ค้นหา Barcode ใน DataFrame
            match = df_items[df_items['Barcode'] == prod_input]
            
            if not match.empty:
                # เจอสินค้า! ดึงข้อมูลมาแสดง
                row = match.iloc[0]
                
                # รวม Zone และ Location เข้าด้วยกัน (เช่น AMZ01-3507)
                # ต้องเช็คชื่อ Column ให้ตรงกับใน Sheet: 'Zone' และ 'Location'
                zone_val = str(row.get('Zone', '')).strip()
                loc_val = str(row.get('Location', '')).strip()
                target_loc_str = f"{zone_val}-{loc_val}"
                
                prod_name = row.get('Product Name (1 Variant Name1 ( Variant Name2 ( Quotation name', 'Unknown Product') 
                # ^ ชื่อ Column ในรูปยาวมาก ผมใส่เผื่อไว้ ถ้าไม่เจอจะขึ้น Unknown

                st.success(f"✅ พบสินค้า: {prod_name}")
                st.info(f"📍 **ต้องไปหยิบที่ (Zone-Loc): {target_loc_str}**")
                
            else:
                st.error(f"❌ ไม่พบ Barcode '{prod_input}' ใน Google Sheet (ตรวจสอบไฟล์ Item_Data)")
        else:
            st.warning("กำลังโหลดข้อมูล หรือ อ่านไฟล์ Sheet ไม่ได้")

    # ==========================================
    # 3️⃣ STEP 3: SCAN LOCATION (ยืนยัน)
    # ==========================================
    if prod_input and target_loc_str: # จะทำขั้นตอนนี้ได้ ต้องเจอสินค้าก่อน
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

        # ช่อง Scan Location (ใส่ค่าอัตโนมัติจากที่ Scan)
        loc_input_val = col_l1.text_input("ยิง Barcode ที่ชั้นวาง", value=st.session_state.loc_val, key="input_loc").strip().upper()

        # ตรวจสอบว่าตรงกับเป้าหมายไหม (Logic นี้ยืดหยุ่นได้)
        # เช่น ถ้าเป้าหมายคือ AMZ01-3507 แต่ Barcode ที่ชั้นแปะแค่ 3507 อาจต้องเขียน Code ตัดคำเพิ่ม
        # เบื้องต้นเอาแบบ ตรงกันเป๊ะๆ ก่อน
        
        valid_loc = False
        if loc_input_val:
            if loc_input_val == target_loc_str:
                st.success("✅ ถูกต้อง! Location ตรงกัน")
                valid_loc = True
            elif loc_input_val in target_loc_str: # อนุโลมให้ถ้า Scan มาแค่บางส่วนของชื่อ
                st.warning(f"⚠️ ใกล้เคียง (Scan: {loc_input_val} / Target: {target_loc_str}) - ยอมให้ผ่าน")
                valid_loc = True
            else:
                st.error(f"❌ ผิดตำแหน่ง (คุณอยู่ที่: {loc_input_val} / ต้องไปที่: {target_loc_str})")

        # ==========================================
        # 4️⃣ STEP 4: ถ่ายรูป PACK
        # ==========================================
        if valid_loc:
            st.markdown("---")
            st.markdown("#### 4. ถ่ายรูปปิดกล่อง")
            final_img = st.camera_input("Pack Shot", key="cam_final")
            
            if final_img:
                if st.button("☁️ Upload to Drive", type="primary"):
                    with st.spinner("Uploading..."):
                        srv = authenticate_drive()
                        if srv:
                            fid = create_or_get_order_folder(srv, order_input, MAIN_FOLDER_ID)
                            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                            
                            # ตั้งชื่อไฟล์แบบละเอียด
                            fn = f"{order_input}_{prod_input}_LOC-{loc_input_val}_{ts}.jpg"
                            
                            upload_photo(srv, final_img, fn, fid)
                            st.balloons()
                            st.success(f"บันทึกเรียบร้อย! ({fn})")
                            
                            # Reset ค่าเพื่อเตรียมชิ้นต่อไป (แต่เก็บ Order ไว้)
                            st.session_state.prod_val = ""
                            st.session_state.loc_val = ""

                            st.rerun()
