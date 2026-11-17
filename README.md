# AURO — Browser Automation Control Panel

AURO হলো Python ও Playwright-ভিত্তিক একটি self-hosted browser automation control panel। YAML ফাইলে workflow সংজ্ঞায়িত করে ওয়েবসাইট টেস্টিং, অনুমোদিত form filling, data entry এবং নির্দিষ্ট পেজ থেকে তথ্য সংগ্রহের কাজ চালানো যায়।

Dashboard থেকে task তৈরি ও সম্পাদনা, CSV/TXT input upload, automation run, live status ও logs দেখা এবং screenshot পর্যালোচনা করা যায়। Task ও run history SQLite-এ সংরক্ষিত হয়।

> **নিরাপত্তা সতর্কতা:** AURO-এর বর্তমান Dashboard-এ authentication/login ব্যবস্থা নেই। তাই Port 8000 কখনো Public Internet-এ উন্মুক্ত করবেন না। Codespaces-এ Port 8000-এর visibility **Private** রাখুন এবং শুধু নিজের অনুমোদিত ব্যবহারকারীদের access দিন। YAML task-এ কেবল আপনার নিজের বা ব্যবহারের অনুমতি আছে এমন ওয়েবসাইট automate করুন। Website-এর Terms of Service, rate limit এবং privacy policy মেনে চলুন। Human-like typing শুধু input interaction test করার সুবিধা; এটি access control বা anti-bot protection bypass করার জন্য নয়।

---

## ১. প্রযুক্তি

- Python 3.12
- Playwright for Python — installed Google Chrome, `channel="chrome"`
- FastAPI + Uvicorn
- Jinja2 templates, vanilla HTML/CSS/JavaScript
- SQLite via Python standard-library `sqlite3`
- YAML task definitions via PyYAML
- Docker + Docker Compose
- GitHub Actions + pytest

## ২. Repository structure

```text
auro/
├── .devcontainer/
│   └── devcontainer.json
├── .github/
│   └── workflows/
│       └── ci.yml
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── runner.py
│   ├── database.py
│   ├── models.py
│   ├── config.py
│   ├── tasks/
│   │   └── demo_form.yaml
│   ├── templates/
│   │   ├── base.html
│   │   ├── index.html
│   │   ├── task_detail.html
│   │   └── settings.html
│   └── static/
│       ├── style.css
│       └── app.js
├── data/
│   └── .gitkeep
├── screenshots/
│   └── .gitkeep
├── sessions/
│   └── .gitkeep
├── tests/
│   ├── test_app.py
│   ├── test_runner.py
│   └── dashboard_browser_smoke.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .gitignore
└── README.md
```

## ৩. GitHub Codespaces-এ শুরু করুন

### Codespace তৈরি

1. [AURO GitHub Repository](https://github.com/connectnexdesh-droid/auro) খুলুন।
2. সবুজ **Code** বাটনে ক্লিক করুন।
3. **Codespaces** tab খুলুন।
4. **Create codespace on main** নির্বাচন করুন।
5. Codespace তৈরি হলে VS Code Web Editor খুলবে।

Repository-এর `.devcontainer/devcontainer.json` স্বয়ংক্রিয়ভাবে Python 3.12 environment তৈরি করে এবং `postCreateCommand`-এ প্রয়োজনীয় Python packages, Playwright browser dependencies ও Google Chrome install করে।

প্রথমবার setup শেষ হতে কয়েক মিনিট লাগতে পারে।

### Installation যাচাই

Codespaces-এর Terminal খুলে চালান:

```bash
python --version
python -m playwright --version
google-chrome --version
```

Python version 3.12 হওয়া এবং Chrome-এর version দেখানো উচিত।

যদি Chrome না পাওয়া যায়, চালান:

```bash
python -m playwright install --with-deps chrome
```

### Database ও runtime directory তৈরি

```bash
python -c "from app.config import ensure_runtime_directories; ensure_runtime_directories()"
python -c "from app.database import init_db; init_db()"
```

### Dashboard চালু

Repository root directory থেকে:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Codespaces সাধারণত Port 8000 detect করে। **Ports** tab থেকে Open in Browser নির্বাচন করুন। Dashboard-এর ঠিকানা হবে:

```text
http://localhost:8000
```

Port 8000-এর visibility **Private** রাখুন। Server বন্ধ করতে Terminal-এ `Ctrl+C` চাপুন।

## ৪. Dashboard ব্যবহার

### Dashboard

Home page-এ নিবন্ধিত YAML tasks, সর্বশেষ run status এবং uploaded input files দেখা যায়।

### নতুন Task তৈরি

1. Dashboard-এর task creation form-এ একটি নাম লিখুন।
2. YAML definition লিখুন।
3. **Validate & save task** চাপুন।

Task name-এ letters, numbers, underscore ও hyphen ব্যবহার করা যায়; নামটি ১–৬৪ অক্ষরের হতে হবে।

### Task সম্পাদনা

Task detail page খুলে YAML editor-এ পরিবর্তন করুন এবং **Save changes** চাপুন। AURO YAML validate করে তারপর ফাইলে সংরক্ষণ করে।

### Automation চালানো

1. Dashboard অথবা task detail page থেকে task নির্বাচন করুন।
2. প্রয়োজন হলে আগে upload করা CSV/TXT input file নির্বাচন করুন।
3. **Run task** চাপুন।
4. Run status, logs ও screenshots দেখুন।

Dashboard JavaScript প্রতি ২ সেকেন্ডে run status poll করে। চলমান run-এর জন্য Stop control-ও আছে।

### Settings

Settings page থেকে নিচের মানগুলো পরিবর্তন করা যায়:

- Headless browser on/off
- Minimum ও maximum step delay (milliseconds)
- Retry count
- Action timeout (milliseconds)

Settings SQLite database-এ সংরক্ষিত হয়। Environment variable থাকলে সেটি SQLite setting-এর চেয়ে অগ্রাধিকার পায়। Docker-এ headless mode বাধ্যতামূলক রাখা হয়েছে, কারণ container-এ desktop display নেই।

## ৫. YAML Task তৈরি

প্রতিটি task `app/tasks/` directory-তে `.yaml` অথবা `.yml` ফাইল।

### সম্পূর্ণ Demo Task

Repository-তে `app/tasks/demo_form.yaml` দেওয়া আছে:

```yaml
name: demo_form
description: "Fill and submit the public Selenium demo form."
headless: true
timeout_ms: 30000
retry: 2

delay:
  min_ms: 500
  max_ms: 1000

storage_state:
  load: false
  save: false

steps:
  - action: goto
    url: "https://www.selenium.dev/selenium/web/web-form.html"

  - action: fill
    selector: "input[name='my-text']"
    value: "AURO Demo User"
    human_like: true

  - action: fill
    selector: "input[name='my-password']"
    value: "DemoPassword123!"
    human_like: true

  - action: select
    selector: "select[name='my-select']"
    value: "1"

  - action: click
    selector: "button[type='submit']"

  - action: wait_for
    selector: "text=Received!"
    state: visible

  - action: screenshot
    name: "success"
    full_page: true
```

### YAML-এর মূল Settings

| Field | কাজ |
|---|---|
| `name` | Unique task name |
| `description` | Task-এর বর্ণনা |
| `headless` | Chrome window দেখাবে কি না |
| `timeout_ms` | প্রতিটি Playwright action-এর timeout |
| `retry` | ব্যর্থ হলে অতিরিক্ত retry সংখ্যা |
| `delay.min_ms` | Step-এর মধ্যবর্তী বিরতির সর্বনিম্ন সময় |
| `delay.max_ms` | Step-এর মধ্যবর্তী বিরতির সর্বোচ্চ সময় |
| `storage_state` | Saved browser session load/save |

### Supported Step Actions

| Action | প্রয়োজনীয় YAML fields | কাজ |
|---|---|---|
| `goto` | `url` | URL খোলে |
| `fill` | `selector`, `value` | Input পূরণ করে |
| `select` | `selector`, `value` | Select option বেছে নেয় |
| `click` | `selector` | Element-এ click করে |
| `wait_for` | `selector` | Element-এর state-এর জন্য অপেক্ষা করে |
| `screenshot` | `name` optional | Screenshot নেয় |
| `press` | `selector`, `key` | Element-এ keyboard key press করে |
| `check` | `selector` | Checkbox check/uncheck করে |
| `scroll` | `selector` অথবা `x`, `y` | Element-এ scroll করে বা page scroll করে |

অতিরিক্ত options:

- `fill`: `human_like: true` দিলে sequential typing হয়। `typing_delay_ms` দিয়ে প্রতি key-এর delay নির্ধারণ করা যায়; না দিলে runner 45–110 ms-এর মধ্যে random delay নেয়।
- `goto`: `wait_until` দেওয়া যায়।
- `wait_for`: `state` হতে পারে `attached`, `detached`, `visible` অথবা `hidden`।
- `screenshot`: `full_page: true` দিলে পুরো page capture হয়।
- `check`: `checked: false` দিলে checkbox uncheck হয়।
- `click`: `button` ও `click_count` optional।

## ৬. CSV ও TXT Input

Dashboard-এর **Upload input file** section থেকে CSV বা TXT upload করা যায়। সর্বোচ্চ file size 10 MB এবং file UTF-8 encoded হতে হবে।

### CSV উদাহরণ

`data/contacts.csv`:

```csv
first_name,email
Amina,amina@example.com
Rafi,rafi@example.com
```

YAML-এ ব্যবহার:

```yaml
- action: fill
  selector: "input[name='name']"
  value: "{{csv.first_name}}"

- action: fill
  selector: "input[name='email']"
  value: "{{csv.email}}"
```

প্রতিটি CSV row-এর জন্য পুরো workflow ধারাবাহিকভাবে execute হয়।

### TXT উদাহরণ

`data/names.txt`:

```text
Amina
Rafi
Nadia
```

YAML-এ ব্যবহার:

```yaml
- action: fill
  selector: "input[name='name']"
  value: "{{line}}"
```

প্রতিটি non-empty TXT line-এর জন্য workflow একবার করে চলে।

### Template tokens

| Token | ফলাফল |
|---|---|
| `{{csv.column_name}}` | বর্তমান CSV row-এর নির্দিষ্ট column |
| `{{line}}` | বর্তমান TXT line |
| `{{random}}` | ৮ অক্ষরের random alphanumeric string |
| `{{now}}` | বর্তমান UTC ISO timestamp |

Input file না দিলে workflow একবার খালি input record দিয়ে চলে। CSV column ভুল হলে বা TXT context ছাড়া `{{line}}` ব্যবহার করলে runner error দেয়।

## ৭. Browser Session পুনর্ব্যবহার

Login session বা cookies সংরক্ষণের জন্য task YAML-এ:

```yaml
storage_state:
  load: true
  save: true
```

অথবা সংক্ষেপে:

```yaml
storage_state: true
```

Session file তৈরি হবে:

```text
sessions/<task_name>.json
```

Runner আগে file থাকলে সেটি load করবে এবং workflow সফল হলে updated state save করবে। Session file-এ authentication cookies বা sensitive local storage থাকতে পারে। এটি কারও সঙ্গে share করবেন না এবং Git-এ commit করবেন না।

## ৮. CLI থেকে Task চালানো

Repository root থেকে:

```bash
python -m app.runner app/tasks/demo_form.yaml --headless
```

CSV input দিয়ে:

```bash
python -m app.runner app/tasks/demo_form.yaml --headless --input data/contacts.csv
```

TXT input দিয়ে:

```bash
python -m app.runner app/tasks/demo_form.yaml --headless --input data/names.txt
```

CLI একটি JSON result print করে। সফল হলে exit code 0, task failure হলে non-zero exit code দেয়।

## ৯. Screenshot, Trace ও Logs

- সফল workflow-এ YAML-এর `screenshot` action screenshot তৈরি করে।
- Screenshot রাখা হয় `screenshots/` directory-তে।
- Failure হলে সম্ভব হলে failure screenshot নেওয়া হয়।
- Failed attempt-এর Playwright trace `.zip` ফাইল হিসেবে রাখা হয়।
- Console logs JSON format-এ লেখা হয়।
- Run logs SQLite database-এ সংরক্ষিত হয়।

Trace inspect করতে:

```bash
playwright show-trace screenshots/<trace-file>.zip
```

Trace-এ page content, network metadata বা form data থাকতে পারে। Share করার আগে sensitive information পরীক্ষা করুন।

## ১০. Docker দিয়ে চালানো

Docker ও Docker Compose ইনস্টল থাকা প্রয়োজন।

Repository root-এ:

```bash
docker compose up --build -d
```

Container status:

```bash
docker compose ps
```

Live logs:

```bash
docker compose logs -f app
```

Dashboard:

```text
http://localhost:8000
```

Health endpoint:

```text
http://localhost:8000/health
```

বন্ধ করতে:

```bash
docker compose down
```

Compose configuration নিচের directory-গুলো host machine-এ mount করে, তাই container recreate করলেও এগুলো থাকে:

- `app/tasks/` — YAML task definitions
- `data/` — SQLite database ও uploaded CSV/TXT
- `screenshots/` — screenshot ও trace
- `sessions/` — saved browser state

Playwright browser-এর shared memory সমস্যা কমাতে Compose-এ `shm_size: 1gb` দেওয়া আছে। Docker container-এ Chrome headless mode-এ চলে।

## ১১. GitHub Actions CI

Workflow: `.github/workflows/ci.yml`

CI স্বয়ংক্রিয়ভাবে চলে:

- `main` branch-এ push হলে
- `main`-এর বিরুদ্ধে Pull Request খুললে বা update হলে
- GitHub Actions-এর **Run workflow** ব্যবহার করলে

CI-তে:

1. Python 3.12 setup
2. requirements install
3. Playwright-এর জন্য Google Chrome install
4. Python compile/syntax check
5. pytest suite — runner unit tests ও Dashboard/API integration tests
6. Selenium demo form-এর headless browser smoke test
7. Real-browser Dashboard E2E — CSV upload, Settings, Task creation, Run, Stop, Logs ও Screenshot Gallery
8. Screenshot artifact upload
9. Docker Compose config validation
10. Docker image build

Local environment-এ Dashboard-এর real-browser E2E test চালাতে:

```bash
python tests/dashboard_browser_smoke.py
```

এই script অস্থায়ী runtime directories তৈরি করে, local Uvicorn server চালু করে, Chrome দিয়ে Dashboard পরীক্ষা করে এবং শেষে server বন্ধ করে।

ফলাফল দেখতে Repository-এর **Actions** tab খুলুন। Screenshot artifact সফল CI run-এর সঙ্গে ৭ দিন রাখা হয়।

## ১২. Troubleshooting

### Chrome not found

Error-এ Chrome executable না পাওয়া গেলে:

```bash
python -m playwright install --with-deps chrome
google-chrome --version
```

Codespaces-এ command শেষ হলে Terminal থেকে runner আবার চালান।

### Playwright browser dependency missing

Linux shared library বা browser launch error হলে:

```bash
python -m playwright install-deps chrome
python -m playwright install chrome
```

### `ModuleNotFoundError: No module named 'app'`

সব command repository root directory থেকে চালান। Pytest-এর জন্য:

```bash
python -m pytest -v tests/
```

### Port 8000 already in use

আগের Uvicorn process বন্ধ করুন (`Ctrl+C`) অথবা অন্য port ব্যবহার করুন:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

Codespaces-এ নতুন port forward করুন।

### Docker browser crash বা shared memory error

Compose-এ `shm_size: "1gb"` আছে। Docker service recreate করুন:

```bash
docker compose down
docker compose up --build -d
docker compose logs -f app
```

### Demo website timeout বা network error

- Codespaces/runner-এর internet access পরীক্ষা করুন।
- Demo URL browser-এ খুলছে কি না দেখুন।
- `timeout_ms` বাড়িয়ে আবার পরীক্ষা করুন।
- Demo website সাময়িক unavailable হলে পরে আবার চেষ্টা করুন।

### Task dashboard-এ দেখা যাচ্ছে না

- Task file `app/tasks/` directory-তে আছে কি না নিশ্চিত করুন।
- YAML-এর `name` valid ও unique কি না দেখুন।
- YAML validation error-এর জন্য application logs দেখুন।
- নতুন file যোগ করার পর dashboard refresh করুন।

## ১৩. Configuration ও Data Safety

Configuration-এর অগ্রাধিকার:

1. Environment variables
2. SQLite-এর `settings` table
3. Built-in defaults

সমর্থিত environment variables:

| Variable | কাজ |
|---|---|
| `DATABASE_PATH` | SQLite file path |
| `TASKS_DIR` | YAML task directory |
| `DATA_DIR` | CSV/TXT upload directory |
| `SCREENSHOTS_DIR` | Screenshot ও trace directory |
| `SESSIONS_DIR` | Browser session directory |
| `AUTOMATION_HEADLESS` | Headless mode |
| `AUTOMATION_TIMEOUT_MS` | Default action timeout |
| `AUTOMATION_DELAY_MIN_MS` | Default minimum delay |
| `AUTOMATION_DELAY_MAX_MS` | Default maximum delay |
| `AUTOMATION_RETRY` | Default retry count |

`.gitignore` database, uploaded data, screenshots, sessions, Python cache ও virtual environment-কে Git থেকে বাদ দেয়। গুরুত্বপূর্ণ runtime data আলাদাভাবে backup রাখুন। Codespace delete করলে তার local runtime data হারিয়ে যেতে পারে; Codespaces-কে permanent hosting বা backup service হিসেবে ধরবেন না।

## ১৪. নতুন Step Action যোগ করার নিয়ম

নতুন action যোগ করতে `app/runner.py`-এ:

1. `ALLOWED_ACTIONS` set-এ action name যোগ করুন।
2. `load_task()`-এর validation logic-এ required fields ও field types যাচাই করুন।
3. `execute_step()`-এ action-এর Playwright implementation লিখুন।
4. প্রয়োজনীয় unit/smoke test `tests/test_runner.py`-এ যোগ করুন।
5. এই README-এর Supported Step Actions table update করুন।

Validation ও execution—দুই জায়গাতেই action যোগ করতে হবে। শুধু `ALLOWED_ACTIONS`-এ নাম যোগ করলে action কাজ করবে না।

## ১৫. Suggested Screenshots for Documentation

পরবর্তীতে README-তে নিচের screenshots যোগ করলে নতুন ব্যবহারকারীরা দ্রুত বুঝতে পারবেন:

1. Codespaces তৈরি করার সময় Code → Codespaces menu
2. Codespaces Terminal-এ dependency installation complete
3. AURO Dashboard-এর task list
4. Task detail page-এর YAML editor
5. CSV/TXT upload section
6. Live run status, logs ও screenshot gallery
7. GitHub Actions-এর সফল CI run ও artifact list

Screenshots-এ cookies, email address, passwords, session tokens বা ব্যক্তিগত তথ্য যেন না থাকে।

---

**AURO development note:** GitHub Actions-এর CI workflow test ও Docker image build যাচাই করে; এটি নিজে থেকে AURO-কে public hosting-এ deploy করে না। Dashboard চালু রাখতে Codespaces session চালু রাখতে হবে, অথবা নিজের Docker host/server-এ container চালাতে হবে।
