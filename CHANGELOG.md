# Changelog

## 0.3.0

- **Re-authentication:** a rejected Bayrol portal password now opens a re-authentication prompt in
  Home Assistant instead of failing forever (cloud entries, and local entries that write through the
  portal).
- **Reconfigure:** change the IP address (local) or the portal credentials (cloud) without deleting
  the entry; entities and their history are kept. Adding the same device again under its new IP is
  detected.
- **Safer writes:** all values of one change (e.g. start and end of an interval) are sent in a single
  request, then read back; a value the device did not apply is reported as an error.
- **Validation:** an active interval whose start equals its end is refused (unused intervals keep
  start = end, as the device stores them). Intervals crossing midnight are allowed.
- **Action `set_timer_interval`:** registered once for the integration; new `device_id` target,
  mandatory when several PoolManagers are configured (it used to silently pick the first one).
- Selecting "Custom" days now explains how to set arbitrary days instead of doing nothing.
- Times above 24:00 from the device are rejected instead of wrapped around.
- Connection tests in the setup and options dialogs no longer leave HTTP sessions open.
- README: pump mode warning, security notes (unencrypted local HTTP, stored credentials, write test).
- CI: ruff (lint + format), coverage, actions pinned by commit, Dependabot, automatic GitHub release
  from `manifest.json` + this changelog.

## 0.2.0

- First public release.
- Local reads; writes through the device's remote user (local) or the Bayrol cloud portal.
- Remote access login handled automatically (fixes "status 113" write errors).
- Diagnostics with redacted credentials.
- English, French and German translations.
