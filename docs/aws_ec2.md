# Deploying bank-python to AWS the cheap way — one EC2 box (no EKS)

This is the **free-tier-friendly** alternative to `docs/aws.md` (which uses EKS). It matches
the roadmap's Phase 5 wording — **"AWS EC2 + S3"** — and drops the three things that cost
money on EKS: the **EKS control plane**, the **load balancer**, and **RDS**.

Same end result: a **public URL serving the FastAPI app** (`/health`, `/transactions`,
`/ask`), backed by Postgres, with **Snowflake** wired in for analytics reads. The whole
stack runs as Docker containers on **one small EC2 virtual machine**, using the
`Dockerfile` and `docker-compose.yml` you already have.

## The mindset shift from EKS

| EKS (docs/aws.md) | EC2 (here) |
|-------------------|------------|
| Managed Kubernetes control plane (~$73/mo, never free) | **No control plane** — just one Linux VM you rent |
| App runs as pods across worker nodes | App runs as a **Docker container** on the box |
| Postgres on **RDS** (paid) | Postgres as a **container** on the same box |
| Public access via **load balancer** ($$) | The box's **public IP**, port 8000 |
| Image pulled from **ECR** | Image **built on the box** from your repo (no registry needed) |
| Sync job = Kubernetes **CronJob** | Sync job = a **host `cron`** entry |

You give up Kubernetes' auto-healing/scaling — fine for a learning/demo deploy. Everything
lives on one machine; if it reboots, `docker compose up` brings it all back.

## What's free, and the one honest caveat

AWS's free tier gives a **`t3.micro` (or `t2.micro`) EC2 instance — 750 hours/month for
your first 12 months**, enough to run 24/7. Storage (an EBS volume up to 30 GB) is free in
the same window.

**The caveat:** "free" means **the first 12 months**. After that the instance is ~$7–9/mo.
AWS has *no* compute that's free forever — if you want always-$0, that's Oracle Cloud or a
scale-to-zero PaaS, not AWS. Within the first year, though, this is genuinely $0.

`$` markers below follow `docs/aws.md`: `$` = small/free-tier-covered, `$$` = real ongoing
cost (Snowflake), unmarked = free.

## Deployment structure (one machine)

```
                Internet
                   │  http://<public-ip>:8000
        ┌──────────▼───────────────────────────┐
        │   EC2 instance (t3.micro, free tier)  │   ← the only machine you rent
        │                                       │
        │   Docker (docker compose):            │
        │   ┌─────────────┐   ┌──────────────┐  │
        │   │ app         │──▶│ postgres     │  │   writes → Postgres (source of truth)
        │   │ (FastAPI)   │   │ (container,  │  │
        │   │             │   │  volume)     │  │
        │   └──────┬──────┘   └──────────────┘  │
        │          │ host cron: sync script     │
        └──────────┼────────────────────────────┘
                   │ reads (analytics) + sync
            ┌──────▼───────────┐
            │  Snowflake (SaaS) │   analytics reads — separate paid service
            └───────────────────┘
```

Three tiers, same as EKS — app, database, analytics warehouse — but the app and database
are two containers on one box instead of pods + RDS, and there's no load balancer.

## Prerequisites — what you need

| Thing | For | Status / value |
|-------|-----|----------------|
| **AWS account** + **AWS CLI** (`aws configure`) | launching the EC2 instance | ✅ configured (account `673515369454`, region `eu-north-1`) |
| **SSH key pair** (in the EC2 region) | logging into the box | ✅ `bank-key` — private key saved locally as `bank-key.pem` |
| **Anthropic API key** | the LLM (`/ask`) | you have one (used for `/ask` already) |
| **Snowflake account** | analytics reads (steps 10+) | needed before step 11 |

Docker is installed **on the EC2 box**, not your laptop — so the only local tool you
strictly need is the AWS CLI (or just the AWS web console).

**About the key pair (`bank-key` / `bank-key.pem`):**
- `bank-key` is the name registered in AWS (used as `--key-name`); `bank-key.pem` is the
  matching **private key** on your machine (used as `ssh -i bank-key.pem`).
- Lock its permissions so SSH will accept it: `chmod 400 bank-key.pem`.
- **Never commit it.** `*.pem` is gitignored. If the private key is ever exposed, delete the
  AWS key pair (`aws ec2 delete-key-pair --key-name bank-key --region eu-north-1`) and make
  a new one — but only before/without an instance that depends on it.

## Deploy checklist (one line each)

1. Launch a `t3.micro` EC2 instance (Amazon Linux 2023), free tier.
2. Set the security group: SSH (22) from your IP, app port (8000) from anywhere.
3. SSH in and install Docker + the Compose plugin.
4. Get the code onto the box (`git clone`).
5. Create a `.env` with `DATABASE_URL`, `ANTHROPIC_API_KEY` (and later `ANALYTICS_URL`).
6. Add an `app` service to `docker-compose.yml` (build from the Dockerfile).
7. `docker compose up -d --build` — app + Postgres come up.
8. Create tables / seed sample data.
9. Verify: open `http://<public-ip>:8000/docs`.

### Snowflake integration (analytics reads, same dual-engine idea)

10. Add `snowflake-sqlalchemy` to `requirements.txt`.
11. In Snowflake, create the database, schema, warehouse, and a **read-only** role/user.
12. Create the `transactions` table in Snowflake.
13. Add `ANALYTICS_URL` (Snowflake connection string) to `.env`.
14. Add a second SQLAlchemy engine in `app/database.py`; point `/ask` reads at it.
15. Keep all writes + the account-exists check on the Postgres container.
16. Add a sync job: a **host `cron`** entry running the sync script on a schedule.
17. Verify: write a row, run the sync, confirm `/ask` analytics see it (allow lag).

## Placeholders — where each value comes from

The commands below contain `<placeholders>`. Here's how to get each one (run in order;
each prints the value you paste into the relevant step).

### `<al2023-ami-id>` — the Amazon Linux 2023 image id (step 1)
AWS publishes the latest id via SSM, so you never hard-code it:
```bash
aws ssm get-parameter --region eu-north-1 \
  --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --query 'Parameter.Value' --output text
```

### `<your-ip>` — your laptop's public IP, for the SSH rule (step 2)
```bash
curl -s https://checkip.amazonaws.com
```
Use it as `<your-ip>/32` (the `/32` means "just this one address").

### `<sg-id>` — the security group id (steps 1–2)
You only have a `default` group; create a dedicated one (free) and capture its id:
```bash
aws ec2 create-security-group --region eu-north-1 \
  --group-name bank-sg --description "bank-python EC2" \
  --query 'GroupId' --output text
```
This prints `sg-...`. Reuse it later with:
```bash
aws ec2 describe-security-groups --region eu-north-1 \
  --group-names bank-sg --query 'SecurityGroups[0].GroupId' --output text
```

### `<instance-id>` / `<public-ip>` — the box itself (after step 1)
`run-instances` returns them, or look them up after launch:
```bash
# newest running instance's id:
aws ec2 describe-instances --region eu-north-1 \
  --filters Name=instance-state-name,Values=running \
  --query 'Reservations[-1].Instances[-1].InstanceId' --output text

# its public IP (used in steps 3 and 9):
aws ec2 describe-instances --region eu-north-1 \
  --instance-ids <instance-id> \
  --query 'Reservations[].Instances[].PublicIpAddress' --output text
```

### `<your-repo-url>` — the code to clone (step 4)
Already known:
```
https://github.com/adirozeri/bank-python.git
```
**⚠️ Push first.** Your latest local changes (these docs, the `app/database.py` analytics
engine, `scripts/sync_to_snowflake.py`, `docker-compose.yml`) may not be on GitHub yet —
`git clone` would pull an older version. Either `git push` before step 4, or skip cloning
and `scp` your local copy to the box:
```bash
scp -i bank-key.pem -r . ec2-user@<public-ip>:bank-python
```

### `ANTHROPIC_API_KEY` — the LLM key (step 5)
Your existing Anthropic key (the same one `/ask` already uses). Paste it into `.env`.

### Snowflake values — `<user>` `<password>` `<account>` `<database>` `<schema>` `<wh>` `<role>` (steps 11–13)
These don't exist until you create them **in Snowflake** at step 11; copy them into the
`ANALYTICS_URL` at step 13.

### Quick reference

| Placeholder | Command / source | Needed at |
|-------------|------------------|-----------|
| `<al2023-ami-id>` | `aws ssm get-parameter … al2023-ami-kernel-default-x86_64` | step 1 |
| `<your-ip>` | `curl -s https://checkip.amazonaws.com` | step 2 |
| `<sg-id>` | `aws ec2 create-security-group … bank-sg` | steps 1–2 |
| `<instance-id>` / `<public-ip>` | `aws ec2 describe-instances …` | steps 1, 3, 9 |
| `<your-repo-url>` | `https://github.com/adirozeri/bank-python.git` (push first!) | step 4 |
| `ANTHROPIC_API_KEY` | your existing Anthropic key | step 5 |
| Snowflake `<user>`/`<account>`/… | created in Snowflake at step 11 | steps 11–13 |

## Steps (detailed)

Numbered to match the checklist (1–9 core EC2, 10–17 Snowflake). Each step says **what** it
is, **why** you need it, **what you fill in**, **what it creates and where**, and **cost**.

### 1. Launch a t3.micro EC2 instance `$`
Console: EC2 → Launch instance → Amazon Linux 2023, type `t3.micro`, your key pair.
Or CLI:
```bash
aws ec2 run-instances \
  --image-id <al2023-ami-id> --instance-type t3.micro \
  --key-name bank-key --security-group-ids <sg-id> \
  --region eu-north-1
```
**What:** rents one small Linux virtual machine in AWS — the single box everything runs on.

**Why:** this replaces the entire EKS cluster + nodes. You only need somewhere to run
Docker; one VM does it. `t3.micro` is the free-tier size.

**You fill in:** the **AMI id** for Amazon Linux 2023 in `eu-north-1` (the console fills
this automatically) and the **security group** from step 2. Key pair is already
`bank-key`.

**Creates (in AWS):** one **EC2 instance** + its **EBS root volume** (disk), with a public
IPv4 address, in `eu-north-1`.

**`$` Cost:** **free** under the 12-month free tier (750 h/month of `t3.micro`, 30 GB EBS).
After 12 months ~$7–9/month. Note: a public IPv4 now carries a tiny hourly charge outside
the free tier.

### 2. Set the security group (firewall) `$`
Allow inbound: **22 (SSH) from your IP only**, **8000 (the app) from `0.0.0.0/0`**.
```bash
aws ec2 authorize-security-group-ingress --group-id <sg-id> \
  --protocol tcp --port 22 --cidr <your-ip>/32 --region eu-north-1
aws ec2 authorize-security-group-ingress --group-id <sg-id> \
  --protocol tcp --port 8000 --cidr 0.0.0.0/0 --region eu-north-1
```
**What:** a security group is the instance's firewall. By default it blocks everything; you
open exactly the two ports you need.

**Why:** SSH (22) is how you log in to set things up — lock it to your own IP so the box
isn't exposed to the world. Port 8000 is where FastAPI/uvicorn listens (see the
`Dockerfile`'s `EXPOSE 8000`), so the public must reach it for the URL to work. Postgres
(5432) is **not** opened — only the app, inside the box, talks to it.

**You fill in:** the **security-group id** and **your current IP** for the SSH rule.

**Creates (in AWS):** two inbound **rules** on the security group. No new machine.

**`$` Cost:** free — security groups cost nothing.

### 3. Install Docker on the box
SSH in, then install Docker + the Compose plugin:
```bash
chmod 400 bank-key.pem                     # one-time: SSH refuses world-readable keys
ssh -i bank-key.pem ec2-user@<public-ip>
sudo dnf update -y
sudo dnf install -y docker
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user        # lets you run docker without sudo
newgrp docker                           # apply the new group to THIS shell (or log out/in)
docker version                          # verify the daemon is reachable (no permission error)
# Compose plugin:
sudo dnf install -y docker-compose-plugin || \
  ( mkdir -p ~/.docker/cli-plugins && \
    curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" \
    -o ~/.docker/cli-plugins/docker-compose && chmod +x ~/.docker/cli-plugins/docker-compose )
docker version && docker compose version   # verify both
```

> **Permission denied on `/var/run/docker.sock`?** You added yourself to the `docker` group
> but your current shell started before that. Run `newgrp docker` (applies it to this shell)
> or log out and SSH back in. Check with `groups` — it should list `docker`.
**What:** installs the container runtime on the EC2 box and the `docker compose` command.

**Why:** the whole point of EC2-without-EKS is that *you* run the containers. Docker is what
runs your `Dockerfile` image and the Postgres image; Compose orchestrates the two together.

**You fill in:** the instance's **public IP** for the `ssh` line (key file is
`bank-key.pem`).

**Creates (on the box):** Docker installed and running; `ec2-user` added to the `docker`
group.

**Cost:** free — open-source software on a box you already pay for (or not, in free tier).

### 4. Get the code onto the box
```bash
sudo dnf install -y git
git clone <your-repo-url> bank-python && cd bank-python
```
**What:** copies the project (with `Dockerfile`, `docker-compose.yml`, `app/`, etc.) onto
the instance.

**Why:** the box needs the source to **build** the image (unlike EKS, there's no ECR step —
you build right here). `git clone` is simplest; `scp -i <key> -r . ec2-user@<ip>:bank-python`
works too if the repo isn't on a remote.

**You fill in:** your **repo URL** (or use `scp`).

**Creates (on the box):** a `bank-python/` directory with the project.

**Cost:** free.

### 5. Create the `.env` file
In the project dir on the box, create `.env`:
```
DATABASE_URL=postgresql://bankuser:bankpass@postgres:5432/bankdb
ANTHROPIC_API_KEY=<your-key>
# ANALYTICS_URL=...        # added in step 13 for Snowflake
```
**What:** the file holding the app's settings/secrets, read at runtime (the app already does
`os.getenv("DATABASE_URL")` in `app/database.py`, and `python-dotenv` is installed).

**Why:** keeps secrets out of the image and out of git (`.env` is gitignored). The host
`postgres` in the URL is the **Compose service name** from step 6 — Docker's internal DNS
resolves it to the Postgres container, so the app reaches the DB over the box's internal
network (5432 is never exposed publicly).

**You fill in:** your real `ANTHROPIC_API_KEY`. The DB credentials match the existing
`docker-compose.yml` (`bankuser`/`bankpass`/`bankdb`).

**Creates (on the box):** a `.env` file (local to the box only — never commit it).

**Cost:** free.

### 6. Add an `app` service to `docker-compose.yml`
Your current compose has only `postgres`. Add the FastAPI app alongside it:
```yaml
  app:
    build: .                      # build the image from the Dockerfile, on the box
    container_name: bank-app
    env_file: .env
    ports:
      - "8000:8000"               # box:container — this is what the public hits
    depends_on:
      postgres:
        condition: service_healthy
```
**What:** tells Compose to also build and run your application container, next to the
Postgres container it already manages.

**Why:** Compose now brings up **both** tiers with one command and puts them on a shared
network so `app` can reach `postgres` by name. `depends_on … service_healthy` waits for the
DB's healthcheck (already defined in your compose) before starting the app, avoiding
"database not ready" crashes on boot. `ports: 8000:8000` maps the box's port 8000 (opened in
step 2) to the container's uvicorn port.

**You fill in:** nothing beyond pasting this block — it reuses your `Dockerfile` and `.env`.

**Creates:** an edit to `docker-compose.yml` (on the box). No running container yet — that's
step 7.

**Cost:** free.

### 7. Start the stack
```bash
docker compose up -d --build
docker compose ps        # both services Up; postgres healthy
```
**What:** builds the app image and starts both containers in the background.

**Why:** `--build` compiles your code into the image the first time (and after changes);
`-d` runs detached so it keeps running after you log out. This is the EC2 equivalent of
`kubectl apply` — the moment config becomes a running system.

**You fill in:** nothing.

**Creates (on the box):** a built **app image**, a running **`bank-app` container** and
**`bank-postgres` container**, plus the **`bank_pgdata` volume** (already in your compose)
that persists DB data across restarts.

**Cost:** free — runs on the instance you already have.

### 8. Create tables / seed data
```bash
docker compose exec app python scripts/seed.py     # if seed.py creates tables + sample rows
```
**What:** initializes the `transactions` table in the Postgres container (and optionally
loads sample data).

**Why:** a fresh Postgres container starts empty. The app's `create_all` (or `scripts/seed.py`)
creates the schema so endpoints have a table to read/write. Because the data lives on the
`bank_pgdata` volume, you only seed once — it survives restarts.

**You fill in:** nothing (uses the existing seed script).

**Creates:** the **`transactions` table** (and sample rows) inside the Postgres container's
volume.

**Cost:** free.

### 9. Verify
```bash
curl http://localhost:8000/health        # from inside the box
# then from your laptop / browser:
#   http://<public-ip>:8000/docs
```
**What:** confirm the app is up locally on the box, then reachable from the public internet.

**Why:** two checks separate two failure modes — "app/DB broken" (localhost fails) vs.
"firewall/networking wrong" (localhost works but the public IP doesn't, meaning the step-2
rule or the IP is off). Hitting `/docs` from your browser is the end-to-end proof.

**You fill in:** the instance's **public IP**.

**Creates:** nothing — read-only checks.

**Cost:** free.

---

**Snowflake integration (steps 10–17) — same dual-engine idea as `docs/aws.md`:** Postgres
(the container) is the **source of truth** for writes; Snowflake is a **read-only analytics
replica** fed by a sync job. The only difference from the EKS version is *where* the pieces
live — the second engine runs in the same app container, and the sync runs from host `cron`
instead of a Kubernetes CronJob.

### 10. Add the Snowflake driver
Add `snowflake-sqlalchemy` to `requirements.txt`, then rebuild on the box
(`docker compose up -d --build`).
**What:** the library that lets SQLAlchemy speak Snowflake.

**Why:** without it a `snowflake://...` URL errors. Dependencies live inside the image, so
you rebuild after editing `requirements.txt` (no registry/tag dance — the build happens on
the box).

**You fill in:** nothing beyond the one line.

**Creates:** an edited `requirements.txt` and a rebuilt app image (on the box).

**Cost:** free.

### 11. Provision Snowflake `$$`
Create a **database**, **schema**, **warehouse**, and a **read-only** role + user.
**What:** the Snowflake side — storage (db/schema), compute (warehouse), and a least-
privilege login for the app.

**Why read-only:** Snowflake is an analytics copy, not the source of truth. A `SELECT`-only
user means a bug or a bad `/ask` query can't corrupt it. Important for banking data.

**You fill in (in Snowflake):** database, schema, warehouse name+size, and a read-only
role/user with a password. Save them for step 13. **Set auto-suspend (~60 s)** on the
warehouse to avoid idle charges.

**Creates (in Snowflake — not AWS):** a database, schema, warehouse, role, and user.

**`$$` Cost:** Snowflake bills **credits** for warehouse compute per query (separate from
AWS, not on any AWS free tier) plus storage. Auto-suspend keeps it near-zero when idle; new
accounts get trial credits.

### 12. Create the table in Snowflake
Create `transactions` (DDL, or `create_all` against the analytics engine).
**What:** a landing place for the synced rows and for `/ask` to read.

**Why:** mirror the Postgres table (same columns) so the sync copies rows 1:1; Snowflake
just stores them in its own columnar format.

**You fill in:** nothing new — reuse the existing model.

**Creates:** the **`transactions` table** in the Snowflake database/schema (empty until the
sync runs).

**Cost:** a tiny bit of warehouse compute to run the DDL (covered by step 11's `$$`).

### 13. Add `ANALYTICS_URL` to `.env`
```
ANALYTICS_URL=snowflake://<user>:<password>@<account>/<database>/<schema>?warehouse=<wh>&role=<role>
```
**What:** the Snowflake connection string, added to the same `.env` the app already reads.

**Why a separate var:** the app now talks to **two** databases — `DATABASE_URL` (Postgres,
writes) and `ANALYTICS_URL` (Snowflake, analytics reads). Two named vars let the code pick
the right engine per operation (step 14).

**You fill in:** all the placeholders from step 11.

**Creates:** one more line in `.env` (on the box). Rebuild/restart isn't needed for env
changes — `docker compose up -d` re-reads `.env`.

**Cost:** free (it's just config).

### 14. Wire up the second engine
In `app/database.py`, add an analytics engine that uses `ANALYTICS_URL` if set, else falls
back to the primary engine; point the `/ask` read tools at it:
```python
ANALYTICS_URL = os.getenv("ANALYTICS_URL")
analytics_engine = create_engine(ANALYTICS_URL, pool_pre_ping=True) if ANALYTICS_URL else engine
AnalyticsSession = sessionmaker(bind=analytics_engine, autoflush=False)
```
Route the `/ask` read tools (`_query_transactions` / `_query_balance`) to `AnalyticsSession`.

**What:** a second SQLAlchemy session pointed at Snowflake, used only for analytics reads.

**Why this shape:** the `if ANALYTICS_URL else engine` fallback means the code runs
unchanged when Snowflake isn't configured (local dev), and only splits traffic in
production. `pool_pre_ping=True` avoids stale-connection errors (Snowflake drops idle
conns). Reads go to the warehouse; writes stay on Postgres (next step).

**You fill in:** nothing manual — code only; it reads `ANALYTICS_URL` from the env.

**Creates:** a code change in `app/database.py` (ships on the next `--build`).

**Cost:** free.

### 15. Keep writes on Postgres
All writes **and** the account-exists check in `create_transfer` stay on `SessionLocal`
(the Postgres container). Snowflake is read-only.
**What:** ensure every write path and read-before-write check uses the Postgres session.

**Why:** Postgres is the source of truth; Snowflake lags by the sync interval (step 17).
Validating "does this account exist?" against stale Snowflake data could approve a bad
transfer. Writes and correctness checks must hit the authoritative store.

**You fill in:** nothing — code only; confirm no write path uses `AnalyticsSession`.

**Creates:** a code change/verification in `app/main.py`.

**Cost:** free.

### 16. Add the sync job (host cron) `$`
Write `scripts/sync_to_snowflake.py` (copy new rows by `created_at`), then add a host crontab
entry on the box:
```bash
crontab -e
# every 15 minutes, run the sync inside the app container:
*/15 * * * * cd /home/ec2-user/bank-python && /usr/bin/docker compose run --rm app python scripts/sync_to_snowflake.py >> sync.log 2>&1
```
**What:** a recurring job that copies new Postgres rows into Snowflake. On EC2 this is just
the box's own `cron`, running the script inside a throwaway app container.

**Why:** Snowflake doesn't know about Postgres — something has to move the data. `cron` is
the EC2 equivalent of the Kubernetes CronJob from `docs/aws.md`. "Incremental by
`created_at`" means each run copies only new rows, not the whole table.

**You fill in:** the **schedule** (cron expression) and the **project path** on the box.

**Creates:** `scripts/sync_to_snowflake.py` (code) and a **crontab entry** on the box.

**`$` Cost:** the cron container runs on the box you already pay for (free), but **each run
wakes the Snowflake warehouse**, burning credits (step 11). A wider interval + auto-suspend
keeps it cheap.

### 17. Verify (mind the lag)
Create a transfer (write → Postgres), run the sync manually once, then ask `/ask` (reads →
Snowflake) and confirm the new row shows up.
**What:** end-to-end test of the dual-engine setup.

**Why "mind the lag":** the row won't appear in `/ask` until the next sync runs — that delay
is the eventual consistency. Running the sync manually first removes the timing variable.

**You fill in:** nothing — read-only checks (plus one test row).

**Creates:** nothing (a test row that the sync copies to Snowflake).

**Cost:** a little warehouse compute on the sync/query (covered by step 11's `$$`).

## End result — what you'll have

- A **public URL** (`http://<public-ip>:8000`) serving the FastAPI app from one EC2 box.
- **Postgres** running as a container with a **persistent volume** — data survives restarts.
- **Snowflake** wired in for `/ask` analytics reads, fed by a `cron` sync — Postgres stays
  the source of truth.
- **No EKS, no load balancer, no RDS** — so **$0 within the 12-month free tier** (Snowflake
  credits are the only ongoing cost, and minimal with auto-suspend).

## What you'll be able to do

- Hit every endpoint (`/health`, `/transactions`, `/ask`) at `http://<public-ip>:8000/...`.
- Use the LLM chat and create transfers against the live Postgres container.
- **Redeploy** by `git pull` + `docker compose up -d --build` on the box.
- **Restart** the whole stack with `docker compose restart` (data persists on the volume).

## Trade-offs vs. EKS (be aware)

- **No auto-healing/scaling** — if the box dies, you restart it manually; one machine = one
  point of failure. Fine for demo/learning, not for production HA.
- **No HTTPS by default** — it's `http://`. Add a free Let's Encrypt cert via a reverse proxy
  (Caddy/nginx) on the box if you want `https://`.
- **Backups are your job** — RDS did automated backups; here, snapshot the EBS volume or
  `pg_dump` on a schedule.

## Short version
**One `t3.micro` EC2 (free 12 mo) → Docker Compose (app + Postgres containers) → public IP
on port 8000 → Snowflake for analytics reads, synced by host `cron`.** No EKS, no LB, no RDS.

## Later / optional
- **HTTPS + domain:** Caddy reverse proxy (auto Let's Encrypt) + a Route 53 / free DNS name.
- **S3 (Phase 5):** backups / Snowpipe files — `boto3` is already in `requirements.txt`.
- **Auto-start on reboot:** a small systemd unit running `docker compose up -d`.
- **When you outgrow one box:** graduate to the EKS path in `docs/aws.md`.
