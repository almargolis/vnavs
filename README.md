# VNAVS
## Visually Navigating Autonomous Vehicle System

[![License: LGPL v3](https://img.shields.io/badge/License-LGPL%20v3-blue.svg)](https://www.gnu.org/licenses/lgpl-3.0)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

**VNAVS** is a high-performance Python framework for autonomous vehicle control and coordination. Designed as a lightweight alternative to ROS (Robot Operating System), VNAVS provides 10-100x faster message passing through a custom protocol while maintaining simplicity and ease of use.

---

## Why VNAVS?

While working with ROS on embedded platforms, I encountered critical performance bottlenecks—message delays of multiple minutes between Raspberry Pi and host systems made real-time control impossible. VNAVS solves this with a custom message broker optimized for vision-heavy robotics applications.

### Key Advantages

**Performance**
- Custom TCP-based message protocol eliminates MQTT broker overhead
- TCP_NODELAY implementation prevents Nagle's algorithm delays
- LIFO queue support prevents message saturation on high-volume sensor streams
- Proven to reduce latency from minutes to milliseconds on RPI platforms

**Architecture**
- Node-based publish-subscribe pattern for autonomous coordination
- Dual broker support: proprietary FastMqttServer or standard Mosquitto
- Integrated vision pipeline with GPS navigation
- Mission-aware logging with message replay capabilities

**Reliability**
- Thread monitoring and automatic resurrection
- Exception rate limiting prevents cascade failures
- Connection recovery with graceful degradation
- Centralized error logging on `system/abend` topic

**Developer Experience**
- Pure Python—no C++ compilation required
- Single base class (`VnavsNode`) for most use cases
- Comprehensive logging built-in
- Lower memory footprint than ROS (ideal for embedded systems)

---

## System Architecture

VNAVS is organized as four packages:

### External Packages (installed separately)

- **[ezcomms](https://github.com/almargolis/ezcomms)** — Communication and data layer
  - `vnavs_node.py`: Base class for all nodes with built-in pub/sub
  - `vnavs_comms.py`: Low-level socket communication with custom protocol
  - `vnavs_mqtt_clients.py`: FastMqttClient and standard MQTT client
  - `vnavs_data.py`: Data serialization, validation, and persistence

- **[eztk](https://github.com/almargolis/eztk)** — Simplified Tkinter widget framework with grid layout engine

- **[cvpipeline](https://github.com/almargolis/cvpipeline)** — Computer vision pipeline
  - `opticchiasm.py`: Core vision primitives, color space tracking, geometry classes
  - `image_filters.py`: Chainable image filter system with 26 built-in filters
  - `image_analyzer.py`: Standalone image analysis (line detection, contour classification)
  - `cvpipeline.py`: GUI editor for building filter pipelines

### This Repository

- **`vnavslib/`** — Hardware abstraction (joystick, servo control, etc.)
- **`vnavsrun/`** — Application-level nodes:
  - `fastmqttserver.py`: High-performance message broker with archiving
  - `navigator.py`: GPS waypoint navigation with PID steering control
  - `helmsman.py`: Motor and steering control
  - `cameraman.py`: Multi-camera image capture and streaming
  - `engineer_1.py`: Sensor data collection and processing
  - `mission_control.py`: Coordination and mission sequencing

---

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/almargolis/vnavs.git
cd vnavs

# Install dependencies (pulls in ezcomms, eztk, cvpipeline from PyPI)
pip install -r requirements.txt

# Install VNAVS packages
pip install -e vnavslib/
pip install -e vnavsrun/
```

### Basic Example

```python
from ezcomms import vnavs_node as vmqtt

# Create a simple node that publishes sensor data
class SensorNode(vmqtt.VnavsNode):
    def __init__(self):
        super().__init__()
        self.subscribe_latest_only('system/mission_start', self.on_mission_start)

    def on_mission_start(self, msg):
        # Publish sensor reading
        self.publish('sensors/temperature', {'value': 25.3, 'unit': 'C'})

# Run the node
if __name__ == '__main__':
    node = SensorNode()
    node.run()
```

### Running the Message Broker

```bash
# Start FastMqttServer (custom high-performance broker)
python -m vnavsrun.fastmqttserver

# Or use standard Mosquitto
mosquitto -p 1883
```

---

## System Requirements

**Minimum:**
- Python 3.8 or higher
- 512 MB RAM (tested on Raspberry Pi 3)
- Linux or macOS

**Dependencies:**
- `ezcomms` — Message passing and data layer
- `cvpipeline` — Computer vision pipeline (brings in OpenCV, NumPy, Pillow)
- `eztk` — GUI toolkit
- `geopy` — GPS coordinate calculations
- `pyserial` — Hardware communication

**Optional:**
- `picamera` — Raspberry Pi camera support
- `pyfirmata` — Arduino integration
- `pygame` — Joystick input

---

## Features

### Message Passing
- **Dual subscription modes**: Latest-only (LIFO) for sensor streams, or all messages for guaranteed delivery
- **Confirmation requests**: Optional message acknowledgment with tracking
- **Topic filtering**: Standard MQTT-style topic wildcards
- **Metadata**: Automatic timestamping, sender ID, sequence numbers on all messages

### Mission Management
- **Mission lifecycle**: init → start → log_start → log_stop → end
- **Message archiving**: All messages captured with metadata in `.nav` files
- **Replay capability**: Debugging and analysis via archived logs
- **System events**: Centralized coordination via system topics

### Error Handling
- **Thread resurrection**: Detects and restarts dead communication threads
- **Exception limiting**: Exits only after 10 exceptions within 60 seconds
- **Stale message detection**: Warnings for messages older than 120 seconds
- **Socket error recovery**: Graceful handling of connection resets and temporary failures

### Navigation & Vision
- **GPS waypoint following**: Coordinate-based navigation with geopy
- **PID steering control**: Proportional-integral-derivative motor control
- **Multi-camera support**: MacBook camera, Raspberry Pi camera, generic USB
- **OpenCV pipeline**: Image filtering, feature detection, transformation chains

---

## Configuration

VNAVS uses `~/vnavs.ini` for configuration (not included in repo—create your own):

```ini
[MqttFast]
broker_host = localhost
broker_port = 1884

[MqttFastServer]
message_archive_path = ~/vnavs_missions
buffer_size = 4096

[Cameraman]
camera_type = picamera
resolution = 1920,1080
framerate = 30

[Navigator]
waypoint_tolerance = 2.0  # meters
max_speed = 1.5  # m/s
```

---

## Performance Benchmarks

**Message Latency** (Raspberry Pi 3 to MacBook over WiFi):
- Standard MQTT (Mosquitto): 30-180 seconds under load
- VNAVS FastMqttServer: 10-50 milliseconds under load
- **Improvement: ~1000x**

**Throughput** (messages per second):
- Standard MQTT: ~100 msg/s before degradation
- VNAVS FastMqttServer: ~5000 msg/s sustained
- **Improvement: ~50x**

**Memory Footprint** (per node):
- ROS Noetic: ~150 MB baseline
- VNAVS: ~20 MB baseline
- **Improvement: ~7x**

---

## License

VNAVS is released under the **GNU Lesser General Public License v3.0 (LGPL-3.0)**.

See [LICENSE](LICENSE) for full terms.

---

## Author

**Al Margolis**
Robotics engineer with 30+ years experience in autonomous systems.

---

## Links

- **GitHub**: https://github.com/almargolis/vnavs
- **ezcomms**: https://github.com/almargolis/ezcomms
- **eztk**: https://github.com/almargolis/eztk
- **cvpipeline**: https://github.com/almargolis/cvpipeline
