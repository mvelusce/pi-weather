# Pi Weather Exporter

Prometheus exporter for 433MHz weather sensors (e.g., EMOS E6016) running on a Raspberry Pi with an RTL-SDR stick.

## Prerequisites
- Raspberry Pi (tested on Pi 5)
- RTL-SDR USB stick
- RTL-433-compatible weather sensor

## Installation

A setup script is provided to automate the installation of system dependencies and the systemd service.

1.  **Clone or copy the repository** to your Raspberry Pi.
2.  **Run the setup script**:
    ```bash
    sudo chmod +x setup.sh
    sudo ./setup.sh
    ```

This script will:
- Install `rtl-433` and python dependencies.
- Create a virtual environment.
- Install and start the `weather-exporter` systemd service.

## Usage

### Check Service Status
```bash
sudo systemctl status weather-exporter
```

### View Logs
```bash
journalctl -u weather-exporter -f
```

### Access Metrics
The exporter runs on port **9550** by default.
```bash
curl http://localhost:9550/metrics
```

## Configuration
- Modify `exporter.py` to update the `SENSOR_MAP` with your specific sensor IDs and names.
- The service monitors 433.92MHz by default.
