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
The exporter runs on port **9550** by default (configurable in `config.yaml`).
```bash
curl http://localhost:9550/metrics
```

### Health Check
A `/health` endpoint provides JSON status for debugging:
```bash
curl http://localhost:9550/health
```

Example response:
```json
{
  "status": "healthy",
  "sensor_count": 2,
  "stale_threshold_seconds": 300,
  "sensors": [
    {
      "id": 104,
      "location": "Living Room",
      "channel": 1,
      "temperature_c": 21.3,
      "humidity_percent": 45,
      "battery_ok": 1,
      "last_update": "2026-03-27T14:30:00",
      "age_seconds": 42.5,
      "stale": false
    }
  ]
}
```

Status values:
- `healthy` - All sensors reporting within threshold
- `degraded` - Some sensors are stale (no data for 5+ minutes)
- `no_data` - No sensor readings received yet

## Configuration

All settings are stored in `config.yaml`. After installation, the config file is located at `/opt/weather-exporter/config.yaml`.

```yaml
exporter:
  port: 9550

rtl433:
  frequency: "433.92M"
  protocol: 214

sensor:
  model: "EMOS-E6016"
  sensors:
    104:
      location: "Living Room"
      channel: 1
    124:
      location: "Window"
      channel: 3
```

Each sensor entry maps an ID to its location and expected channel. Readings from unexpected channels are ignored to prevent duplicate time series. To add or update sensors, edit the `sensors` map. After making changes, restart the service:

```bash
sudo systemctl restart weather-exporter
```
