import gradio as gr
import os
import config
import api_client
import text_processor
import queue_worker
import video_merger

# Start background queue daemon thread
queue_worker.start_worker_thread()

def handle_project_dir_scan(project_dir):
    if not project_dir:
        return "", "", "", "", None
        
    project_dir = os.path.abspath(project_dir)
    if not os.path.exists(project_dir) or not os.path.isdir(project_dir):
        raise gr.Error(f"Thư mục không tồn tại: {project_dir}")
        
    audio_extensions = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".wma"}
    audio_files = []
    srt_files = []
    
    try:
        for f in os.listdir(project_dir):
            full_path = os.path.join(project_dir, f)
            if os.path.isfile(full_path):
                ext = os.path.splitext(f)[1].lower()
                if ext in audio_extensions:
                    audio_files.append(full_path)
                elif ext == ".srt":
                    srt_files.append(full_path)
    except Exception as e:
        raise gr.Error(f"Lỗi khi đọc thư mục: {str(e)}")
        
    if not audio_files:
        raise gr.Error("Thiếu file: Không tìm thấy file âm thanh (.wav, .mp3, ...) nào trong thư mục dự án!")
        
    if not srt_files:
        raise gr.Error("Thiếu file: Không tìm thấy file phụ đề (.srt) nào trong thư mục dự án!")
        
    detected_audio = audio_files[0]
    detected_srt = srt_files[0]
    
    # Check for videos directory (case insensitive)
    detected_videos_dir = ""
    try:
        for d in os.listdir(project_dir):
            full_path = os.path.join(project_dir, d)
            if os.path.isdir(full_path) and d.lower() == "videos":
                detected_videos_dir = full_path
                break
    except Exception:
        pass
        
    if not detected_videos_dir:
        raise gr.Error("Thiếu thư mục: Không tìm thấy thư mục con 'videos' chứa các video minh họa trong thư mục dự án!")
        
    # Output path
    base_name = os.path.splitext(os.path.basename(detected_audio))[0]
    detected_output = os.path.join(project_dir, f"{base_name}_video.mp4")
    abs_output = os.path.abspath(detected_output)
    
    # Automatically preview existing video output if it exists (gr.Video only supports video formats; passing WAV/MP3 audio causes Gradio validation errors)
    preview_path = None
    if os.path.exists(abs_output):
        preview_path = abs_output
        
    return detected_audio, detected_srt, detected_videos_dir, abs_output, preview_path

def get_latest_completed_audio():
    import config
    with config.tasks_lock:
        for task in reversed(config.tasks_list):
            if task.get("status") == "✅ Hoàn thành" and task.get("path"):
                audio_path = task["path"]
                base_name, _ = os.path.splitext(audio_path)
                srt_path = f"{base_name}.srt"
                if os.path.exists(srt_path):
                    return audio_path, srt_path
                return audio_path, ""
    return "", ""

def handle_load_latest():
    audio, srt = get_latest_completed_audio()
    if not audio:
        raise gr.Error("Không tìm thấy file audio nào đã hoàn thành trong hàng chờ hiện tại!")
    base_name = os.path.splitext(os.path.basename(audio))[0]
    out_video = os.path.abspath(os.path.join(os.path.dirname(audio), f"{base_name}_video.mp4"))
    return audio, srt, out_video

def handle_auto_detect_srt(audio_path):
    if not audio_path:
        raise gr.Error("Vui lòng điền đường dẫn file âm thanh trước!")
    base_name, _ = os.path.splitext(audio_path)
    srt_path = f"{base_name}.srt"
    if os.path.exists(srt_path):
        return srt_path
    else:
        raise gr.Error(f"Không tìm thấy file phụ đề tương ứng tại: {srt_path}")

def handle_video_merge(audio_path, srt_path, video_dir, output_path, font_name, font_size, primary_color, outline_color, outline_width, margin_v, margin_h=120, use_gpu=False):
    logs = []
    def log_callback(msg):
        logs.append(msg)
        print(msg)
        
    try:
        if not audio_path or not os.path.exists(audio_path):
            return f"Lỗi: File âm thanh gốc không tồn tại hoặc chưa được quét: {audio_path}", None
        if not srt_path or not os.path.exists(srt_path):
            return f"Lỗi: File phụ đề SRT không tồn tại hoặc chưa được quét: {srt_path}", None
        if not video_dir or not os.path.exists(video_dir) or not os.path.isdir(video_dir):
            return f"Lỗi: Thư mục chứa videos minh họa không tồn tại hoặc chưa được quét: {video_dir}", None
        if not output_path:
            return "Lỗi: Vui lòng nhập đường dẫn file video đầu ra!", None
            
        audio_path = os.path.abspath(audio_path)
        srt_path = os.path.abspath(srt_path)
        video_dir = os.path.abspath(video_dir)
        output_path = os.path.abspath(output_path)
        
        # Run merge process
        video_merger.merge_video_process(
            audio_path=audio_path,
            srt_path=srt_path,
            videos_dir=video_dir,
            output_path=output_path,
            font_name=font_name,
            font_size=font_size,
            primary_color=primary_color,
            outline_color=outline_color,
            outline_width=outline_width,
            margin_v=margin_v,
            margin_h=margin_h,
            use_gpu=use_gpu,
            log_callback=log_callback
        )
        
        return "\n".join(logs), output_path
    except Exception as e:
        import traceback
        err_msg = f"Lỗi xảy ra trong quá trình ghép video:\n{str(e)}\n\nChi tiết:\n{traceback.format_exc()}"
        return "\n".join(logs) + "\n\n" + err_msg, None

def update_subtitle_preview(video_dir, font_name, font_size, primary_color, outline_color, outline_width, margin_v, margin_h=120):
    import subprocess
    import imageio_ffmpeg
    import video_merger
    
    FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
    
    # 1. Resolve videos directory and find a sample frame
    sample_frame_path = os.path.abspath(os.path.join("output", "temp_video_merger", "sample_frame.jpg"))
    os.makedirs(os.path.dirname(sample_frame_path), exist_ok=True)
    
    has_sample = False
    
    if video_dir and os.path.exists(video_dir) and os.path.isdir(video_dir):
        # Find first video
        allowed_extensions = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv", ".m4v"}
        videos = []
        try:
            for f in os.listdir(video_dir):
                if os.path.splitext(f)[1].lower() in allowed_extensions:
                    videos.append(os.path.join(video_dir, f))
        except Exception:
            pass
        
        if videos:
            videos.sort()
            first_video = videos[0]
            # Extract first frame at 1.0s to avoid potential black start frames
            try:
                cmd = [
                    FFMPEG_EXE, "-y",
                    "-ss", "00:00:01.00",
                    "-i", first_video,
                    "-vframes", "1",
                    "-f", "image2",
                    sample_frame_path
                ]
                result = subprocess.run(cmd, capture_output=True, timeout=5)
                if result.returncode != 0 or not os.path.exists(sample_frame_path):
                    cmd_fallback = [
                        FFMPEG_EXE, "-y",
                        "-i", first_video,
                        "-vframes", "1",
                        "-f", "image2",
                        sample_frame_path
                    ]
                    subprocess.run(cmd_fallback, capture_output=True, timeout=5)
                
                if os.path.exists(sample_frame_path):
                    has_sample = True
            except Exception as e:
                print(f"Error extracting sample frame: {e}")
                
    # 2. If no sample video frame, generate a placeholder image (dark gray 1920x1080 background)
    if not has_sample:
        try:
            cmd = [
                FFMPEG_EXE, "-y",
                "-f", "lavfi",
                "-i", "color=c=0x1E1E2E:s=1920x1080:d=1",
                "-vframes", "1",
                sample_frame_path
            ]
            subprocess.run(cmd, capture_output=True, timeout=5)
            if os.path.exists(sample_frame_path):
                has_sample = True
        except Exception as e:
            print(f"Error generating placeholder: {e}")
            
    if not has_sample or not os.path.exists(sample_frame_path):
        return None
        
    # 3. Create a temporary ASS file for preview
    temp_dir = os.path.dirname(sample_frame_path)
    preview_ass_path = os.path.join(temp_dir, "preview.ass")
    preview_output_path = os.path.join(temp_dir, "preview_output.jpg")
    
    # Convert hex colors to ASS
    ass_primary = video_merger.hex_to_ass_color(primary_color)
    ass_outline = video_merger.hex_to_ass_color(outline_color)
    
    # Generate ASS with style and a single dialogue line
    ass_content = f"""[Script Info]
Title: Preview
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
Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,Đây là chữ mẫu xem trước phụ đề (Live Preview)
Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,Dòng thứ hai: Cỡ chữ {font_size}px - Font {font_name}
"""
    
    try:
        with open(preview_ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)
            
        # Draw subtitles on the sample frame using FFmpeg ass filter
        cmd = [
            FFMPEG_EXE, "-y",
            "-i", "sample_frame.jpg",
            "-vf", "ass=preview.ass",
            "preview_output.jpg"
        ]
        
        result = subprocess.run(cmd, cwd=temp_dir, capture_output=True, timeout=10)
        if result.returncode == 0 and os.path.exists(preview_output_path):
            return preview_output_path
    except Exception as e:
        print(f"Error rendering subtitle preview: {e}")
        
    return None

def handle_draft_preview(audio_path, srt_path, video_dir, font_name, font_size, primary_color, outline_color, outline_width, margin_v, margin_h=120, use_gpu=False):
    import subprocess
    import imageio_ffmpeg
    import video_merger
    
    FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()
    
    try:
        if not audio_path or not os.path.exists(audio_path):
            return "Lỗi: Chưa có file âm thanh!", None
        if not srt_path or not os.path.exists(srt_path):
            return "Lỗi: Chưa có file phụ đề!", None
        if not video_dir or not os.path.exists(video_dir) or not os.path.isdir(video_dir):
            return "Lỗi: Chưa có thư mục video!", None
            
        # Create temp directory
        temp_dir = os.path.abspath(os.path.join("output", "temp_video_merger"))
        os.makedirs(temp_dir, exist_ok=True)
        
        # Find first video
        allowed_extensions = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv", ".m4v"}
        videos = []
        for f in os.listdir(video_dir):
            if os.path.splitext(f)[1].lower() in allowed_extensions:
                videos.append(os.path.join(video_dir, f))
                
        if not videos:
            return "Lỗi: Không tìm thấy video nào!", None
            
        videos.sort()
        first_video = videos[0]
        
        # Standardize the first video to cache if not done
        std_path = video_merger.get_standardized_cache_path(first_video, temp_dir)
        if not os.path.exists(std_path):
            video_merger.standardize_video(first_video, std_path, use_gpu=use_gpu)
            
        # Create a preview ASS file with style and first few lines of subtitles
        preview_ass_path = os.path.join(temp_dir, "draft_preview.ass")
        
        # Convert hex colors to ASS
        ass_primary = video_merger.hex_to_ass_color(primary_color)
        ass_outline = video_merger.hex_to_ass_color(outline_color)
        
        # Read first few lines of SRT
        with open(srt_path, "r", encoding="utf-8") as f:
            srt_content = f.read()
            
        # Parse SRT and convert to ASS
        srt_content = srt_content.replace('\r\n', '\n').strip()
        blocks = srt_content.split('\n\n')
        dialogues = []
        
        for block in blocks:
            lines = [l.strip() for l in block.split('\n') if l.strip()]
            if len(lines) < 2:
                continue
            time_line = ""
            text_start_idx = 1
            if "-->" in lines[0]:
                time_line = lines[0]
                text_start_idx = 1
            elif len(lines) >= 2 and "-->" in lines[1]:
                time_line = lines[1]
                text_start_idx = 2
            else:
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
            start_ass = video_merger.srt_time_to_ass(start_srt)
            end_ass = video_merger.srt_time_to_ass(end_srt)
            
            # Skip dialogues that start after 5 seconds to keep it focused
            parts = start_srt.replace(',', '.').split(':')
            if len(parts) == 3:
                s = float(parts[2])
                m = int(parts[1])
                h = int(parts[0])
                if h * 3600 + m * 60 + s > 5.0:
                    continue
                    
            sub_text = "\\N".join(lines[text_start_idx:])
            dialogues.append(f"Dialogue: 0,{start_ass},{end_ass},Default,,0,0,0,,{sub_text}")
            
        if not dialogues:
            dialogues.append("Dialogue: 0,0:00:00.00,0:00:05.00,Default,,0,0,0,,Xem trước kiểu chữ nháp (Draft Preview)")
            
        ass_content = f"""[Script Info]
Title: Draft Preview
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
""" + "\n".join(dialogues) + "\n"

        with open(preview_ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)
            
        # Output draft video path
        draft_video_path = os.path.join(temp_dir, "draft_preview.mp4")
        
        # Run FFmpeg to slice first 5s of standardized video, first 5s of audio, burn subtitles
        video_encoder = "h264_nvenc" if use_gpu else "libx264"
        preset_args = ["-preset", "p1"] if use_gpu else ["-preset", "ultrafast"]
        cmd = [
            FFMPEG_EXE, "-y",
            "-ss", "0", "-t", "5.0",
            "-i", "std_" + os.path.basename(std_path)[4:],
            "-ss", "0", "-t", "5.0",
            "-i", audio_path,
            "-filter_complex", "[0:v]ass=draft_preview.ass[v]",
            "-map", "[v]",
            "-map", "1:a",
            "-c:v", video_encoder,
        ] + preset_args + [
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-shortest",
            "draft_preview.mp4"
        ]
        
        result = subprocess.run(cmd, cwd=temp_dir, capture_output=True, timeout=15)
        if result.returncode == 0 and os.path.exists(draft_video_path):
            return "Thành công: Đã tạo video xem thử nháp 5s!", draft_video_path
        else:
            return f"Lỗi FFmpeg: {result.stderr}", None
            
    except Exception as e:
        import traceback
        return f"Lỗi xảy ra: {str(e)}\n\nChi tiết:\n{traceback.format_exc()}", None

with gr.Blocks(title="AivisSpeech TTS Script Engine") as demo:
    
    # Title Section
    gr.HTML(
        '''
        <div class="title-section">
            <h1>🎙️ AivisSpeech Long-form Script TTS Engine</h1>
            <p>Hệ thống chuyển đổi kịch bản tiếng Nhật dài tập trung vào Hàng chờ Tuần tự & Xử lý Nền</p>
        </div>
        '''
    )
    
    with gr.Tabs():
        with gr.Tab("🎙️ Tạo Voice & Phụ Đề (TTS)"):
            with gr.Row(equal_height=True):
                # Left Column: Configuration & Inputs
                with gr.Column(scale=1):
                    gr.Markdown("### ⚙️ BẢNG ĐIỀU KHIỂN & NHẬP LIỆU")
                    
                    with gr.Group():
                        gr.Markdown("#### 📝 Nhập Kịch Bản")
                        script_input = gr.Textbox(
                            label="Kịch bản tiếng Nhật (Nhiều dòng)",
                            placeholder="Nhập kịch bản tại đây. Mỗi dòng sẽ được chuyển đổi và nối lại...",
                            lines=8,
                            max_lines=12
                        )
                        with gr.Row():
                            max_chars_slider = gr.Slider(
                                label="Giới hạn ký tự một câu",
                                minimum=10,
                                maximum=100,
                                value=30,
                                step=1,
                                scale=3
                            )
                            split_btn = gr.Button("✂️ Tách câu (Xuống dòng)", elem_classes="refresh-btn", scale=2)
                    
                    with gr.Group():
                        gr.Markdown("#### 🎙️ Chọn Giọng Đọc & Engine")
                        with gr.Row():
                            engine_radio = gr.Radio(
                                label="Chọn Engine TTS",
                                choices=["AivisSpeech", "VOICEVOX"],
                                value=config.ACTIVE_ENGINE,
                                interactive=True,
                                scale=2
                            )
                            speaker_dropdown = gr.Dropdown(
                                label="Nhân vật giọng đọc",
                                choices=config.GLOBAL_SPEAKER_CHOICES,
                                value=config.GLOBAL_SPEAKER_CHOICES[0] if config.GLOBAL_SPEAKER_CHOICES else None,
                                interactive=True,
                                scale=3
                            )
                        refresh_btn = gr.Button("🔄 Làm mới danh sách giọng", elem_classes="refresh-btn")
                        
                    with gr.Group():
                        gr.Markdown("#### 🎚️ Thiết Lập Âm Thanh")
                        with gr.Row():
                            speed_slider = gr.Slider(
                                label="Tốc độ đọc (speedScale)",
                                minimum=0.5,
                                maximum=2.0,
                                value=1.0,
                                step=0.05
                            )
                            post_phoneme_slider = gr.Slider(
                                label="Độ trễ câu (postPhonemeLength - giây)",
                                minimum=0.0,
                                maximum=3.0,
                                value=0.5,
                                step=0.1
                            )
                    
                    with gr.Group():
                        gr.Markdown("#### 💾 Cấu Hình File Đầu Ra")
                        filename_input = gr.Textbox(
                            label="Tên file đích (.wav)",
                            placeholder="Ví dụ: kichban_tap1.wav (Bỏ trống sẽ tự động sinh tên)",
                            lines=1
                        )
                        with gr.Row():
                            output_dir_input = gr.Textbox(
                                label="Thư mục đầu ra (Output Folder)",
                                value=os.path.abspath("output"),
                                placeholder="Đường dẫn thư mục lưu file WAV...",
                                scale=4
                            )
                            select_dir_btn = gr.Button("📁 Chọn thư mục", elem_classes="refresh-btn", scale=1)
                        generate_srt_checkbox = gr.Checkbox(
                            label="☑️ Tự động tạo file phụ đề (.srt) cùng tên",
                            value=True
                        )
                    
                    submit_btn = gr.Button("⚡ THÊM VÀO HÀNG CHỜ", variant="primary", elem_classes="primary-btn")
                    
                # Right Column: Queue Monitoring & Results
                with gr.Column(scale=1):
                    gr.Markdown("### 📋 QUẢN LÝ HÀNG CHỜ (BACKGROUND QUEUE)")
                    
                    queue_table = gr.Dataframe(
                        headers=["ID", "Tên File", "Trạng Thái", "Đường Dẫn File Audio"],
                        datatype=["number", "str", "str", "str"],
                        column_count=(4, "fixed"),
                        value=queue_worker.get_queue_data(),
                        interactive=False,
                        elem_classes="queue-table"
                    )
                    
                    with gr.Row():
                        manual_refresh = gr.Button("🔄 Cập nhật trạng thái bảng", elem_classes="refresh-btn")
                    
                    gr.HTML(
                        '''
                        <div class="info-note">
                            <strong>💡 Hướng dẫn & Thông tin lưu trữ:</strong>
                            <ul style="margin-top: 5px; margin-bottom: 0; padding-left: 20px;">
                                <li>File âm thanh dạng <strong>.wav</strong> và phụ đề <strong>.srt</strong> sẽ được lưu tự động vào thư mục đầu ra đã chỉ định.</li>
                                <li>Trạng thái hàng chờ tự động cập nhật sau mỗi <strong>2 giây</strong>.</li>
                                <li>Hãy đảm bảo các ứng dụng Engine trên PC của bạn đã được khởi động trước khi thực hiện render.</li>
                            </ul>
                        </div>
                        '''
                    )
                    
        with gr.Tab("🎬 Ghép Video & Phụ Đề"):
            gr.Markdown("### 🎬 MODULE GHÉP VIDEO & BURN PHỤ ĐỀ")
            
            with gr.Row(equal_height=True):
                # Left Column: Inputs & Style Config
                with gr.Column(scale=1):
                    gr.Markdown("#### 📂 Chọn Thư Mục Dự Án")
                    with gr.Group():
                        with gr.Row():
                            project_dir_input = gr.Textbox(
                                label="Thư mục dự án (Chứa srt, mp3/wav và videos)",
                                placeholder="Chọn thư mục chứa dự án để quét tự động...",
                                lines=1,
                                scale=4
                            )
                            select_project_dir_btn = gr.Button("📁 Mở thư mục", elem_classes="refresh-btn", scale=1)

                    gr.Markdown("#### 📁 Đường Dẫn Tập Tin & Thư Mục Chi Tiết")
                    with gr.Group():
                        video_audio_input = gr.Textbox(
                            label="Đường dẫn file Âm thanh gốc (.wav / .mp3)",
                            placeholder="Đường dẫn file âm thanh (sẽ tự động điền khi quét thư mục)...",
                            lines=1,
                            interactive=False
                        )
                        video_srt_input = gr.Textbox(
                            label="Đường dẫn file Phụ đề (.srt)",
                            placeholder="Đường dẫn file phụ đề (sẽ tự động điền khi quét thư mục)...",
                            lines=1,
                            interactive=False
                        )
                        video_dir_input = gr.Textbox(
                            label="Thư mục chứa Videos minh họa",
                            placeholder="Thư mục videos (sẽ tự động điền khi quét thư mục)...",
                            lines=1,
                            interactive=False
                        )
                            
                    gr.Markdown("#### 🎨 Cấu Hình Kiểu Chữ Phụ Đề (ASS Styling)")
                    with gr.Group():
                        with gr.Row():
                            subtitle_font = gr.Dropdown(
                                label="Font chữ",
                                choices=["Segoe UI", "Arial", "Tahoma", "Times New Roman", "Impact", "Verdana", "Courier New", "Georgia", "Calibri", "Consolas"],
                                value="Segoe UI",
                                allow_custom_value=True,
                                interactive=True,
                                scale=3
                            )
                            subtitle_size = gr.Slider(
                                label="Cỡ chữ (Font Size)",
                                minimum=10,
                                maximum=100,
                                value=36,
                                step=1,
                                scale=3
                            )
                        
                        with gr.Row():
                            font_color = gr.ColorPicker(
                                label="Màu chữ chính",
                                value="#FFFFFF",
                                scale=1
                            )
                            outline_color = gr.ColorPicker(
                                label="Màu viền chữ",
                                value="#000000",
                                scale=1
                            )
                            outline_width = gr.Slider(
                                label="Độ dày viền (Stroke)",
                                minimum=0.0,
                                maximum=10.0,
                                value=3.0,
                                step=0.5,
                                scale=2
                            )
                        with gr.Row():
                            margin_v = gr.Slider(
                                label="Căn lề dưới (Bottom Margin)",
                                minimum=10,
                                maximum=200,
                                value=60,
                                step=5,
                                scale=1
                            )
                            margin_h = gr.Slider(
                                label="Căn lề trái/phải (Horizontal Margin)",
                                minimum=10,
                                maximum=300,
                                value=120,
                                step=10,
                                scale=1
                            )
                            
                    with gr.Group():
                        gr.Markdown("#### 💾 Cấu Hình Video Đầu Ra")
                        video_output_path = gr.Textbox(
                            label="Đường dẫn file video đầu ra (.mp4)",
                            value=os.path.abspath(os.path.join("output", "merged_video.mp4")),
                            placeholder="Đường dẫn lưu file mp4 kết quả...",
                            lines=1
                        )
                        use_gpu = gr.Checkbox(
                            label="🚀 Kích hoạt Tăng tốc phần cứng GPU (NVIDIA NVENC)",
                            value=True
                        )
                        
                    with gr.Row():
                        btn_update_preview = gr.Button("🔄 XEM THỬ NHÁP (5s)", variant="secondary", elem_classes="refresh-btn")
                        merge_video_btn = gr.Button("⚡ GHÉP VIDEO & RENDER", variant="primary", elem_classes="primary-btn")
                    
                # Right Column: Output Logs & Player Preview
                with gr.Column(scale=1):
                    gr.Markdown("### 🖥️ XEM TRƯỚC PHỤ ĐỀ & VIDEO KẾT QUẢ")
                    
                    subtitle_preview_image = gr.Image(
                        label="Xem trước kiểu chữ (Subtitle Live Preview)",
                        interactive=False
                    )
                    
                    video_preview = gr.Video(
                        label="Xem trước Video kết quả (Sau khi Render)",
                        interactive=False
                    )
                    
                    video_log_output = gr.Textbox(
                        label="Nhật ký xử lý (Process Logs)",
                        placeholder="Trạng thái render sẽ được hiển thị tại đây...",
                        lines=8,
                        max_lines=10,
                        interactive=False
                    )
            
    # --- Event Binding ---
    
    # --- Event Binding for Video Tab ---
    
    # Select Project Directory and auto-scan files
    select_project_dir_btn.click(
        fn=api_client.choose_output_directory,
        inputs=project_dir_input,
        outputs=project_dir_input
    ).then(
        fn=handle_project_dir_scan,
        inputs=project_dir_input,
        outputs=[video_audio_input, video_srt_input, video_dir_input, video_output_path, video_preview]
    ).then(
        fn=update_subtitle_preview,
        inputs=[video_dir_input, subtitle_font, subtitle_size, font_color, outline_color, outline_width, margin_v, margin_h],
        outputs=subtitle_preview_image
    )
    
    # Live preview updates when style settings change
    style_inputs = [video_dir_input, subtitle_font, subtitle_size, font_color, outline_color, outline_width, margin_v, margin_h]
    for comp in style_inputs:
        comp.change(
            fn=update_subtitle_preview,
            inputs=style_inputs,
            outputs=subtitle_preview_image
        )
        
    # Update draft preview video button
    btn_update_preview.click(
        fn=handle_draft_preview,
        inputs=[video_audio_input, video_srt_input, video_dir_input, subtitle_font, subtitle_size, font_color, outline_color, outline_width, margin_v, margin_h, use_gpu],
        outputs=[video_log_output, video_preview]
    )
    
    # Run video merge process
    merge_video_btn.click(
        fn=handle_video_merge,
        inputs=[
            video_audio_input, 
            video_srt_input, 
            video_dir_input, 
            video_output_path, 
            subtitle_font, 
            subtitle_size, 
            font_color, 
            outline_color, 
            outline_width, 
            margin_v,
            margin_h,
            use_gpu
        ],
        outputs=[video_log_output, video_preview]
    )

    # 1. Split Text Button
    split_btn.click(
        fn=text_processor.handle_split_text,
        inputs=[script_input, max_chars_slider],
        outputs=script_input
    )
    
    # 1b. Engine Selection Change
    engine_radio.change(
        fn=api_client.handle_engine_change,
        inputs=engine_radio,
        outputs=speaker_dropdown
    )
    
    # 2. Refresh Speakers Button
    refresh_btn.click(
        fn=api_client.handle_refresh,
        inputs=engine_radio,
        outputs=speaker_dropdown
    )
    
    # 3. Submit Button
    submit_btn.click(
        fn=queue_worker.add_task_to_queue,
        inputs=[script_input, filename_input, output_dir_input, speaker_dropdown, speed_slider, post_phoneme_slider, generate_srt_checkbox],
        outputs=[queue_table, script_input, filename_input]
    )
    
    # 3b. Select Output Directory Button
    select_dir_btn.click(
        fn=api_client.choose_output_directory,
        inputs=output_dir_input,
        outputs=output_dir_input
    )
    
    # 4. Manual Table Refresh Button
    manual_refresh.click(
        fn=queue_worker.get_queue_data,
        inputs=None,
        outputs=queue_table
    )
    
    # 5. Auto-Refresh mechanism triggered every 2 seconds using gr.Timer
    timer = gr.Timer(2)
    timer.tick(
        fn=queue_worker.get_queue_data,
        outputs=queue_table
    )
    
    # 6. Load speakers list automatically when the web page is opened/reloaded
    demo.load(
        fn=api_client.handle_refresh,
        inputs=engine_radio,
        outputs=speaker_dropdown
    )
    
    # 7. Load initial subtitle preview style placeholder
    demo.load(
        fn=update_subtitle_preview,
        inputs=[video_dir_input, subtitle_font, subtitle_size, font_color, outline_color, outline_width, margin_v, margin_h],
        outputs=subtitle_preview_image
    )

def get_drives():
    import os
    if os.name == 'nt':
        import string
        from ctypes import windll
        drives = []
        try:
            bitmask = windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drives.append(f"{letter}:/")
                bitmask >>= 1
        except Exception:
            drives = ["C:/", "D:/", "E:/", "F:/", "G:/", "H:/"]
        return drives
    return ["/"]

if __name__ == "__main__":
    print("Starting AivisSpeech TTS UI App ...")
    demo.launch(
        server_name="127.0.0.1", 
        server_port=7860, 
        share=False, 
        theme=gr.themes.Soft(primary_hue="violet", secondary_hue="indigo"), 
        css=config.CSS_STYLING,
        allowed_paths=get_drives()
    )
