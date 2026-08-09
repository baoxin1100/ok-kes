# ok-kes

![ok-kes icon](https://raw.githubusercontent.com/baoxin1100/ok-kes/master/icons/icon.png){ .hero-logo }

`ok-kes` is an image-recognition-based automation assistant for Chaos Zero Nightmare. It supports background operation and interacts with the game through normal Windows input APIs without reading game memory or modifying game files.

!!! warning "Disclaimer"
    This project is open-source and free, and is intended only for personal learning and communication. Users are responsible for understanding the risks of third-party automation tools.

## Quick start

1. Download the latest `ok-kes-win32-portable-v*.exe` from [GitHub Releases](https://github.com/baoxin1100/ok-kes/releases). Do not download the Source Code archive.
2. Run the application as administrator.
3. For the international client, set **Game language** to Traditional Chinese in the application settings.
4. Enable Auto Chaos Mode, Auto Sortie Mode, or Semi-auto Story Mode as needed.

## Features

### Auto Chaos Mode

- Handles routes, events, battles, rest areas, shops, and reward settlement.
- Manages card acquisition, removal, copying, and flash effects by priority.
- Supports equipment selection, target members, masks, and save-data flows.
- Supports configuration import, export, and popular shared configurations.

### Auto Sortie Mode

- Plays cards automatically using configurable priorities.
- Selects battle members, cards, and route nodes.
- Handles rest areas, shops, supplies, and reward settlement.

### Semi-auto Story Mode

- Advances dialogue and opens story events automatically.
- Lets the user switch to the corresponding automation mode for battles or Chaos stages.

## Requirements

- Windows and a 16:9 game resolution.
- 1920×1080 is recommended; 1600×900 and 1280×720 are also supported.
- Disable GPU filters, sharpening, and overlays drawn over the game.
- Enable automatic battle and dialogue in the game when using Chaos Mode.
- Show battle shortcut keys because card recognition depends on them.

## Support

- [GitHub Issues](https://github.com/baoxin1100/ok-kes/issues)
- [QQ channel](https://pd.qq.com/s/eopggnxcu)

For source setup and project internals, see the [development guide](../development/index.md) and [software requirements and design](../srd.md).
