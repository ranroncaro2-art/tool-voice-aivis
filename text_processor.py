def format_srt_time(seconds):
    """Formats raw seconds into the standard SRT timestamp format (HH:MM:SS,mmm)."""
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

def handle_split_text(text, max_chars):
    """Splits full script text by grouping sentences until they exceed max_chars, only breaking at punctuation."""
    if not text:
        return ""
        
    paragraphs = text.split('\n')
    all_lines = []
    punctuations = {'。', '？', '！', '?', '!', '.', '　'}
    closing_brackets = {'」', '』', '）', ')', ']', '}', '”', '"'}
    max_chars = int(max_chars)
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
            
        current_line = []
        n = len(para)
        i = 0
        while i < n:
            current_line.append(para[i])
            if para[i] in punctuations:
                # Consume any trailing closing brackets/quotes immediately so they stay with the sentence
                while i + 1 < n and para[i + 1] in closing_brackets:
                    i += 1
                    current_line.append(para[i])
                
                current_str = "".join(current_line).strip()
                if len(current_str) >= max_chars:
                    all_lines.append(current_str)
                    current_line = []
            i += 1
            
        remaining = "".join(current_line).strip()
        if remaining:
            all_lines.append(remaining)
            
    return "\n".join(all_lines)
