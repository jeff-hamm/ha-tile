# Tile Tracker Tests

Standalone test scripts for the Tile Tracker integration.
These can run without Home Assistant installed.

## Running Tests

```bash
# Set credentials
export TILE_EMAIL="your@email.com"
export TILE_PASSWORD="yourpassword"

# Run all tests
python test_tile_api.py

# Run specific test
python test_tile_api.py --test login
python test_tile_api.py --test tiles
python test_tile_api.py --test states
python test_tile_api.py --test details

# Or pass credentials directly
python test_tile_api.py --email your@email.com --password yourpass
```

## Test Coverage

- **login**: Tests authentication with Tile API
- **tiles**: Lists all tiles with full details (RSSI, location, battery, etc.)
- **states**: Gets current state for all tiles (location, lost status)
- **details**: Gets raw JSON response for a specific tile

## Requirements

```bash
pip install aiohttp
```
