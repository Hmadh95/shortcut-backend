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

CORS(app, resources={r"/api/*": {"origins": "*"}}, 
     supports_credentials=False,
     allow_headers=["Content-Type"],
     methods=["GET", "POST", "DELETE", "OPTIONS"])

jobs = {}

# تحقق من المتغيرات عند البدء
cookies = os.environ.get('YOUTUBE_COOKIES')
api_key = os.environ.get('YOUTUBE_API_KEY')
print(f"[{'✅' if cookies else '⚠️'}] YOUTUBE_COOKIES: {'loaded' if cookies else 'NOT FOUND'}")
print(f"[{'✅' if api_key else '⚠️'}] YOUTUBE_API_KEY: {'loaded' if api_key else 'NOT FOUND'}")


@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
    return response


@app.route('/api/<path:path>', methods=['OPTIONS'])
def handle_options(path):
    return '', 204


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


# ── POST /api/render/<job_id>/<clip_index> ────────────────────
# يعيد تصيير الكليب مع النصوص والتأثيرات والنسبة المطلوبة
@app.route('/api/render/<job_id>/<int:clip_index>', methods=['POST'])
def render_clip(job_id, clip_index):
    job = jobs.get(job_id)
    if not job or job['status'] != 'done':
        return jsonify({'error': 'الكليب غير جاهز'}), 404

    clips = job.get('clips', [])
    if clip_index >= len(clips):
        return jsonify({'error': 'رقم الكليب غير صحيح'}), 400

    data = request.get_json() or {}
    caption_text = data.get('text', clips[clip_index].get('text', ''))
    font_color   = data.get('color', 'white')
    font_size    = data.get('fontSize', 32)
    ratio        = data.get('ratio', '9:16')
    start        = data.get('start', clips[clip_index].get('start', 0))
    duration     = data.get('duration', clips[clip_index].get('duration', 45))

    input_path  = clips[clip_index]['file']
    render_id   = str(uuid.uuid4())[:8]
    output_path = f"outputs/{job_id}_render_{clip_index}_{render_id}.mp4"

    try:
        import subprocess

        # بناء فلتر النسبة
        ratio_filters = {
            '9:16': 'scale=640:360,pad=640:1136:0:(1136-360)/2:black',
            '1:1':  'scale=640:640:force_original_aspect_ratio=decrease,pad=640:640:(ow-iw)/2:(oh-ih)/2:black',
            '16:9': 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:black',
        }
        scale_filter = ratio_filters.get(ratio, ratio_filters['9:16'])

        # بناء فلتر النص
        if caption_text:
            safe_text = caption_text.replace("'", "\\'").replace(':', '\\:')[:100]
            text_filter = (
                f",drawtext=text='{safe_text}'"
                f":fontsize={font_size}"
                f":fontcolor={font_color}"
                f":x=(w-text_w)/2"
                f":y=h-text_h-30"
                f":box=1:boxcolor=black@0.6:boxborderw=8"
            )
        else:
            text_filter = ''

        vf = scale_filter + text_filter

        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-vf', vf,
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-crf', '28',
            '-c:a', 'aac',
            '-b:a', '128k',
            '-movflags', '+faststart',
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            return jsonify({'error': f'FFmpeg error: {result.stderr[-300:]}'}), 500

        # حفظ الملف المصيّر
        render_key = f'render_{clip_index}'
        if 'renders' not in job:
            job['renders'] = {}
        job['renders'][render_key] = output_path

        return jsonify({
            'success': True,
            'download': f'/api/download_render/{job_id}/{clip_index}/{render_id}'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── GET /api/download_render ──────────────────────────────────
@app.route('/api/download_render/<job_id>/<int:clip_index>/<render_id>')
def download_render(job_id, clip_index, render_id):
    output_path = f"outputs/{job_id}_render_{clip_index}_{render_id}.mp4"
    if not os.path.exists(output_path):
        return jsonify({'error': 'الملف غير موجود'}), 404
    return send_file(
        output_path,
        as_attachment=True,
        download_name=f'short_{clip_index + 1}_edited.mp4',
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
