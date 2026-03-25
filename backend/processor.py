# ============================================================
#  processor.py — منطق معالجة الفيديو
#  المراحل: تحميل → استخراج صوت → Whisper → FFmpeg → Shorts
# ============================================================

import os
import subprocess
import yt_dlp
from faster_whisper import WhisperModel


def process_video(job_id: str, url: str, jobs: dict):
    """الدالة الرئيسية — تُشغَّل في خيط منفصل"""

    try:
        os.makedirs('downloads', exist_ok=True)
        os.makedirs('outputs', exist_ok=True)

        # ── المرحلة 1: تحميل الفيديو من YouTube ─────────
        _update(jobs, job_id, 5, 'جارٍ تحميل الفيديو من YouTube...')

        video_path, duration, title = _download_video(job_id, url)

        # ── المرحلة 2: استخراج ملف الصوت ────────────────
        _update(jobs, job_id, 25, 'جارٍ استخراج الصوت...')

        audio_path = _extract_audio(job_id, video_path)

        # ── المرحلة 3: Whisper يحوّل الصوت إلى نص ───────
        _update(jobs, job_id, 40, 'الذكاء الاصطناعي يتعرف على الكلام...')

        segments = _transcribe(audio_path)

        # ── المرحلة 4: اختيار أفضل اللحظات ─────────────
        _update(jobs, job_id, 65, 'AI يحدد أفضل اللحظات...')

        best_clips = _find_best_clips(segments, duration)

        # ── المرحلة 5: قص الفيديو وتحويله إلى 9:16 ──────
        _update(jobs, job_id, 75, 'جارٍ إنشاء الـ Shorts...')

        clip_results = []
        total = len(best_clips)

        for i, clip in enumerate(best_clips):
            progress = 75 + int((i / total) * 20)
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

        # ── النهاية ──────────────────────────────────────
        jobs[job_id].update({
            'status':   'done',
            'progress': 100,
            'step':     f'تم إنشاء {len(clip_results)} Shorts بنجاح! 🎉',
            'clips':    clip_results,
            'title':    title,
        })

        # تنظيف الملفات المؤقتة
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
    """تحديث حالة المهمة"""
    jobs[job_id]['progress'] = progress
    jobs[job_id]['step'] = step
    print(f"[{job_id[:8]}] {progress}% — {step}")


def _download_video(job_id: str, url: str):
    """تحميل الفيديو بأفضل جودة مع الحفاظ على السرعة"""
    output_template = f"downloads/{job_id}.%(ext)s"

    ydl_opts = {
        'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'match_filter': yt_dlp.utils.match_filter_func('duration < 1200'),
    }

    # أولاً: جرب قراءة الـ Cookies من Environment Variable
    cookies_content = os.environ.get('YOUTUBE_COOKIES')
    if cookies_content:
        cookies_path = f"downloads/{job_id}_cookies.txt"
        with open(cookies_path, 'w') as f:
            f.write(cookies_content)
        ydl_opts['cookiefile'] = cookies_path

    # ثانياً: إذا لم يوجد، جرب الملف المحلي
    else:
        cookies_path = os.path.join(os.path.dirname(__file__), 'cookies.txt')
        if os.path.exists(cookies_path):
            ydl_opts['cookiefile'] = cookies_path

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        duration = info.get('duration', 0)
        title = info.get('title', 'video')

    # ابحث عن الملف الفعلي الذي تم تحميله
    video_path = None
    for f in os.listdir('downloads'):
        if f.startswith(job_id) and '_audio' not in f and '_cookies' not in f:
            video_path = f"downloads/{f}"
            break

    if not video_path:
        raise RuntimeError("لم يتم العثور على الفيديو بعد التحميل")

    return video_path, duration, title


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
    """
    خوارزمية اختيار أفضل المقاطع:
    - كثافة الكلام العالية = محتوى مهم
    - تجنب الفترات الهادئة والمقدمات
    - ضمان عدم تداخل المقاطع
    """
    if not segments:
        # إذا لم يُتعرف على كلام، قسّم الفيديو بالتساوي
        return _equal_split(total_duration, clip_duration, max_clips)

    # احسب نقاط لكل موضع ممكن
    candidates = []
    step = 5  # جرّب كل 5 ثواني

    for start in range(0, max(1, int(total_duration - clip_duration)), step):
        end = start + clip_duration
        # اجمع كل الكلام الذي يقع في هذا النطاق
        text_in_range = ' '.join(
            seg['text'] for seg in segments
            if seg['start'] >= start and seg['end'] <= end
        )
        word_count = len(text_in_range.split())
        # النقاط = عدد الكلمات لكل ثانية
        score = word_count / clip_duration
        candidates.append({
            'start':    float(start),
            'duration': float(min(clip_duration, total_duration - start)),
            'text':     text_in_range.strip(),
            'score':    score
        })

    # رتّب من الأعلى نقاطاً
    candidates.sort(key=lambda x: x['score'], reverse=True)

    # اختر أفضل المقاطع مع ضمان عدم التداخل
    selected = []
    for candidate in candidates:
        if len(selected) >= max_clips:
            break
        # تأكد أنه لا يتداخل مع مقطع مختار مسبقاً
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
    """
    قص الفيديو وتحويله إلى نسبة 9:16 (Shorts/Reels/TikTok)
    الدقة: 1080x1920 — الجودة: عالية
    """
    cmd = [
        'ffmpeg', '-y',
        '-ss', str(clip['start']),          # نقطة البداية
        '-i', video_path,
        '-t', str(clip['duration']),        # المدة
        # تحويل النسبة: اقتص المنتصف ثم تحجيم
        '-vf', 'crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920',
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '23',                       # جودة عالية (أقل = أفضل)
        '-c:a', 'aac',
        '-b:a', '128k',
        '-movflags', '+faststart',          # تحسين للـ streaming
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error: {result.stderr}")


def _cleanup(*paths):
    """حذف الملفات المؤقتة بعد الانتهاء"""
    for path in paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
