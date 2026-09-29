# ASAP

An end-to-end, cross-platform remote control system and autonomous process observer that links your mobile device (iOS/Android) and desktop companion app with your laptop.

This project enables real-time device control (volume, brightness, screen lock), a hands-free local voice pipeline (wake-word + Whisper STT), background workflow recording (pynput + OCR), and AI agent orchestration (LangGraph + LanceDB) to automate repetitive laptop actions.

### Key Components
* **Direct Hardware Control**: Adjust system volume, screen brightness, and lock workstation state directly over local Wi-Fi or encrypted networks.
* **Hands-Free Local Voice Engine**: Continuous background listening using wake-word parsing (openwakeword) and local AI speech-to-text transcription (faster-whisper).
* **Behavioral Process Observer**: Background monitoring of active window focus, keyboard/mouse events (pynput), and screen OCR sampling (pytesseract).
* **Autonomous Agent Orchestration**: Vector embedding of observed workflows into LanceDB paired with a LangGraph state machine to automate learned multi-step tasks.
---

## Tech Stack

### Client App (Mobile & Desktop)
* **Framework**: Flutter (Dart)
* **State Management**: Riverpod
* **Networking**: web_socket_channel, nsd (mDNS Network Service Discovery), http
* **Secure Storage**: flutter_secure_storage

### Laptop Daemon & System Bridge
* **Server Framework**: FastAPI & Uvicorn (WebSockets + REST)
* **OS Automation**: pycaw (Windows), osascript (macOS), pactl (Linux), screen-brightness-control, pyautogui
* **Network Discovery**: zeroconf

### Voice & AI Processing
* **Speech-to-Text**: faster-whisper (CTranslate2 local inference)
* **Wake-Word Engine**: openwakeword
* **Vector Store**: LanceDB (Local document embeddings)
* **Agent Framework**: LangGraph & LangChain

## Quick Start Guide

### Laptop Daemon Prerequisites
* Python 3.12+
* Tesseract OCR installed on your laptop system PATH:
* Windows: Install Tesseract for Windows.
* macOS: brew install tesseract
* Linux: sudo apt install tesseract-ocr


### Installation & Execution

    Bash
    # Navigate to daemon directory
    cd daemon

    # Install dependencies
    pip install fastapi uvicorn screen-brightness-control pycaw comtypes zeroconf \
                websockets faster-whisper openwakeword sounddevice numpy scipy \
                pynput mss pytesseract pillow psutil pygetwindow langgraph \
                langchain-community lancedb pyarrow pyautogui

    # Launch the daemon
    python daemon.py

The server will start on [http://0.0.0.0:8000](http://0.0.0.0:8000) and broadcast its local discovery service over mDNS (_appcontrol._tcp.local.).

### Mobile / Client Setup
Running on Mobile Device (Android/iOS)
Connect your physical phone to your laptop via USB (with USB Debugging enabled for Android).
Ensure both your phone and laptop are connected to the same Wi-Fi network.
Launch the Flutter app:

    Bash

    cd flutter_client
    flutter run

### Manual Connection (If mDNS is isolated)
If your local Wi-Fi router blocks mDNS discovery packets, enter your laptop's IPv4 address directly into the app (e.g., 192.168.x.x or Tailscale IP 100.x.y.z) to connect to ws://<LAPTOP_IP>:8000/ws/control.

### Build & Export Mobile APK
To package a standalone .apk for installation on Android phones:

    Bash

    cd flutter_client
    flutter build apk --release

The generated installer will be saved to:
flutter_client/build/app/outputs/flutter-apk/app-release.apk

### Using Tailscale
1. Install and activate Tailscale on both your phone and laptop.
2. Connect using your laptop's Tailscale static IP address:
ws://100.x.y.z:8000/ws/control
