# Auto Run on Mac

This project is intentionally alerts-only. It does not log in to a broker and
does not place real-money orders.

To run every 15 minutes manually:

```bash
sh run.sh --loop --sleep 900
```

For background auto-run, create a macOS LaunchAgent that runs:

```bash
/bin/sh /path/to/low-time-trading-assistant/run.sh --loop --sleep 900
```

Keep `config.json` private. Do not commit Telegram tokens or chat IDs.
