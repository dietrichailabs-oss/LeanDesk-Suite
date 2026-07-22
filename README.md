# LeanDesk Suite 0.7.0

LeanDesk Suite is a local-first Windows desktop office suite from Dietrich AI Labs. It includes Writer, Sheets, Slides, Notes, Draw, Tasks, Calendar, and Contacts.

## Install or run

- **Installer package:** extract the installer ZIP, run `LeanDesk_Suite_Setup_0.7.0.exe`, and follow the setup wizard.
- **Portable package:** extract the portable ZIP completely, then run `LeanDesk_Suite\LeanDesk_Suite.exe`.

Do not run the application directly from inside a ZIP archive.

## Local data and privacy

LeanDesk stores settings, recent-file history, organizer data, recovery copies, backups, templates, imported slide assets, preserved damaged-data copies, and short-lived print-temporary files locally under `%LOCALAPPDATA%\Dietrich AI Labs\LeanDesk Suite`. Print-temporary files use unpredictable names, are scheduled for delayed deletion, and stale leftovers are removed on a later startup.

LeanDesk does not require an online account or cloud service for normal operation.

## Reporting a problem safely

Provide the version/build and the smallest reproducible steps. Before sharing a screenshot or file, remove personal information, credentials, customer data, and confidential content. Do not submit an original document; use a minimal redacted example only when it is necessary to reproduce the issue.

## Unsigned Windows release

This release is intentionally unsigned because no publicly trusted Authenticode certificate was supplied. Windows may show an Unknown Publisher or SmartScreen warning. Verify downloaded artifacts using the published SHA-256 values before execution.

## Included documentation

Each public distribution exposes `SOURCE_TREE_ID.txt` beside this README, together with `LICENSE.txt`, `EULA.txt`, `THIRD_PARTY_NOTICES.txt`, `SIGNING_POLICY.md`, and `CHANGELOG.md`. Source, current QA evidence, historical evidence, and internal build records are maintained as separate packages.
