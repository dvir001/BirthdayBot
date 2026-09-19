# Security Policy

Use the latest release and review Dependabot updates before deployment.

Report vulnerabilities through this repository's GitHub Security Advisories
private reporting feature when enabled. Do not put tokens, database passwords,
or member data in public issues. If private reporting is unavailable, ask the
maintainer for a private contact channel without disclosing the vulnerability.

Rotate exposed Discord tokens immediately in the Discord Developer Portal.
Rotate database credentials separately. Removing a secret from the latest commit
does not remove it from Git history or invalidate it.

Birthdays, timezones, Discord IDs, and uploaded media are personal data. Restrict
database and backup access, define a backup retention policy, and do not expose
PostgreSQL to the public internet. User deletion affects the live database;
operators must separately manage backups. Upload validation is not antivirus
scanning. Keep Discord and database credentials out of screenshots and logs.