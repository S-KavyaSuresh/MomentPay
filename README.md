# MomentPay

MomentPay is an AI-assisted experience-planning platform. Users can discuss an occasion with **Pip**, explore ideas and product suggestions, refine a budget-aware plan, and try a PayPal Sandbox payment demonstration.

> **Project status:** Demonstration/educational project. The included PayPal integration targets the Sandbox environment. It is not production-ready payment software.

## Features

- Conversational planning assistant (Pip)
- Occasion and idea exploration
- Product discovery and plan refinement
- Budget-aware planning
- PayPal Sandbox payment demonstration
- SQLite-backed demo data
- Optional AI and search integrations, with configurable demo fallback

## Technology stack

- **Backend:** Python, FastAPI, Uvicorn
- **Frontend:** HTML, CSS, JavaScript
- **Database:** SQLite
- **AI providers:** Gemini and Groq (optional)
- **Payments:** PayPal Sandbox
- **Product/search integrations:** DummyJSON, FakeStore API, SerpAPI and Channel3 (optional)

## Project structure

```text
MomentPay/
├── main.py
├── requirements.txt
├── .env.example
├── .gitignore
├── LICENSE
├── PROMPT.md
└── static/
    ├── index.html
    └── images/
```

The SQLite database is created automatically at runtime. By default, it is stored as `momentpay.db` in the working directory. Set `DB_PATH` to use another location. Database files and local credentials are excluded from Git.

## Run locally

### 1. Requirements

- Python 3.10 or later
- Git

### 2. Clone the repository

```bash
git clone https://github.com/<your-username>/<your-repository>.git
cd <your-repository>
```

### 3. Create a virtual environment

**Windows (PowerShell):**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**

```bat
py -m venv .venv
.venv\Scripts\activate.bat
```

**macOS/Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Configure environment variables

Copy `.env.example` to `.env` and add the credentials for the integrations you want to enable.

**PowerShell:**

```powershell
Copy-Item .env.example .env
```

**Command Prompt:**

```bat
copy .env.example .env
```

**macOS/Linux:**

```bash
cp .env.example .env
```

The app can start without optional AI/search credentials when demo fallback is enabled. PayPal payment features require valid PayPal Sandbox credentials.

### 6. Start MomentPay

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000** in your browser.

## Environment variables

| Variable | Purpose |
|---|---|
| `PAYPAL_CLIENT_ID` | PayPal Sandbox application client ID |
| `PAYPAL_CLIENT_SECRET` | PayPal Sandbox application secret |
| `GEMINI_API_KEY` | Optional Gemini API key |
| `GEMINI_MODEL` | Gemini model name |
| `GROQ_API_KEY` | Optional Groq API key |
| `GROQ_MODEL` | Groq model name |
| `SERPAPI_KEY` | Optional SerpAPI key for search |
| `CHANNEL3_API_KEY` | Optional Channel3 API key |
| `COLLECT_TO_ORGANISER` | Whether the configured PayPal flow pays the organiser directly |
| `BASE_URL` | Public/base URL used by the backend |
| `DEMO_FALLBACK` | Enables configured demo fallback behaviour |
| `DB_PATH` | Optional SQLite database path |

See `.env.example` for the complete variable list and example defaults. Never commit `.env` or real API credentials.

## Demo notes and limitations

- Use PayPal **Sandbox** accounts and credentials when testing payments.
- AI-generated responses require a valid Gemini or Groq key unless the configured fallback path is used.
- Product and search results depend on external services and their availability.
- Demo fallback is for local development and presentations; it is not a production substitute for live integrations.
- Before any public/production deployment, review authentication, authorisation, password handling, payment workflows, input validation, secrets management, logging, privacy, and database security.

## Contributing

1. Fork the repository.
2. Create a feature branch.
3. Make and test your changes.
4. Commit with a descriptive message.
5. Open a pull request describing the change.

## License

This project is distributed under the MIT License. See [LICENSE](LICENSE).
