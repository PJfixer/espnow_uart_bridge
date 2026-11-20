from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
import socket
import struct
import threading
import uuid
from fastapi import FastAPI, HTTPException
import uvicorn

BRIDGE_SOCKET = "/tmp/espnow_bridge.sock"
CLIENT_SOCKET = f"/tmp/espnow_client_{uuid.uuid4()}.sock"

# Capteurs BME280 autorisés : {"ADRESSE_MAC_MAJUSCULE": "Nom lisible"}
ALLOWED_SENSORS: dict[str, str] = {
    "44:BD:8D:29:99:AC": "bme280_salon",
    # "AA:BB:CC:DD:EE:FF": "bme280_exterieur",
}

latest_readings: dict[str, dict] = {}
data_lock = threading.Lock()
stop_event = threading.Event()


def decode_bme280_payload(hex_data: str) -> tuple[float, float, float]:
    """Décode 12 octets (3 floats little-endian) : température, humidité, pression."""
    raw = bytes.fromhex(hex_data)
    if len(raw) != 12:
        raise ValueError(f"Taille de trame invalide : {len(raw)} octets (12 attendus)")
    return struct.unpack("<fff", raw)


def receiver_loop(rx_sock: socket.socket) -> None:
    """Écoute le socket UNIX en continu (sans timeout) tant que le serveur tourne."""
    while not stop_event.is_set():
        try:
            # Reste bloqué en attente d'une trame (peut attendre 15 min, 1 h, etc.)
            packet, _ = rx_sock.recvfrom(4096)
        except OSError:
            # Déclenché uniquement lors de la fermeture volontaire du socket (Ctrl+C)
            break

        try:
            frame = json.loads(packet.decode("utf-8"))
            src = str(frame.get("src", "")).upper()

            if src not in ALLOWED_SENSORS:
                continue

            if frame.get("len") != 12:
                continue

            temp, hum, press = decode_bme280_payload(frame["data"])

            reading = {
                "mac": src,
                "sensor": ALLOWED_SENSORS[src],
                "temperature_c": round(temp, 2),
                "humidity_pct": round(hum, 2),
                "pressure_hpa": round(press, 2),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            with data_lock:
                latest_readings[src] = reading

            print(f"[BME280] {src} ({reading['sensor']}) -> {reading}")

        except (json.JSONDecodeError, KeyError, ValueError, struct.error) as err:
            print(f"[WARN] Trame ignorée : {err}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise le socket UNIX et maintient l'écoute active."""
    if os.path.exists(CLIENT_SOCKET):
        os.remove(CLIENT_SOCKET)

    rx = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    rx.bind(CLIENT_SOCKET)
    # Aucun settimeout() : écoute infinie en arrière-plan
    rx.sendto(b"REGISTER", BRIDGE_SOCKET)

    print(f"Écoute ESP-NOW permanente active pour {len(ALLOWED_SENSORS)} capteur(s)...")

    thread = threading.Thread(target=receiver_loop, args=(rx,), daemon=True)
    thread.start()

    try:
        yield
    finally:
        stop_event.set()
        rx.close()
        thread.join(timeout=2.0)
        if os.path.exists(CLIENT_SOCKET):
            os.remove(CLIENT_SOCKET)


app = FastAPI(title="ESP-NOW BME280 Gateway", lifespan=lifespan)


@app.get("/sensors")
def get_all_sensors():
    """Retourne la dernière mesure connue de tous les capteurs BME280 surveillés."""
    with data_lock:
        return {
            "monitored_macs": ALLOWED_SENSORS,
            "readings": dict(latest_readings),
        }


@app.get("/sensors/{mac}")
def get_sensor_by_mac(mac: str):
    """Retourne la dernière mesure d'un capteur spécifique via son adresse MAC."""
    normalized_mac = mac.upper()

    if normalized_mac not in ALLOWED_SENSORS:
        raise HTTPException(
            status_code=404,
            detail=f"Adresse MAC {normalized_mac} non configurée dans la liste d'écoute.",
        )

    with data_lock:
        reading = latest_readings.get(normalized_mac)

    if reading is None:
        raise HTTPException(
            status_code=503,
            detail=f"Aucune donnée reçue pour {normalized_mac} depuis le démarrage.",
        )

    return reading


if __name__ == "__main__":
    # Maintient le programme actif indéfiniment (arrêt avec Ctrl+C)
    uvicorn.run(app, host="0.0.0.0", port=8001)
