import telebot
from telebot import types
import pyrebase
import re
import os
import tempfile

# ---------- Firebase config (استبدل حسب مشروعك) ----------
firebaseConfig = {
    "apiKey": "AIzaSyBzGA7-EmKaSm389djOkWFyXq9Ue_50EZo",
    "authDomain": "supersyber-technology.firebaseapp.com",
    "databaseURL": "https://supersyber-technology-default-rtdb.firebaseio.com",
    "projectId": "supersyber-technology",
    "storageBucket": "supersyber-technology.appspot.com",
    "messagingSenderId": "739983143346",
    "appId": "1:739983143346:android:864619e23c4e227a3334ab"
}

firebase = pyrebase.initialize_app(firebaseConfig)
db = firebase.database()
storage = firebase.storage()

# ---------- Bot config ----------
TOKEN = "8405401309:AAEFBpzrmxzR4sctTv6pU09MURVZ_GCmklE"
ADMINS = [1086351274]
bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# ---------- Helpers to get display names ----------
def _first_nonempty(*vals):
    for v in vals:
        if v is None:
            continue
        if isinstance(v, str) and v.strip() != "":
            return v
        if not isinstance(v, str):
            return v
    return None

def get_display_name(node, id_fallback):
    """
    Robustly extract a human-readable name from a firebase node.
    node can be a dict (metadata) or a plain string/id.
    We try many common keys and fall back to the provided id_fallback.
    """
    if node is None:
        return id_fallback
    if isinstance(node, str):
        return node or id_fallback
    if not isinstance(node, dict):
        return str(node) or id_fallback
    # common possible name keys
    candidates = [
        "universityname", "university_name", "universityName",
        "namecollege", "collegename", "college_name", "collegeName",
        "departmentname", "department_name", "departmentName",
        "semestername", "semester_name", "semesterName",
        "name", "title", "display_name", "displayName"
    ]
    for k in candidates:
        if k in node and node.get(k):
            return str(node.get(k))
    # also if node has a nested short label
    for k in ["label", "title_ar", "name_ar"]:
        if k in node and node.get(k):
            return str(node.get(k))
    # fallback to the id provided
    return id_fallback

# ---------- Persistent reply keyboard (buttons near input field) ----------
def get_main_reply_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    kb.add(
        types.KeyboardButton("/myid"),
        types.KeyboardButton("/files"),
        types.KeyboardButton("/uploadfile_tg")
    )
    kb.add(
        types.KeyboardButton("/start"),
        types.KeyboardButton("/menu"),
        types.KeyboardButton("/help")
    )
    return kb

# ---------- Utilities ----------
pendinguploads = {}  # userid -> pending file info

def safe_id(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^0-9A-Za-z_\-]", "", s)
    return s or "id"

def ensure_university_root():
    root = db.child("university").child("universities_list").get().val()
    if root is None:
        db.child("university").child("universities_list").set({})

def download_telegram_file_by_id(file_id):
    finfo = bot.get_file(file_id)
    filepath = finfo.file_path
    filebytes = bot.download_file(filepath)
    return filepath, filebytes

def guess_extension(mime_type, original_name=None):
    if original_name:
        root, ext = os.path.splitext(original_name)
        if ext:
            return ext
    if not mime_type:
        return ".bin"
    m = mime_type.lower()
    if "pdf" in m:
        return ".pdf"
    if "word" in m or "msword" in m or "openxmlformats" in m:
        return ".docx"
    if "image" in m:
        if "jpeg" in m or "jpg" in m:
            return ".jpg"
        if "png" in m:
            return ".png"
        return ".img"
    if "video" in m:
        return ".mp4"
    if "audio" in m:
        return ".mp3"
    return ".bin"

def parse_caption_for_type_name(caption: str):
    if not caption:
        return None
    caption = caption.strip()
    for sep in ["|", ":", "-", "—"]:
        if sep in caption:
            parts = caption.split(sep, 1)
            return parts[0].strip().lower(), parts[1].strip()
    parts = caption.split(None, 1)
    if len(parts) == 2:
        return parts[0].strip().lower(), parts[1].strip()
    return None

def process_and_upload_file(file_id, original_name, mime, uniid, colid, depid, semid, filetype, filename):
    # download
    _, file_bytes = download_telegram_file_by_id(file_id)
    ext = guess_extension(mime, original_name)
    local_name = safe_id(filename) + ext
    tmpdir = tempfile.gettempdir()
    local_path = os.path.join(tmpdir, local_name)
    with open(local_path, "wb") as f:
        f.write(file_bytes)
    storage_path = f"files/{uniid}/{colid}/{depid}/{semid}/{filetype}s/{local_name}"
    try:
        storage.child(storage_path).put(local_path)
    except Exception:
        # if storage put fails, still store metadata with storage path
        pass
    try:
        file_url = storage.child(storage_path).get_url(None)
    except Exception:
        file_url = f"storage://{storage_path}"
    file_id_store = safe_id(filename)
    # write metadata under consistent node
    db.child("university").child("universities_list").child(uniid).child("colleges").child(colid).child("department").child(depid).child("semesters").child(semid).child("files").child(f"{filetype}s").child(file_id_store).set({
        "name": filename,
        "url": file_url,
        "telegramfileid": file_id,
        "mime": mime,
        "storagepath": storage_path
    })
    try:
        os.remove(local_path)
    except Exception:
        pass

# ---------- Start / navigation ----------
@bot.message_handler(commands=["start"])
def cmd_start(message):
    chat_id = message.chat.id
    ensure_university_root()
    universities = db.child("university").child("universities_list").get().val()
    if not universities:
        if message.from_user.id in ADMINS:
            bot.send_message(chat_id, "✅ قاعدة البيانات فارغة. استخدم /add_university لإضافة أول جامعة.", reply_markup=get_main_reply_keyboard())
        else:
            bot.send_message(chat_id, "🚫 لا توجد جامعات حالياً.", reply_markup=get_main_reply_keyboard())
        return
    # normalize to dict
    if isinstance(universities, list):
        universities = {str(i): uni for i, uni in enumerate(universities)}
    markup = types.InlineKeyboardMarkup()
    for uniid, unidata in universities.items():
        # unidata may be a string or dict
        display = get_display_name(unidata, uniid)
        markup.add(types.InlineKeyboardButton(display, callback_data=f"uni|{uniid}"))
    if message.from_user.id in ADMINS:
        markup.add(types.InlineKeyboardButton("➕ إضافة جامعة", callback_data="adduniv"))
    bot.send_message(chat_id, "🎓 اختر الجامعة:", reply_markup=markup)

@bot.message_handler(commands=["menu"])
def cmd_menu(message):
    bot.send_message(message.chat.id, "📋 القائمة السريعة:", reply_markup=get_main_reply_keyboard())

@bot.message_handler(commands=["myid"])
def cmd_myid(message):
    uid = message.from_user.id
    bot.send_message(message.chat.id, f"🆔 معرفك: `{uid}`", parse_mode="Markdown")

@bot.message_handler(commands=["help"])
def cmd_help(message):
    help_text = (
        "قائمة الأوامر المتاحة:\n"
        "/start - بدء / اختيار الجامعة\n"
        "/menu - إظهار لوحة الأزرار\n"
        "/myid - عرض معرفك\n"
        "/files - عرض الملفات (عند التصفح داخل الجامعات)\n"
        "/uploadfile_tg - رفع ملف من تيليجرام (لمشرفين)\n"
        "مشرفون: /add_university, /addcollege, /adddepartment, /addsemester, /addfile\n"
    )
    bot.send_message(message.chat.id, help_text, reply_markup=get_main_reply_keyboard())

@bot.message_handler(commands=["files"])
def cmd_files(message):
    bot.send_message(message.chat.id, "استخدم /start لاختيار الجامعة ثم التنقل لعرض الملفات.", reply_markup=get_main_reply_keyboard())

# Admin shortcut commands (map to existing handlers)
@bot.message_handler(commands=["add_university", "adduniversity"])
def cmd_add_university_alias(message):
    if message.from_user.id not in ADMINS:
        bot.send_message(message.chat.id, "🚫 ليس لديك صلاحية.", reply_markup=get_main_reply_keyboard())
        return
    try:
        msg = bot.send_message(message.chat.id, "✏️ أرسل بيانات الجامعة بهذا الشكل:\nuniversityid|university_name|description|city|country")
        bot.register_next_step_handler(msg, add_university_step)
    except Exception:
        bot.send_message(message.chat.id, "❌ حدث خطأ عند الطلب.")

# ---------- Callback handler ----------
@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    chat_id = call.message.chat.id
    data = call.data or ""
    parts = data.split("|")

    if parts[0] == "adduniv" and call.from_user.id in ADMINS:
        msg = bot.send_message(chat_id, "✏️ أرسل بيانات الجامعة بهذا الشكل:\nuniversityid|universityname|description|city|country")
        bot.register_next_step_handler(msg, add_university_step)
        return

    if parts[0] == "uni":
        uni_id = parts[1]
        colleges = db.child("university").child("universities_list").child(uni_id).child("colleges").get().val()
        if isinstance(colleges, list):
            colleges = {str(i): c for i, c in enumerate(colleges)}
        markup = types.InlineKeyboardMarkup()
        if colleges:
            for col_id, col in colleges.items():
                display = get_display_name(col, col_id)
                markup.add(types.InlineKeyboardButton(display, callback_data=f"col|{uni_id}|{col_id}"))
        if call.from_user.id in ADMINS:
            markup.add(types.InlineKeyboardButton("➕ إضافة كلية", callback_data=f"addcol|{uni_id}"))
        if not colleges:
            bot.send_message(chat_id, "🚫 لا توجد كليات. استخدم الزر لإضافة كلية:", reply_markup=markup)
        else:
            bot.send_message(chat_id, "🏫 اختر الكلية أو أضف كلية جديدة:", reply_markup=markup)
        return

    if parts[0] == "addcol" and call.from_user.id in ADMINS:
        uni_id = parts[1]
        msg = bot.send_message(chat_id, "✏️ أرسل بيانات الكلية بهذا الشكل:\ncollegeid|collegename")
        bot.register_next_step_handler(msg, add_college_step, uni_id)
        return

    if parts[0] == "col":
        uniid = parts[1]; colid = parts[2]
        dept = db.child("university").child("universities_list").child(uniid).child("colleges").child(colid).child("department").get().val()
        if isinstance(dept, list):
            dept = {str(i): d for i, d in enumerate(dept)}
        markup = types.InlineKeyboardMarkup()
        if dept:
            for dep_id, dep in dept.items():
                display = get_display_name(dep, dep_id)
                markup.add(types.InlineKeyboardButton(display, callback_data=f"dep|{uniid}|{colid}|{dep_id}"))
        if call.from_user.id in ADMINS:
            markup.add(types.InlineKeyboardButton("➕ إضافة قسم", callback_data=f"adddep|{uniid}|{colid}"))
        if not dept:
            bot.send_message(chat_id, "🚫 لا توجد أقسام. استخدم الزر لإضافة قسم:", reply_markup=markup)
        else:
            bot.send_message(chat_id, "💻 اختر القسم أو أضف قسم جديد:", reply_markup=markup)
        return

    if parts[0] == "adddep" and call.from_user.id in ADMINS:
        uniid = parts[1]; colid = parts[2]
        msg = bot.send_message(chat_id, "✏️ أرسل بيانات القسم بهذا الشكل:\ndepartmentid|departmentname")
        bot.register_next_step_handler(msg, add_department_step, uniid, colid)
        return

    if parts[0] == "dep":
        uniid = parts[1]; colid = parts[2]; dep_id = parts[3]
        sems = db.child("university").child("universities_list").child(uniid).child("colleges").child(colid).child("department").child(dep_id).child("semesters").get().val()
        if isinstance(sems, list):
            sems = {str(i): s for i, s in enumerate(sems)}
        markup = types.InlineKeyboardMarkup()
        if sems:
            for sem_id, sem in sems.items():
                display = get_display_name(sem, sem_id)
                markup.add(types.InlineKeyboardButton(display, callback_data=f"sem|{uniid}|{colid}|{dep_id}|{sem_id}"))
        if call.from_user.id in ADMINS:
            markup.add(types.InlineKeyboardButton("➕ إضافة سمستر", callback_data=f"addsem|{uniid}|{colid}|{dep_id}"))
        if not sems:
            bot.send_message(chat_id, "🚫 لا توجد سمسترات. استخدم الزر لإضافة سمستر:", reply_markup=markup)
        else:
            bot.send_message(chat_id, "📚 اختر السمستر أو أضف سمستر جديد:", reply_markup=markup)
        return

    if parts[0] == "addsem" and call.from_user.id in ADMINS:
        uniid = parts[1]; colid = parts[2]; dep_id = parts[3]
        msg = bot.send_message(chat_id, "✏️ أرسل بيانات السمستر بهذا الشكل:\nsemesterid|semestername")
        bot.register_next_step_handler(msg, add_semester_step, uniid, colid, dep_id)
        return

    if parts[0] == "sem":
        uniid = parts[1]; colid = parts[2]; depid = parts[3]; semid = parts[4]
        files = db.child("university").child("universities_list").child(uniid).child("colleges").child(colid).child("department").child(depid).child("semesters").child(semid).child("files").get().val()
        markup = types.InlineKeyboardMarkup()
        if isinstance(files, dict) and files:
            msg_text = "🗂️ الملفات المتاحة:\n"
            for ftype, fdict in files.items():
                if not fdict: continue
                for fid, f in fdict.items():
                    fname = f.get("name") if isinstance(f, dict) else str(fid)
                    fname = fname or str(fid)
                    cb = f"playfile|{uniid}|{colid}|{depid}|{semid}|{ftype}|{fid}"
                    markup.add(types.InlineKeyboardButton(f"{fname} ▶️", callback_data=cb))
        else:
            msg_text = "🚫 لا توجد ملفات لهذا السمستر."
        if call.from_user.id in ADMINS:
            markup.add(types.InlineKeyboardButton("➕ إضافة ملف (من تيليجرام)", callback_data=f"addfiletg|{uniid}|{colid}|{depid}|{semid}"))
            markup.add(types.InlineKeyboardButton("➕ إضافة ملف (بـ رابط)", callback_data=f"addfile|{uniid}|{colid}|{depid}|{semid}"))
        bot.send_message(chat_id, msg_text, reply_markup=markup)
        return

    if parts[0] == "addfile" and call.from_user.id in ADMINS:
        uniid, colid, depid, semid = parts[1], parts[2], parts[3], parts[4]
        sample = "filetype|filename|fileurl\nfiletype: lecture, book, video, audio, image"
        msg = bot.send_message(chat_id, f"✏️ أرسل بيانات الملف بهذا الشكل (باستخدام رابط):\n{sample}")
        bot.register_next_step_handler(msg, add_file_from_text_step_with_ids, uniid, colid, depid, semid)
        return

    if parts[0] == "addfiletg" and call.from_user.id in ADMINS:
        uniid, colid, depid, semid = parts[1], parts[2], parts[3], parts[4]
        msg = bot.send_message(chat_id, "📤 أرسل الملف الآن كمرفق مع وصف في الـ caption يحتوي على: filetype|filename\nمثال في الوصف: lecture|Intro")
        bot.register_next_step_handler(msg, handle_uploaded_file, uniid, colid, depid, semid)
        return

    if parts[0] == "playfile":
        try:
            _, uniid, colid, depid, sem_id, ftype, fid = parts
        except Exception:
            bot.answer_callback_query(call.id, "خطأ في البيانات.")
            return
        filerec = db.child("university").child("universities_list").child(uniid).child("colleges").child(colid).child("department").child(depid).child("semesters").child(sem_id).child("files").child(ftype).child(fid).get().val()
        if not filerec:
            bot.answer_callback_query(call.id, "الملف غير موجود.")
            return
        telegramfileid = filerec.get("telegramfileid") or filerec.get("telegram_file_id") or filerec.get("telegramFileId")
        name = filerec.get("name") if isinstance(filerec, dict) else fid
        mime = filerec.get("mime", "") if isinstance(filerec, dict) else ""
        try:
            if telegramfileid:
                if "audio" in mime or ftype.startswith("lecture") or ftype.startswith("audio"):
                    bot.send_audio(call.message.chat.id, telegramfileid, caption=name)
                elif "video" in mime or ftype.startswith("video"):
                    bot.send_video(call.message.chat.id, telegramfileid, caption=name)
                elif "image" in mime or ftype.startswith("image"):
                    bot.send_photo(call.message.chat.id, telegramfileid, caption=name)
                else:
                    bot.send_document(call.message.chat.id, telegramfileid, caption=name)
                bot.answer_callback_query(call.id, "جارٍ الإرسال...")
                return
            url = filerec.get("url") if isinstance(filerec, dict) else None
            if url and str(url).startswith("http"):
                if ftype.startswith("lecture") or "audio" in mime:
                    bot.send_audio(call.message.chat.id, url, caption=name)
                elif ftype.startswith("video"):
                    bot.send_video(call.message.chat.id, url, caption=name)
                elif ftype.startswith("image"):
                    bot.send_photo(call.message.chat.id, url, caption=name)
                else:
                    bot.send_document(call.message.chat.id, url, caption=name)
                bot.answer_callback_query(call.id, "جارٍ الإرسال من URL...")
                return
            storage_path = filerec.get("storagepath") if isinstance(filerec, dict) else None
            if storage_path:
                tmp = tempfile.NamedTemporaryFile(delete=False)
                local_path = tmp.name
                tmp.close()
                try:
                    storage.child(storage_path).download(local_path)
                    ext = os.path.splitext(local_path)[1].lower()
                    if ext in [".mp3", ".wav", ".ogg"]:
                        bot.send_audio(call.message.chat.id, open(local_path, "rb"), caption=name)
                    elif ext in [".mp4", ".mkv", ".mov"]:
                        bot.send_video(call.message.chat.id, open(local_path, "rb"), caption=name)
                    elif ext in [".jpg", ".jpeg", ".png"]:
                        bot.send_photo(call.message.chat.id, open(local_path, "rb"), caption=name)
                    else:
                        bot.send_document(call.message.chat.id, open(local_path, "rb"), caption=name)
                finally:
                    try:
                        os.remove(local_path)
                    except Exception:
                        pass
                bot.answer_callback_query(call.id, "تم الإرسال.")
                return
            bot.answer_callback_query(call.id, "لا يوجد طريقة لإرسال هذا الملف.")
        except Exception as e:
            bot.answer_callback_query(call.id, f"خطأ أثناء الإرسال: {e}")
        return

# ---------- Add handlers implementations ----------
def add_university_step(message):
    try:
        text = message.text.strip()
        uniid, uniname, description, city, country = [p.strip() for p in text.split("|", 4)]
        uniid_safe = safe_id(uniid)
        db.child("university").child("universities_list").child(uniid_safe).set({
            "universityname": uniname,
            "description": description,
            "city": city,
            "country": country,
            "colleges": {}
        })
        bot.reply_to(message, f"✅ تم إضافة الجامعة: {uniname}")
    except Exception:
        bot.reply_to(message, "❌ خطأ في التنسيق. استخدم: universityid|university_name|description|city|country")

def add_college_step(message, uni_id):
    try:
        text = message.text.strip()
        collegeid, collegename = [p.strip() for p in text.split("|", 1)]
        collegeid_safe = safe_id(collegeid)
        db.child("university").child("universities_list").child(uni_id).child("colleges").child(collegeid_safe).set({
            "collegename": collegename,
            "department": {}
        })
        bot.reply_to(message, f"✅ تم إضافة الكلية: {collegename}")
    except Exception:
        bot.reply_to(message, "❌ خطأ في التنسيق. استخدم: collegeid|college_name")

def add_department_step(message, uniid, colid):
    try:
        text = message.text.strip()
        depid, depname = [p.strip() for p in text.split("|", 1)]
        depid_safe = safe_id(depid)
        db.child("university").child("universities_list").child(uniid).child("colleges").child(colid).child("department").child(depid_safe).set({
            "departmentname": depname,
            "semesters": {}
        })
        bot.reply_to(message, f"✅ تم إضافة القسم: {depname}")
    except Exception:
        bot.reply_to(message, "❌ خطأ في التنسيق. استخدم: departmentid|department_name")

def add_semester_step(message, uniid, colid, dep_id):
    try:
        text = message.text.strip()
        semid, semname = [p.strip() for p in text.split("|", 1)]
        semid_safe = safe_id(semid)
        db.child("university").child("universities_list").child(uniid).child("colleges").child(colid).child("department").child(dep_id).child("semesters").child(semid_safe).set({
            "semestername": semname,
            "files": {}
        })
        bot.reply_to(message, f"✅ تم إضافة السمستر: {semname}")
    except Exception:
        bot.reply_to(message, "❌ خطأ في التنسيق. استخدم: semesterid|semester_name")

def add_file_from_text_step(message):
    try:
        text = message.text.strip()
        uniid, colid, depid, semid, filetype, filename = [p.strip() for p in text.split("|", 5)]
        bot.reply_to(message, "✏️ الآن أرسل رابط الملف (URL) أو استخدم الأمر /uploadfile_tg لترفع الملف من تيليجرام.")
        bot.register_next_step_handler(message, add_file_from_text_handle_url, uniid, colid, depid, semid, filetype, filename)
    except Exception:
        bot.reply_to(message, "❌ خطأ في التنسيق. استخدم: universityid|collegeid|departmentid|semesterid|filetype|file_name")

def add_file_from_text_handle_url(message, uniid, colid, depid, semid, filetype, filename):
    try:
        file_url = message.text.strip()
        fileid = safe_id(filename)
        db.child("university").child("universities_list").child(uniid).child("colleges").child(colid).child("department").child(depid).child("semesters").child(semid).child("files").child(f"{filetype}s").child(fileid).set({
            "name": filename,
            "url": file_url
        })
        bot.reply_to(message, f"✅ تم إضافة الملف بالرابط: {filename}")
    except Exception as e:
        bot.reply_to(message, f"❌ خطأ: {e}")

def add_file_from_text_step_with_ids(message, uniid, colid, depid, semid):
    try:
        text = message.text.strip()
        filetype, filename, file_url = [p.strip() for p in text.split("|", 2)]
        fileid = safe_id(filename)
        db.child("university").child("universities_list").child(uniid).child("colleges").child(colid).child("department").child(depid).child("semesters").child(semid).child("files").child(f"{filetype}s").child(fileid).set({
            "name": filename,
            "url": file_url
        })
        bot.reply_to(message, f"✅ تم إضافة الملف: {filename}")
    except Exception as e:
        bot.reply_to(message, f"❌ خطأ: {e}")

# ---------- Upload via Telegram flow ----------
def handle_uploaded_file(message, uniid, colid, depid, semid):
    userid = message.from_user.id
    try:
        if message.content_type not in ["document", "photo", "video", "audio", "voice"]:
            pending = pendinguploads.get(userid)
            if pending:
                parsed = parse_caption_for_type_name(message.text or "")
                if not parsed:
                    bot.reply_to(message, "❌ الوصف غير صحيح. أرسل وصف بهذا الشكل: filetype|file_name")
                    return
                filetype, filename = parsed
                finalize_pending_upload(userid, filetype, filename)
                bot.reply_to(message, f"✅ تم إضافة الملف: {filename}")
                return
            else:
                bot.reply_to(message, "❌ لم نستلم ملف. أرسل الملف كمرفق مع وصف في الـ caption أو أرسل الملف أولاً ثم الوصف.")
                return

        caption = (message.caption or "").strip()
        parsed = parse_caption_for_type_name(caption)

        if message.content_type == "document":
            fileid = message.document.file_id
            originalname = message.document.file_name
            mime = message.document.mime_type
        elif message.content_type == "photo":
            fileid = message.photo[-1].file_id
            originalname = None
            mime = "image/jpeg"
        elif message.content_type == "video":
            fileid = message.video.file_id
            originalname = getattr(message.video, "file_name", None)
            mime = getattr(message.video, "mime_type", "video/mp4")
        elif message.content_type == "audio":
            fileid = message.audio.file_id
            originalname = getattr(message.audio, "file_name", None)
            mime = getattr(message.audio, "mime_type", "audio/mpeg")
        elif message.content_type == "voice":
            fileid = message.voice.file_id
            originalname = None
            mime = "audio/ogg"
        else:
            bot.reply_to(message, "❌ نوع المرفق غير مدعوم.")
            return

        if parsed:
            filetype, filename = parsed
            process_and_upload_file(fileid, originalname, mime, uniid, colid, depid, semid, filetype, filename)
            bot.reply_to(message, f"✅ تم رفع الملف و إضافته بنجاح: {filename}")
            return
        else:
            pendinguploads[userid] = {
                "fileid": fileid,
                "originalname": originalname,
                "mime": mime,
                "uniid": uniid,
                "colid": colid,
                "depid": depid,
                "semid": semid
            }
            msg = bot.send_message(message.chat.id, "❗ استلمت الملف لكن لم يحتوي الوصف المطلوب. أرسل الآن وصفًا بهذا الشكل:\nfiletype|file_name\nمثال: lecture|Intro")
            bot.register_next_step_handler(msg, handle_caption_after_file)
            return

    except Exception as e:
        bot.reply_to(message, f"❌ خطأ أثناء المعالجة: {e}")

def handle_caption_after_file(message):
    userid = message.from_user.id
    pending = pendinguploads.get(userid)
    if not pending:
        bot.reply_to(message, "❌ لا يوجد ملف معلق للربط به. أرسل الملف مجددًا مع الوصف في الـ caption.")
        return
    parsed = parse_caption_for_type_name(message.text or "")
    if not parsed:
        bot.reply_to(message, "❌ الوصف غير صحيح. الرجاء إرسال وصف بهذا الشكل: filetype|file_name")
        return
    filetype, filename = parsed
    try:
        finalize_pending_upload(userid, filetype, filename)
        bot.reply_to(message, f"✅ تم إضافة الملف: {filename}")
    except Exception as e:
        bot.reply_to(message, f"❌ خطأ أثناء الرفع: {e}")
    finally:
        if userid in pendinguploads:
            del pendinguploads[userid]

def finalize_pending_upload(userid, filetype, filename):
    pending = pendinguploads.get(userid)
    if not pending:
        raise Exception("لا يوجد ملف معلق")
    fileid = pending["fileid"]
    originalname = pending.get("originalname")
    mime = pending.get("mime")
    uniid = pending["uniid"]
    colid = pending["colid"]
    depid = pending["depid"]
    semid = pending["semid"]
    process_and_upload_file(fileid, originalname, mime, uniid, colid, depid, semid, filetype, filename)
    del pendinguploads[userid]

# ---------- Run ----------
if __name__ == "__main__":
    print("✅ البوت شغال...")
    bot.polling(none_stop=True)