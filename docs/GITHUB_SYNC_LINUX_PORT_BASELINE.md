# LeanDesk Suite 0.8.0 — Linux Port GitHub Sync Anchor

This branch records the accepted Windows source baseline and Linux-port requirements while the active Linux implementation proceeds separately.

## Authoritative Windows starting point

- Product: LeanDesk Suite 0.8.0
- Accepted Windows source lineage: C6
- Accepted C6 source-tree ID: `1A373230C55849A405B715C663FD7665C72B3B2DD3CCD365F913A9E55041E77E`
- Windows release artifacts/lineage are frozen and must not be rewritten by Linux work.

## Linux-port branch rule

Linux work must be developed as a new platform line from the accepted Windows source, keeping Windows behavior intact and isolating platform-specific behavior behind adapters/helpers where practical.

The Linux port is being developed in ChatGPT proper rather than by Codex for this cycle. Independent QA remains separate from Engineering review.

## Required Linux compatibility

Lubuntu compatibility is a hard acceptance requirement.

Broad support should cover mainstream modern desktop Linux, including the major Debian/Ubuntu, Fedora/RHEL, Arch/Manjaro and openSUSE families where practical.

The project must not claim literal compatibility with every Linux distribution/kernel/libc/architecture without evidence.

## Required delivery lanes

The Linux engineering order calls for practical cross-distro delivery, including:

- AppImage
- Flatpak
- Debian package
- RPM package/spec outputs as appropriate
- generic portable tarball

Normal application operation should not require root.

## Platform requirements

Linux work must address at least:

- XDG data/config/cache paths
- safe file/browser opening without shell interpolation
- desktop launchers/icons/MIME integration
- printing via normal Linux/CUPS facilities
- Linux-compatible image/icon handling
- updater behavior without telemetry or silent executable replacement
- clean uninstall behavior
- GNOME/KDE behavior and consideration for Xfce/LXQt/Lubuntu

## Source-control / evidence rule

Git is for source, tests, build scripts and documentation.

Do not commit generated release packages, giant QA handoffs, screenshots, VM images, build caches, or superseded evidence archives into ordinary history.

Immutable QA/release artifacts remain preserved separately by exact filename, bytes and SHA-256.

## Current status

Linux port: **IN DEVELOPMENT — NOT QA-APPROVED / NOT PUBLISHED**

Final Linux routing remains:

`Engineering -> Independent QA`

No Linux release/publication claim is authorized until the exact immutable Linux candidate passes Independent QA.
