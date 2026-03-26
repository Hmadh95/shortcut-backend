# ============================================================
#  processor.py — منطق معالجة الفيديو
#  المراحل: تحميل → استخراج صوت → Whisper → FFmpeg → Shorts
# ============================================================

import os
import subprocess
import requests
import urllib.request
from faster_whisper import WhisperModel


def process_video(job_id: str, url: str, jobs: dict):
    """الدالة الرئيسية — تُشغَّل في خيط منفصل"""

    try:
        os.makedirs('downloads', exist_ok=True)
        os.makedirs('outputs', exist_ok=True)

        # ── المرحلة 1: استخراج معلومات الفيديو ──────────
        _update(jobs, job_id, 5, 'جارٍ استخراج معلومات الفيديو...')

        video_id = _extract_video_id(url)
        video_info = _get_video_info(video_id)
        duration = video_info['duration']
        title = video_info['title']

        # ── المرحلة 2: تحميل الفيديو ─────────────────────
        _update(jobs, job_id, 15, 'جارٍ تحميل الفيديو...')
        video_path = _download_video(job_id, video_id)

        # ── المرحلة 3: استخراج ملف الصوت ────────────────
        _update(jobs, job_id, 35, 'جارٍ استخراج الصوت...')
        audio_path = _extract_audio(job_id, video_path)

        # ── المرحلة 4: Whisper يحوّل الصوت إلى نص ───────
        _update(jobs, job_id, 50, 'الذكاء الاصطناعي يتعرف على الكلام...')
        segments = _transcribe(audio_path)

        # ── المرحلة 5: اختيار أفضل اللحظات ─────────────
        _update(jobs, job_id, 70, 'AI يحدد أفضل اللحظات...')
        best_clips = _find_best_clips(segments, duration)

        # ── المرحلة 6: قص الفيديو وتحويله إلى 9:16 ──────
        _update(jobs, job_id, 80, 'جارٍ إنشاء الـ Shorts...')

        clip_results = []
        total = len(best_clips)

        for i, clip in enumerate(best_clips):
            progress = 80 + int((i / total) * 15)
            _update(jobs, job_id, progress, f'جارٍ معالجة الكليب {i + 1} من {total}...')

            output_path = f"outputs/{job_id}_short_{i}.mp4"
            _create_short(video_path, output_path, clip)

            clip_results.append({
                'file':     output_path,
                'start':    round(clip['start'], 2),
                'end':      round(clip['start'] + clip['duration'], 2),
                'duration': round(clip['duration'], 2),
                'text':     clip['text'],
                'score':    round(clip['score'], 2),
                'download': f"/api/download/{job_id}/{i}"
            })

        jobs[job_id].update({
            'status':   'done',
            'progress': 100,
            'step':     f'تم إنشاء {len(clip_results)} Shorts بنجاح! 🎉',
            'clips':    clip_results,
            'title':    title,
        })

        _cleanup(video_path, audio_path)

    except Exception as e:
        jobs[job_id].update({
            'status': 'error',
            'step':   'حدث خطأ أثناء المعالجة',
            'error':  str(e)
        })
        print(f"[ERROR] job {job_id}: {e}")


# ── دوال مساعدة ───────────────────────────────────────────────

def _update(jobs, job_id, progress, step):
    jobs[job_id]['progress'] = progress
    jobs[job_id]['step'] = step
    print(f"[{job_id[:8]}] {progress}% — {step}")


def _extract_video_id(url: str) -> str:
    """استخراج معرّف الفيديو من الرابط"""
    import re
    patterns = [
        r'(?:v=|youtu\.be/|embed/|shorts/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"لم يتم التعرف على رابط YouTube: {url}")


def _get_video_info(video_id: str) -> dict:
    """جلب معلومات الفيديو عبر YouTube Data API"""
    api_key = os.environ.get('YOUTUBE_API_KEY')
    if not api_key:
        raise ValueError("YOUTUBE_API_KEY غير موجود في المتغيرات")

    url = f"https://www.googleapis.com/youtube/v3/videos"
    params = {
        'id': video_id,
        'key': api_key,
        'part': 'snippet,contentDetails'
    }

    response = requests.get(url, params=params)
    data = response.json()

    if not data.get('items'):
        raise ValueError(f"الفيديو غير موجود أو محظور: {video_id}")

    item = data['items'][0]
    title = item['snippet']['title']

    # تحويل مدة ISO 8601 إلى ثواني
    duration_str = item['contentDetails']['duration']
    duration = _parse_duration(duration_str)

    return {'title': title, 'duration': duration, 'id': video_id}


def _parse_duration(duration_str: str) -> float:
    """تحويل PT1H2M3S إلى ثواني"""
    import re
    pattern = r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?'
    match = re.match(pattern, duration_str)
    if not match:
        return 0
    hours   = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def _download_video(job_id: str, video_id: str) -> str:
    """تحميل الفيديو عبر YT-API على RapidAPI"""
    import urllib.request

    rapidapi_key = os.environ.get('RAPIDAPI_KEY', '')
    if not rapidapi_key:
        raise RuntimeError("RAPIDAPI_KEY غير موجود في المتغيرات")

    # جلب رابط التحميل المباشر
    api_url = "https://yt-api.p.rapidapi.com/dl"
    headers = {
        "X-RapidAPI-Key": rapidapi_key,
        "X-RapidAPI-Host": "yt-api.p.rapidapi.com"
    }
    params = {"id": video_id}

    print(f"[⬇️] Fetching download URL for video: {video_id}")
    response = requests.get(api_url, headers=headers, params=params)
    data = response.json()

    if response.status_code != 200:
        raise RuntimeError(f"فشل جلب رابط التحميل: {response.status_code} — {data}")

    # ابحث عن رابط mp4 بأفضل جودة
    download_url = None
    formats = data.get('formats', []) or data.get('adaptiveFormats', [])

    for fmt in formats:
        mime = fmt.get('mimeType', '')
        if 'video/mp4' in mime and fmt.get('qualityLabel') in ['720p', '480p', '360p']:
            download_url = fmt.get('url')
            print(f"[✅] Found format: {fmt.get('qualityLabel')}")
            break

    if not download_url:
        # جرب أي رابط متاح
        for fmt in formats:
            if fmt.get('url'):
                download_url = fmt.get('url')
                break

    if not download_url:
        raise RuntimeError(f"لم يتم العثور على رابط تحميل: {list(data.keys())}")

    # تحميل الفيديو
    video_path = f"downloads/{job_id}.mp4"
    print(f"[⬇️] Downloading to {video_path}...")
    urllib.request.urlretrieve(download_url, video_path)

    size = os.path.getsize(video_path)
    if size < 1000:
        raise RuntimeError("الملف المُحمَّل فارغ أو تالف")

    print(f"[✅] Downloaded: {size / 1024 / 1024:.1f} MB")
    return video_path


def _extract_audio(job_id: str, video_path: str) -> str:
    """استخراج ملف صوتي مضغوط لـ Whisper"""
    audio_path = f"downloads/{job_id}_audio.wav"

    # ابحث عن الملف الفعلي إذا كان الامتداد مختلفاً
    if not os.path.exists(video_path):
        # جرب امتدادات مختلفة
        for ext in ['mp4', 'webm', 'mkv', 'm4a', 'mp4.part']:
            alt = f"downloads/{job_id}.{ext}"
            if os.path.exists(alt):
                video_path = alt
                break

    if not os.path.exists(video_path):
        # ابحث عن أي ملف يبدأ بـ job_id
        for f in os.listdir('downloads'):
            if f.startswith(job_id) and '_audio' not in f:
                video_path = f"downloads/{f}"
                break

    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-vn',
        '-acodec', 'pcm_s16le',
        '-ar', '16000',
        '-ac', '1',
        audio_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg audio error: {result.stderr[-500:]}")

    return audio_path


def _transcribe(audio_path: str) -> list:
    """
    استخدام faster-whisper للتعرف على الكلام
    أخف وأسرع من openai-whisper بنفس الدقة
    النموذج 'tiny' = سريع جداً وحجم صغير
    النموذج 'base' = توازن بين السرعة والدقة
    """
    model = WhisperModel("tiny", device="cpu", compute_type="int8")

    segments_gen, _ = model.transcribe(
        audio_path,
        word_timestamps=True,
        language=None  # اكتشاف تلقائي للغة
    )

    # تحويل generator إلى list
    segments = []
    for seg in segments_gen:
        segments.append({
            'start': seg.start,
            'end':   seg.end,
            'text':  seg.text.strip()
        })

    return segments


def _find_best_clips(segments: list, total_duration: float,
                     clip_duration: int = 45, max_clips: int = 3) -> list:
    """اختيار أفضل المقاطع"""

    # تأكد أن المدة الكلية معقولة
    if total_duration <= 0:
        total_duration = 300

    # قلل مدة الكليب إذا كان الفيديو قصيراً
    clip_duration = min(clip_duration, int(total_duration / 2))
    clip_duration = max(10, clip_duration)

    if not segments:
        return _equal_split(total_duration, clip_duration, max_clips)

    candidates = []
    step = 5

    for start in range(0, max(1, int(total_duration - clip_duration)), step):
        end = min(start + clip_duration, total_duration)
        actual_duration = end - start

        if actual_duration < 10:
            continue

        text_in_range = ' '.join(
            seg['text'] for seg in segments
            if seg['start'] >= start and seg['end'] <= end
        )
        word_count = len(text_in_range.split())
        score = word_count / actual_duration

        candidates.append({
            'start':    float(start),
            'duration': float(actual_duration),
            'text':     text_in_range.strip(),
            'score':    score
        })

    if not candidates:
        return _equal_split(total_duration, clip_duration, max_clips)

    candidates.sort(key=lambda x: x['score'], reverse=True)

    selected = []
    for candidate in candidates:
        if len(selected) >= max_clips:
            break
        overlap = any(
            abs(candidate['start'] - s['start']) < clip_duration
            for s in selected
        )
        if not overlap:
            selected.append(candidate)

    return selected if selected else _equal_split(total_duration, clip_duration, max_clips)


def _equal_split(total_duration: float, clip_duration: int, max_clips: int) -> list:
    """تقسيم متساوٍ احتياطي عندما لا يوجد كلام"""
    clips = []
    step = total_duration / (max_clips + 1)
    for i in range(max_clips):
        start = step * (i + 1)
        clips.append({
            'start': start,
            'duration': min(clip_duration, total_duration - start),
            'text': '',
            'score': 0.0
        })
    return clips


def _create_short(video_path: str, output_path: str, clip: dict):
    """قص الفيديو وتحويله إلى نسبة 9:16"""

    start    = max(0, float(clip['start']))
    duration = max(10, min(60, float(clip['duration'])))

    print(f"[FFmpeg] start={start} duration={duration} input={video_path}")

    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-ss', str(start),
        '-t',  str(duration),
        '-vf', 'scale=640:360,pad=640:1136:0:(1136-360)/2:black',
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
        print(f"[FFmpeg STDERR]: {result.stderr[-1000:]}")
        raise RuntimeError(f"FFmpeg failed: {result.stderr[-300:]}")

    if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
        raise RuntimeError("FFmpeg produced empty file")


def _cleanup(*paths):
    """حذف الملفات المؤقتة بعد الانتهاء"""
    for path in paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
