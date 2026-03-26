# ============================================================
#  ShortCut AI — Backend API
#  Stack: Python + Flask + yt-dlp + Whisper + FFmpeg
# ============================================================

import os
import uuid
import threading
import json
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from processor import process_video

app = Flask(__name__)
CORS(app, origins=["*"])
jobs = {}

# تحقق من المتغيرات عند البدء
cookies = os.environ.get('YOUTUBE_COOKIES')
api_key = os.environ.get('YOUTUBE_API_KEY')
print(f"[{'✅' if cookies else '⚠️'}] YOUTUBE_COOKIES: {'loaded' if cookies else 'NOT FOUND'}")
print(f"[{'✅' if api_key else '⚠️'}] YOUTUBE_API_KEY: {'loaded' if api_key else 'NOT FOUND'}")


# ── Health Check ─────────────────────────────────────────────
@app.route('/')
def home():
    return jsonify({
        'status': 'running',
        'service': 'ShortCut AI Backend',
        'version': '1.0.0'
    })


# ── POST /api/convert ─────────────────────────────────────────
# يستقبل رابط YouTube ويبدأ عملية التحويل
@app.route('/api/convert', methods=['POST'])
def convert():
    data = request.get_json()

    if not data or not data.get('url'):
        return jsonify({'error': 'الرابط مطلوب'}), 400

    url = data['url'].strip()

    # التحقق أن الرابط من YouTube
    if 'youtube.com' not in url and 'youtu.be' not in url:
        return jsonify({'error': 'الرجاء إدخال رابط YouTube صحيح'}), 400

    # إنشاء معرّف فريد للمهمة
    job_id = str(uuid.uuid4())

    # تهيئة حالة المهمة
    jobs[job_id] = {
        'status': 'processing',
        'progress': 0,
        'step': 'جارٍ الاتصال بـ YouTube...',
        'clips': [],
        'error': None
    }

    # تشغيل المعالجة في خيط منفصل حتى لا يتجمد السيرفر
    thread = threading.Thread(
        target=process_video,
        args=(job_id, url, jobs)
    )
    thread.daemon = True
    thread.start()

    return jsonify({'jobId': job_id}), 202


# ── GET /api/status/<job_id> ──────────────────────────────────
# يعيد حالة المهمة والتقدم الحالي
@app.route('/api/status/<job_id>')
def status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'المهمة غير موجودة'}), 404
    return jsonify(job)


# ── GET /api/download/<job_id>/<clip_index> ───────────────────
# يرسل ملف الـ Short الجاهز للتحميل
@app.route('/api/download/<job_id>/<int:clip_index>')
def download(job_id, clip_index):
    job = jobs.get(job_id)

    if not job:
        return jsonify({'error': 'المهمة غير موجودة'}), 404

    if job['status'] != 'done':
        return jsonify({'error': 'المهمة لم تنته بعد'}), 400

    clips = job.get('clips', [])
    if clip_index >= len(clips):
        return jsonify({'error': 'رقم الكليب غير صحيح'}), 400

    file_path = clips[clip_index]['file']
    if not os.path.exists(file_path):
        return jsonify({'error': 'الملف غير موجود'}), 404

    return send_file(
        file_path,
        as_attachment=True,
        download_name=f'short_{clip_index + 1}.mp4',
        mimetype='video/mp4'
    )


# ── DELETE /api/job/<job_id> ──────────────────────────────────
# حذف المهمة وملفاتها لتوفير المساحة
@app.route('/api/job/<job_id>', methods=['DELETE'])
def delete_job(job_id):
    job = jobs.pop(job_id, None)
    if job:
        # حذف الملفات المؤقتة
        for clip in job.get('clips', []):
            if os.path.exists(clip.get('file', '')):
                os.remove(clip['file'])
    return jsonify({'message': 'تم الحذف'})


if __name__ == '__main__':
    os.makedirs('downloads', exist_ok=True)
    os.makedirs('outputs', exist_ok=True)

    port = int(os.environ.get('PORT', 8080))
    print(f"Starting server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
