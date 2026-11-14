# Horizon Requirements Explorer

A **read-only** Python 3.12 tool for turning a manually shared, already authenticated
Horizon browser session into structured UI evidence and a Markdown requirements report.
It is designed for `discoverhorizon.com`, including the Schedule Day View:

`https://www.discoverhorizon.com/authenticated/schedule/ScheduleDayViewX.aspx`

## Safety model

- It never collects, asks for, writes, or persists usernames, passwords, cookies, tokens,
  or browser profiles.
- It does **not** log in or automate MFA.
- It only attaches to a browser the user has already authenticated and explicitly exposed.
- It inventories page structure (tabs, links, fields, controls, headings, and forms) and
  follows only same-origin links that do not look risky.
- It never clicks buttons or submits forms. It does not create, edit, delete, approve,
  schedule, export, print, upload, download, or send data.
- Risky controls and links are recorded as blocked; navigation to a risky URL needs an
  explicit `--confirm-risky-url` exact-URL confirmation. This still does not authorize
  submitting or clicking a risky action.
- Evidence is stored locally in the output directory. Review it before sharing because
  UI labels can contain sensitive operational or personal data.

## Share an authenticated session

1. Open Chrome or Edge with a **separate, disposable browser profile** that you control.
   Sign in to Horizon yourself. Do not provide credentials to this tool.
2. Close that browser and launch it with local remote debugging enabled (replace the path
   with a new empty folder; never use your normal profile):

   ```powershell
   & "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" `
     --remote-debugging-port=9222 `
     --user-data-dir="$env:TEMP\horizon-readonly-profile"
   ```

   Then sign in manually in that window and open the target schedule page.
3. Keep that browser running. Remote debugging grants local control of the browser, so bind
   it only to localhost and do not expose port 9222 to a network.

> If you are using the integrated browser instead, share the already authenticated tab with
> the agent. The CLI connection method below is for your locally launched browser.

## Install and run

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
playwright install chromium

horizon-explorer `
  --cdp-url http://127.0.0.1:9222 `
  --start-url https://www.discoverhorizon.com/authenticated/schedule/ScheduleDayViewX.aspx `
  --output-dir .\evidence `
  --max-pages 30 `
  --max-depth 2
```

The command writes:

- `evidence.json` — schema-versioned page inventory and visited-page log.
- `requirements.md` — a reviewable report generated only from that evidence.

The default crawl is deliberately bounded. Re-run with a different safe start page to
cover other application modules. Do not increase scope until you have reviewed the prior
evidence.

### Explicit risky URL review

The explorer blocks URLs whose path/query appears to imply a state-changing action. If a
user has reviewed a **specific** URL and wants its structure inspected, pass that exact
URL (repeat the flag as needed):

```powershell
horizon-explorer ... --confirm-risky-url "https://www.discoverhorizon.com/authenticated/example/View.aspx"
```

This confirmation permits only navigation and inspection. Buttons and forms remain
non-interactive.

## Test

```powershell
python -m pytest
```

