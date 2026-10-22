# Table Planner

Generates circular seating plans across multiple meals: alternates men and women, keeps relations apart, seats preferred neighbours together, and avoids repeat neighbours from one meal to the next.

## Run locally

```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000

## Host it online (Render — free, one click)

1. Go to https://render.com and sign in with GitHub.
2. Click **New → Blueprint** and pick this repository.
3. Render reads `render.yaml`, generates a `SECRET_KEY` for you, and deploys.
4. Your app is live at `https://table-planner-xxxx.onrender.com`.

The free plan sleeps after 15 minutes idle, so the first visit after a break takes ~30 seconds to wake up.

## Host it on Railway instead

1. https://railway.app → **New Project → Deploy from GitHub repo** → pick this repo.
2. Under **Variables**, add `SECRET_KEY` (any long random string) and `SESSION_COOKIE_SECURE=true`.
3. Under **Settings → Networking**, click **Generate Domain**.

Railway uses the `Procfile` automatically.

## Use it on your phone

Open the hosted URL, then:
- **iPhone (Safari):** Share → Add to Home Screen
- **Android (Chrome):** ⋮ menu → Add to Home Screen

## CSV format

```
name,sex,relations,preferred people,Breakfast,Lunch,Dinner
Olivia,female,Duncan,Tom,Yes,No,Yes
Duncan,male,Olivia,,Yes,Yes,No
```

- **relations** — people who should *not* sit next to this person (e.g. a spouse)
- **preferred people** — people they *should* sit next to if possible
- Every column after `preferred people` is a meal: `Yes` or `No`

Templates: `static/Example_Plan.csv`, `static/Blank_Plan.csv`.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | dev value | **Set this in production** |
| `SESSION_COOKIE_SECURE` | `false` | Set `true` when served over HTTPS |
| `PORT` | `5000` | Set automatically by the host |
| `FLASK_DEBUG` | `false` | Local development only |
| `UPLOAD_DIR` | `uploads/` | Where uploaded CSVs are stored |
| `SESSION_DIR` | system temp | Where session data is stored |

Uploads and sessions live on the server's temporary disk, so they reset when the app redeploys or restarts. That's fine for planning an event in one sitting.
