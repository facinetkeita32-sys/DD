# Offline desktop terminals — first release

## Scope and recovery point

The existing Flask/SQLite desktop application now has an **opt-in offline mode**.
Each Windows POS has a separate local database and pairs with the Hostinger server
over HTTPS. The central web POS keeps its existing checkout and authentication.

Recovery point before this work: Git commit `9a785c7`. Before enabling server
synchronization, download a version 3 backup and retain the current VPS service
configuration. Enabling creates five additive `_offline_*` metadata tables; no
business tables or columns are deleted, replaced, or migrated. Older application
backups retain their existing registered-table schema and remain restorable.
Rolling code back does not require deleting the new metadata tables.

Supported on terminals: fully paid **cash sales**, local HTML/PDF receipts,
cashier sessions, existing customer selection, local reporting, English/French,
automatic retry and manual synchronization. Admins and managers can create/edit
products and categories offline, including images, prices, costs and stock
adjustments. Admins can also change company details/logo, POS settings and delivery
zones offline. Each operation uses the existing role permission, checked locally
and again against the current server role when uploaded. Managers retain their
existing product-management permissions; admin-only settings stay admin-only.

The original role-based screens are visible, including Settings for admins and
Products for managers. The local Users screen is a read-only list of users verified
on that terminal. Account/password/role administration, server backup/restore,
electronic payments, credit, cancellations, deletion, bulk import, customer editing
and purchasing use the central application. Their controls are hidden or explicitly
disabled with explanatory notices, rather than pretending an unsupported write
was saved. Server role definitions and normal online APIs are unchanged.

Only an unambiguous single company/currency installation is supported. There is
no authorized user/store membership in the current schema; multi-company pairing
fails closed. Devices cannot pick an arbitrary company or cashier during upload.

## Enable the Hostinger server (after tests and deployment approval)

1. Save a backup and deploy the matching application version.
2. Add a systemd drop-in for `shopdd.service`:

   ```ini
   [Service]
   Environment="OFFLINE_SYNC_ENABLED=1"
   ```

3. Keep Gunicorn at **one worker, four threads**. Run `systemctl daemon-reload`
   and restart `shopdd.service`. No separate synchronization process is needed.
4. Use the existing public **HTTPS** POS origin when registering terminals, e.g.
   `https://pos.example.com`, without `/api` or another path. HTTPS redirects are
   deliberately not followed when sending credentials.
5. Administrators can see/revoke registered terminals in Settings. Managers can
   register terminals and manage their own registrations through the API.

Nothing is enabled by default on the server, and these changes do not deploy
themselves to Hostinger. Do not set `POS_OFFLINE_MODE=1` on the VPS.

## Install and pair a Windows terminal

Use the same application release as the server. With Python installed, run
`python desktop_app.py`; the existing desktop build entry point can also be used.
The native window uses optional pywebview; otherwise the launcher opens the
default browser and keeps the local backend running. No new runtime dependency
is required beyond the existing Flask stack.

The launcher:

- Binds the application to `127.0.0.1` on a free port, never the LAN.
- Forces local SQLite instead of an inherited PostgreSQL URL.
- Uses `%LOCALAPPDATA%\ShopWithDD\OfflinePOS\terminal.db` (or the equivalent user
  application-data folder on other systems).
- Keeps a private persistent session key and a single-instance file lock.
- Leaves existing portable `pos_data.db` files and the installed server DB alone.
- Refuses to enroll over a pre-existing unpaired business database; it never
  fills the offline database with demo records or default admin credentials.

For development only, `POS_OFFLINE_DATA_DIR` selects a separate terminal folder.
Never point it at the existing business data folder or copy it between terminals.
The database contains business records and device credentials; keep the Windows
user account/application-data folder private and include it in protected local
backups. Credentials are not hardware-bound or encrypted at rest by this release.

On the first screen, enter the server URL, a terminal name, and an existing
admin/manager account. Initial registration requires internet. After the catalogue
download completes, sign in normally. Every additional cashier must complete one
online login on that terminal before they can sign in offline there.

## Authentication

- Registration issues a random revocable device credential. Its server copy is
  hashed. Only a registered device can download its catalogue and submit events.
- Online cashier authorization verifies the existing server credentials; existing
  server login behavior and passwords are unchanged.
- The desktop caches only a salted Werkzeug password verifier for users who
  actually authenticated there. It never downloads server passwords or all user
  hashes. Passwords/verifiers are omitted from terminal login responses.
- Offline login and new sales require an unexpired **seven-day** grant for that
  user/device. Online login renews the grant. A wrong password rejected online
  does not fall back to accepting an older offline password.
- Server revocations are learned on reconnection, not while disconnected.
  Expired grants require online sign-in. Clock rollback beyond the last known
  server time blocks new offline activity; the PC clock must be kept correct.
- Uploads retain the original sale's grant. Sales created within its validity
  can arrive after it expires; user/device revocation still requires a manager
  to reconcile unsent events.
- Local sessions use a per-installation key/cookie name, normal inactivity and
  session-generation checks. Restart requires local sign-in, not internet.

## Durable synchronization

A local cash sale follows the existing checkout route inside an opt-in unit of
work. The order, lines, payments, stock changes, unique reference, and outbox event
commit **together**. Failure rolls them all back, including the ORM cache. Cashier
session changes use the same mechanism. Normal central web requests continue to
use the existing path.

Each event has a UUID, device-bound user grant, stable content digest, and durable
sequence. The worker retries every 15 seconds, releasing the database lock during
network I/O. The server imports a sale, its lines/payments, stock changes, resource
ID mappings, and acknowledgement in one transaction. It acknowledges a retry
without applying it twice, and rejects reuse of an ID with changed contents.

Server and local numeric order/session IDs may differ; UUID mappings connect them.
New products, categories and delivery zones also receive stable UUIDs. References
in later sales/edits resolve through these mappings. Downloads retain stable local
IDs, including when another server record used the same numeric ID while the
terminal was disconnected. Historical local orders/receipts therefore keep valid
product references. Existing already-queued events remain compatible with the new
protocol, and metadata is upgraded additively. Customer records still originate
centrally. Historical sale prices/subtotals are retained, not repriced.

Catalogue edits and their outbox entries commit together. Edits send only changed
fields with their prior values: a server edit to an unrelated field is preserved;
a conflicting edit to the same field pauses the queue for review. Product quantity
edits send **stock deltas**, not replacement totals, so concurrent server sales are
not erased. Stale product forms are rejected before changing local data. Stock,
currency and settings changes do not convert or reprice existing sales.

The worker uploads in creation order, then refreshes reference tables only when
there are **no pending events**, checking again after the network response. This
prevents a downloaded stock total from erasing an unsynchronized local deduction.
No historical central orders, other users' sales, backup API keys, or passwords
are downloaded. Purchase costs are only included when a valid additional
admin/manager grant authorizes product management. Local cashier product responses
exclude purchase costs. When no verified cost has been downloaded, the product
form disables that field instead of overwriting an unknown cost with zero.
Local BI does not display a cost-based inventory valuation.

The terminal status button shows connectivity, pending operations, and conflicts.
The count includes cashier session events as well as sales. It offers a manual
retry. Temporary network failures never remove queue entries. The local dashboard
reports this terminal's records; the central dashboard consolidates synced sales.
Counts also include queued product/settings changes.

## Offline receipts and printing

Printing loads the receipt from the terminal's authenticated local backend into
a sandboxed in-app preview. It does not open an external browser with a different
cookie jar. Choose **Print** in the preview to open the Windows/WebView2 print UI,
or **Download PDF** to open the native Save As dialog. Desktop downloads are enabled
explicitly. HTML and PDF receipts work without contacting the central server and
honor the selected English/French language. Receipt text is HTML-escaped before
embedding, and print failures do not recreate or modify a saved sale.

Windows must have a working printer/driver. An internet outage does not prevent a
USB printer from working; a Wi-Fi/Ethernet printer still requires its local network
connection. Choose the receipt printer and its supported paper width in the print
dialog. Opening the dialog confirms the software path, not physical paper output.

Updating the desktop requires closing the application and replacing the executable.
Its data stays in the same application-data folder; pairing and pending operations
remain available after signing in again. Updating Hostinger alone does not replace
the executable/assets already installed on a desktop.

## Stock conflicts and server recovery

Offline stock cannot be reserved across disconnected terminals. If a sale cannot
be imported because a product/customer was removed, stock is insufficient, a grant
was revoked, or the protocol differs, the sale remains locally saved and pending.
Do not re-enter that sale on the server: a successful retry would duplicate it.
Resolve ordinary stock/reference conflicts on the server and retry the same event.
Later events wait behind the conflict so a session cannot close before its sales.
For catalogue conflicts, the status dialog provides a role-authorized review UI:
keep the server values for an edit, or explicitly queue local values against the
latest reported base. Barcode/name collisions require a unique replacement; a
new product cannot simply be discarded if pending sales could depend on it.
Review creates a new event ID at the same queue position and retains the original
as superseded history. The server rechecks both the role and comparison base.

A successful central restore rotates a persistent database epoch within the restore
transaction. Paired terminals detect the change and block synchronization/new
activity rather than blindly replaying orders against the restored database.
Server metadata is intentionally outside JSON business backups: device credentials,
outbox state and idempotency records must not be blindly copied/restored between
installations. Full server filesystem/DB backups should retain these tables too.

**Automatic reconciliation after a restore/revocation is not included in this
release.** The catalogue review UI does not bypass identity/grant revocations.
Keep the terminal database and its
private metadata, compare the server's acknowledged UUIDs with local pending
references, and have a manager reconcile before resetting/re-pairing. Never delete
the database, stash/replace it with a server JSON backup, or clear outbox tables to
make a warning disappear. Restore/revocation blocks are intentionally not bypassed
by the ordinary retry button.

## Verification

`python -m unittest discover -s tests -v` runs existing regression tests plus real
HTTP tests with independent temporary server and terminal databases. The offline
tests cover first pairing/login, hashed local passwords, seven-day expiry, restart
while disconnected, atomic rollback, cash-only restrictions, lost acknowledgements,
exactly-once retry, stock conflicts, revocation, and restored-server epoch changes.
They also cover admin/manager offline edits, cashier restrictions, server-side
permission tampering, stock deltas during concurrent central sales, field-level
conflicts/review, barcode collisions, settings and delivery-zone changes, and
stable product/category IDs across numeric collisions and terminal restarts.
Receipt checks cover authenticated local HTML/PDF access without a server
connection, explicit language selection, read-only behavior and safe HTML text.
Browser checks exercise the in-app preview, print action and PDF download without
opening a new browser session. Native Windows checks visually confirm the embedded
print preview and detect/cancel the Save As dialog; no paper job is submitted.
Neither installed POS data nor the Hostinger database is used by these tests.
Launcher regression checks also verify duplicate-instance rejection, release of
the OS lock on exit, and preservation of the private session key after restarting.

The native Windows launcher has additionally been piloted with permanent storage:
registering against an isolated local server, signing in while that server was
stopped, saving a cash sale, closing/reopening the actual window, recovering its
cashier session and pending events, and uploading once after reconnection. A
desktop paired with a test server remains a **test terminal**. For production,
close it after the queue is empty, preserve/archive its test folder, and use a fresh
terminal folder for Hostinger registration; do not overwrite or re-pair its DB.

Local test servers can explicitly set `OFFLINE_ALLOW_HTTP=1` to permit loopback
HTTP origins only. Never use this development switch as an HTTPS replacement for
the live VPS. The browser setup and actual desktop executable should be piloted on
one Windows terminal before broad deployment. PostgreSQL support uses the existing
adapter but has not been exercised by the SQLite integration suite.
