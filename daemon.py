import asyncio, platform, json, re, os, socket, openwakeword, threading
import numpy as np
import sounddevice as sd
import screen_brightness_control as sbc
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from process_observer import ProcessObserver
from faster_whisper import WhisperModel
from openwakeword.model import Model
from zeroconf import ServiceInfo, Zeroconf
from agent_orchestrator import run_autonomous_agent

app = FastAPI()
observer = ProcessObserver()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins (Chrome, Mobile, Desktop)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- INITIALIZE LOCAL AI MODELS ---
print("Loading Faster-Whisper model...")
# Using 'tiny.en' or 'base.en' for high speed; use 'small.en' or 'medium.en' for higher precision
stt_model = WhisperModel("base.en", device="cpu", compute_type="int8") 

print("Loading OpenWakeWord model...")
openwakeword.utils.download_models()
# Triggers on standard built-in models like 'hey_jarvis' or 'alexa'
wake_model = Model(wakeword_models=["hey_jarvis"]) 

# Global WebSockets pool for client UI updates
active_cnct = []
#------

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def set_system_volume(level):
    system = platform.system()
    level = max(0, (min(100, level)))

    if system == "Windows":
        from pycaw.pycaw import AudioUtilities

        devices = AudioUtilities.GetSpeakers()
        volume = devices.EndpointVolume
        volume.SetMasterVolumeLevelScalar(level / 100.0, None)

    elif system == "Darwin":
        import os
        os.system(f"osascript -e 'set volume output volume {level}'")

    elif system == "Linux":
        import os
        os.system(f"pactl set-sink-volume @DEFAULT-SINK@ {level}%")

def lockScreen():
    system = platform.system()
    if system == "Windows":
        import ctypes
        ctypes.windll.user32.LockWorkstation()
    elif system == "Darwin":
        os.system("pmset displaysleepnow")
    elif system == "Linux":
        os.system("xdg-screensaver lock")

# --- INTENT PARSER ---
async def parse_and_execute_intent(transcript: str):
    print(f"[Voice Intent Received]: '{transcript}'")
    text = transcript.lower()
    
    # Notify clients of transcription
    await broadcast_event({"type": "transcription", "text": transcript})

    # Volume Parsing
    if "volume" in text:
        match = re.search(r'\d+', text)
        if match:
            val = int(match.group())
            set_system_volume(val)
            await broadcast_event({"type": "status", "action": "set_volume", "value": val})
        elif "mute" in text or "zero" in text:
            set_system_volume(0)
            await broadcast_event({"type": "status", "action": "set_volume", "value": 0})

    # Brightness Parsing
    elif "brightness" in text:
        match = re.search(r'\d+', text)
        if match:
            val = int(match.group())
            sbc.set_brightness(val)
            await broadcast_event({"type": "status", "action": "set_brightness", "value": val})

async def broadcast_event(data: dict):
    for connection in active_cnct:
        try:
            await connection.send_json(data)
        except Exception:
            pass

# --- CONTINUOUS AUDIO LISTENER & WAKE-WORD DETECTION ---
def listen_for_wakeword_and_transcribe(loop):
    sample_rate = 16000
    chunk_size = 1280  # 80ms audio frames for openwakeword
    
    def audio_callback(indata, frames, time, status):
        audio_data = (indata[:, 0] * 32767).astype(np.int16)
        
        # Predict wake-word
        prediction = wake_model.predict(audio_data)
        
        for model_name, score in prediction.items():
            if score > 0.5: # Threshold for trigger
                print(f"\n[Wake Word Detected]: {model_name}!")
                wake_model.reset()
                
                # Record next 3 seconds of command audio
                print("[Listening for command...]")
                command_audio = sd.rec(int(3.5 * sample_rate), samplerate=sample_rate, channels=1, dtype='float32')
                sd.wait()
                
                # Transcribe with Faster-Whisper
                segments, _ = stt_model.transcribe(command_audio.flatten(), beam_size=1)
                command_text = " ".join([segment.text for segment in segments]).strip()
                
                if command_text:
                    asyncio.run_coroutine_threadsafe(parse_and_execute_intent(command_text), loop)

    with sd.InputStream(samplerate=sample_rate, channels=1, blocksize=chunk_size, callback=audio_callback):
        print("Voice Pipeline Active: Listening for wake-word 'Hey Jarvis'...")
        while True:
            sd.sleep(1000)

# ------

'''
@app.get("/api/v1/traces")
async def get_recent_traces():
    """Endpoint for Phase 5 AI Agent to read recorded workflows."""
    traces = []
    if os.path.exists("workflow_traces.jsonl"):
        with open("workflow_traces.jsonl", "r", encoding="utf-8") as f:
            for line in f.readlines()[-20:]:  # Return last 20 snapshot logs
                traces.append(json.loads(line))
    return {"status": "success", "traces": traces}

@app.on_event("startup")
def start_observer_background():
    # Run process observer in a separate background thread
    t = threading.Thread(target=observer.start, kwargs={"poll_interval": 5.0}, daemon=True)
    t.start()

@app.on_event("shutdown")
def stop_observer_background():
    observer.stop()
'''
@app.post("/api/v1/agent/execute")
async def execute_agent_intent(payload):
    prompt = payload.get("prompt")
    if not prompt:
        return { "status":"error", "message":"Missing Prompt" }
    
    import threading
    t = threading.Thread(target=run_autonomous_agent, args=(prompt,), daemon=True)
    t.start()

    return { "status":"success", "message":f"Agent started Execution for {prompt}" }


@app.websocket("/ws/control")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_cnct.append(websocket)
    print("WebSocket Client Connected Successfully!")
    
    try:
        while True:
            data = await websocket.receive_json()
            print(f"[Received Command]: {data}")

            action = data.get("action")
            value = data.get("value")

            if action == "set_volume":
                set_system_volume(int(value))
                await websocket.send_json({"status": "success", "action": "set_volume", "value": value})
            elif action == "set_brightness":
                sbc.set_brightness(int(value))
                await websocket.send_json({"status": "success", "action": "set_brightness", "value": value})

    except WebSocketDisconnect:
        print("Client disconnected")


zeroconf = Zeroconf()

@app.on_event("startup")
def startup_event():
    local_ip = "100.112.28.37"
    port = 8000
    print(f"Registering mDNS service at: {local_ip}:{port}")

    info = ServiceInfo(
        "_appcontrol._tcp.local.",
        "LaptopDaemon._appcontrol._tcp.local.",
        addresses=[socket.inet_aton(local_ip)],
        port=port,
        properties={"version":"1.0"},
        server="laptop-daemon.local"
    )

    zeroconf.register_service(info)

@app.on_event("shutdown")
def shutdown_event():
    zeroconf.unregister_all_services()
    zeroconf.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)