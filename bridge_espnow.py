#!/usr/bin/env python3
import os
import json
import socket
import serial
import threading
import uuid

SERIAL_PORT = "/dev/ttyACM0"
BRIDGE_SOCKET = "/tmp/espnow_bridge.sock"

# Socket principal du bridge
if os.path.exists(BRIDGE_SOCKET):
    os.remove(BRIDGE_SOCKET)

bridge = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
bridge.bind(BRIDGE_SOCKET)

clients = set()

REGISTER = "REGISTER"

ser = serial.Serial(SERIAL_PORT, 115200, timeout=1)


# ---------------------------------------------------------
#  THREAD : écoute des messages venant des clients
# ---------------------------------------------------------
def handle_client_messages():
    while True:
        data, addr = bridge.recvfrom(4096)
        msg = data.decode()

        # Un client demande l'inscription
        if msg == REGISTER:
            clients.add(addr)
            continue

        # Sinon c'est un message à envoyer à l'ESP32
        try:
            payload = json.loads(msg)
            ser.write((json.dumps(payload) + "\n").encode())
        except:
            print("[BRIDGE] invalid client message:", msg)


threading.Thread(target=handle_client_messages, daemon=True).start()


# ---------------------------------------------------------
#  Fonction pour envoyer un message à tous les clients
# ---------------------------------------------------------
def broadcast(msg):
    dead = []
    for c in clients:
        try:
            bridge.sendto(msg.encode(), c)
        except:
            dead.append(c)
    for d in dead:
        clients.remove(d)


print("[BRIDGE] Running bidirectional bridge...")

# ---------------------------------------------------------
#  Boucle principale : lecture série (ESP32 → clients)
# ---------------------------------------------------------
while True:
    line = ser.readline().decode(errors="ignore").strip()
    if not line:
        continue
    broadcast(line)
