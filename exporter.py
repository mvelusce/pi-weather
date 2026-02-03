import subprocess
import json
import time
import os
import signal
import sys
import logging
from prometheus_client import start_http_server, Gauge

# Prometheus Metrics
TEMPERATURE = Gauge('weather_temperature_celsius', 'Temperature in Celsius', ['model', 'id', 'channel'])
HUMIDITY = Gauge('weather_humidity_percent', 'Humidity in Percent', ['model', 'id', 'channel'])
BATTERY = Gauge('weather_battery_ok', 'Battery Status (1=OK, 0=Low)', ['model', 'id', 'channel'])
SIGNAL_DB = Gauge('weather_signal_db', 'Signal strength in dB', ['model', 'id', 'channel'])

# Configuration
TARGET_IDS = os.environ.get('SENSOR_IDS', '').split(',')
TARGET_IDS = [x.strip() for x in TARGET_IDS if x.strip()] # Clean list
DEBUG = os.environ.get('DEBUG', 'false').lower() == 'true'

# Configure Logging
logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

def run_rtl433():
    # Command to run rtl_433 and output JSON
    # Added Flex Decoder for the 8.1C sensor (EMOS?)
    # -X 'n=MySensor,m=OOK_PWM,s=276,l=796,r=820,g=0,t=0,y=1836'
    cmd = [
        'rtl_433',
        '-F', 'json',
        '-M', 'level',
        '-X', 'n=MySensor,m=OOK_PWM,s=276,l=796,r=820,g=0,t=0,y=1836'
    ]
    
    logging.info(f"Starting rtl_433: {' '.join(cmd)}")
    if TARGET_IDS:
        logging.info(f"Filtering for Sensor IDs: {TARGET_IDS}")
    else:
        logging.info("No SENSOR_IDS specified. Exporting ALL sensors.")
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, # Capture stderr to debug startup issues
        universal_newlines=True
    )
    
    return process

def parse_bcd(byte_val):
    """Convert BCD byte to integer."""
    return (byte_val >> 4) * 10 + (byte_val & 0x0F)

def process_line(line):
    try:
        data = json.loads(line)
        
        model = data.get('model', 'unknown')
        sensor_id = str(data.get('id', 'unknown'))
        channel = str(data.get('channel', 'unknown'))

        if model == 'MySensor':
            # JSON output from Flex Decoder puts data in "rows" list
            rows = data.get('rows', [])
            payload_hex = None
            
            # Find the first row with data
            for row in rows:
                if 'data' in row:
                    payload_hex = row['data']
                    break
            
            if payload_hex:
                # Filter out noise (short payloads)
                if len(payload_hex) > 16:
                    logging.info(f"Raw payload: {payload_hex}")
                    try:
                        # Clean and parse hex
                        payload = bytes.fromhex(payload_hex)
                        if len(payload) > 8:
                            # Function: Temp = Raw / 597.3 (Calibrated to ~21.0C)
                            raw_temp = (payload[6] << 8) | payload[7]
                            temp_c = raw_temp / 597.3
                            
                            # Humidity (Byte 8)
                            # Function: (Raw & 0xDF) / 4.0 
                            # Mask 0xDF removes bit 5 (0x20) which appears to be a flag toggling between 0x5F and 0x7F
                            # 0x5F (95) / 4 = 23.75%
                            # 0x7F (127) & 0xDF = 95. 95 / 4 = 23.75%
                            hum_raw = payload[8] & 0xDF
                            humidity = hum_raw / 4.0
                            
                            logging.info(f"Decoded: Temp={temp_c:.2f}C, Humidity={humidity:.2f}%")
                            
                            HUMIDITY.labels(model=model, id="custom-emos", channel='0').set(humidity)
                            TEMPERATURE.labels(model=model, id="custom-emos", channel='0').set(temp_c)
                            return
                    except ValueError:
                        pass

        # Filter if TARGET_IDS is set
        if TARGET_IDS and sensor_id not in TARGET_IDS:
             return

        # Regular sensors
        temp_c = data.get('temperature_C')
        if temp_c is None and 'temperature_F' in data:
             temp_c = (float(data['temperature_F']) - 32) * 5.0 / 9.0

        if temp_c is not None:
            TEMPERATURE.labels(model=model, id=sensor_id, channel=channel).set(temp_c)
            
        if 'humidity' in data:
            HUMIDITY.labels(model=model, id=sensor_id, channel=channel).set(data['humidity'])
            
        if 'battery_ok' in data:
            BATTERY.labels(model=model, id=sensor_id, channel=channel).set(data['battery_ok'])
            
        if 'rssi' in data: 
             SIGNAL_DB.labels(model=model, id=sensor_id, channel=channel).set(data['rssi'])
             
    except json.JSONDecodeError:
        logging.warning(f"JSON Decode Error for line: {line}")
    except Exception as e:
        logging.error(f"Error processing line: {e}", exc_info=True)

def main():
    # Start Prometheus HTTP server
    start_http_server(9550)
    logging.info("Prometheus metrics available on port 9550")
    
    proc = run_rtl433()
    
    try:
        while True:
            output = proc.stdout.readline()
            
            # Check if process has exited
            if proc.poll() is not None:
                logging.error("rtl_433 process exited unexpectedly.")
                stderr_output = proc.stderr.read()
                if stderr_output:
                    logging.error(f"rtl_433 stderr: {stderr_output}")
                break

            if output == '':
                continue
                
            if output:
                process_line(output.strip())
                
    except KeyboardInterrupt:
        # print("Stopping...")
        proc.terminate()
        
    if proc.poll() is None:
        proc.terminate()

if __name__ == '__main__':
    main()
