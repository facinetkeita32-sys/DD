# Backup and restore

Use **Settings → Download Backup** to save a version 3 JSON backup. Pictures and
logos are embedded in the file; there is no separate image folder to copy.

The backup includes every registered application table and many-to-many link:
products, customers, orders, order lines, payments, sessions, users, categories,
taxes, POS configuration, companies, currencies, delivery zones, languages,
activity logs, and saved automatic-backup settings (including the backup API key).
Server environment variables and browser-only state are not database records.

To recover, select the JSON file under **Restore Backup** and confirm. Version 3
restores replace the application data, including removal of records that were
created after the backup. Validation and all database writes run in one
transaction. A failed restore leaves the database and application cache unchanged.
After success, all browsers must sign in again using credentials from the
restored backup. Sessions also require a fresh login after a server restart.

Older version 1/2 exports can still be restored. Tables included in those files
are replaced, while omitted tables are retained. The UI shows a warning because
links and records omitted by the old exporter cannot be reconstructed. Download
a new version 3 backup after deploying this update.

Automatic-backup settings persist across restarts and are included in new backups.
When enabled, the first scheduled push occurs after the configured interval.

## Deployment

The ORM stores its live cache in the web process. The supplied Gunicorn commands
use **one worker with four threads**, with API access and backups coordinated by
a shared lock. Keep the app on one process/instance so every request observes the
same restored cache. Restart/redeploy the service to apply updated startup commands.
Remote backup uploads release the database lock after taking their snapshot, so
waiting for the backup server does not block sales or other API requests.

The database adapter supports SQLite and PostgreSQL. Backup rows preserve IDs,
stored image text, timestamps, and relationships; restore uses backend-specific
parameter placeholders and explicit transactions.

## Verification

Run `python -m unittest discover -s tests -v`. The integration suite creates an
isolated temporary SQLite database and checks full JSON round trips, image data,
relationships, transactions/rollback, cache reloads, legacy files, HTTP download
and restore, sign-out, and persisted automatic-backup settings.
