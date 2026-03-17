# ESPN Fantasy Basketball Playoff Tracker

Track live playoff matchups and standings for your ESPN H2H Categories fantasy basketball league.

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Get your ESPN cookies

Your league is private, so you need two browser cookies to authenticate.

1. Log in to your ESPN fantasy league at [fantasy.espn.com](https://fantasy.espn.com)
2. Open browser Developer Tools (F12 or Cmd+Opt+I)
3. Go to **Application** (Chrome) or **Storage** (Firefox) > **Cookies** > `espn.com`
4. Find and copy these two cookie values:
   - **espn_s2** — a long alphanumeric string
   - **SWID** — a GUID wrapped in curly braces, e.g. `{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}`

### 3. Create your `.env` file

```bash
cp .env.example .env
```

Paste your cookie values into `.env`:

```
ESPN_S2=your_espn_s2_cookie_here
SWID={your-swid-here}
```

### 4. Run the script

```bash
# Show current matchups and standings
python espn_playoffs.py

# Export matchups and standings to CSV files
python espn_playoffs.py --export
```

CSV files are saved with timestamps, e.g. `matchups_2025-03-16_14-30-00.csv`.
