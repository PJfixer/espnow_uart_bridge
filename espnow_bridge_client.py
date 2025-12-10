import socket
import os
import uuid
import json

BRIDGE_SOCKET = "/tmp/espnow_bridge.sock"
CLIENT_SOCKET = f"/tmp/espnow_client_{uuid.uuid4()}.sock"

# Socket privé du client pour recevoir
if os.path.exists(CLIENT_SOCKET):
    os.remove(CLIENT_SOCKET)

rx = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
rx.bind(CLIENT_SOCKET)

# Envoi de REGISTER
rx.sendto(b"REGISTER", BRIDGE_SOCKET)

print("Client prêt (Rx + Tx)")

# Socket pour envoyer vers le bridge
tx = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)

# THREAD de réception
import threading
def receiver():
    while True:
        msg = rx.recv(4096).decode()
        print("[RX]", msg)

threading.Thread(target=receiver, daemon=True).start()

# Boucle d’envoi interactive
while True:
    mac = input("MAC destination: ")
    data = input("Data (hex): ")

    msg = json.dumps({"dst": mac, "data": data})
    tx.sendto(msg.encode(), BRIDGE_SOCKET)
