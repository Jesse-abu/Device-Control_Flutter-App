import asyncio
import platform
import json
import re
import os
import socket
import openwakeword
import numpy as np
import sounddevice as sd
import jwt
import screen_brightness_control as sbc
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, status, Query
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from typing import Optional
from datetime import datetime, timedelta
from faster_whisper import WhisperModel
from openwakeword.model import Model
from zeroconf import ServiceInfo, Zeroconf
from passlib.context import CryptContext
from pydantic import BaseModel



SECRET_KEY = "SUPER_SECRET_COMPANION_KEY_CHANGE_IN_PRODUCTION" # Keep secure!
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # 7 Days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")

app = FastAPI(title="AI Device Companion Gateway")

# Mock User Database (In Phase 5, this routes to PostgreSQL/Supabase)
MOCK_USER_DB = {
    "admin@companion.ai": {
        "username": "admin@companion.ai",
        "hashed_password": pwd_context.hash("securepassword123"),
        "device_id": "laptop-master-01"
    }
}

# --- AUTH HELPER FUNCTIONS ---
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None

# --- REST AUTH ENDPOINTS ---
class TokenResponse(BaseModel):
    access_token: str
    token_type: str

@app.post("/api/v1/auth/login", response_model=TokenResponse)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = MOCK_USER_DB.get(form_data.username)
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"], "device_id": user["device_id"]},
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}
#------

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
        from ctypes import cast, POINTER
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
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

@app.websocket("ws/control")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("Client Connected!")

    try:
        while True:
            data = await websocket.receive_json() 
            action = data.get("action")
            value = data.get("value")

            if action == "set_volume":
                set_system_volume(int(value))
                await websocket.send_json({ "status":"success", "msg":f"Volume set to {value}" })

            elif action == "set_brightness":
                sbc.set_brightness(int(value))
                await websocket.send_json({ "status":"success", "msg":f"Brightness set to {value}"})

            else:
                await websocket.send_json({ "status":"error", "msg":f"Unknown action" })

    except WebSocketDisconnect:
        print("Client Disconnected!")


zeroconf = Zeroconf()

@app.on_event("startup")
def startup_event():
    local_ip = get_local_ip()
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

        

