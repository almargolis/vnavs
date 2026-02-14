# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

VNAVS (Visually Navigating Autonomous Vehicle System) — a high-performance Python robotics framework designed as a lightweight ROS alternative, optimized for Raspberry Pi and embedded platforms. Uses custom MQTT-like messaging for inter-node communication with millisecond-level latency.

## Commands

```bash
# Run all tests
pytest

# Run tests for one package
pytest vnavslib/test
pytest vnavsrun/test

# Run a single test file
pytest vnavsrun/test/test_cvlab.py -v

# Run a single test function
pytest vnavsrun/test/test_cvlab.py::test_clear_info_empties_existing_list -v

# Format code
black .

# Lint
pylint vnavslib/vnavslib/ vnavsrun/vnavsrun/
```

## Architecture

### Two-Package Structure

- **`vnavslib/vnavslib/`** — Reusable core library (communication, vision, hardware abstraction)
- **`vnavsrun/vnavsrun/`** — Application-level nodes (servers, controllers, GUIs)
- Tests live in `vnavslib/test/` and `vnavsrun/test/`, mirroring module names as `test_<module>.py`

### Communication Layer (vnavslib)

`VnavsNode` (in `vnavs_node.py`) is the base class for nearly every module. It provides pub/sub messaging, automatic reconnection, thread management, and exception rate limiting. All nodes inherit from it.

Two broker backends share a unified API:
- **FastMqttServer** (`vnavsrun/fastmqttserver.py`) — Custom high-performance broker on port 4000, using TCP with zero/one framing protocol and TCP_NODELAY. Supports LIFO subscriptions for high-volume sensor streams.
- **Mosquitto** — Standard MQTT on port 1883, wrapped via `PahoClient` in `vnavs_mqtt_clients.py`.

`vnavs_comms.py` implements the low-level socket layer: `SocketWrapper` → `SocketWrapperServer`/`SocketWrapperClient`, plus `SocketXfer` for multi-process file transfer.

### Vision Pipeline (vnavslib)

`opticchiasm.py` provides `Image` (OpenCV wrapper tracking color space to prevent conversion bugs), `ImageFilter` (chainable processing step with code template), and `ImageFilterCollection` (registry of all filters). `cvlab.py` is the GUI editor for building filter pipelines.

### Key Patterns

- **`__slots__` everywhere** — All domain classes use `__slots__` for memory efficiency on embedded platforms.
- **Class-level state on ProcessStep** — `ProcessStep.steps` (list) and `ProcessStep.app` (in `cvlab.py`) are class variables shared across instances, representing the global pipeline state. Tests must save/restore these.
- **Subscription modes** — LIFO (keep only latest, for sensors) vs FIFO (all messages, for commands), configured per-subscription via `VnavsNode`.
- **Message metadata** — Every published message gets `_topic`, `_sender`, `_sendTime`, `_sendSeq` automatically.
- **Threading** — Multi-threaded by default; single-threaded mode for Tkinter GUI apps (configured via `single_threaded=True` in VnavsNode).
- **Configuration** — `~/vnavs.ini` (not versioned); structure defined in `vnavs_const.py`.

### Testing Classes With Tkinter Dependencies

Classes like `ProcessStep` and `CvLab` have `__init__` methods that create GUI widgets. Tests bypass this using `object.__new__(ClassName)` to allocate without calling `__init__`, then manually set `__slots__` attributes. See `test_cvlab.py` for the `make_process_step()` factory pattern and `MockLabel`/`MockCanvas` stand-ins.

## Coding Conventions

- **PEP 8 snake_case** for all methods and parameters (ongoing modernization from CamelCase)
- **`class Foo:` not `class Foo(object):`** — Python 3 style
- Black formatter with 88 char line length
- easytk widget API parameters (`OnClick`, `OnTabSelected`, `Selection`, `Where`) keep their CamelCase — that's easytk's API, not ours
- Constants are UPPER_SNAKE_CASE
- Tests use plain `assert` statements (no unittest classes)
- **Prefer dot-notation access over `from` imports** — Import modules, not their contents. Access names via `module.name` to keep the namespace explicit. This applies especially to project-internal code. The exception is widely established external conventions (e.g., `from PIL import Image`, `import numpy as np`) where `from` imports are standard practice.
