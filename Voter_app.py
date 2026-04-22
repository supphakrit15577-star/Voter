import streamlit as st
from st_supabase_connection import SupabaseConnection
import time
import pandas as pd

# 1. เชื่อมต่อฐานข้อมูล
conn = st.connection("supabase", type=SupabaseConnection)

# --- ฟังก์ชันช่วยส่งคำสั่งพร้อมลองใหม่ (Retry) กรณีเน็ตหลุด ---
def execute_with_retry(query_func, retries=3, delay=1):
    for i in range(retries):
        try:
            return query_func().execute()
        except Exception as e:
            if "10054" in str(e) or "connection" in str(e).lower():
                if i < retries - 1:
                    time.sleep(delay)
                    continue
            raise e

# --- จัดการ Session State สำหรับการ Login ---
if "authenticated" not in st.session_state:
    if "user" in st.query_params:
        username = st.query_params["user"]
        # พยายามดึงข้อมูลผู้ใช้เพื่อโหลด voted_count กลับมา
        try:
            response = execute_with_retry(lambda: conn.table("users").select("voted_count, role, dept").eq("username", username))
            if response.data:
                user_data = response.data[0]
                st.session_state.authenticated = True
                st.session_state.username = username
                st.session_state.voted_count = user_data.get("voted_count", 0)
                st.session_state.role = user_data.get("role", "user") # ดึงบทบาทผู้ใช้
                st.session_state.dept = user_data.get("dept", "") # ดึงแผนกของผู้ใช้
            else:
                st.session_state.authenticated = False
        except:
            st.session_state.authenticated = False
    else:
        st.session_state.authenticated = False

if "username" not in st.session_state:
    st.session_state.username = st.query_params.get("user", "")
if "voted_count" not in st.session_state:
    st.session_state.voted_count = 0
if "role" not in st.session_state:
    st.session_state.role = "user"
if "dept" not in st.session_state:
    st.session_state.dept = ""
if "scoring_choice" not in st.session_state:
    st.session_state.scoring_choice = None  # id ของ choice ที่กำลังให้คะแนนอยู่
if "page" not in st.session_state:
    # อ่านหน้าล่าสุดจาก URL (ถ้ามี)
    url_page = st.query_params.get("view")
    if url_page:
        st.session_state.page = url_page
    else:
        # กำหนดค่าเริ่มต้นตามบทบาท
        if st.session_state.get("role") == "supervisor":
             st.session_state.page = "โหวต Level 2"
        else:
             st.session_state.page = "หน้าโหวต"

# 2. ฟังก์ชันดึงรายการโหวต (CHOICES) จากฐานข้อมูล
def get_db_choices():
    try:
        response = execute_with_retry(lambda: conn.table("choices").select("*"))
        if response.data:
            return response.data
        else:
            # กรณีไม่มีข้อมูลใน DB ให้คืนค่าว่าง
            return []
    except Exception as e:
        # หากยังไม่ได้สร้างตาราง หรือเกิดข้อผิดพลาด ให้คืนค่าข้อมูลจำลอง (Fallback)
        # หรือแจ้งเตือนให้ผู้ใช้ทราบ
        return []

# ดึงข้อมูล CHOICES มาเตรียมไว้
CHOICES = get_db_choices()

# --- ฟังก์ชัน Filter CHOICES ตาม dept ของ user ---
def get_filtered_choices():
    """Admin เห็นทุก choice, User ทั่วไปเห็นเฉพาะ choice ที่มี dept ตรงกัน"""
    is_admin = st.session_state.get("role") == "admin"
    if is_admin:
        return CHOICES
    user_dept = st.session_state.get("dept", "")
    return [c for c in CHOICES if c.get("dept", "") == user_dept]

# --- ฟังก์ชันตรวจสอบ Login ---
def login(username, password):
    try:
        response = execute_with_retry(lambda: conn.table("users").select("voted_count, role, dept").eq("username", username).eq("password", password))
        if response.data:
            user_data = response.data[0]
            st.session_state.authenticated = True
            st.session_state.username = username
            # ดึงจำนวนที่เคยโหวตไปแล้ว, บทบาท และแผนก (ถ้าไม่มีให้ใช้ค่าเริ่มต้น)
            st.session_state.voted_count = user_data.get("voted_count", 0)
            st.session_state.role = user_data.get("role", "user")
            st.session_state.dept = user_data.get("dept", "") # ดึงแผนกของผู้ใช้
            # เก็บชื่อผู้ใช้ไว้ใน URL เพื่อให้ไม่ต้อง Login ใหม่ตอน Refresh
            st.query_params["user"] = username
            st.success("ล็อกอินสำเร็จ!")
            st.rerun()
        else:
            st.error("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการตรวจสอบสิทธิ์ (อาจเป็นที่เน็ตเวิร์ก): {e}")

def logout():
    st.session_state.authenticated = False
    st.session_state.username = ""
    st.query_params.clear()  # ล้างพารามิเตอร์ใน URL
    st.rerun()

# 3. ฟังก์ชันดึงคะแนนจาก Supabase
def get_db_votes():
    try:
        response = execute_with_retry(lambda: conn.table("votes_table").select("item_id, vote_count"))
        if not response.data:
            st.warning("ไม่พบข้อมูลใน votes_table หรือไม่มีสิทธิ์เข้าถึง")
        return {row['item_id']: row['vote_count'] for row in response.data}
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการดึงข้อมูล: {e}")
        return {}

# 4. ฟังก์ชันดึงรายการ choice ที่ user คนนี้โหวตไปแล้ว
def get_user_voted_choices():
    try:
        response = execute_with_retry(
            lambda: conn.table("detailed_votes").select("choice_id").eq("username", st.session_state.username)
        )
        if response.data:
            return {row["choice_id"] for row in response.data}
        return set()
    except:
        return set()

# 5. ฟังก์ชันส่งคะแนนแบบละเอียด (6 ด้าน รวม 100 คะแนน)
def submit_detailed_vote(choice_id, scores: dict):
    """scores = {"score_1": x, ..., "score_6": x} รวม 100 คะแนน (20+20+20+15+20+5)
    - Admin: โหวตได้ไม่จำกัด (โหวตซ้ำ choice เดิมได้)
    - User/Supervisor: โหวตได้ 1 ครั้งต่อ 1 choice (ตรวจจาก detailed_votes)
    """
    is_admin = st.session_state.role == "admin"

    total_score = sum(scores.values())

    with st.spinner("กำลังบันทึกคะแนน..."):
        try:
            # 1. บันทึกรายละเอียดคะแนนลง detailed_votes
            execute_with_retry(lambda: conn.table("detailed_votes").insert({
                "username": st.session_state.username,
                "choice_id": choice_id,
                **scores,
                "total_score": total_score
            }))

            # 2. อัปเดตคะแนนรวมใน votes_table (บวกเพิ่มจากเดิม)
            votes_now = get_db_votes()
            current_count = votes_now.get(choice_id, 0)
            execute_with_retry(lambda: conn.table("votes_table").update(
                {"vote_count": current_count + total_score}
            ).eq("item_id", choice_id))

            # 3. อัปเดตจำนวน choice ที่ user โหวตไปแล้ว (ไม่นับ admin)
            if not is_admin:
                new_count = st.session_state.voted_count + 1
                execute_with_retry(lambda: conn.table("users").update(
                    {"voted_count": new_count}
                ).eq("username", st.session_state.username))
                st.session_state.voted_count = new_count

            return True
        except Exception as e:
            st.error(f"เกิดข้อผิดพลาดในการบันทึกคะแนน: {e}")
            return False

# --- ฟังก์ชันช่วยปรับแต่ง UI ---
def inject_custom_css():
    st.markdown(
        """
        <style>
            /* ปรับแต่ง Container ให้โชว์สีพื้นหลังแน่นอน */
            [data-testid="stVerticalBlockBorderWrapper"] {
                background-color: #FF0000 !important; /* เปลี่ยนเป็นสีเทาเข้มเพื่อรับกับตัวหนังสือสีขาว */
                border-radius: 12px !important;
                border: 1px solid #444 !important;
                transition: transform 0.2s ease, box-shadow 0.2s ease !important;
                margin-bottom: 20px !important;
                padding: 15px !important;
                color: white !important;
            }
            [data-testid="stVerticalBlockBorderWrapper"]:hover {
                transform: translateY(-5px) !important;
                box-shadow: 0 4px 15px rgba(0,0,0,0.3) !important;
            }
            /* ปรับแต่งสีตัวหนังสือข้างในการ์ด */
            .card-id {
                font-size: 0.85rem;
                color: #bbbbbb !important;
                margin-bottom: 2px;
            }
            .card-name {
                font-size: 1.1rem;
                font-weight: bold;
                color: #ffffff !important;
                margin-bottom: 5px;
            }
            .vote-count {
                font-size: 1rem;
                font-weight: bold;
                color: #ff4b4b !important; /* สีแดงสว่างให้ตัดกับพื้นหลังเข้ม */
            }
            /* บังคับให้หัวข้อและ Markdown เป็นสีขาว */
            [data-testid="stVerticalBlockBorderWrapper"] p, 
            [data-testid="stVerticalBlockBorderWrapper"] h3 {
                color: white !important;
            }
        </style>
        """,
        unsafe_allow_html=True
    )


# --- 5. ฟังก์ชันแสดงฟอร์มให้คะแนน 6 ด้าน (รวม 100 คะแนน) ---

def show_scoring_form(choice):
    """แสดงฟอร์มให้คะแนน 6 ด้าน (รวม 100 คะแนน) สำหรับ choice ที่เลือก"""
    inject_custom_css()
    # ปุ่มกลับ
    if st.button("← กลับไปหน้ารายการ", key="back_btn"):
        st.session_state.scoring_choice = None
        st.rerun()

    st.markdown("---")
    st.title(f"📝 ให้คะแนน: {choice['name']}")

    col_img, col_form = st.columns([1, 2])
    with col_img:
        st.image(choice["img"], use_container_width=True)
        st.markdown(f"<p class='card-id' style='text-align:center;'>ID: {choice['id']}</p>", unsafe_allow_html=True)

    with col_form:
        with st.form(f"scoring_form_{choice['id']}"):
            st.markdown("#### กรุณาให้คะแนนในแต่ละด้าน (รวม 100 คะแนน)")
            scores = {}
            st.markdown("""
            <p><strong>การจัดการคอมเพลน</strong></p>
            <p>วัตถุประสงค์: สร้างความพึงพอใจและความเชื่อมั่นของคนในทีม</p>
            <p>พิจารณาจาก</p>
            <p style='padding-left: 40px;'>
            1. จำนวนคอมเพลนที่เกี่ยวข้องโดยตรง<br>
            2. ความสามารถในการแก้ไขปัญหาอย่างรวดเร็วและเหมาะสม<br>
            3. การป้องกันไม่ให้ปัญหาเดิมเกิดซ้ำ<br>
            4. Feedback เชิงบวกจากของทีม
            </p>
            """, unsafe_allow_html=True)
            scores['score_1'] = st.slider("การจัดการคอมเพลน (20 คะแนน)", min_value=0, max_value=20, value=10, key="sl_score_1")

            st.markdown("""
            <p><strong>ความปลอดภัยในการทำงาน และความยั่งยืน</strong></p>
            <p>วัตถุประสงค์: Zero Accident และการทำงานอย่างรับผิดชอบต่อสิ่งแวดล้อม</p>
            <p>พิจารณาจาก</p>
            <p style='padding-left: 40px;'>
            1. ปฏิบัติตามกฎความปลอดภัยอย่างเคร่งครัด<br>
            2. ไม่มีส่วนเกี่ยวข้องกับอุบัติเหตุจากความประมาท<br>
            3. เสนอแนวคิด/กิจกรรมด้านความปลอดภัยหรือสิ่งแวดล้อม<br>
            4. ใช้ทรัพยากรอย่างคุ้มค่า ลดของเสีย
            </p>
            """, unsafe_allow_html=True)
            
            scores['score_2'] = st.slider("ความปลอดภัยในการทำงาน และความยั่งยืน (20 คะแนน)", min_value=0, max_value=20, value=10, key="sl_score_2")

            st.markdown("""
            <p><strong>คุณภาพของสินค้าและงานที่รับผิดชอบ</strong></p>
            <p>วัตถุประสงค์: ส่งมอบคุณภาพที่สม่ำเสมอและได้มาตรฐาน​</p>
            <p>พิจารณาจาก</p>
            <p style='padding-left: 40px;'>
            1. อัตราของเสีย / งานแก้ไขซ้ำ​<br>
            2. ความถูกต้องตามมาตรฐาน (SOP, WI, QA)<br>
            3. ความใส่ใจในรายละเอียดมีส่วนร่วมในการปรับปรุงคุณภาพ​<br>
            4. มีส่วนร่วมในการปรับปรุงคุณภาพ​
            </p>
            """, unsafe_allow_html=True)

            scores['score_3'] = st.slider("คุณภาพของสินค้าและงานที่รับผิดชอบ (20 คะแนน)", min_value=0, max_value=20, value=10, key="sl_score_3")

            st.markdown("""
            <p><strong>ความสัมพันธ์และการทำงานร่วมกับเพื่อนร่วมงาน</strong></p>
            <p>วัตถุประสงค์: สร้างทีมที่เข้มแข็งและทำงานร่วมกันได้ดี​</p>
            <p>พิจารณาจาก</p>
            <p style='padding-left: 40px;'>
            1. การให้ความช่วยเหลือ แบ่งปันความรู้​<br>
            2. การสื่อสารเชิงบวก เคารพซึ่งกันและกัน​<br>
            3. การรับฟังความคิดเห็น​<br>
            4. ไม่มีพฤติกรรมสร้างความขัดแย้ง​
            </p>
            """, unsafe_allow_html=True)

            scores['score_4'] = st.slider("ความสัมพันธ์และการทำงานร่วมกับเพื่อนร่วมงาน (15 คะแนน)", min_value=0, max_value=15, value=7, key="sl_score_4")

            st.markdown("""
            <p><strong>ความสอดคล้องกับค่านิยมขององค์กร</strong></p>
            <p>วัตถุประสงค์: ให้รางวัลกับพฤติกรรมที่องค์กรต้องการในระยะยาว​</p>
            <p>พิจารณาจาก</p>
            <p style='padding-left: 40px;'>
            1. การแสดงพฤติกรรมตาม Core Values<br>
            2. การเป็นแบบอย่างที่ดีให้เพื่อนร่วมงาน​<br>
            3. ความรับผิดชอบและจริยธรรมในการทำงาน​
            </p>
            """, unsafe_allow_html=True)
            
            scores['score_5'] = st.slider("ความสอดคล้องกับค่านิยมขององค์กร (20 คะแนน)", min_value=0, max_value=20, value=10, key="sl_score_5")

            st.markdown("""
            <p><strong>พฤติกรรมเชิงบวกและการพัฒนาตนเอง</strong></p>
            <p>วัตถุประสงค์: ส่งเสริม Mindset การเรียนรู้และปรับตัว</p>
            <p>พิจารณาจาก</p>
            <p style='padding-left: 40px;'>
            1. ความตั้งใจเรียนรู้สิ่งใหม่​<br>
            2. การเสนอแนวคิดปรับปรุงงาน<br>
            3. เปิดรับการเปลี่ยนแปลง​
            </p>
            """, unsafe_allow_html=True)

            scores['score_6'] = st.slider("พฤติกรรมเชิงบวกและการพัฒนาตนเอง (5 คะแนน)", min_value=0, max_value=5, value=3, key="sl_score_6")

            total_preview = sum(scores.values())
            st.info(f"คะแนนรวม: **{total_preview} / 100 คะแนน**")

            submitted = st.form_submit_button("✅ ยืนยันการให้คะแนน", use_container_width=True, type="primary")
            if submitted:
                success = submit_detailed_vote(choice["id"], scores)
                if success:
                    st.toast(f"บันทึกคะแนนให้ {choice['name']} สำเร็จ! 🎉", icon="✅")
                    st.session_state.scoring_choice = None
                    st.rerun()

# --- 6. ฟังก์ชันแสดงหน้าโหวต (Vote Page) ---
def show_vote_page():
    # ถ้ากำลังอยู่ในหน้าให้คะแนน ให้แสดงฟอร์มนั้นแทน
    if st.session_state.scoring_choice:
        choice = next((c for c in get_filtered_choices() if c["id"] == st.session_state.scoring_choice), None)
        if choice:
            show_scoring_form(choice)
            return
        else:
            st.session_state.scoring_choice = None

    inject_custom_css()
    st.title("🏆 Voting App")

    # กรอง choices ตาม dept ของ user
    filtered_choices = get_filtered_choices()
    if not filtered_choices:
        user_dept = st.session_state.get("dept", "ไม่ระบุ")
        st.warning(f"⚠️ ไม่พบรายการโหวตสำหรับแผนก '{user_dept}' กรุณาติดต่อผู้ดูแลระบบ")
        return

    # ดึงรายการที่ user นี้โหวตไปแล้ว
    voted_choices = get_user_voted_choices()

    # แสดงรายการโหวตแบบแถวละ 4 คอลัมน์
    COL_PER_ROW = 4
    for i in range(0, len(filtered_choices), COL_PER_ROW):
        batch = filtered_choices[i : i + COL_PER_ROW]
        cols = st.columns(COL_PER_ROW)

        for idx, item in enumerate(batch):
            with cols[idx]:
                with st.container(border=True):
                    st.image(item["img"], use_container_width=True)
                    st.markdown(f"<p class='card-id'>ID: {item['id']}</p>", unsafe_allow_html=True)
                    st.markdown(f"<p class='card-name'>{item['name']}</p>", unsafe_allow_html=True)

                    is_admin_user = st.session_state.role == "admin"
                    already_voted = item["id"] in voted_choices
                    btn_key = f"vote_{item['id']}"

                    # Admin โหวตได้เสมอ (ไม่จำกัด), User อื่นโหวตได้ 1 ครั้งต่อ choice
                    if already_voted and not is_admin_user:
                        st.button("✅ ให้คะแนนแล้ว", key=btn_key, use_container_width=True, disabled=True)
                    else:
                        label = "⭐ ให้คะแนน" if not already_voted else "🔄 แก้คะแนน (Admin)"
                        if st.button(label, key=btn_key, use_container_width=True, type="primary"):
                            st.session_state.scoring_choice = item["id"]
                            st.rerun()

# --- 6. ฟังก์ชันแสดงหน้าโหวต Level 2 (Top 5 Only) ---
def show_vote_level2_page():
    is_admin_user = st.session_state.role == "admin"

    # ถ้ากำลังอยู่ในหน้าให้คะแนน ให้แสดงฟอร์ม 6 ด้านแทน
    if st.session_state.scoring_choice:
        choice = next((c for c in CHOICES if c["id"] == st.session_state.scoring_choice), None)
        if choice:
            show_scoring_form(choice)
            return
        else:
            st.session_state.scoring_choice = None

    inject_custom_css()
    st.title("🔥 Vote Level 2: The Final 5")
    st.info("หน้านี้สำหรับผู้เชี่ยวชาญ (Supervisor/Admin) เพื่อโหวตคัดเลือกจาก 5 อันดับแรกเท่านั้น")

    # 1. ค้นหา Top 5 จากคะแนนปัจจุบัน
    votes_data = get_db_votes()
    if not votes_data:
        st.warning("ยังไม่มีข้อมูลการโหวตเพื่อจัดลำดับ Top 5")
        return

    # กรองและเรียงลำดับ (admin ใช้ทุก choice, supervisor/user ใช้ filtered)
    filtered_choices = get_filtered_choices()
    results_list = []
    for choice in filtered_choices:
        results_list.append({
            "id": choice["id"],
            "name": choice["name"],
            "img": choice["img"],
            "votes": votes_data.get(choice["id"], 0)
        })
    
    top_5 = sorted(results_list, key=lambda x: x["votes"], reverse=True)[:5]
    top_5_ids = [item["id"] for item in top_5]

    # 2. แสดงรายการโหวต (เฉพาะที่อยู่ใน Top 5)
    cols = st.columns(len(top_5))
    for idx, item in enumerate(top_5):
        with cols[idx]:
            with st.container(border=True):
                st.markdown(f"<div style='background-color: #ff4b4b; color: white; text-align: center; border-radius: 5px; font-weight: bold;'>Top {idx+1}</div>", unsafe_allow_html=True)
                st.image(item['img'], use_container_width=True)
                st.markdown(f"<p class='card-id' style='text-align:center;'>ID: {item['id']}</p>", unsafe_allow_html=True)
                st.markdown(f"<p class='card-name' style='text-align:center;'>{item['name']}</p>", unsafe_allow_html=True)

                # ปุ่มกดโหวต (ใช้ key แยกจากหน้าแรก)
                btn_key = f"vote_l2_{item['id']}"
                already_voted_l2 = item["id"] in get_user_voted_choices()

                # Admin โหวตได้ไม่จำกัด, Supervisor โหวตได้ 1 ครั้งต่อ choice
                if already_voted_l2 and not is_admin_user:
                    st.button("✅ ให้คะแนนแล้ว", key=btn_key, use_container_width=True, disabled=True)
                else:
                    label = "⭐ ให้คะแนน" if not already_voted_l2 else "🔄 แก้คะแนน (Admin)"
                    if st.button(label, key=btn_key, use_container_width=True, type="primary"):
                        st.session_state.scoring_choice = item["id"]
                        st.rerun()

# --- 7. ฟังก์ชันแสดงหน้าโหวต Level 3 (Top 3, Admin + special เท่านั้น) ---
def show_vote_level3_page():
    is_admin_user = st.session_state.role == "admin"

    # ถ้ากำลังอยู่ในหน้าให้คะแนน ให้แสดงฟอร์ม 6 ด้านแทน
    if st.session_state.scoring_choice:
        choice = next((c for c in CHOICES if c["id"] == st.session_state.scoring_choice), None)
        if choice:
            show_scoring_form(choice)
            return
        else:
            st.session_state.scoring_choice = None

    inject_custom_css()
    st.title("🏆 Vote Level 3: The Final 3")
    st.info("หน้านี้สำหรับ Admin และ Special เท่านั้น เพื่อโหวตคัดเลือกจาก 3 อันดับแรกเท่านั้น")

    # เตรียมรายการ Top 3 — Level 3 เป็นรอบ Final ดูทุก choice ข้ามแผนก
    votes_data = get_db_votes()
    all_choices = CHOICES  # ใช้ทุก choice ไม่ filter dept
    results_list = sorted(
        [{"id": c["id"], "name": c["name"], "img": c["img"],
          "votes": votes_data.get(c["id"], 0) if votes_data else 0}
         for c in all_choices],
        key=lambda x: x["votes"], reverse=True
    )

    if not votes_data:
        st.warning("ยังไม่มีข้อมูลการโหวตเพื่อจัดลำดับ Top 3")
        return

    # ทั้ง Admin และ Special เห็นแค่ Top 3 เรียงลำดับ 1→2→3 ซ้ายไปขวา
    top3_list = results_list[:3]
    # เรียงตาม rank จาก results_list เพื่อให้แสดง อันดับ 1, 2, 3 ซ้ายไปขวา
    display_choices = [c for item in top3_list for c in all_choices if c["id"] == item["id"]]

    if not display_choices:
        st.warning("⚠️ ไม่พบรายการโหวต")
        return

    # rank map: id -> rank
    rank_map = {item["id"]: rank+1 for rank, item in enumerate(results_list)}
    voted_choices = get_user_voted_choices()

    # แสดงการ์ดแบบ 4 คอลัมน์
    COL_PER_ROW = 4
    for i in range(0, len(display_choices), COL_PER_ROW):
        batch = display_choices[i : i + COL_PER_ROW]
        cols = st.columns(COL_PER_ROW)
        for idx, item in enumerate(batch):
            with cols[idx]:
                with st.container(border=True):
                    rank = rank_map.get(item["id"])
                    badge_color = {1: "#FFD700", 2: "#C0C0C0", 3: "#CD7F32"}
                    if rank and rank <= 3:
                        st.markdown(
                            f"<div style='background-color:{badge_color.get(rank,'#ff4b4b')};color:{'black' if rank<=3 else 'white'};"
                            f"text-align:center;border-radius:5px;font-weight:bold;margin-bottom:4px;'>"
                            f"Top {rank} 🏅</div>",
                            unsafe_allow_html=True
                        )
                    st.image(item["img"], use_container_width=True)
                    st.markdown(f"<p class='card-id'>ID: {item['id']}</p>", unsafe_allow_html=True)
                    st.markdown(f"<p class='card-name'>{item['name']}</p>", unsafe_allow_html=True)

                    already_voted = item["id"] in voted_choices
                    btn_key = f"vote_l3_{item['id']}"

                    if already_voted and not is_admin_user:
                        st.button("✅ ให้คะแนนแล้ว", key=btn_key, use_container_width=True, disabled=True)
                    else:
                        label = "⭐ ให้คะแนน" if not already_voted else "🔄 แก้คะแนน (Admin)"
                        if st.button(label, key=btn_key, use_container_width=True, type="primary"):
                            st.session_state.scoring_choice = item["id"]
                            st.rerun()


def show_results_page():
    inject_custom_css()
    st.title("📊 สรุปผลการโหวต (Admin Only)")
    
    votes_data = get_db_votes()
    if votes_data:
        # 0. เตรียมข้อมูลและหา Top 5
        # รวมข้อมูลจาก CHOICES กับคะแนนจริง
        filtered_choices = get_filtered_choices()
        results_list = []
        for choice in filtered_choices:
            results_list.append({
                "id": choice["id"],
                "name": choice["name"],
                "img": choice["img"],
                "votes": votes_data.get(choice["id"], 0)
            })
        
        # เรียงลำดับตามคะแนน (มากไปน้อย)
        top_5 = sorted(results_list, key=lambda x: x["votes"], reverse=True)[:5]

        # 1. แสดง Top 5 Leaderboard
        st.subheader("🥇 Top 5 ผู้ที่มีคะแนนสูงสุด")
        cols = st.columns(5)
        for idx, item in enumerate(top_5):
            with cols[idx]:
                with st.container(border=True):
                    # ส่วนแสดงลำดับ
                    rank_color = ["#FFD700", "#C0C0C0", "#CD7F32", "#4e5d6c", "#4e5d6c"] # สีทอง, เงิน, ทองแดง, เทา
                    rank_idx = idx if idx < len(rank_color) else 4
                    st.markdown(f"""
                        <div style='background-color: {rank_color[rank_idx]}; color: black; border-radius: 5px; text-align: center; font-weight: bold; margin-bottom: 5px;'>
                            Rank #{idx+1}
                        </div>
                    """, unsafe_allow_html=True)
                    
                    st.image(item['img'], use_container_width=True)
                    st.markdown(f"<p class='card-id' style='text-align:center;'>ID: {item['id']}</p>", unsafe_allow_html=True)
                    st.markdown(f"<p class='card-name' style='text-align:center;'>{item['name']}</p>", unsafe_allow_html=True)
                    st.markdown(f"<p class='vote-count' style='text-align:center; font-size: 1.2rem;'>{item['votes']} คะแนน</p>", unsafe_allow_html=True)

        st.markdown("---")

        # 2. กราฟเปรียบเทียบคะแนน
        st.subheader("📊 เปรียบเทียบคะแนนทั้งหมด")
        df = pd.DataFrame(results_list)
        st.bar_chart(df.rename(columns={"name": "รายการ", "votes": "คะแนนโหวต"}).set_index("รายการ")[["คะแนนโหวต"]])
    else:
        st.info("ยังไม่มีข้อมูลการโหวต")

    st.markdown("---")
    
    # 2. รายชื่อคนที่โหวตแล้ว
    st.subheader("📑 รายชื่อผู้ที่ใช้สิทธิ์แล้ว")
    try:
        # ดึงข้อมูลผู้ใช้ทั้งหมดที่ไม่ใช่ Admin
        response = execute_with_retry(lambda: conn.table("users").select("username, voted_count, dept, role").neq("role", "admin"))
        
        if response.data:
            # คำนวณจำนวนตัวเลือกทั้งหมดแยกตามแผนกจาก CHOICES
            dept_counts = {}
            for c in CHOICES:
                d = c.get("dept", "Unknown")
                dept_counts[d] = dept_counts.get(d, 0) + 1
            
            # เตรียมข้อมูลสำหรับตารางสรุป
            voter_status = []
            for user in response.data:
                username = user.get("username")
                voted = user.get("voted_count", 0)
                dept = user.get("dept", "Unknown")
                role = user.get("role", "user")
                
                # ถ้าเป็น Special Role ให้มีสิทธิสูงสุด 3 (Top 3)
                # สำหรับบทบาทอื่นๆ ให้ใช้จำนวนตามแผนก
                total_limit = 3 if role == "special" else dept_counts.get(dept, 0)
                
                status = "✅ ใช้สิทธิครบแล้ว" if voted >= total_limit and total_limit > 0 else "⏳ ยังไม่ครบ"
                
                voter_status.append({
                    "ชื่อผู้ใช้": username,
                    "แผนก": dept,
                    "จำนวนโหวต (ใช้/ทั้งหมด)": f"{voted} / {total_limit}",
                    "สถานะ": status
                })
            
            df_voters = pd.DataFrame(voter_status)
            st.table(df_voters)
        else:
            st.info("ยังไม่มีข้อมูลผู้โหวตในระบบ")
    except Exception as e:
        st.error(f"ไม่สามารถดึงรายชื่อผู้โหวตได้: {e}")

# --- เริ่มแสดงผล UI ---
if not st.session_state.authenticated:
    _, center_col, _ = st.columns([1, 3.5, 1])
    with center_col:
        st.title("🔐 Login to Vote")
        with st.form("login_form"):
            user_input = st.text_input("Username")
            pass_input = st.text_input("Password", type="password")
            submit = st.form_submit_button("Login", use_container_width=True)
            if submit:
                login(user_input, pass_input)
else:
    # Sidebar สำหรับ Logout และสถานะการโหวต
    st.sidebar.title(f"สวัสดี, {st.session_state.username}")
    
    # แสดงสถานะ Role
    role_display = {
        "admin": "⭐ Admin",
        "supervisor": "🎯 Supervisor",
        "special": "🔥 Special",
    }.get(st.session_state.role, "👤 User")
    st.sidebar.info(f"บทบาท: **{role_display}**")
    
    # สำหรับ Admin และ Supervisor: การควบคุมหน้าเว็บ
    is_admin = st.session_state.role == "admin"
    is_supervisor = st.session_state.role == "supervisor"
    is_special = st.session_state.role == "special"

    if is_admin:
        st.sidebar.markdown("### 🧭 เมนูผู้ดูแล")
        page_options = ["หน้าโหวต", "โหวต Level 2", "โหวต Level 3", "สรุปผลคะแนน"]
        
        # ตรวจสอบ index ปัจจุบัน
        if st.session_state.page not in page_options:
            st.session_state.page = "หน้าโหวต"
            
        current_idx = page_options.index(st.session_state.page)
        selected_page = st.sidebar.selectbox("เลือกหน้าเว็บ", page_options, index=current_idx, label_visibility="collapsed")
        
        if selected_page != st.session_state.page:
            st.session_state.page = selected_page
            st.query_params["view"] = selected_page
            st.rerun()
        st.sidebar.divider()
        
    elif is_supervisor:
        st.sidebar.markdown("### 🎯 รอบผู้เชี่ยวชาญ")
        st.sidebar.info("คุณกำลังอยู่ในโหมดโหวตเลือก 5 อันดับสุดท้าย")
        st.session_state.page = "โหวต Level 2"
        st.sidebar.divider()
    elif is_special:
        st.sidebar.markdown("### 🔥 รอบ ตัดสิน Final")
        st.sidebar.info("คุณกำลังอยู่ในโหมดโหวตเลือก 3 อันดับสุดท้าย")
        st.session_state.page = "โหวต Level 3"
        st.sidebar.divider()

    # แสดงสถานะสิทธิ์การโหวต
    st.sidebar.markdown("---")
    st.sidebar.subheader("สิทธิ์การโหวตของคุณ")
    
    if is_admin:
        st.sidebar.success("✅ Admin: โหวตได้ไม่จำกัด")
    elif is_special:
        voted_so_far = st.session_state.voted_count
        st.sidebar.info(f"โหวตแล้ว: **{voted_so_far}** choice")
        st.sidebar.caption("📌 โหวตได้ 1 ครั้งต่อ 1 choice")
    else:
        voted_so_far = st.session_state.voted_count
        st.sidebar.info(f"โหวตแล้ว: **{voted_so_far}** choice")
        st.sidebar.caption("📌 โหวตได้ 1 ครั้งต่อ 1 choice")
    
    st.sidebar.markdown("---")
    if st.sidebar.button("Logout"):
        logout()

    # แสดงหน้าเว็บตามที่เลือก
    if not CHOICES:
        st.warning("⚠️ ไม่พบข้อมูลรายการโหวตในฐานข้อมูล (ตาราง choices) กรุณาตรวจสอบข้อมูลหลังบ้านครับ")
    elif is_special:
        show_vote_level3_page()
    elif is_supervisor:
        show_vote_level2_page()
    elif st.session_state.page == "สรุปผลคะแนน" and is_admin:
        show_results_page()
    elif st.session_state.page == "โหวต Level 3" and is_admin:
        show_vote_level3_page()
    elif st.session_state.page == "โหวต Level 2" and is_admin:
        show_vote_level2_page()
    else:
        show_vote_page()
                    
