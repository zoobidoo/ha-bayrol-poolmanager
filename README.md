# PoolManager for Home Assistant (unofficial Bayrol integration)

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/zoobidoo/ha-bayrol-poolmanager/actions/workflows/validate.yml/badge.svg)](https://github.com/zoobidoo/ha-bayrol-poolmanager/actions/workflows/validate.yml)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-support-FFDD00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/zoobidoo)
[![Tests](https://github.com/zoobidoo/ha-bayrol-poolmanager/actions/workflows/tests.yml/badge.svg)](https://github.com/zoobidoo/ha-bayrol-poolmanager/actions/workflows/tests.yml)

*[Version française](README.fr.md)*

A Home Assistant integration for the **Bayrol PoolManager 5** pool controller. It reads measurements
and the filter pump state, and lets you **change the filter pump timer and operating mode**, either
directly on your local network or through the Bayrol cloud portal (bayrol-poolaccess.de).

> [!WARNING]
> **Unofficial project, not affiliated with or endorsed by Bayrol.** "Bayrol" and "PoolManager" are
> trademarks of their respective owner and are used here only to describe compatibility.
> The PoolManager itself warns that remote access must only be used when the safety of people,
> animals and property is guaranteed at all times. Stopping the filter pump also stops circulation
> and chemical dosing. You remain fully responsible for your installation. This integration
> deliberately does **not** expose dosing, calibration or safety settings.

## Features

| Entity | Description |
|---|---|
| `sensor.*_ph`, `*_redox`, `*_water_temperature` | Measurements |
| `sensor.*_ph_setpoint`, `*_redox_setpoint` | Setpoints (read-only) |
| `sensor.*_filter_pump_status` | Running / stopped / warning / error |
| `binary_sensor.*_filter_pump` | Filter pump running |
| `binary_sensor.*_collective_alarm`, `*_no_flow_alarm` | Alarms |
| `sensor.*_ph_dosing_status`, `*_chlorine_dosing_status` | Dosing status text (e.g. "No Flow") |
| `sensor.*_scheduled_filtration_today` | Hours of filtration scheduled today (attribute `per_day`) |
| `select.*_filter_pump_mode` | Auto (timer) / forced on / off |
| `sensor.*_interval_1` … `_6` | Summary of each timer interval |
| `time.*_interval_N_start` / `_end` | Start / end time of each interval (writable) |
| `select.*_interval_N_mode` | Pump off / normal / eco / increased |
| `select.*_interval_N_days` | Every day / Mon–Fri / weekend / none |

An action, `bayrol_poolmanager.set_timer_interval`, changes one interval in a single call (any
combination of `start`, `end`, `mode` and `days`, with arbitrary days of the week).

Diagnostics can be downloaded from the device page (credentials and identifiers are redacted).

## Compatibility

Tested on a **PoolManager 5 "Chlorine (Cl)", firmware v221216-M1 (7.8.3)**. Other PoolManager 5
variants (Oxygen, Bromine, pH-only…) or firmware versions probably work for reading, but the internal
identifiers may differ. If something is missing or wrong, please open an issue and attach the
**diagnostics** file (see [Contributing](#contributing)).

Requires Home Assistant 2025.1 or newer (tested on 2026.2 and 2026.9).

## Installation

### HACS (recommended)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/zoobidoo/ha-bayrol-poolmanager`, category
   **Integration**.
2. Install **PoolManager (Bayrol, unofficial)**, then restart Home Assistant.

### Manual

Copy `custom_components/bayrol_poolmanager` into the `config/custom_components/` folder of your
Home Assistant, then restart.

## Configuration

**Settings → Devices & services → Add integration → "PoolManager (Bayrol, unofficial)"**, then
choose how to connect.

### Option A: local network (recommended)

Readings stay on your network and do not depend on the Bayrol servers.

1. **Find the PoolManager's IP address**, using either of:
   - your router's list of connected devices (look for a device named after Bayrol or PoolManager);
   - on the PoolManager touch screen: **Menu → Communication & Interfaces → Network (IP)
     Configuration**.

   Tip: give it a fixed IP (DHCP reservation) in your router.
2. Check that it answers: open `http://<IP>/cgi-bin/webgui.fcgi?xmlitem=34.4001` in a browser.
   It should return a small XML document with your pH value.
3. Enter the IP address in the integration. The *Customer access code* field is optional.

At this point the integration is **read-only**. To enable changes (timer, pump mode), open the
integration's **options** (gear icon) and fill in **one** of these:

- **Remote user + password (local writes):** an "individual user" with remote access, defined on
  the PoolManager under **Menu → User management → Individual users (menu & remote access)**. If
  changes are still refused, check the remote access rights in **User management → Enable remote
  access for add-on functions** (the filter pump is an add-on function).
- **Bayrol portal e-mail + password (cloud writes):** readings stay local, changes go through
  bayrol-poolaccess.de. Use this if you do not know the remote user's password: the portal logs in
  as that user automatically.

### Option B: Bayrol cloud portal

Enter your **bayrol-poolaccess.de** e-mail and password. Everything (reads and writes) goes through
the portal. Polling every 60 s is plenty: please do not hammer the vendor's servers.

**Device id:** leave it empty and it is detected automatically (the first device on the account).
If you have several devices, or want to set it explicitly: log in to bayrol-poolaccess.de, click
**Direct access** ("Accès direct" / "Direktzugriff") next to your device, and read the number after
`c=` in the address bar:

```
https://www.bayrol-poolaccess.de/webview/p/device.php?c=12345
                                                        ^^^^^ device id
```

The *Device data* link (`plant_settings.php?c=12345`) shows the same number.

> [!TIP]
> Browsers sometimes auto-fill the **Home Assistant** login into the e-mail/password fields of this
> form. Double-check that they contain your **Bayrol** credentials before submitting.

## Usage examples

Change interval 1 to 10:00–18:00, every day:

```yaml
action: bayrol_poolmanager.set_timer_interval
data:
  interval: 1
  start: "10:00:00"
  end: "18:00:00"
  days: [mon, tue, wed, thu, fri, sat, sun]
  mode: normal
```

The [`examples/`](examples/) folder contains:

- [`automation_filtration_temperature.yaml`](examples/automation_filtration_temperature.yaml):
  adjusts the end of interval 1 every morning, using the common rule of thumb "daily filtration hours
  ≈ water temperature (°C) / 2". This is a rule of thumb, not a Bayrol recommendation.
- [`dashboard_card.yaml`](examples/dashboard_card.yaml): a ready-to-paste dashboard card.
- [`local_xml_rest.yaml`](examples/local_xml_rest.yaml): a read-only alternative without this
  integration, based on Bayrol's documented local XML interface.

## How it works

The PoolManager 5 web interface (the same screen as **Direct access** on the portal) talks to the
device through a small JSON API:

```
POST /cgi-bin/webgui.fcgi?sid=<session id>
{"get": ["34.4001.value", "40.8533.value"], "set": {"40.8536.value": "18:00:00"}}
→ {"data": {...}, "status": {"code": 0}, "event": {...}}
```

- **Local:** `http://<IP>/cgi-bin/webgui.fcgi`. **Cloud:** the portal proxies the same API at
  `https://www.bayrol-poolaccess.de/cgi-bin/webgui.fcgi`, after a normal portal login and
  `/webview/pm5/?c=<device id>`.
- A session id is read from the page that initialises the web interface (`wui.init('<sid>')`).
- Every new session starts on a **"User Login (remote access)"** page. Until it is submitted, reads
  work but **every write is refused with status 113**. On the portal this page is pre-filled with
  the account's remote user; on the local network it is empty, hence the options above.
- Within a session, the device only returns values that **changed** since the previous request: the
  integration keeps a cache and opens a fresh session every 30 minutes.
- The integration polls every 60 s by default (configurable, minimum 30 s).

Main identifiers (PoolManager 5 Chlorine, firmware 7.8.3):

| Identifier | Meaning | Values |
|---|---|---|
| `34.4001` / `34.4022` / `34.4033` | pH / redox (mV) / temperature T1 (°C) | |
| `55.17106.status` | Filter pump LED | 0 green (running), 1 off, 2 yellow, 3 red |
| `60.5432.value` | Filter pump mode | 1 on, 2 auto, 4 off |
| `35.5184` … `35.5189` | Mode of intervals 1–6 | 1 off, 2 normal, 4 eco, 8 increased |
| `36.5203` … `36.5208` | Days of intervals 1–6 | bit mask, Monday = 1 … Sunday = 64 (127 = every day) |
| `40.8533/8534/8535/8539/8540/8541` | Start of intervals 1–6 | `HH:MM:SS` |
| `40.8536/8537/8538/8542/8543/8544` | End of intervals 1–6 | `HH:MM:SS` |
| `9.17401.user` / `9.17401.pass` | Remote access login | |

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| "The PoolManager refused the change (status 113)" | No remote user logged in. Local entry: set the remote user or the portal credentials in the options. Cloud entry: check that the portal account has remote access to the device. |
| "Cannot reach the PoolManager" while setting up the cloud option | Check the e-mail/password (browser auto-fill!) and the device id. The exact reason is in the Home Assistant log (`custom_components.bayrol_poolmanager`). |
| Values stay unavailable | Check `http://<IP>/cgi-bin/webgui.fcgi?xmlitem=34.4001` from the Home Assistant host. |
| Pump shows "stopped" during an active interval | A timer change that happens *during* an interval may only take effect at the next switch-on time. |

Enable debug logs:

```yaml
logger:
  logs:
    custom_components.bayrol_poolmanager: debug
```

## Contributing

Issues and pull requests are welcome, especially reports from **other PoolManager models**:

1. Device page → ⋮ → **Download diagnostics**, and attach the file to an issue.
2. To find the identifier of a value that is missing: open **Direct access** on the portal (or
   `http://<IP>/` locally), open your browser's developer tools → *Network*, navigate to the screen
   that shows the value, and look at the `get` lists sent to `webgui.fcgi`.

Development: `pip install -r requirements_test.txt && pytest`. The tests run against a fake portal
that reproduces the protocol (`tests/mock_server.py`).

This project is maintained on my spare time; response times may vary.

## Support the project

If this integration saves you a few trips to the pump room, you can say thanks:

- **GitHub Sponsors:** coming soon (the ❤️ *Sponsor* button at the top of this page lists all options)
- **Buy Me a Coffee:** [buymeacoffee.com/zoobidoo](https://buymeacoffee.com/zoobidoo)
- **Crypto (EVM: ETH, USDC… on Ethereum, Base, Arbitrum, Optimism…):**
  `0x3D7FC7EEb2375b71C3156De836A0866059C65697`

Totally optional: bug reports and pull requests are just as valuable.

## License

[MIT](LICENSE). Provided "as is", without warranty of any kind.
