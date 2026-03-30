import subprocess
import json
import time
import threading
from datetime import datetime
from pathlib import Path
import yaml
from flask import Flask, jsonify, Response
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

"""
sudo rtl_433 -f 433.92M -R 214 -F json

{"time" : "2026-02-05 14:41:03", "model" : "EMOS-E6016", "id" : 104, "channel" : 1, "battery_ok" : 1, "temperature_C" : 20.600, "humidity" : 23, "wind_avg_m_s" : 0.000, "wind_dir_deg" : 0.000, "radio_clock" : "2026-02-05T14:41:03", "mic" : "CHECKSUM"}
{"time" : "2026-02-05 14:41:08", "model" : "EMOS-E6016", "id" : 124, "channel" : 3, "battery_ok" : 0, "temperature_C" : 12.400, "humidity" : 45, "wind_avg_m_s" : 0.000, "wind_dir_deg" : 0.000, "radio_clock" : "2026-02-05T14:40:50", "mic" : "CHECKSUM"}
 """

# Load configuration
CONFIG_PATH = Path(__file__).parent / "config.yaml"
with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

# Prometheus Metrics
TEMPERATURE = Gauge('weather_temperature_celsius', 'Temperature in Celsius', ['model', 'id', 'channel', 'location'])
HUMIDITY = Gauge('weather_humidity_percent', 'Humidity percentage', ['model', 'id', 'channel', 'location'])
BATTERY = Gauge('weather_battery_ok', 'Battery status (1=OK, 0=Low)', ['model', 'id', 'channel', 'location'])
LAST_UPDATE = Gauge('weather_last_update_timestamp', 'Unix timestamp of last sensor reading', ['model', 'id', 'channel', 'location'])

# In-memory state for health endpoint
sensor_states = {}

# Configuration from file
MODEL = config['sensor']['model']
SENSOR_MAP = config['sensor']['sensors']
STALE_THRESHOLD_SECONDS = 300  # 5 minutes

# Flask app for health endpoint
app = Flask(__name__)

@app.route('/metrics')
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)

@app.route('/health')
def health():
    now = time.time()
    sensors = []
    all_healthy = True

    for sensor_id, state in sensor_states.items():
        age_seconds = now - state['last_update']
        is_stale = age_seconds > STALE_THRESHOLD_SECONDS
        if is_stale:
            all_healthy = False

        sensors.append({
            'id': sensor_id,
            'location': state['location'],
            'channel': state['channel'],
            'temperature_c': state['temperature'],
            'humidity_percent': state['humidity'],
            'battery_ok': state['battery'],
            'last_update': datetime.fromtimestamp(state['last_update']).isoformat(),
            'age_seconds': round(age_seconds, 1),
            'stale': is_stale
        })

    status = 'healthy' if all_healthy and sensors else 'degraded' if sensors else 'no_data'

    return jsonify({
        'status': status,
        'sensor_count': len(sensors),
        'stale_threshold_seconds': STALE_THRESHOLD_SECONDS,
        'sensors': sensors
    })

def run_flask(port):
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host='0.0.0.0', port=port, threaded=True)

def main():
    port = config['exporter']['port']

    flask_thread = threading.Thread(target=run_flask, args=(port,), daemon=True)
    flask_thread.start()
    print(f"Exporter started on port {port} (endpoints: /metrics, /health)")

    rtl_config = config['rtl433']
    cmd = ['rtl_433', '-f', rtl_config['frequency'], '-R', str(rtl_config['protocol']), '-F', 'json']
    
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)

    for line in iter(process.stdout.readline, ''):
        try:
            packet = json.loads(line)
            # print(line.strip()) # Debug raw line if needed
            s_id = packet.get('id')
            
            model = packet.get('model')
            if model != MODEL:
                continue

            sensor_config = SENSOR_MAP.get(s_id)
            chan = packet.get('channel')

            if not sensor_config:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Unknown sensor {s_id} (Ch {chan}), skipping")
                continue

            expected_channel = sensor_config.get('channel')
            if expected_channel is not None and chan != expected_channel:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Sensor {s_id} on unexpected channel {chan} (expected {expected_channel}), skipping")
                continue

            location = sensor_config['location']
            temp = packet.get('temperature_C')
            hum = packet.get('humidity')
            battery = packet.get('battery_ok')

            print(f"[{datetime.now().strftime('%H:%M:%S')}] {location} (Ch {chan}): {temp}°C, {hum}%")

            now = time.time()
            labels = dict(model=model, id=s_id, channel=chan, location=location)

            if temp is not None:
                TEMPERATURE.labels(**labels).set(temp)

            if hum is not None:
                HUMIDITY.labels(**labels).set(hum)

            if battery is not None:
                BATTERY.labels(**labels).set(battery)

            LAST_UPDATE.labels(**labels).set(now)

            sensor_states[s_id] = {
                'location': location,
                'channel': chan,
                'temperature': temp,
                'humidity': hum,
                'battery': battery,
                'last_update': now
            }
            
        except Exception:
            continue

if __name__ == '__main__':
    main()
