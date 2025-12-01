import streamlit as st
import pandas as pd
from datetime import datetime
from streamlit.connections import SQLConnection
# ลบ qrcode_scanner ออก เพราะเราจะใช้ camera_input + pyzbar แทน
# from streamlit_qrcode_scanner import qrcode_scanner 
import uuid
import pytz
from sqlalchemy import text
import numpy as np
from PIL import Image
from pyzbar.pyzbar import decode 

# --- (CSS เดิมของคุณ - คงไว้เหมือนเดิม) ---
st.markdown("""
<style>
/* ... (CSS เดิมของคุณ ใส่ไว้ตรงนี้เหมือนเดิม) ... */
div.block-container {
    padding-top: 1rem; padding-bottom: 1rem;
    padding-left: 1rem; padding-right: 1rem;
}
/* ... */
</style>
""", unsafe_allow_html=True)
# --- จบ Custom CSS ---

# --- 1. ตั้งค่าหน้าจอและเชื่อมต่อ Supabase ---
st.set_page_config(page_title="Box Scanner", layout="wide")
st.title("📦 สแกนแปะ Tracking")

@st.cache_resource
def init_supabase_connection():
    return st.connection("supabase", type=SQLConnection)

supabase_conn = init_supabase_connection()

# --- 2. Session State ---
# (State เดิมของคุณ คงไว้ทั้งหมด)
if "current_user" not in st.session_state: st.session_state.current_user = ""
if "scan_count" not in st.session_state: st.session_state.scan_count = 0 
if "staged_scans" not in st.session_state: st.session_state.staged_scans = [] 
if "scanner_key" not in st.session_state: st.session_state.scanner_key = "scanner_v1"
if "last_scan_processed" not in st.session_state: st.session_state.last_scan_processed = ""

if "temp_barcode" not in st.session_state: st.session_state.temp_barcode = "" 
if "show_duplicate_tracking_error" not in st.session_state: st.session_state.show_duplicate_tracking_error = False 
if "last_scanned_tracking" not in st.session_state: st.session_state.last_scanned_tracking = "" 
if "show_user_not_found_error" not in st.session_state: st.session_state.show_user_not_found_error = False
if "last_failed_user_scan" not in st.session_state: st.session_state.last_failed_user_scan = ""
if "selected_user_to_edit" not in st.session_state: st.session_state.selected_user_to_edit = None
if "scan_mode" not in st.session_state: st.session_state.scan_mode = None 

if "temp_tracking" not in st.session_state: st.session_state.temp_tracking = ""
if "show_dialog_for" not in st.session_state: st.session_state.show_dialog_for = None 
if "show_scan_error_message" not in st.session_state: st.session_state.show_scan_error_message = False

# --- 3. Functions ---
# (คง Function เดิมไว้ทั้งหมด ยกเว้นส่วนที่ต้องเพิ่ม Helper function ในการอ่าน Barcode)

def read_barcode_from_image(img_file):
    """ฟังก์ชันช่วยอ่าน Barcode จากรูปภาพ"""
    if img_file is None:
        return None
    try:
        image = Image.open(img_file)
        decoded_objects = decode(image)
        if decoded_objects:
            # คืนค่า Barcode แรกที่เจอ และแปลงเป็น string
            return decoded_objects[0].data.decode("utf-8").strip()
        return None
    except Exception as e:
        st.error(f"Error reading barcode: {e}")
        return None

def delete_item(item_id_to_delete):
    st.session_state.staged_scans = [
        item for item in st.session_state.staged_scans 
        if item["id"] != item_id_to_delete
    ]

def set_scan_mode(mode):
    st.session_state.scan_mode = mode

def clear_all_and_restart():
    st.session_state.current_user = ""
    st.session_state.staged_scans = []
    st.session_state.scanner_key = f"scanner_{uuid.uuid4()}" 
    st.session_state.last_scan_processed = ""
    st.session_state.show_user_not_found_error = False
    st.session_state.last_failed_user_scan = ""
    st.session_state.temp_barcode = ""
    st.session_state.show_duplicate_tracking_error = False
    st.session_state.last_scanned_tracking = ""
    st.session_state.temp_tracking = ""
    st.session_state.show_dialog_for = None 
    st.session_state.show_scan_error_message = False
    st.session_state.scan_mode = None 

def acknowledge_error_and_reset_scanner():
    st.session_state.show_user_not_found_error = False
    st.session_state.last_failed_user_scan = ""
    st.session_state.show_duplicate_tracking_error = False
    st.session_state.last_scanned_tracking = ""
    st.session_state.scanner_key = f"scanner_{uuid.uuid4()}"
    st.session_state.last_scan_processed = ""

def validate_and_lock_user(user_id_to_check):
    if not user_id_to_check: return False
    try:
        query = "SELECT COUNT(1) as count FROM user_data WHERE user_id = :user_id"
        params = {"user_id": user_id_to_check}
        result_df = supabase_conn.query(query, params=params, ttl=60) 
        
        if not result_df.empty and result_df['count'][0] > 0:
            st.session_state.current_user = user_id_to_check
            st.success(f"User: {user_id_to_check} ถูกล็อคแล้ว")
            st.session_state.show_user_not_found_error = False
            return True
        else:
            st.session_state.show_user_not_found_error = True
            st.session_state.last_failed_user_scan = user_id_to_check
            return False
    except Exception as e:
        st.error(f"Error checking user: {e}")
        return False

def check_tracking_exists(tracking_code):
    if not tracking_code: return False
    try:
        query = "SELECT COUNT(1) as count FROM scans WHERE tracking_code = :tracking"
        params = {"tracking": tracking_code}
        df = supabase_conn.query(query, params=params, ttl=0)
        return not df.empty and df['count'][0] > 0
    except Exception as e:
        st.error(f"Error Checking DB: {e}")
        return False

def add_and_clear_staging():
    if st.session_state.temp_tracking and st.session_state.temp_barcode:
        st.session_state.staged_scans.append({
            "id": str(uuid.uuid4()),
            "tracking": st.session_state.temp_tracking,
            "barcode": st.session_state.temp_barcode
        })
        st.session_state.temp_tracking = ""
        st.session_state.temp_barcode = "" 
        st.session_state.show_dialog_for = None 
    st.rerun() 

@st.dialog("✅ สแกนสำเร็จ")
def show_confirmation_dialog(is_tracking):
    code_type = "Tracking Number" if is_tracking else "Barcode สินค้า"
    code_value = st.session_state.temp_tracking if is_tracking else st.session_state.temp_barcode
    st.info(f"ยืนยัน {code_type} ที่สแกนได้:")
    st.code(code_value)
    if is_tracking:
        st.warning("ขั้นต่อไป: กด 'ปิด' แล้วสแกน Barcode")
        if st.button("ปิด (และเตรียมสแกน Barcode)"):
            st.session_state.show_dialog_for = None
            st.rerun()
    else:
        st.success("Barcode ถูกสแกนและยืนยันแล้ว!")
        st.warning("ข้อมูลจะถูกเพิ่มลงในรายการทันที")
        if st.button("ปิด (และเพิ่มลงในรายการ)"):
            st.session_state.show_dialog_for = 'staging' 
            st.rerun()

def save_all_to_db():
    if not st.session_state.staged_scans:
        st.warning("ไม่มีข้อมูลในรายการให้บันทึก")
        return
    if not st.session_state.current_user:
         st.error("ไม่พบชื่อผู้ใช้งาน!")
         return
    
    try:
        data_to_insert = []
        THAI_TZ = pytz.timezone("Asia/Bangkok")
        current_time = datetime.now(THAI_TZ)
        
        for item in st.session_state.staged_scans:
            data_to_insert.append({
                "user_id": st.session_state.current_user,
                "tracking_code": item["tracking"],
                "product_barcode": item["barcode"], 
                "created_at": current_time.replace(tzinfo=None) 
            })
        
        df_to_insert = pd.DataFrame(data_to_insert)
        
        with supabase_conn.session as session:
            df_to_insert.to_sql("scans", con=session.connection(), if_exists="append", index=False)
            session.commit()
        
        saved_count = len(st.session_state.staged_scans)
        st.session_state.scan_count += saved_count 
        st.success(f"บันทึกข้อมูลทั้ง {saved_count} รายการ สำเร็จ!")
        clear_all_and_restart()
        
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการบันทึก: {e}")

# --- 4. Tabs ---
tab1, tab2 = st.tabs(["📷 สแกนกล่อง", "📊 ดูข้อมูลและดาวน์โหลด"])

with tab1:
    if st.session_state.scan_mode is None:
        st.header("เลือก Menu")
        st.button("โหมด Bulk (1 Barcode ➔ หลาย Trackings)", on_click=set_scan_mode, args=("Bulk",), use_container_width=True, type="primary")
        st.button("โหมด Single (1 Tracking ➔ 1 Barcode)", on_click=set_scan_mode, args=("Single",), use_container_width=True)
        st.divider()
        st.metric("กล่องที่บันทึกไปแล้ว (รอบนี้)", st.session_state.scan_count)
        if st.session_state.scan_count > 0:
            if st.button("ล้าง Scan Count"):
                st.session_state.scan_count = 0
                st.rerun()

    elif st.session_state.scan_mode is not None and not st.session_state.current_user:
        mode_name = "โหมด Bulk" if st.session_state.scan_mode == "Bulk" else "โหมด Single"
        st.header(f"{mode_name}")
        
        scanner_prompt_placeholder = st.empty()
        
        # --- 🟢 (แก้) เปลี่ยน qrcode_scanner เป็น st.camera_input + pyzbar ---
        img_file = st.camera_input("📸 ถ่ายรูป QR/Barcode User", key=st.session_state.scanner_key)
        scan_value = read_barcode_from_image(img_file)
        # -------------------------------------------------------------
        
        st.button("🔙 กลับ Menu หลัก", on_click=clear_all_and_restart, key="back_menu_1")

        with st.expander("คีย์ User ID (กรณีสแกนไม่ได้)"):
            with st.form(key="manual_user_form"):
                manual_user_id = st.text_input("ป้อน User ID:")
                manual_user_submit = st.form_submit_button("ล็อค User")

            if manual_user_submit:
                if manual_user_id:
                    manual_user_id = manual_user_id.strip()
                    if validate_and_lock_user(manual_user_id):
                        st.session_state.last_scan_processed = manual_user_id 
                        st.rerun() 
                else:
                    st.warning("กรุณาป้อน User ID")

        # Logic ตรวจสอบค่า Scan
        is_new_scan = (scan_value is not None)
        
        if is_new_scan:
            # ถ้าอ่านค่าได้ ให้ทำงานเหมือนเดิม
            if validate_and_lock_user(scan_value):
                 # รีเซ็ตกล้องหลังจากสแกนสำเร็จ เพื่อให้ถ่ายรูปต่อไปได้ (โดยเปลี่ยน key)
                 st.session_state.scanner_key = f"scanner_{uuid.uuid4()}"
                 st.rerun()
            elif img_file is not None and scan_value is None:
                 # กรณีถ่ายรูปติดแต่ pyzbar อ่านไม่ออก
                 st.warning("อ่าน Barcode ไม่ได้ กรุณาถ่ายใหม่ให้ชัดเจน/ใกล้ขึ้น")

        if st.session_state.show_user_not_found_error:
            scanner_prompt_placeholder.error(f"⚠️ ไม่พบ User '{st.session_state.last_failed_user_scan}'! กรุณาสแกน User ที่ถูกต้อง", icon="⚠️")
        else:
            scanner_prompt_placeholder.info("ขั้นตอนที่ 1: ถ่ายรูป 'Barcode User' (หรือคีย์ด้านล่าง)")

    else:
        # --- Scanning Phase (User Login แล้ว) ---
        if st.session_state.scan_mode == "Bulk":
            mode_name = "โหมด Bulk" 
            st.header(f"{mode_name}") 

            scanner_prompt_placeholder = st.empty() 
            
            # --- 🟢 (แก้) ใช้ Camera Input ---
            label_text = "ถ่ายรูป Barcode สินค้า" if not st.session_state.temp_barcode else "ถ่ายรูป Tracking Number"
            img_file = st.camera_input(f"📸 {label_text}", key=st.session_state.scanner_key)
            scan_value = read_barcode_from_image(img_file)
            # -------------------------------
            
            st.button("🔙 กลับ Menu หลัก", on_click=clear_all_and_restart, key="back_menu_bulk")

            is_new_scan = (scan_value is not None)
            
            if is_new_scan:
                st.session_state.last_scan_processed = scan_value 
                
                if not st.session_state.temp_barcode:
                    # Case 1: กำลังสแกน Barcode สินค้า
                    st.session_state.show_user_not_found_error = False 
                    if scan_value == st.session_state.current_user:
                        st.warning("⚠️ นั่นคือ User! กรุณาสแกน Barcode สินค้า", icon="⚠️")
                    else:
                        st.session_state.temp_barcode = scan_value
                        st.success(f"Barcode: {scan_value} ถูกล็อคแล้ว")
                        # Reset กล้อง
                        st.session_state.scanner_key = f"scanner_{uuid.uuid4()}"
                        st.rerun()

                else:
                    # Case 2: กำลังสแกน Tracking
                    st.session_state.show_user_not_found_error = False 
                    if scan_value == st.session_state.temp_barcode:
                        st.warning("⚠️ นั่นคือ Barcode เดิม! กรุณาสแกน Tracking Number", icon="⚠️")
                        st.session_state.show_duplicate_tracking_error = False
                    elif scan_value == st.session_state.current_user:
                        st.warning("⚠️ นั่นคือ User! กรุณาสแกน Tracking Number", icon="⚠️")
                        st.session_state.show_duplicate_tracking_error = False
                    elif any(item["tracking"] == scan_value for item in st.session_state.staged_scans):
                        st.session_state.show_duplicate_tracking_error = True
                        st.session_state.last_scanned_tracking = scan_value 
                    elif check_tracking_exists(scan_value):
                        st.session_state.show_duplicate_tracking_error = True
                        st.session_state.last_scanned_tracking = f"{scan_value} (มีในระบบแล้ว)"
                    else:
                        st.session_state.staged_scans.append({
                            "id": str(uuid.uuid4()),
                            "tracking": scan_value,
                            "barcode": st.session_state.temp_barcode 
                        })
                        st.session_state.show_duplicate_tracking_error = False
                        st.success(f"เพิ่ม Tracking: {scan_value} สำเร็จ!")
                        # Reset กล้องเพื่อให้ถ่ายต่อได้ทันที
                        st.session_state.scanner_key = f"scanner_{uuid.uuid4()}"
                        st.rerun()
            
            elif img_file is not None and scan_value is None:
                 st.error("❌ อ่านรหัสไม่ได้ กรุณาถ่ายใหม่")

            # (ส่วนแสดงผล UI ที่เหลือเหมือนเดิม)
            has_sticky_error = st.session_state.show_user_not_found_error or st.session_state.show_duplicate_tracking_error
            
            if not st.session_state.temp_barcode:
                scanner_prompt_placeholder.info("ขั้นตอนที่ 2: ถ่ายรูป Barcode สินค้า...")
            else:
                if st.session_state.show_duplicate_tracking_error:
                    scanner_prompt_placeholder.error(f"⚠️ สแกนซ้ำ! '{st.session_state.last_scanned_tracking}'", icon="⚠️")
                else:
                    scanner_prompt_placeholder.info("ขั้นตอนที่ 3: ถ่ายรูป Tracking Number ทีละกล่อง...")

            if has_sticky_error:
                st.button("❌ ปิดแจ้งเตือน (และถ่ายใหม่)", 
                          on_click=acknowledge_error_and_reset_scanner, 
                          use_container_width=True, type="primary") 
                          
            st.divider()
            col_user, col_barcode = st.columns(2)
            with col_user:
                st.subheader("1.User")
                st.code(st.session_state.current_user)
                st.button("❌ เปลี่ยน User", on_click=clear_all_and_restart, use_container_width=True) 
            with col_barcode:
                st.subheader("2.Barcode")
                if st.session_state.temp_barcode:
                    st.code(st.session_state.temp_barcode)
                else:
                    st.info("...รอล็อค Barcode...")
            
            st.divider() 
            st.button("💾 บันทึกทั้งหมด (และเริ่มใหม่)", type="primary", use_container_width=True, on_click=save_all_to_db, disabled=(not st.session_state.staged_scans or not st.session_state.temp_barcode))
            st.subheader(f"3. รายการที่กำลังสแกน ({len(st.session_state.staged_scans)} รายการ)")
            
            if st.session_state.staged_scans:
                for item in reversed(st.session_state.staged_scans): 
                    with st.container(border=True):
                        st.caption(f"Barcode: {item['barcode']}")
                        st.caption("Tracking:")
                        col_code, col_del = st.columns([4, 1]) 
                        with col_code: st.code(item["tracking"]) 
                        with col_del: st.button("❌ ลบ", key=f"del_{item['id']}", on_click=delete_item, args=(item['id'],), use_container_width=True)

        elif st.session_state.scan_mode == "Single":
            mode_name = "โหมด Single" 
            st.header(f"{mode_name}") 
            st.subheader("ผู้ใช้งาน (User)")
            st.code(st.session_state.current_user)
            st.button("❌ เปลี่ยน User", on_click=clear_all_and_restart, use_container_width=True)
            st.divider()

            if st.session_state.show_dialog_for == 'tracking': show_confirmation_dialog(is_tracking=True)
            elif st.session_state.show_dialog_for == 'barcode': show_confirmation_dialog(is_tracking=False)
            
            st.subheader("1. ถ่ายรูปที่นี่ (Scan Here)")
            scanner_prompt_placeholder = st.empty() 
            
            if st.session_state.show_dialog_for == 'staging': add_and_clear_staging()

            if st.session_state.show_dialog_for is None:
                # --- 🟢 (แก้) ใช้ Camera Input ---
                img_file = st.camera_input("📸 ถ่ายรูป", key=st.session_state.scanner_key)
                scan_value = read_barcode_from_image(img_file)
                # -------------------------------
                
                st.button("🔙 กลับ Menu หลัก", on_click=clear_all_and_restart, key="back_menu_single")

                is_new_scan = (scan_value is not None)

                if not st.session_state.temp_tracking:
                    scanner_prompt_placeholder.info("ขั้นตอนที่ 2: ถ่ายรูป Tracking...")
                else:
                    if st.session_state.show_scan_error_message:
                         scanner_prompt_placeholder.error("⚠️ สแกนซ้ำ! กรุณาถ่าย Barcode", icon="⚠️")
                    else:
                         scanner_prompt_placeholder.success("ขั้นตอนที่ 3: ถ่ายรูป Barcode...")

                if is_new_scan:
                    st.session_state.last_scan_processed = scan_value
                    
                    if not st.session_state.temp_tracking:
                        if scan_value == st.session_state.current_user:
                            st.warning("⚠️ นั่นคือ User! กรุณาถ่าย Tracking", icon="⚠️")
                        elif check_tracking_exists(scan_value):
                            st.warning(f"⚠️ Tracking {scan_value} มีในระบบแล้ว!", icon="⚠️")
                        else:
                            st.session_state.temp_tracking = scan_value
                            st.session_state.show_dialog_for = 'tracking' 
                            st.rerun() 
                    
                    elif st.session_state.temp_tracking and not st.session_state.temp_barcode:
                        if scan_value != st.session_state.temp_tracking and scan_value != st.session_state.current_user:
                            st.session_state.temp_barcode = scan_value
                            st.session_state.show_dialog_for = 'barcode' 
                            st.session_state.show_scan_error_message = False 
                            st.rerun() 
                        else:
                            st.session_state.show_scan_error_message = True
                            st.rerun()
                elif img_file is not None and scan_value is None:
                     st.error("❌ อ่านรหัสไม่ได้ กรุณาถ่ายใหม่")
            
            else:
                 st.info(f"... กด 'ปิด' ใน Popup ยืนยัน ...")

            st.subheader("2. ข้อมูลที่กำลังสแกน")
            col_t, col_b = st.columns(2)
            with col_t:
                st.text_input("Tracking", value=st.session_state.temp_tracking, disabled=True, label_visibility="collapsed")
            with col_b:
                st.text_input("Barcode", value=st.session_state.temp_barcode, disabled=True, label_visibility="collapsed")
            
            st.divider()
            st.button("💾 บันทึกทั้งหมด (และเริ่มใหม่)", type="primary", use_container_width=True, on_click=save_all_to_db, disabled=(not st.session_state.staged_scans))
            st.subheader(f"3. รายการที่กำลังสแกน ({len(st.session_state.staged_scans)} รายการ)")
            if st.session_state.staged_scans:
                for item in reversed(st.session_state.staged_scans): 
                    with st.container(border=True):
                        st.caption("Tracking:"); st.code(item["tracking"])
                        st.caption("Barcode:"); st.code(item["barcode"])
                        st.button("❌ ลบ", key=f"del_{item['id']}", on_click=delete_item, args=(item['id'],), use_container_width=True)

# --- TAB 2: (ส่วนนี้ของคุณเหมือนเดิม ไม่ต้องแก้) ---
with tab2:
    # ... (Code Tab 2 เดิมของคุณ) ...
    pass
