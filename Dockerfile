# اختر نسخة Python
FROM python:3.12-slim

# خلي مجلد العمل /app
WORKDIR /app

# انسخ الملفات
COPY requirements.txt .
COPY . .

# ثبت المكتبات
RUN pip install --upgrade pip setuptools wheel
RUN pip install -r requirements.txt

# شغل البرنامج
CMD ["python", "albutana.py"]