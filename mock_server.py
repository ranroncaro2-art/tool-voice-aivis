from flask import Flask, request, jsonify, send_file
import base64
import struct
import io
import math

app = Flask(__name__)

# Sample Speakers list
MOCK_SPEAKERS = [
    {
        "name": "Aivis Female (Normal)",
        "speaker_uuid": "aivis-f-normal-uuid",
        "styles": [
            {"name": "Normal", "id": 1},
            {"name": "Sweet", "id": 2},
            {"name": "Angry", "id": 3}
        ]
    },
    {
        "name": "Aivis Male (Deep)",
        "speaker_uuid": "aivis-m-deep-uuid",
        "styles": [
            {"name": "Normal", "id": 10},
            {"name": "Whisper", "id": 11}
        ]
    }
]

def make_dummy_wav(text, speaker_id, speed_scale=1.0, post_phoneme_length=0.5):
    # Generates a simple sound wave
    char_count = len(text) if text else 5
    duration = max(0.5, char_count * 0.1) / speed_scale
    
    # Add the post_phoneme_length to the total duration
    duration += post_phoneme_length
    
    sample_rate = 24000
    num_samples = int(duration * sample_rate)
    
    # Generate a quiet 440Hz sine wave (or silence for post_phoneme_length)
    data = bytearray(num_samples * 2) # 16-bit mono PCM
    frequency = 440.0
    for i in range(num_samples):
        # We only generate sine wave for the non-silent part
        if i < int((duration - post_phoneme_length) * sample_rate):
            t = float(i) / sample_rate
            value = int(2000.0 * math.sin(2.0 * math.pi * frequency * t))
            struct.pack_into('<h', data, i * 2, value)
        else:
            # Silence
            struct.pack_into('<h', data, i * 2, 0)
            
    header = bytearray(44)
    struct.pack_into('<4sI4s4sIHHIIHH4sI', header, 0,
                     b'RIFF',
                     36 + len(data),
                     b'WAVE',
                     b'fmt ',
                     16, # Subchunk1Size
                     1,  # AudioFormat (PCM)
                     1,  # NumChannels (Mono)
                     sample_rate,
                     sample_rate * 2, # ByteRate
                     2,  # BlockAlign
                     16, # BitsPerSample
                     b'data',
                     len(data))
    return bytes(header) + bytes(data)

@app.route('/speakers', methods=['GET'])
def get_speakers():
    if '50021' in request.host or '50025' in request.host:
        return jsonify([
            {
                "name": "VOICEVOX Speaker",
                "speaker_uuid": "vv-uuid",
                "styles": [{"name": "Normal", "id": 100}]
            }
        ])
    return jsonify(MOCK_SPEAKERS)

@app.route('/audio_query', methods=['POST'])
def audio_query():
    text = request.args.get('text', '')
    speaker = request.args.get('speaker', '1')
    if speaker == "-999":
        return jsonify({"detail": "Speaker not found"}), 400
    
    # Return VOICEVOX AudioQuery structure
    query = {
        "accent_phrases": [],
        "speedScale": 1.0,
        "pitchScale": 0.0,
        "intonationScale": 1.0,
        "volumeScale": 1.0,
        "prePhonemeLength": 0.1,
        "postPhonemeLength": 0.5,
        "outputSamplingRate": 24000,
        "outputStereo": False,
        "kana": "",
        "text": text
    }
    return jsonify(query)

@app.route('/synthesis', methods=['POST'])
def synthesis():
    speaker = request.args.get('speaker', '1')
    query_data = request.json or {}
    
    text = query_data.get('text', 'サンプル')
    speed_scale = query_data.get('speedScale', 1.0)
    post_phoneme_length = query_data.get('postPhonemeLength', 0.5)
    
    wav_bytes = make_dummy_wav(text, speaker, speed_scale, post_phoneme_length)
    
    return send_file(
        io.BytesIO(wav_bytes),
        mimetype="audio/wav",
        as_attachment=True,
        download_name="synthesis.wav"
    )

@app.route('/connect_waves', methods=['POST'])
def connect_waves():
    b64_list = request.json
    if not isinstance(b64_list, list):
        return jsonify({"detail": "Invalid body, must be list of base64 strings"}), 400
        
    wav_bytes_list = []
    for item in b64_list:
        try:
            decoded = base64.b64decode(item)
            wav_bytes_list.append(decoded)
        except Exception as e:
            return jsonify({"detail": f"Failed to decode base64 item: {e}"}), 400
            
    # Merge the WAV files
    merged = merge_wavs(wav_bytes_list)
    
    return send_file(
        io.BytesIO(merged),
        mimetype="audio/wav",
        as_attachment=True,
        download_name="connected.wav"
    )

def merge_wavs(wav_bytes_list):
    if not wav_bytes_list:
        return b""
    
    first_wav = wav_bytes_list[0]
    if len(first_wav) < 44:
        return b"".join(wav_bytes_list)
    
    header = bytearray(first_wav[:44])
    
    pcm_data = b""
    for wav in wav_bytes_list:
        if len(wav) >= 44:
            pcm_data += wav[44:]
        else:
            pcm_data += wav
            
    struct.pack_into('<I', header, 4, 36 + len(pcm_data))
    struct.pack_into('<I', header, 40, len(pcm_data))
    
    return bytes(header) + pcm_data

if __name__ == '__main__':
    print("Starting AivisSpeech Mock Server on http://127.0.0.1:10101 ...")
    app.run(host='127.0.0.1', port=10101)
