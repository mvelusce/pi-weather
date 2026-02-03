import subprocess
import json
import time
import os
import signal
import sys
from prometheus_client import start_http_server, Gauge

# Prometheus Metrics
TEMPERATURE = Gauge('weather_temperature_celsius', 'Temperature in Celsius', ['model', 'id', 'channel'])
HUMIDITY = Gauge('weather_humidity_percent', 'Humidity in Percent', ['model', 'id', 'channel'])
BATTERY = Gauge('weather_battery_ok', 'Battery Status (1=OK, 0=Low)', ['model', 'id', 'channel'])
SIGNAL_DB = Gauge('weather_signal_db', 'Signal strength in dB', ['model', 'id', 'channel'])

def run_rtl433():
    # Command to run rtl_433 and output JSON
    cmd = ['rtl_433', '-F', 'json', '-M', 'level']
    
    print(f"Starting rtl_433: {' '.join(cmd)}")
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True
    )
    
    return process

def process_line(line):
    try:
        data = json.loads(line)
        
        # Log the raw data for debugging (can be noisy)
        # print(f"Received: {data}")
        
        model = data.get('model', 'unknown')
        sensor_id = str(data.get('id', 'unknown'))
        channel = str(data.get('channel', 'unknown'))
        
        # EMOS ES5001 and similar sensors usually report temperature and humidity
        if 'temperature_C' in data:
            TEMPERATURE.labels(model=model, id=sensor_id, channel=channel).set(data['temperature_C'])
            print(f"Update Temp: {model} {sensor_id} -> {data['temperature_C']}C")
            
        if 'humidity' in data:
            HUMIDITY.labels(model=model, id=sensor_id, channel=channel).set(data['humidity'])
            print(f"Update Hum: {model} {sensor_id} -> {data['humidity']}%")
            
        if 'battery_ok' in data:
            BATTERY.labels(model=model, id=sensor_id, channel=channel).set(data['battery_ok'])
            
        if 'rssi' in data: # Received Signal Strength Indicator
             SIGNAL_DB.labels(model=model, id=sensor_id, channel=channel).set(data['rssi'])
             
    except json.JSONDecodeError:
        pass
    except Exception as e:
        print(f"Error processing line: {e}")

def main():
    # Start Prometheus HTTP server
    start_http_server(9550)
    print("Prometheus metrics available on port 9550")
    
    proc = run_rtl433()
    
    try:
        while True:
            output = proc.stdout.readline()
            if output == '' and proc.poll() is not None:
                break
            if output:
                process_line(output.strip())
                
            # Check for errors
            err = proc.stderr.readline()
            if err:
                print(f"rtl_433 stderr: {err.strip()}", file=sys.stderr)
                
    except KeyboardInterrupt:
        print("Stopping...")
        proc.terminate()
        
    if proc.poll() is None:
        proc.terminate()

if __name__ == '__main__':
    main()
