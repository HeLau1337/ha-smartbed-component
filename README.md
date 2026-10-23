# Home Assistant Integration for SmartBed

This Home Assistant custom component integrates a DIY motorized adjustable bed powered by an ESP8266 controller. The ESP controller exposes a REST API that operates the relays for raising and lowering the head and foot sections of the bed.

The integration exposes two `cover` entities in Home Assistant:
- `cover.<configured_name>_head_motor`
- `cover.<configured_name>_foot_motor`

---

## Configuration

Add the following to your `configuration.yaml`:

```yaml
cover:
  - platform: smartbed
    name: "My SmartBed"
    base_url: "http://esp-smartbed-controller.local"
    scan_interval: 20
```

### Configuration Variables

| Key | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `platform` | string | **Yes** | — | Must be `smartbed`. |
| `base_url` | string | **Yes** | `http://esp-smartbed-controller.local` | Base URL of the ESP8266 REST API. |
| `name` | string | No | `SmartBed` | Friendly name prefix for the bed entities. |
| `scan_interval` | integer | No | `30` | Polling interval in seconds to sync relay states. |

---

## Development Environment Setup

This project uses [`uv`](https://docs.astral.sh/uv/) for fast, reproducible Python dependency management and virtual environments.

### 1. Prerequisites

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) (recommended):
  ```bash
  # macOS / Linux
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # or via Homebrew on macOS
  brew install uv
  ```

### 2. Initial Setup

Clone the repository and synchronize the development environment:

```bash
git clone https://github.com/HeLau1337/ha-smartbed-component.git
cd ha-smartbed-component

# Create virtual environment and install all dev/test dependencies
uv sync
```

This will automatically create a `.venv` directory with `homeassistant`, `pytest`, `pytest-homeassistant-custom-component`, and all required test tooling.

### 3. Running Unit Tests

Run the test suite using `uv`:

```bash
# Run all tests
uv run pytest

# Run tests with verbose output
uv run pytest -v

# Run a specific test file
uv run pytest tests/test_cover.py
```

### 4. Updating Dependencies

Dependencies are managed in [`pyproject.toml`](file:///Users/hendrik/Documents/dev/ha-smartbed-component/pyproject.toml) and locked in [`uv.lock`](file:///Users/hendrik/Documents/dev/ha-smartbed-component/uv.lock):

```bash
# Add a new development package
uv add --group dev <package_name>

# Update lockfile after editing pyproject.toml
uv lock
```
