# Low-Time Trading Assistant

Ye setup real-money auto trading nahi karta. Ye broker login, OTP, wallet, Paytm Money, Zerodha, Angel, Upstox ya kisi bhi broker me order place nahi karega.

Ye kya karega:

- Yahoo Finance se market data read karega.
- SMA + RSI ke basis par signal banayega.
- Quantity, stop-loss, target aur max loss calculate karega.
- Paper trading CSV log banayega.
- Telegram alert bhej sakta hai.
- Final trade aap manually broker app me karoge.

## Files

- `trading_assistant.py` - main script
- `config.example.json` - sample settings
- `paper_trades.csv` - run karne ke baad auto banega

## Setup

1. Is folder me terminal kholo.
2. Config ready hai. Agar fresh sample se reset karna ho:

```bash
cp config.example.json config.json
```

3. Run karo:

```bash
sh run.sh
```

4. Har 15 minute auto scan ke liye:

```bash
sh run.sh --loop --sleep 900
```

## Telegram Alert Setup

Telegram optional hai. Agar alert phone par chahiye:

1. Telegram me `@BotFather` se bot banao.
2. Bot token lo.
3. Apna chat id nikalo.
4. `config.json` me ye fields bharo:

```json
"telegram_bot_token": "YOUR_TOKEN",
"telegram_chat_id": "YOUR_CHAT_ID"
```

## Risk Rules

Default rules:

- Capital: Rs 10,000
- Max risk per trade: Rs 100
- Daily max loss: Rs 200
- Leverage nahi
- F&O nahi
- Stop-loss ke bina trade nahi

## Signal Ka Meaning

- `BUY_WATCH`: Setup interesting hai. App kholkar manually check karo.
- `WAIT`: Clear trade nahi hai.
- `AVOID_OR_EXIT`: Trend weak hai, entry avoid karo.

## Important

Script ka signal guarantee nahi hai. Market me loss ho sakta hai. Isko assistant ki tarah use karo, autopilot ki tarah nahi.
