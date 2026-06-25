import os
import re
import random
import subprocess
import hashlib
import imageio_ffmpeg

# Get the bundled FFmpeg executable path
FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()

def get_media_duration(file_path):
    """
    Retrieves the duration of a media file (audio or video) in seconds
    by running ffmpeg -i and parsing the output.
    """
    if not os.path.exists(file_path):
        return 0.0
    
    try:
        # Run ffmpeg -i which outputs details to stderr
        result = subprocess.run(
            [FFMPEG_EXE, "-i", file_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )
        
        # Search for Duration: HH:MM:SS.xx
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", result.stderr)
        if match:
            hours = int(match.group(1))
            minutes = int(match.group(2))
            seconds = float(match.group(3))
            return hours * 3600 + minutes * 60 + seconds
    except Exception as e:
        print(f"Error getting duration for {file_path}: {e}")
    return 0.0

def hex_to_ass_color(hex_str):
    """
    Converts a standard Hex color (#RRGGBB or #RRGGBBAA) to ASS color format (&H00BBGGRR or &HAABBGGRR).
    Note: ASS uses Alpha Blue Green Red, and Alpha 00 is opaque, FF is transparent.
    """
    hex_str = hex_str.strip().lstrip('#')
    if len(hex_str) == 6:
        r = hex_str[0:2]
        g = hex_str[2:4]
        b = hex_str[4:6]
        return f"&H00{b}{g}{r}"  # &H00BBGGRR (Alpha=00 means opaque)
    elif len(hex_str) == 8:
        r = hex_str[0:2]
        g = hex_str[2:4]
        b = hex_str[4:6]
        a = hex_str[6:8]
        # ASS transparency: 00 is opaque, FF is transparent.
        # Normal hex alpha: FF is opaque, 00 is transparent.
        # So we invert the alpha value.
        val_a = 255 - int(a, 16)
        return f"&H{val_a:02X}{b}{g}{r}"
    else:
        return "&H00FFFFFF"  # Default to white opaque

def srt_time_to_ass(srt_time_str):
    """
    Converts SRT timestamp (HH:MM:SS,mmm) to ASS timestamp (H:MM:SS.cs).
    Example: "00:01:23,456" -> "0:01:23.45"
    """
    parts = srt_time_str.replace(',', '.').split(':')
    if len(parts) == 3:
        h = int(parts[0])
        m = int(parts[1])
        s_ms = parts[2]
        s_parts = s_ms.split('.')
        s = int(s_parts[0])
        ms = int(s_parts[1]) if len(s_parts) > 1 else 0
        cs = ms // 10  # convert milliseconds (3 digits) to centiseconds (2 digits)
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"
    return srt_time_str

def convert_srt_to_ass(srt_path, ass_path, font_name, font_size, primary_color, outline_color, outline_width, margin_v, margin_h=120):
    """
    Reads an SRT file and converts it to an ASS file with custom styles.
    """
    if not os.path.exists(srt_path):
        raise FileNotFoundError(f"Không tìm thấy file phụ đề SRT: {srt_path}")
        
    with open(srt_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Normalize line endings
    content = content.replace('\r\n', '\n').strip()
    
    # Split by double newlines to get blocks
    blocks = content.split('\n\n')
    
    ass_dialogues = []
    
    for idx, block in enumerate(blocks):
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if len(lines) < 2:
            continue
            
        # Find the line containing the timestamp
        time_line = ""
        text_start_idx = 1
        
        # Sometimes there's an index number line before the timestamp
        if "-->" in lines[0]:
            time_line = lines[0]
            text_start_idx = 1
        elif len(lines) >= 2 and "-->" in lines[1]:
            time_line = lines[1]
            text_start_idx = 2
        else:
            # Look for any line with -->
            for i, l in enumerate(lines):
                if "-->" in l:
                    time_line = l
                    text_start_idx = i + 1
                    break
                    
        if not time_line:
            continue
            
        time_parts = time_line.split("-->")
        if len(time_parts) != 2:
            continue
            
        start_srt = time_parts[0].strip()
        end_srt = time_parts[1].strip()
        
        start_ass = srt_time_to_ass(start_srt)
        end_ass = srt_time_to_ass(end_srt)
        
        # Subtitle text consists of the remaining lines
        sub_text_lines = lines[text_start_idx:]
        # In ASS, newlines are represented as \N
        sub_text = "\\N".join(sub_text_lines)
        
        # Dialogue format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
        ass_dialogues.append(f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{sub_text}")
        
    # Format styles
    ass_primary = hex_to_ass_color(primary_color)
    ass_outline = hex_to_ass_color(outline_color)
    
    ass_header = f"""[Script Info]
Title: Subtitles
ScriptType: v4.00+
WrapStyle: 0
PlayResX: 1920
PlayResY: 1080
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{ass_primary},&H000000FF,{ass_outline},&H00000000,-1,0,0,0,100,100,0,0,1,{outline_width},1,2,{margin_h},{margin_h},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    with open(ass_path, "w", encoding="utf-8") as f_ass:
        f_ass.write(ass_header)
        f_ass.write("\n".join(ass_dialogues))
        f_ass.write("\n")

def get_standardized_cache_path(video_path, temp_dir):
    """
    Generates a unique cache file path in temp_dir based on video_path, mtime, and size.
    """
    stat = os.stat(video_path)
    key_str = f"{video_path}_{stat.st_mtime}_{stat.st_size}"
    h = hashlib.md5(key_str.encode('utf-8')).hexdigest()
    return os.path.join(temp_dir, f"std_{h}.mp4")

def standardize_video(input_path, output_path, use_gpu=False, log_callback=None):
    """
    Standardizes a single video clip to 1920x1080, 30fps, libx264 or h264_nvenc, yuv420p, no audio (-an).
    """
    if log_callback:
        gpu_info = " (GPU)" if use_gpu else ""
        log_callback(f"Chuẩn hóa video{gpu_info}: {os.path.basename(input_path)} -> 1080p 30fps...")
        
    encoder = "h264_nvenc" if use_gpu else "libx264"
    cmd = [
        FFMPEG_EXE, "-y",
        "-i", input_path,
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30",
        "-c:v", encoder,
        "-pix_fmt", "yuv420p",
        "-an",
        output_path
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"Lỗi khi chuẩn hóa video {input_path}: {result.stderr}")

def merge_video_process(audio_path, srt_path, videos_dir, output_path, 
                        font_name, font_size, primary_color, outline_color, 
                        outline_width, margin_v, margin_h=120, use_gpu=False, log_callback=None):
    """
    Main function to run the video merger process.
    """
    if log_callback:
        log_callback("Bắt đầu xử lý ghép video...")
        
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Không tìm thấy file âm thanh kịch bản: {audio_path}")
        
    if not os.path.exists(srt_path):
        raise FileNotFoundError(f"Không tìm thấy file phụ đề srt: {srt_path}")
        
    if not os.path.exists(videos_dir) or not os.path.isdir(videos_dir):
        raise FileNotFoundError(f"Không tìm thấy thư mục video: {videos_dir}")
        
    # Get audio duration
    audio_duration = get_media_duration(audio_path)
    if audio_duration <= 0:
        raise ValueError(f"Thời lượng file âm thanh không hợp lệ (<= 0): {audio_path}")
        
    if log_callback:
        log_callback(f"Thời lượng audio kịch bản: {audio_duration:.2f} giây.")
        
    # Find all videos in directory
    allowed_extensions = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv", ".m4v"}
    video_files = []
    for f in os.listdir(videos_dir):
        ext = os.path.splitext(f)[1].lower()
        if ext in allowed_extensions:
            video_files.append(os.path.join(videos_dir, f))
            
    if not video_files:
        raise ValueError(f"Không tìm thấy file video minh họa nào trong thư mục: {videos_dir}")
        
    # Sort files alphabetically to respect order
    video_files.sort()
    
    if log_callback:
        log_callback(f"Tìm thấy {len(video_files)} video minh họa trong thư mục.")
        
    # Create temp directory
    temp_dir = os.path.join(os.path.dirname(output_path), "temp_video_merger")
    os.makedirs(temp_dir, exist_ok=True)
    
    # Analyze duration of each video and build sequence
    video_durations = {}
    sequence = []
    current_total_duration = 0.0
    
    # 1. First add all videos in order
    for v in video_files:
        dur = get_media_duration(v)
        if dur > 0:
            video_durations[v] = dur
            sequence.append(v)
            current_total_duration += dur
            if log_callback:
                log_callback(f"Đọc video: {os.path.basename(v)} ({dur:.2f}s)")
        else:
            if log_callback:
                log_callback(f"[Cảnh báo] Bỏ qua video lỗi hoặc không lấy được thời lượng: {os.path.basename(v)}")
                
    if not sequence:
        raise ValueError("Không có video minh họa nào hợp lệ!")
        
    # 2. If total duration is less than audio, loop randomly
    if current_total_duration < audio_duration:
        if log_callback:
            log_callback(f"Tổng thời lượng video ({current_total_duration:.2f}s) ít hơn âm thanh ({audio_duration:.2f}s). Bắt đầu loop random...")
        
        # We loop until we cover the duration
        while current_total_duration < audio_duration:
            v = random.choice(video_files)
            dur = video_durations.get(v, 0.0)
            if dur > 0:
                sequence.append(v)
                current_total_duration += dur
                
        if log_callback:
            log_callback(f"Đã tạo chuỗi video loop ngẫu nhiên. Tổng thời lượng mới: {current_total_duration:.2f}s (gồm {len(sequence)} phân đoạn).")
    else:
        if log_callback:
            log_callback(f"Tổng thời lượng video ({current_total_duration:.2f}s) đã đủ đáp ứng âm thanh ({audio_duration:.2f}s). Cắt phần thừa khi xuất.")
 
    # 3. Standardize all unique videos in the sequence (using cache)
    unique_videos_needed = set(sequence)
    standardized_paths = {}
    
    for idx, v in enumerate(unique_videos_needed):
        std_path = get_standardized_cache_path(v, temp_dir)
        standardized_paths[v] = std_path
        
        # Only standardize if cache doesn't exist
        if not os.path.exists(std_path):
            if log_callback:
                log_callback(f"[{idx+1}/{len(unique_videos_needed)}] Chưa có cache chuẩn hóa.")
            standardize_video(v, std_path, use_gpu=use_gpu, log_callback=log_callback)
        else:
            if log_callback:
                log_callback(f"[{idx+1}/{len(unique_videos_needed)}] Sử dụng cache chuẩn hóa của: {os.path.basename(v)}")
                
    # 4. Write concat file (concat_list.txt)
    concat_list_path = os.path.join(temp_dir, "concat_list.txt")
    with open(concat_list_path, "w", encoding="utf-8") as f_list:
        for v in sequence:
            std_p = standardized_paths[v]
            # Convert backslash to forward slash for FFmpeg concat compatibility on Windows
            std_p_normalized = std_p.replace('\\', '/')
            # Escape single quotes in path just in case
            std_p_escaped = std_p_normalized.replace("'", "'\\''")
            f_list.write(f"file '{std_p_escaped}'\n")
            
    # 5. Convert SRT to ASS in temp directory
    ass_path = os.path.join(temp_dir, "subtitles.ass")
    if log_callback:
        log_callback("Chuyển đổi phụ đề SRT sang định dạng ASS...")
    convert_srt_to_ass(
        srt_path=srt_path,
        ass_path=ass_path,
        font_name=font_name,
        font_size=font_size,
        primary_color=primary_color,
        outline_color=outline_color,
        outline_width=outline_width,
        margin_v=margin_v,
        margin_h=margin_h
    )
    
    # 6. Execute final stitching and burn-in subtitles
    if log_callback:
        log_callback("Đang tiến hành ghép nối video và burn phụ đề...")
        
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Run FFmpeg in the context of temp_dir to avoid absolute path colons issues inside the ass filter
    # e.g., filter will just be [0:v]ass=subtitles.ass[v]
    video_encoder = "h264_nvenc" if use_gpu else "libx264"
    cmd = [
        FFMPEG_EXE, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", "concat_list.txt",
        "-i", audio_path,
        "-filter_complex", "[0:v]ass=subtitles.ass[v]",
        "-map", "[v]",
        "-map", "1:a",
        "-t", f"{audio_duration:.3f}",
        "-c:v", video_encoder,
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        output_path
    ]
    
    result = subprocess.run(
        cmd,
        cwd=temp_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore"
    )
    
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"FFmpeg error: {result.stderr}")
        
    if log_callback:
        log_callback(f"✅ Ghép video hoàn tất thành công! Đầu ra lưu tại: {output_path}")
        
    return output_path
