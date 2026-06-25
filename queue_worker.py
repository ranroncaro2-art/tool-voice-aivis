import threading
import queue
import requests
import base64
import os
import json
import gradio as gr
import config
import api_client
import text_processor

def save_queue_state():
    """Saves the current tasks list and counters to a local JSON file. Thread-safe."""
    with config.tasks_lock:
        state = {
            "tasks_list": [dict(t) for t in config.tasks_list],
            "task_counter": config.task_counter,
            "auto_filename_counter": config.auto_filename_counter
        }
    state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queue_state.json")
    try:
        temp_file = state_file + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, state_file)
    except Exception as e:
        print(f"Error saving queue state: {repr(e)}")

def load_queue_state():
    """Loads the tasks list and counters from the JSON file. Thread-safe."""
    state_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "queue_state.json")
    if not os.path.exists(state_file):
        return
        
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
            
        loaded_tasks = state.get("tasks_list", [])
        loaded_task_counter = state.get("task_counter", 1)
        loaded_auto_counter = state.get("auto_filename_counter", 1)
        
        with config.tasks_lock:
            config.tasks_list.clear()
            # Clear queue safely
            while not config.task_queue.empty():
                try:
                    config.task_queue.get_nowait()
                except (queue.Empty, ValueError):
                    break
                    
            for task in loaded_tasks:
                # If a task was running or waiting, reset its status to queued and re-queue it
                if task.get("status", "").startswith("⚡") or task.get("status") == "⏳ Đang xếp hàng":
                    task["status"] = "⏳ Đang xếp hàng"
                    config.task_queue.put(task["id"])
                
                config.tasks_list.append(task)
                
            config.task_counter = max(loaded_task_counter, max([t["id"] for t in config.tasks_list] + [0]) + 1)
            config.auto_filename_counter = loaded_auto_counter
            
        # Resave state immediately so that any reset statuses are reflected on disk
        save_queue_state()
        print(f"Successfully loaded {len(config.tasks_list)} tasks from queue state. Counter={config.task_counter}")
    except Exception as e:
        print(f"Error loading queue state: {repr(e)}")

def tts_worker():
    """Background daemon thread that processes tasks from the queue sequentially (FIFO)."""
    while True:
        task_id = config.task_queue.get()
        if task_id is None:
            break
        
        task = None
        with config.tasks_lock:
            for t in config.tasks_list:
                if t["id"] == task_id:
                    task = t
                    break
        
        if not task:
            config.task_queue.task_done()
            continue
            
        with config.tasks_lock:
            task["status"] = "⚡ Đang xử lý..."
        save_queue_state()
            
        try:
            script_text = task["text"]
            speaker_id = task["speaker_id"]
            speed_scale = task["speed_scale"]
            post_phoneme_length = task["post_phoneme_length"]
            filename = task["filename"]
            output_dir = task["output_dir"]
            generate_srt = task["generate_srt"]
            engine_url = task.get("engine_url", config.ENGINE_URL)
            
            # Split Japanese script by newline, removing empty lines
            lines = [line.strip() for line in script_text.split('\n') if line.strip()]
            if not lines:
                raise ValueError("Kịch bản rỗng hoặc không chứa nội dung hợp lệ.")
                
            audio_segments = []
            srt_blocks = []
            current_time = 0.0
            
            for idx, line in enumerate(lines):
                with config.tasks_lock:
                    task["status"] = f"⚡ Đang xử lý... (Dòng {idx+1}/{len(lines)})"
                
                # Step 1: POST /audio_query
                query_url = f"{engine_url}/audio_query"
                query_params = {"text": line, "speaker": speaker_id}
                
                try:
                    query_res = requests.post(query_url, params=query_params, timeout=10)
                except Exception as ex:
                    print(f"Connection error calling /audio_query for line {idx+1}: {repr(ex)}")
                    raise RuntimeError(f"Lỗi tại dòng {idx+1}")
                
                if query_res.status_code != 200:
                    print(f"API error calling /audio_query for line {idx+1}: HTTP {query_res.status_code}")
                    raise RuntimeError(f"Lỗi tại dòng {idx+1}")
                    
                try:
                    query_json = query_res.json()
                except Exception as ex:
                    print(f"JSON decode error for line {idx+1}: {repr(ex)}")
                    raise RuntimeError(f"Lỗi tại dòng {idx+1}")
                
                # Step 2: Modify JSON configurations
                query_json["speedScale"] = speed_scale
                query_json["postPhonemeLength"] = post_phoneme_length
                
                # Step 3: POST /synthesis
                synth_url = f"{engine_url}/synthesis"
                synth_params = {"speaker": speaker_id}
                try:
                    synth_res = requests.post(synth_url, params=synth_params, json=query_json, timeout=30)
                except Exception as ex:
                    print(f"Connection error calling /synthesis for line {idx+1}: {repr(ex)}")
                    raise RuntimeError(f"Lỗi tại dòng {idx+1}")
                    
                if synth_res.status_code != 200:
                    print(f"API error calling /synthesis for line {idx+1}: HTTP {synth_res.status_code}")
                    raise RuntimeError(f"Lỗi tại dòng {idx+1}")
                    
                audio_bytes = synth_res.content
                audio_segments.append(audio_bytes)
                
                # Calculate timing and build SRT blocks if requested
                duration = api_client.get_wav_duration(audio_bytes)
                
                start_str = text_processor.format_srt_time(current_time)
                # Spoken duration excludes the postPhonemeLength silence gap
                spoken_duration = max(0.1, duration - post_phoneme_length)
                end_str = text_processor.format_srt_time(current_time + spoken_duration)
                
                srt_blocks.append(f"{idx + 1}\n{start_str} --> {end_str}\n{line}\n")
                current_time += duration
            
            # Step 4: Stitch files using /connect_waves
            with config.tasks_lock:
                task["status"] = "⚡ Đang ghép nối âm thanh..."
            save_queue_state()
                
            b64_segments = [base64.b64encode(seg).decode('utf-8') for seg in audio_segments]
            
            connect_url = f"{engine_url}/connect_waves"
            try:
                connect_res = requests.post(connect_url, json=b64_segments, timeout=60)
            except Exception as ex:
                print(f"Connection error calling /connect_waves: {repr(ex)}")
                raise RuntimeError("Lỗi ghép nối âm thanh")
                
            if connect_res.status_code != 200:
                print(f"API error calling /connect_waves: HTTP {connect_res.status_code}")
                raise RuntimeError("Ghép nối âm thanh thất bại (Engine trả về lỗi)")
                
            final_wav_bytes = connect_res.content
                
            # Step 5: Save physical files (WAV and optionally SRT)
            os.makedirs(output_dir, exist_ok=True)
            output_filepath = os.path.join(output_dir, filename)
            with open(output_filepath, "wb") as f:
                f.write(final_wav_bytes)
                
            # If enabled, save subtitle file
            if generate_srt:
                base_name, _ = os.path.splitext(filename)
                srt_filepath = os.path.join(output_dir, f"{base_name}.srt")
                with open(srt_filepath, "w", encoding="utf-8") as f_srt:
                    f_srt.write("\n".join(srt_blocks))
            
            abs_path = os.path.abspath(output_filepath)
            
            with config.tasks_lock:
                task["status"] = "✅ Hoàn thành"
                task["path"] = abs_path
            save_queue_state()
                
        except RuntimeError as re:
            with config.tasks_lock:
                task["status"] = f"❌ {str(re)}"
            save_queue_state()
        except Exception as e:
            with config.tasks_lock:
                task["status"] = f"❌ Lỗi: {str(e)}"
            save_queue_state()
        finally:
            config.task_queue.task_done()

def get_queue_data():
    """Formats the current task list for the Gradio Dataframe."""
    with config.tasks_lock:
        data = []
        for t in config.tasks_list:
            data.append([
                t["id"],
                t["filename"],
                t["status"],
                t["path"]
            ])
        return data

def add_task_to_queue(script_text, filename, output_dir, speaker_name, speed_scale, post_phoneme_length, generate_srt):
    """Validates inputs, constructs a task, and pushes it into the background worker queue."""
    script_text = script_text.strip() if script_text else ""
    if not script_text:
        raise gr.Error("Vui lòng nhập nội dung kịch bản!")
        
    if not speaker_name or speaker_name.startswith("Chưa kết nối"):
        raise gr.Error("Chưa có kết nối tới Engine! Hãy bật ứng dụng tương ứng và nhấn làm mới danh sách giọng.")
        
    speaker_id = config.GLOBAL_SPEAKER_MAP.get(speaker_name)
    if speaker_id is None and speaker_name:
        # Suffix matching fallback for cached selections or missing prefixes
        for k, v in config.GLOBAL_SPEAKER_MAP.items():
            if k.endswith(speaker_name) or speaker_name.endswith(k):
                speaker_id = v
                speaker_name = k
                break
                
    if speaker_id is None:
        raise gr.Error("Giọng đọc đã chọn không tồn tại!")
        
    filename = filename.strip() if filename else ""
    if not filename:
        filename = f"script_{config.auto_filename_counter}.wav"
        config.auto_filename_counter += 1
    else:
        if not filename.lower().endswith(".wav"):
            filename += ".wav"
            
    # Resolve output directory
    output_dir = output_dir.strip() if output_dir else ""
    if not output_dir:
        output_dir = os.path.abspath("output")
    else:
        output_dir = os.path.abspath(output_dir)
        
    os.makedirs(output_dir, exist_ok=True)
            
    # Package task configuration
    task_id = config.task_counter
    config.task_counter += 1
    
    task_obj = {
        "id": task_id,
        "filename": filename,
        "output_dir": output_dir,
        "status": "⏳ Đang xếp hàng",
        "path": "",
        "text": script_text,
        "speaker_id": speaker_id,
        "speed_scale": speed_scale,
        "post_phoneme_length": post_phoneme_length,
        "generate_srt": generate_srt,
        "engine_url": config.ENGINES.get(config.ACTIVE_ENGINE, config.ENGINE_URL)
    }
    
    with config.tasks_lock:
        config.tasks_list.append(task_obj)
        
    save_queue_state()
    config.task_queue.put(task_id)
    
    return get_queue_data(), "", ""

def start_worker_thread():
    """Starts the background worker as a daemon thread."""
    load_queue_state()
    worker_thread = threading.Thread(target=tts_worker, daemon=True)
    worker_thread.start()
    return worker_thread
