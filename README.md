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
  "stale_threshold_seconds": 300,
  "sensors": [
    {
      "channel": 1,
      "id": 104,
      "location": "Indoor Ch1",
      "temperature_c": 21.3,
      "humidity_percent": 45,
      "battery_ok": 1,
      "last_update": "2026-11-03T14:30:00",
      "age_seconds": 42.5,
      "stale": false
    }
  ],
  "ignored": []
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
  sample_rate: "1024k"
  protocol: 214

sensor:
  model: "EMOS-E6016"
  id_switch_after_seconds: 900
  id_switch_min_readings: 2
  channels:
    1:
      location: "Indoor Ch1"
    2:
      location: "Outdoor Ch2"
    3:
      location: "Outdoor Ch3"
```

`sample_rate` sets how wide a band rtl_433 listens to. EMOS sensors can transmit up to ~200 kHz away from 433.92 MHz and drift further when hot, so the rtl_433 default (250k, ±125 kHz) misses some sensors entirely and loses others on hot days. 1024k (±512 kHz) covers them.

### Sensors are identified by channel

Each sensor is configured by its channel switch, not its ID, because EMOS sensors pick a new random ID on every battery swap. Metrics are labelled `model`, `channel` and `location` only, so a battery swap doesn't create a new time series. Query by `channel` in Grafana (e.g. `max by(channel) (weather_temperature_celsius{channel="3"})`) and `location` can be renamed freely.

Each channel locks to the ID it hears. Readings from a different ID on the same channel (e.g. a neighbour's sensor) are ignored, unless the locked ID has been silent for `id_switch_after_seconds` and the new ID has sent at least `id_switch_min_readings` readings: then the new ID takes over (battery swap). Locked IDs are saved in `state.json` next to `exporter.py`, so restarts keep them. `weather_sensor_info{channel, id}` shows the current ID per channel, `weather_ignored_readings` counts ignored readings, and `/health` lists them under `ignored`.

To force a new ID right away (e.g. after moving a sensor to another channel), stop the service, edit or delete `state.json`, and start it again.

After changing the config, restart the service:

```bash
sudo systemctl restart weather-exporter
```

### Finding sensors

To find sensors that aren't being received, stop the service and scan all decoders on a wide band:

```bash
sudo systemctl stop weather-exporter
sudo rtl_433 -f 433.92M -s 1024k -F json -M level
sudo systemctl start weather-exporter
```

The exporter also exports `weather_signal_rssi_db`, `weather_signal_snr_db` and `weather_signal_frequency_mhz` per sensor.
