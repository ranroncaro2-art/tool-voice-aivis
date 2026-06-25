import threading
import queue

# Target Engines Configurations
ENGINES = {
    "AivisSpeech": "http://127.0.0.1:10101",
    "VOICEVOX": "http://127.0.0.1:50021"
}
ACTIVE_ENGINE = "AivisSpeech"
ENGINE_URL = ENGINES[ACTIVE_ENGINE]

# Task Management States
tasks_list = []
tasks_lock = threading.Lock()
task_queue = queue.Queue()
task_counter = 1
auto_filename_counter = 1

# Speaker Caching
GLOBAL_SPEAKER_MAP = {}
GLOBAL_SPEAKER_CHOICES = []

# Premium CSS for futuristic dark styling
CSS_STYLING = """
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap');

/* Main Body & Background */
body, .gradio-container {
    font-family: 'Outfit', sans-serif !important;
    background: linear-gradient(135deg, #07050f 0%, #0d091e 50%, #040308 100%) !important;
    color: #f1f5f9 !important;
}

/* Container Cards */
.gradio-container .block,
.gradio-container .form,
.gradio-container .prose {
    background: rgba(22, 17, 43, 0.96) !important;
    border: 1px solid rgba(139, 92, 246, 0.22) !important;
    border-radius: 16px !important;
    box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5) !important;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
}

.gradio-container .block:hover {
    border-color: rgba(167, 139, 250, 0.45) !important;
    box-shadow: 0 12px 40px rgba(139, 92, 246, 0.18) !important;
}

/* Prevent clipping of dropdown lists */
.gradio-container .block,
.gradio-container .form,
.gradio-container .row,
.gradio-container .col,
.gradio-container .group {
    overflow: visible !important;
}

/* Form Groups styling */
.gradio-container .group {
    background: rgba(25, 20, 52, 0.4) !important;
    border: 1px solid rgba(139, 92, 246, 0.12) !important;
    border-radius: 12px !important;
    padding: 15px !important;
    margin-bottom: 12px !important;
}

/* Headers styling */
.title-section {
    text-align: center;
    margin-bottom: 30px !important;
    padding: 20px !important;
    background: linear-gradient(135deg, rgba(124, 58, 237, 0.1) 0%, rgba(244, 114, 182, 0.05) 100%) !important;
    border-radius: 16px !important;
    border: 1px solid rgba(124, 58, 237, 0.2) !important;
}

.title-section h1 {
    font-weight: 800 !important;
    font-size: 2.5rem !important;
    background: linear-gradient(90deg, #a78bfa 0%, #f472b6 50%, #60a5fa 100%) !important;
    -webkit-background-clip: text !important;
    -webkit-text-fill-color: transparent !important;
    margin-bottom: 10px !important;
    letter-spacing: -0.5px !important;
}

.title-section p {
    color: #94a3b8 !important;
    font-size: 1.15rem;
    font-weight: 300 !important;
}

/* Buttons Styling */
.primary-btn {
    background: linear-gradient(135deg, #7c3aed 0%, #db2777 100%) !important;
    color: #ffffff !important;
    font-weight: 700 !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 12px 24px !important;
    box-shadow: 0 4px 20px rgba(124, 58, 237, 0.4) !important;
    cursor: pointer;
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
}

.primary-btn:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 6px 25px rgba(219, 39, 119, 0.6) !important;
    filter: brightness(1.1);
}

.primary-btn:active {
    transform: translateY(1px) !important;
}

.refresh-btn {
    background: rgba(255, 255, 255, 0.03) !important;
    color: #e2e8f0 !important;
    border: 1px solid rgba(139, 92, 246, 0.25) !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    cursor: pointer;
    transition: all 0.2s ease !important;
}

.refresh-btn:hover {
    background: rgba(139, 92, 246, 0.15) !important;
    border-color: #a78bfa !important;
    color: #ffffff !important;
    box-shadow: 0 0 12px rgba(167, 139, 250, 0.2) !important;
}

/* Input Fields overrides */
textarea, input[type=text], select {
    background: rgba(10, 8, 20, 0.8) !important;
    border: 1px solid rgba(139, 92, 246, 0.2) !important;
    border-radius: 8px !important;
    color: #f8fafc !important;
    padding: 10px !important;
    font-size: 0.95rem !important;
}

textarea:focus, input[type=text]:focus, select:focus {
    border-color: #f472b6 !important;
    box-shadow: 0 0 0 2px rgba(244, 114, 182, 0.25) !important;
}

/* Dropdown list customization to prevent overlap and click issues */
ul.options, .dropdown-options, .gradio-container .options {
    background-color: #110d26 !important;
    border: 1px solid rgba(139, 92, 246, 0.35) !important;
    border-radius: 8px !important;
    z-index: 9999 !important;
}

ul.options li, .dropdown-options li, .option, .gradio-container .option {
    background-color: #110d26 !important;
    color: #ffffff !important;
}

ul.options li:hover, .dropdown-options li:hover, .option:hover, .gradio-container .option:hover {
    background-color: #7c3aed !important;
    color: #ffffff !important;
}

.gradio-container .option.selected {
    background-color: rgba(139, 92, 246, 0.3) !important;
}

/* Sliders */
input[type=range] {
    accent-color: #db2777 !important;
}

/* Radio buttons container */
.gradio-container .wrap.vertical {
    flex-direction: row !important;
    gap: 15px !important;
}

.gradio-container .wrap.vertical label {
    background: rgba(255, 255, 255, 0.02) !important;
    border: 1px solid rgba(139, 92, 246, 0.15) !important;
    border-radius: 6px !important;
    padding: 6px 12px !important;
    cursor: pointer;
    transition: all 0.2s ease;
}

.gradio-container .wrap.vertical label:hover {
    background: rgba(139, 92, 246, 0.08) !important;
}

.gradio-container .wrap.vertical label.selected {
    background: rgba(124, 58, 237, 0.2) !important;
    border-color: #a78bfa !important;
}

/* Dataframe styling */
.queue-table table {
    border-collapse: collapse !important;
    border-radius: 8px !important;
    overflow: hidden !important;
}

.queue-table th {
    background: rgba(124, 58, 237, 0.18) !important;
    color: #f472b6 !important;
    font-weight: 700 !important;
    border-bottom: 2px solid rgba(124, 58, 237, 0.3) !important;
    padding: 12px !important;
    font-size: 0.95rem !important;
}

.queue-table td {
    padding: 10px !important;
    border-bottom: 1px solid rgba(139, 92, 246, 0.1) !important;
    font-size: 0.9rem !important;
}

.queue-table tr:hover {
    background: rgba(139, 92, 246, 0.04) !important;
}

/* Accordion styling */
.gradio-container .accordion {
    border: 1px solid rgba(139, 92, 246, 0.2) !important;
    border-radius: 8px !important;
    margin-top: 10px !important;
}

/* Info Box styling */
.info-note {
    background: linear-gradient(135deg, rgba(59, 130, 246, 0.08) 0%, rgba(147, 51, 234, 0.04) 100%) !important;
    border-left: 4px solid #3b82f6 !important;
    padding: 12px 16px !important;
    border-radius: 8px !important;
    margin-top: 15px !important;
    font-size: 0.9rem !important;
    color: #cbd5e1 !important;
}
"""
