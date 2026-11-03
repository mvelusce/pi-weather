import subprocess
import json
import sys
import time
import threading
from datetime import datetime
from pathlib import Path
import yaml
from flask import Flask, jsonify, Response
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

"""
rtl_433 -f 433.92M -s 1024k -R 214 -F json -M level

{"time" : "2026-02-05 14:41:03", "model" : "EMOS-E6016", "id" : 104, "channel" : 1, "battery_ok" : 1, "temperature_C" : 20.600, "humidity" : 23, ...}

Sensors are identified by channel, not by ID: EMOS sensors pick a new random
ID every time the batteries are replaced. Each channel is locked to the ID it
last heard; another ID on the same channel is ignored (e.g. a neighbour's
sensor) unless the locked ID has been silent for `id_switch_after_seconds`
and the new ID has sent at least `id_switch_min_readings` readings.
"""

# Flush each log line so journald timestamps are accurate
sys.stdout.reconfigure(line_buffering=True)

BASE_DIR = Path(__file__).parent
CONFIG_PATH = BASE_DIR / "config.yaml"
STATE_PATH = BASE_DIR / "state.json"

with open(CONFIG_PATH) as f:
    config = yaml.safe_load(f)

MODEL = config['sensor']['model']
CHANNELS = {int(ch): c for ch, c in config['sensor']['channels'].items()}
ID_SWITCH_AFTER = config['sensor'].get('id_switch_after_seconds', 900)
ID_SWITCH_MIN_READINGS = config['sensor'].get('id_switch_min_readings', 2)
STALE_THRESHOLD_SECONDS = 300
START_TIME = time.time()

LABELS = ['model', 'channel', 'location']
TEMPERATURE = Gauge('weather_temperature_celsius', 'Temperature in Celsius', LABELS)
HUMIDITY = Gauge('weather_humidity_percent', 'Humidity percentage', LABELS)
BATTERY = Gauge('weather_battery_ok', 'Battery status (1=OK, 0=Low)', LABELS)
RSSI = Gauge('weather_signal_rssi_db', 'Received signal strength (dB) of last reading', LABELS)
SNR = Gauge('weather_signal_snr_db', 'Signal-to-noise ratio (dB) of last reading', LABELS)
FREQ = Gauge('weather_signal_frequency_mhz', 'Received frequency (MHz) of last reading', LABELS)
LAST_UPDATE = Gauge('weather_last_update_timestamp', 'Unix timestamp of last sensor reading', LABELS)
SENSOR_INFO = Gauge('weather_sensor_info', 'Sensor ID currently locked to each channel (value always 1)', LABELS + ['id'])
IGNORED = Gauge('weather_ignored_readings', 'Readings ignored since start, by channel and ID', ['model', 'channel', 'id'])

lock = threading.Lock()
locked_ids = {}       # channel -> id
sensor_states = {}    # channel -> last accepted reading
candidates = {}       # (channel, id) -> {'count', 'first_seen', 'last_seen'}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def load_state():
    try:
        data = json.loads(STATE_PATH.read_text())
        for ch, s_id in data.get('locked_ids', {}).items():
            locked_ids[int(ch)] = int(s_id)
        log(f"Loaded locked IDs {locked_ids}")
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f"Could not read {STATE_PATH}: {e}")


def save_state():
    tmp = STATE_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps({'locked_ids': {str(k): v for k, v in locked_ids.items()}}, indent=2))
    tmp.replace(STATE_PATH)


def set_locked_id(chan, s_id):
    location = CHANNELS[chan]['location']
    old = locked_ids.get(chan)
    if old is not None:
        try:
            SENSOR_INFO.remove(MODEL, str(chan), location, str(old))
        except KeyError:
            pass
    locked_ids[chan] = s_id
    SENSOR_INFO.labels(model=MODEL, channel=chan, location=location, id=s_id).set(1)
    save_state()


def accept(chan, s_id, now):
    """Decide whether a reading from s_id on chan belongs to our sensor."""
    current = locked_ids.get(chan)
    if current is None:
        log(f"Channel {chan}: locking to ID {s_id}")
        set_locked_id(chan, s_id)
        return True
    if s_id == current:
        candidates.pop((chan, s_id), None)
        return True

    cand = candidates.setdefault((chan, s_id), {'count': 0, 'first_seen': now})
    cand['count'] += 1
    cand['last_seen'] = now
    IGNORED.labels(model=MODEL, channel=chan, id=s_id).inc()

    # After a restart, count silence from start-up, not from 1970
    last_heard = sensor_states.get(chan, {}).get('last_update', START_TIME)
    silent_for = now - last_heard
    if silent_for >= ID_SWITCH_AFTER and cand['count'] >= ID_SWITCH_MIN_READINGS:
        log(f"Channel {chan}: ID {current} silent for {silent_for / 60:.0f} min, switching to ID {s_id} (battery swap?)")
        set_locked_id(chan, s_id)
        candidates.pop((chan, s_id), None)
        return True

    log(f"Channel {chan}: ignoring ID {s_id} (locked to {current}, seen {cand['count']}x)")
    return False


app = Flask(__name__)


@app.route('/metrics')
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


@app.route('/health')
def health():
    now = time.time()
    sensors = []
    all_healthy = True
    with lock:
        for chan, cfg in sorted(CHANNELS.items()):
            state = sensor_states.get(chan)
            entry = {'channel': chan, 'location': cfg['location'], 'id': locked_ids.get(chan)}
            if state:
                age = now - state['last_update']
                entry.update({
                    'temperature_c': state['temperature'],
                    'humidity_percent': state['humidity'],
                    'battery_ok': state['battery'],
                    'last_update': datetime.fromtimestamp(state['last_update']).isoformat(),
                    'age_seconds': round(age, 1),
                    'stale': age > STALE_THRESHOLD_SECONDS,
                })
            else:
                entry['stale'] = True
            all_healthy &= not entry['stale']
            sensors.append(entry)
        ignored = [
            {'channel': ch, 'id': s_id, 'count': c['count'],
             'last_seen': datetime.fromtimestamp(c['last_seen']).isoformat()}
            for (ch, s_id), c in candidates.items()
        ]

    any_data = any('last_update' in s for s in sensors)
    status = 'healthy' if all_healthy else 'degraded' if any_data else 'no_data'
    return jsonify({
        'status': status,
        'stale_threshold_seconds': STALE_THRESHOLD_SECONDS,
        'sensors': sensors,
        'ignored': ignored,
    })


def run_flask(port):
    import logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    app.run(host='0.0.0.0', port=port, threaded=True)


def handle(packet):
    if packet.get('model') != MODEL:
        return
    s_id = packet.get('id')
    chan = packet.get('channel')
    if s_id is None or chan not in CHANNELS:
        if s_id is not None:
            log(f"Ignoring ID {s_id} on unconfigured channel {chan}")
        return

    now = time.time()
    with lock:
        if not accept(chan, s_id, now):
            return
        temp = packet.get('temperature_C')
        hum = packet.get('humidity')
        battery = packet.get('battery_ok')
        sensor_states[chan] = {'temperature': temp, 'humidity': hum, 'battery': battery, 'last_update': now}

    location = CHANNELS[chan]['location']
    labels = dict(model=MODEL, channel=chan, location=location)
    log(f"{location} (Ch {chan}, ID {s_id}): {temp}°C, {hum}%")
    for gauge, value in ((TEMPERATURE, temp), (HUMIDITY, hum), (BATTERY, battery),
                         (RSSI, packet.get('rssi')), (SNR, packet.get('snr')), (FREQ, packet.get('freq'))):
        if value is not None:
            gauge.labels(**labels).set(value)
    LAST_UPDATE.labels(**labels).set(now)


def main():
    load_state()
    for chan, s_id in locked_ids.items():
        if chan in CHANNELS:
            SENSOR_INFO.labels(model=MODEL, channel=chan, location=CHANNELS[chan]['location'], id=s_id).set(1)

    port = config['exporter']['port']
    threading.Thread(target=run_flask, args=(port,), daemon=True).start()
    log(f"Exporter started on port {port} (endpoints: /metrics, /health)")

    rtl = config['rtl433']
    cmd = ['rtl_433', '-f', rtl['frequency'], '-R', str(rtl['protocol']), '-F', 'json', '-M', 'level']
    if rtl.get('sample_rate'):
        cmd += ['-s', str(rtl['sample_rate'])]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    for line in iter(process.stdout.readline, ''):
        try:
            handle(json.loads(line))
        except json.JSONDecodeError:
            continue
        except Exception as e:
            log(f"Error handling {line.strip()[:200]}: {e}")
    sys.exit(f"rtl_433 exited with code {process.wait()}")


if __name__ == '__main__':
    main()
