# Votix — Bureau Edition

> Forked from [ClubNix/Votix](https://github.com/ClubNix/Votix).

A secure, self-hosted electronic voting application built with Flask, extended to support **multi-role bureau elections**. Instead of a single pool of candidates, you declare the positions that make up your association's bureau (président, vice-président, trésorier, secrétaire, …), assign candidates to those positions, and voters cast one vote per position in a single ballot.

Ballots are encrypted with an RSA public key at the moment of the vote. The private key never stays on the server after the ARM phase — results can only be revealed by the administrator who holds the key offline.

## Features

- **Multi-role bureau elections** — declare positions (roles), assign candidates to each, and voters vote for every position in one go
- **RSA-encrypted ballots** — each ballot encodes all role choices and is encrypted with a 2 048-bit public key; the private key is downloaded and deleted from the server immediately after generation
- **Unique voting links** — each voter receives a personal UUID-based URL and a 4-digit secret code
- **Time-gated voting window** — configurable start/end timestamps enforced on every vote request
- **Email workflows** — send invitations, voting links, and reminders in bulk via SMTP (background threads, rate-limited)
- **Email domain whitelist** — restrict voter registration to specific organisational domains
- **Configurable association name** — displayed in all outgoing emails; set from the admin UI without restarting
- **Candidate management** — add, edit, and delete candidates with role assignment and optional logo upload (auto-converted to WebP)
- **CSV voter import** — bulk-import voters from a spreadsheet
- **Role-based access** — `admin` and `technician` system roles with separate permission levels
- **Deliberation UI** — upload the encrypted private key at deliberation time to decrypt and tally votes per bureau position
- **CLI tools** — batch email sending, voter import, user creation, and reset from the command line
- **Docker-ready** — single `compose.yml` for production deployment with Gunicorn

## Security model

```text
ARM phase        Generate RSA key pair.
                 Public key stays on the server.
                 Encrypted private key is downloaded → stored offline by the admin.
                 Private key file is deleted from the server.

Vote phase       Each ballot encodes the voter's full set of choices
                 (one candidate per bureau position) as:
                   "role_id:candidate_id,role_id:candidate_id,…/voter_uuid"
                 The string is encrypted with the public key before storage.
                 The server never sees plaintext votes.

Deliberation     Admin uploads the encrypted private key + passphrase.
                 Ballots are decrypted in memory, parsed, and tallied per position.
                 The uploaded key file is deleted immediately after.
                 The server never persists the private key.
```

## Requirements

- Docker and Docker Compose, **or**
- Python 3.10+ with `pip`

## Quick start with Docker Compose

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd votix-role

# 2. Configure the environment
cp app/.env.example app/.env
$EDITOR app/.env   # fill in at minimum SECRET_KEY, ASSOCIATION_NAME, and SMTP_* values

# 3. Start the stack
docker compose up -d

# 4. Create the first admin user
docker compose exec votix python cli.py create_user --role admin
```

The application is now reachable at `http://localhost:5000`.

## Running locally (without Docker)

```bash
pip install -r app/requirements.txt
cp app/.env.example app/.env
# Edit app/.env, then:
python cli.py create_user --role admin
gunicorn -w 4 -b 0.0.0.0:5000 start:app
```

## Configuration

All runtime settings live in `app/.env`. Copy `app/.env.example` as a starting point.

| Variable | Description | Example |
| --- | --- | --- |
| `SECRET_KEY` | Flask session secret — change this | `a-long-random-string` |
| `ASSOCIATION_NAME` | Name shown in all voter emails | `ESIEESPACE` |
| `VOTING_URL` | Public base URL used in voting-link emails | `https://votix.example.com/vote` |
| `VOTING_START` | Unix timestamp for when voting opens | `1779400801` |
| `VOTING_END` | Unix timestamp for when voting closes | `1779458400` |
| `VALID_EMAIL_DOMAINS` | Comma-separated list of allowed voter email domains | `esiee.fr,edu.esiee.fr` |
| `PROMOTION_LIST` | Comma-separated list of promotion/class labels | `E1,E2,E3,E4,E5` |
| `SMTP_SERVER` | SMTP hostname | `ssl0.ovh.net` |
| `SMTP_PORT` | SMTP port (SSL) | `465` |
| `SMTP_USERNAME` | SMTP login | `no-reply@example.com` |
| `SMTP_PASSWORD` | SMTP password | `changeme` |
| `SMTP_FROM` | Sender address | `no-reply@example.com` |
| `SMTP_REPLY_TO` | Reply-to address | `admin@example.com` |
| `SMTP_VERIFY_SSL` | Verify SSL certificate (`True`/`False`) | `True` |

All of these (except `SECRET_KEY` and `PROMOTION_LIST`) can also be updated at runtime from the `/configure` admin page without restarting the application.

## Voting workflow

### 1. Setup

1. Log in as **admin** and open `/configure → Association` to set your association name.
2. Go to `/configure → Période de vote` to set the voting window, SMTP settings, and public voting URL.
3. Declare bureau positions at `/roles` (technician or admin) — e.g. Président, Trésorier, Secrétaire. Set the display order to control the order voters see them.
4. Register candidates at `/register-candidate`, assigning each to their position.
5. Import voters via CSV at `/import-voters`, or register them individually at `/register-voter`.

CSV format (with header row):

```csv
last_name,first_name,email,promotion
Dupont,Alice,alice.dupont@esiee.fr,E3
```

### 2. ARM the election

Go to `/arm` (admin only) and click **Arm**. The application will:

- Generate a 2 048-bit RSA key pair.
- Display a one-time passphrase — **save it**.
- Let you download the encrypted private key — **store it offline**.
- Delete the private key from the server.

> Once armed, the public key is stored on the server and voting can begin.

### 3. Send emails

From `/configure → Envoi des emails` (or the CLI) you can send:

- **Invitations** — notify voters that an election is coming.
- **Voting links** — send each voter their personal link + 4-digit secret code.
- **Reminders** — nudge voters who have not voted yet.

### 4. Voting

Voters receive a link like `https://votix.example.com/vote/<uuid>`. On the voting page they see one section per bureau position, each listing the candidates for that position. They choose one candidate per position, enter their 4-digit secret code, and submit. The full ballot is encrypted in a single RSA operation and stored. A voter can only vote once.

### 5. Deliberation

After voting closes, go to `/deliberate` (admin only):

1. Upload the encrypted private key file saved during the ARM phase.
2. Enter the passphrase.
3. All ballots are decrypted in memory and results are displayed per bureau position, ranked by votes. The uploaded key file is deleted immediately.

## Bureau positions (roles)

Manage positions at `/roles`. Each position has:

| Field | Description |
| --- | --- |
| **Name** | Label shown to voters (e.g. `Président`) |
| **Display order** | Integer that controls the order positions appear on the ballot — lower numbers appear first |

A position only appears on the voting page if it has at least one candidate assigned to it.

## CLI reference

```bash
# Inside Docker
docker compose exec votix python cli.py <command>

# Locally
python cli.py <command>
```

| Command | Description |
| --- | --- |
| `create_user --role admin\|technician` | Interactively create a system user |
| `import_voters --file voters.csv [--send-link]` | Import voters from CSV, optionally send voting links immediately |
| `validate_csv --file voters.csv` | Validate a CSV file before import |
| `send_invitations` | Send invitation emails to voters who haven't received one |
| `send_links` | Send voting-link emails to voters who haven't received one |
| `send_reminders` | Send reminder emails to voters who haven't voted yet |
| `send_admin_test` | Send a test email to the admin to verify SMTP configuration |
| `reset` | Wipe voters, candidates, roles, and RSA keys (confirmation required) |

## System roles

| Role | Capabilities |
| --- | --- |
| `admin` | Everything: configure, arm, deliberate, manage users, reset, send bulk emails |
| `technician` | Manage bureau positions, candidates, and voters; view dashboard; send individual voting links |

## Data persistence (Docker)

The `compose.yml` mounts two host directories:

```text
./data          →  /app/app/var             (SQLite database, RSA public key)
./logs          →  /app/app/logs            (log files)
./data/uploads  →  /app/app/static/uploads  (candidate logos, temporary files)
```

Back up `./data/db.sqlite` regularly. The private key is never stored here — it lives only on the admin's machine.

## Logs

| File | Contents |
| --- | --- |
| `app.log` | General application events |
| `admin.log` | Admin and configuration actions (ARM, deliberation, user management) |
| `votix.log` | Voter, candidate, and role operations |
| `email.log` | Email delivery events |
| `database.log` | Database operations |
