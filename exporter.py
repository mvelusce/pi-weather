import subprocess
import json
from datetime import datetime
from prometheus_client import start_http_server, Gauge

""" 
sudo rtl_433 -f 433.92M -R 214 -F json

{"time" : "2026-02-05 14:41:03", "model" : "EMOS-E6016", "id" : 104, "channel" : 1, "battery_ok" : 1, "temperature_C" : 20.600, "humidity" : 23, "wind_avg_m_s" : 0.000, "wind_dir_deg" : 0.000, "radio_clock" : "2026-02-05T14:41:03", "mic" : "CHECKSUM"}
{"time" : "2026-02-05 14:41:08", "model" : "EMOS-E6016", "id" : 124, "channel" : 3, "battery_ok" : 0, "temperature_C" : 12.400, "humidity" : 45, "wind_avg_m_s" : 0.000, "wind_dir_deg" : 0.000, "radio_clock" : "2026-02-05T14:40:50", "mic" : "CHECKSUM"}
 """

# Prometheus Metrics
TEMPERATURE = Gauge('weather_temperature_celsius', 'Temperature in Celsius', ['model', 'id', 'channel'])
HUMIDITY = Gauge('weather_humidity_percent', 'Humidity percentage', ['model', 'id', 'channel'])
BATTERY = Gauge('weather_battery_ok', 'Battery status (1=OK, 0=Low)', ['model', 'id', 'channel'])

# Configuration
MODEL = "EMOS-E6016"
SENSOR_MAP = {
    104: "Living Room", 
    124: "Window"
}

def main():
    start_http_server(9550)
    print("Prometheus exporter started on port 9550")
    
    cmd = ['rtl_433', '-f', '433.92M', '-R', '214', '-F', 'json']
    
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)

    for line in iter(process.stdout.readline, ''):
        try:
            packet = json.loads(line)
            # print(line.strip()) # Debug raw line if needed
            s_id = packet.get('id')
            
            model = packet.get('model')
            if model != MODEL:
                continue

            # This will log ANY sensor found, even if not in our SENSOR_MAP yet
            location = SENSOR_MAP.get(s_id, f"Unknown_Sensor_{s_id}")
            
            temp = packet.get('temperature_C')
            hum = packet.get('humidity')
            chan = packet.get('channel')
            battery = packet.get('battery_ok')

            print(f"[{datetime.now().strftime('%H:%M:%S')}] {location} (Ch {chan}): {temp}°C, {hum}%")
            
            if temp is not None:
                TEMPERATURE.labels(model=model, id=s_id, channel=chan).set(temp)
            
            if hum is not None:
                HUMIDITY.labels(model=model, id=s_id, channel=chan).set(hum)
                
            if battery is not None:
                BATTERY.labels(model=model, id=s_id, channel=chan).set(battery)
            
        except Exception:
            continue

if __name__ == '__main__':
    main()
