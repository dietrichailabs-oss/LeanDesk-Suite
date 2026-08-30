# Changelog

## 0.8.0 Reconstructed Correction 5 — QA Resubmission

- Bound backup restore verification, extraction, manifest use, and reported SHA-256 to one private immutable source snapshot rather than repeatedly reopening a replaceable pathname
- Closed the final backup-creation hash/replace race by binding candidate, rollback, and committed-destination identities and hashes across every commit and recovery boundary
- Added semantic OOXML content-type classification so XML and relationship parts receive protected parsing even when stored as `.dat`, extensionless, mixed-case, or default-mapped members
- Corrected raw CP932 DBCS trail bytes that equal RTF syntax (`0x5C`, `0x7B`, and `0x7D`) without weakening real control words, groups, depth limits, or malformed-input rejection
- Applied raw parent-chain symlink/reparse/mount and identity-race containment to backup source roots during enumeration and file reads
- Added a mandatory 67-test Correction 5 suite and raised the complete canonical gate from 280 to 347 tests; 347/347 Pytest, 67/67 focused Correction 5, and 35/35 legacy unittest-discovery tests pass in Engineering

## 0.8.0 Reconstructed Correction 4 — QA Resubmission

- Reworked RTF ANSI decoding into a stateful multibyte byte stream with CP932, CP936, CP949, and CP65001 raw/hex fixtures, controlled malformed-sequence handling, Writer round trips, and LibreOffice readback
- Replaced fixed-prefix OOXML DTD/entity scanning with parser-level declaration rejection that covers late prologs, UTF-16, mixed-case XML parts, internal entities, depth/node limits, cancellation, and deadlines before third-party parser invocation
- Made backup creation destination-transactional: same-directory temporary output is flushed, fully verified, identity/hash checked, and only then atomically replaces the selected destination
- Added a final verified-temporary replacement-race check while preserving the old destination under every injected pre-commit failure
- Rejected raw symlink, linked-parent, mount, simulated Windows reparse, and parent/target replacement restore paths before rename boundaries
- Added an exact source-stage cleanliness gate, disabled test cache/bytecode creation, moved the Windows build environment outside the source tree, and required the Correction 4 suite explicitly
- Expanded the canonical recursive gate from 220 to 280 tests; 280/280 Pytest, 60/60 focused Correction 4, and 35/35 legacy unittest-discovery tests pass in Engineering

## 0.8.0 Reconstructed Correction 3 — QA Resubmission

- Defined the backup-restore commit point at the validated staging-to-live rename and made every pre-commit failure restore or retain the previous profile
- Converted post-commit durability/cleanup faults into truthful successful-restore warnings; the only rollback copy is never deleted by a failure path
- Added conservative restart recovery for abandoned target-specific staging and rollback directories
- Replaced inconsistent case-folded prerelease ordering with one antisymmetric, transitive, equality-consistent comparator and rejected leading-zero numeric prerelease identifiers
- Added one shared immutable-byte OOXML preflight before python-docx, OpenPyXL, or python-pptx for DOCX, XLSX, and PPTX
- Rejected duplicate/case-colliding members, unsafe paths, links/special entries, encryption, excessive expansion, compression bombs, malformed XML/relationships, missing targets, unsafe external relationships, cancellation, and timeout conditions
- Replaced the naive RTF regex path with a bounded Unicode-aware plain-text RTF codec supporting code pages, hexadecimal escapes, `\ucN`, signed `\uN`, surrogate pairs, destination groups, and ASCII-only interoperable output
- Verified LeanDesk-generated RTF through LeanDesk and LibreOffice without metadata injection or Unicode loss
- Expanded the canonical recursive gate from 147 to 220 tests; 220/220 Pytest and 35/35 legacy unittest-discovery tests pass in the Correction 3 engineering environment

## 0.8.0 Reconstructed Correction 2 — QA Resubmission

- Enforced imported-document protection at the shared Writer, Sheets, and Slides write boundaries, including Save As, hard-link/symlink aliases, and import-only suffixes
- Converted ordinary imported-file Save into a controlled Save-a-Copy workflow with no uncaught protection exception
- Restored strict, traversal-safe, quarantining recovery coverage across Writer, Sheets, Slides, Notes, Draw, Tasks, Calendar, and Contacts
- Added duplicate-safe, schema-versioned, non-destructive loading for settings, native documents, Notes, and organizer data
- Rejected malformed native Sheets, Slides, and Draw field types instead of silently coercing and later rewriting them
- Integrated a privacy-conscious weekly update check using only `https://www.dietrichailabs.com/updates/leandesk.json`
- Added Settings and Help update controls, semantic/prerelease version comparison, final-URL validation, short timeouts, offline isolation, session-level notification suppression, and no download/install path
- Added a real verified profile backup and staged transactional restore workflow with bounded streaming validation
- Bounded spreadsheet formulas, exposed a truthful 200-row by 52-column grid, internalized slide images, and guaranteed compatibility-conversion cleanup
- Corrected the actual converted DOC/ODT in-memory Writer load path and verified six legacy/OpenDocument files through the running GUI
- Replaced incomplete test entry points with one canonical recursive gate; 147 tests are now collected in the Correction 2 engineering environment
- Exact-pinned direct build/test dependencies and corrected Windows file-version metadata

## 0.8.0 — All-Modules Functional Preview

- Cleaned the Writer ribbon and removed clipped placeholder descriptions
- Added offline spell checking with a bundled 100,000+ word English dictionary
- Added live underlining, suggestions, next-error navigation, and personal words
- Completed functional Insert, Layout, Review, View, and Help ribbon tabs
- Added Sheets with formulas, multiple worksheets, CSV, and XLSX
- Added Slides with themes, notes, presenter mode, images, and PPTX
- Added Notes with Markdown preview, notebooks, tags, pinning, and search
- Added Draw with shapes, movement, SVG, and PNG export
- Added local Tasks, Calendar, and Contacts modules
- Added optional associations for `.ldoc`, `.lsheet`, `.ldeck`, and `.ldraw`
- Updated packaging dependencies, documentation, tests, and artwork labels

## 0.2.0 — Writer Ribbon Redesign

- Replaced the flat Writer toolbar with an original grouped ribbon
- Moved file operations under File
- Added line and paragraph spacing controls

## 0.1.0 — Suite Foundation

- Added the shared suite shell, Writer foundation, recent files, settings, and recovery
