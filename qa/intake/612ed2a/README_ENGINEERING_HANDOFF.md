# LeanDesk Suite 0.9.0 - Engineering to Independent QA

Candidate: 612ed2a4829ee43f4513647c6fdd922d466f3a32
Status: ENGINEERING CANDIDATE / INDEPENDENT QA PENDING / NOT RELEASE APPROVED.

Start with CURRENT_DISPOSITION.json and CURRENT_REQUIREMENTS_MATRIX.json. Signed_Binaries contains the exact signed EXE, installer and PUBLIC certificate. Packages contains the unchanged Portable, Installer and Complete ZIPs. Source contains the exact frozen source archive.

The correction changes only Writer style-tile semantic contrast and its regression, plus generated identity files. The full source gate recorded 808 passed and 9 expected LibreOffice skips. The ten-theme affected GUI, normal close/reopen, signature verification, archive integrity and installed-candidate smoke records are included. The frozen branch is codex/qa-frozen-0.9.0-612ed2a.

Historical/Superseded preserves the unchanged prior consolidated master. Historical/Continuation retains older and parent-candidate reports, screenshots and fixtures, including failures. Evidence/Current holds the new candidate's raw and supplemental reports. Preliminary records with pending statuses are intentionally preserved; CURRENT_DISPOSITION.json is the current reconciliation, not a rewrite of raw history.

QA issue #7 comment 5785311739 scopes product corrections to affected tests plus source/build identity gates. The unchanged-layout, Sheets, updater, dispatch, printing and Office behavior evidence retains its original candidate identity; no complete fresh lifecycle on 612ed2a is claimed. Exact 1365x768 desktop coverage is ENVIRONMENT_LIMITATION_ACCEPTED, not PASS. Review the limitations in CURRENT_DISPOSITION.json, including unavailable numeric exit codes for the interactive installer smoke and the saved blank-document recovery prompt.

Both new binaries passed Authenticode and SignTool verification under CN=Dietrich AI Labs in the normal-user QA VM. The certificate is self-signed; public trust is not claimed. No private keys, PFX/P12 files, signing passwords or transient transport configurations are included. The host's earlier untrusted-root result is retained, and the VM verification resolves it only for the configured QA trust context.

The failed installed-report upload happened after the installed EXE identity/close checks. Its error record remains alongside the successful transport receipt and firewall-cleanup result. No runtime test was repeated to repair transport.

SHA256SUMS.txt and EVIDENCE_MANIFEST.json identify every payload member. The master ZIP's own size/SHA and post-write CRC/member verification appear in the external MASTER_RECEIPT.json to avoid self-reference. This handoff does not publish anything. Keep release draft, issue open, main and public 0.8.1/site/updater unchanged pending Independent QA.
