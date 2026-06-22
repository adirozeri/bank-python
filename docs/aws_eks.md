# Deploying bank-python to AWS (Phase 5)

Target: run the existing Kubernetes manifests on **EKS** (managed Kubernetes), reusing
the `k8s/` setup built for minikube. This is Phase 5 — looking ahead of the current phase.

## The mindset shift from minikube

| minikube (now) | AWS (target) |
|----------------|--------------|
| Image built into minikube's local Docker | Image pushed to a **registry (ECR)** and pulled from there |
| Local single-node cluster | **EKS** managed cluster |
| Postgres pod in-cluster (no persistence) | **RDS for PostgreSQL** (managed, persistent) |
| Secrets in plain YAML | Kubernetes Secret / **AWS Secrets Manager** |
| Service `NodePort` | Service `LoadBalancer` or ALB Ingress |

The manifests largely carry over; the big change is that they point at AWS
infrastructure (cluster + registry + database) that must exist first.

## Deployment structure (which machines, and what's on each)

```
        Internet
           │
   ┌───────▼────────┐
   │  Load Balancer │   (AWS-managed)
   └───────┬────────┘
           │
   ┌───────▼─────────────────────────┐
   │   EKS Worker Nodes (EC2)         │   ← you manage these
   │   ┌──────────┐   ┌──────────┐    │
   │   │ pod:     │   │ pod:     │    │
   │   │ bank-py  │   │ bank-py  │    │   (FastAPI app containers)
   │   └────┬─────┘   └────┬─────┘    │
   └────────┼──────────────┼──────────┘
            └──────┬───────┘
                   │ SQL (5432)
            ┌──────▼───────┐
            │  RDS Postgres │   (AWS-managed, separate machine)
            └───────────────┘

  ECR (image storage) ── pulled by nodes at startup
  S3  (file storage)  ── optional, later
```

| Machine | Managed by | What runs on it |
|---------|-----------|-----------------|
| **EKS control plane** | AWS (invisible to you) | Kubernetes brain — API server, scheduler, etcd. You never log into it. |
| **Worker nodes** (EC2, e.g. 2) | **You** | Your **bank-python pods** (the FastAPI containers). This is where the app actually runs. |
| **RDS instance** | AWS | **PostgreSQL** only — your database, on its own machine, *not* in the cluster. |
| **Load Balancer** (NLB/ALB) | AWS | No app code — just routes internet traffic to the pods across the nodes. |

Not machines (just services):
- **ECR** — stores your image; nodes download it when starting pods.
- **S3** — file storage, only if/when you need it.

Key idea: **app runs on the worker nodes, database runs on RDS (separate), traffic
enters through the load balancer.** Three tiers, cleanly separated.

## Key facts

- **ECR** (Elastic Container Registry) is part of AWS — no separate account. You just
  create a *repository* to hold this project's image (like a repo on GitHub).
- A **registry** stores Docker images. Kubernetes does not build images; it *pulls*
  pre-built ones. minikube didn't need a registry because the image was built straight
  into its own Docker daemon. EKS nodes are separate machines that have never seen the
  image, so they pull it from ECR.
- **Database: use RDS, not S3.** S3 stores *files* (objects) — it can't run SQL, has no
  tables/rows. The app talks SQL via SQLAlchemy, so it needs **RDS for PostgreSQL**.
  S3 is only for files (backups, Snowpipe files), and comes up later.

| Service | For | Use here |
|---------|-----|----------|
| RDS | databases (SQL) | the `transactions` table ✅ |
| S3 | files / objects | later — backups, Snowpipe files |

## Prerequisites — what to install

Install commands are for Linux. Each tool has a one-time install, then a verify/usage command.

### AWS CLI — talk to AWS (ECR, RDS, etc.)
```bash
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o awscliv2.zip
unzip awscliv2.zip && sudo ./aws/install
aws configure        # enter your Access Key, Secret, region; do this once
aws sts get-caller-identity   # verify: prints your account/user
```

### Docker — build and push the app image
```bash
sudo apt-get update && sudo apt-get install -y docker.io
sudo usermod -aG docker $USER   # then log out/in so you can run docker without sudo
docker version       # verify
```

### kubectl — apply manifests and operate the cluster
```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
kubectl version --client   # verify
```

### eksctl — create and manage the EKS cluster
```bash
curl -sSL "https://github.com/eksctl-io/eksctl/releases/latest/download/eksctl_Linux_amd64.tar.gz" \
  | tar xz -C /tmp && sudo mv /tmp/eksctl /usr/local/bin
eksctl version       # verify
```

### helm — install cluster add-ons (LB Controller, External Secrets)
```bash
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
helm version         # verify
```

Plus: an **AWS account** (ECR, EKS, RDS all live inside it — no separate signups) and,
for Snowflake later, a **Snowflake account**.

## Account info to obtain & where to save it

### What to obtain

| Source | Values | Used for |
|--------|--------|----------|
| **AWS — IAM user/role** | Access Key ID, Secret Access Key, default region | `aws` CLI auth (ECR, EKS, RDS) |
| **AWS — account** | 12-digit Account ID | the ECR image URI `<acct>.dkr.ecr.<region>...` |
| **RDS** | endpoint host, port, db name, username, password | the app's `DATABASE_URL` |
| **Anthropic** | `ANTHROPIC_API_KEY` | the LLM (`/ask`) |
| **Snowflake** (later) | account identifier, user, password (or key-pair), warehouse, database, schema, role | the app's `ANALYTICS_URL` |

### Where to save it

| Secret | Local dev | In the cluster (AWS) |
|--------|-----------|----------------------|
| AWS keys | `~/.aws/credentials` (written by `aws configure`) | not needed in pods — use **IRSA** roles instead |
| `DATABASE_URL`, `ANTHROPIC_API_KEY`, `ANALYTICS_URL` | `.env` (gitignored) | a Kubernetes **Secret** (or **AWS Secrets Manager** + External Secrets) |

**Rules:**
- **Never commit secrets** — `.env` stays gitignored; `~/.aws/credentials` lives only on your machine.
- **Never bake secrets into the image** or put them in `k8s/` YAML.
- Prefer **AWS-native** storage in the cluster (Secrets Manager / IRSA) over static keys.

## Deploy checklist (one line each)

1. Create an ECR repository for the image.
2. Build the Docker image and push it to ECR.
3. Create the EKS cluster (control plane + worker nodes).
4. Provision an RDS PostgreSQL instance in the same VPC.
5. Create Kubernetes Secrets for `DATABASE_URL` (RDS) and `ANTHROPIC_API_KEY`.
6. Create a ConfigMap for non-secret config (e.g. `LLM_MODEL`).
7. Update the deployment manifest: ECR image, Secret/ConfigMap env, health probes.
8. Remove the in-cluster Postgres manifests (replaced by RDS).
9. Switch the Service from `NodePort` to `LoadBalancer` (or add an ALB Ingress).
10. `kubectl apply -f k8s/` (Secrets/ConfigMap first, then deployment, then service).
11. Verify: pods Running, logs show startup, `curl http://<lb-address>/health`.

### Snowflake integration (dual-engine: RDS writes, Snowflake analytics reads)

12. Add `snowflake-sqlalchemy` to `requirements.txt` and rebuild/push the image.
13. In Snowflake, create the database, schema, warehouse, and a read-only role/user.
14. Create the `transactions` table in Snowflake (DDL or `create_all`).
15. Add a Kubernetes Secret `ANALYTICS_URL` with the Snowflake connection string.
16. Add a second SQLAlchemy engine (`AnalyticsSession`) and point `/ask` read tools at it.
17. Keep all writes + the account-exists check on RDS (Snowflake is read-only).
18. Add a sync job (Postgres→Snowflake): batch CronJob now, Snowpipe via S3 later.
19. Verify: write a row to RDS, run the sync, confirm `/ask` analytics see it (allow lag).

## Steps (detailed)

Numbered to match the checklist above (1–11 core EKS, 12–19 Snowflake).

### 💲 Cost markers

Steps that **cost money and are not (fully) covered by the AWS free tier** are flagged:

| Marker | Meaning |
|--------|---------|
| `$` | small / usage-based; often within the 12-month free tier if you stay tiny |
| `$$` | real ongoing cost, but partly free-tier-eligible for the first 12 months |
| `$$$` | significant always-on cost, **never** free tier — the expensive part |

Unmarked steps create config/code only (Secrets, ConfigMaps, YAML edits) and are free.
**The big spenders are step 3 (EKS) and step 9 (load balancer); turn the cluster off when
not using it** (`eksctl delete cluster`) to stop the meter.

### 1. Create an ECR repository `$`
```bash
aws ecr create-repository --repository-name bank-python
```
**What:** creates a private "folder" inside AWS's container registry (ECR) to hold the
versions of your app image.

**Why:** Kubernetes never *builds* images — each worker node *pulls* a pre-built image by
name. On minikube the image already lived in minikube's own Docker daemon, so there was
nothing to pull from. EKS nodes are brand-new EC2 machines that have never seen your image,
so it must live somewhere they can reach. ECR is that place (think "GitHub, but for Docker
images"). One repository per project; it can hold many tags (`v1`, `v2`, …).

**You fill in:** nothing for you — repo name (`bank-python`) and region (`eu-north-1`) are
already chosen. AWS returns the `repositoryUri` you'll reuse below.

**Creates:** an empty ECR **repository** — in AWS, region `eu-north-1`, at
`673515369454.dkr.ecr.eu-north-1.amazonaws.com/bank-python`. No image in it yet.

**`$` Cost:** the empty repo is free; you pay for **image storage** (~$0.10/GB-month) once
you push. **500 MB free for 12 months**, so a single small image is effectively free at
first.

### 2. Build and push the image to ECR `$`
```bash
aws ecr get-login-password | docker login --username AWS \
  --password-stdin <acct>.dkr.ecr.<region>.amazonaws.com
docker build -t <acct>.dkr.ecr.<region>.amazonaws.com/bank-python:v1 .
docker push <acct>.dkr.ecr.<region>.amazonaws.com/bank-python:v1
```
**What:** logs Docker into your ECR repo, builds your app into an image, and uploads it.

**Why each line:**
- `aws ecr get-login-password | docker login …` — ECR is private. This hands Docker a
  short-lived token so it's allowed to push. (You're proving "this is my account.")
- `docker build -t <full-ecr-uri>/bank-python:v1 .` — packages your code + Python deps
  into one immutable image. The full ECR URI as the *name* is how Docker knows where it
  will eventually be pushed.
- `docker push …` — uploads the image so EKS nodes can later pull it.

**Why a real tag (`v1`), not `:latest`:** `:latest` is a moving target — two deploys can
mean two different images under the same name, which makes "what's actually running?" and
rollbacks ambiguous. A fixed tag like `v1` pins an exact build, so a rollback is just
re-deploying `v1`.

**You fill in:**
- `<acct>` → `673515369454`
- `<region>` → `eu-north-1`
- the tag (`v1`, then `v2`, … on each rebuild)
- `--platform linux/amd64` on `docker build` if you're on an ARM machine

**Creates:** an **image** locally (in your machine's Docker), then a **pushed image
tag** `:v1` inside the ECR repo from step 1 (in AWS). A `~/.docker/config.json` login
entry is also written locally.

**`$` Cost:** the local build is free; pushing consumes ECR **storage** (counts against the
500 MB/12-month free tier). Each extra tag (`v2`, …) adds a little more storage — clean up
old tags to stay free.

### 3. Create the EKS cluster `$$$`
```bash
eksctl create cluster --name bank-python --region <region> --nodes 2 --managed
```
**What:** one command provisions a whole Kubernetes cluster on AWS — the control plane
(the "brain"), 2 worker EC2 nodes (where your pods run), a VPC (private network), and the
IAM permissions nodes need to pull from ECR.

**Why:** this is the machine(s) that will actually run your app. minikube gave you a
single throwaway node on your laptop; EKS gives you a real, multi-node, AWS-managed cluster
that survives restarts and can be scaled. `--managed` means AWS handles node provisioning
and upgrades for you. `--nodes 2` means your pods can spread across two machines, so one
node dying doesn't take the app down. (Heads-up: this step takes ~15–20 minutes and costs
money while it runs.)

**You fill in:**
- `<region>` → `eu-north-1`
- cluster name (`bank-python`) and `--nodes` count
- optionally `--node-type` (instance size) and `--nodes-min/--nodes-max`

**Creates (all in AWS, `eu-north-1`):** an **EKS cluster** (control plane), a **node
group** of 2 **EC2 instances**, a **VPC** + subnets/route tables, **IAM roles** for the
nodes, and a **CloudFormation stack** managing it all. Locally: a kube-context is added to
`~/.kube/config` so `kubectl` points at this cluster.

**`$$$` Cost — the expensive step, none of it free tier:**
- **EKS control plane: ~$0.10/hour (~$73/month)** — flat fee, never free, charged as long
  as the cluster exists.
- **2 × EC2 worker nodes** — billed per hour by instance size. Free tier only covers a
  *single* `t3.micro` (750 h); 2 nodes (or anything bigger) is real money.
- **NAT Gateway(s)** — `eksctl`'s default VPC adds one (~$32/month + data) so private nodes
  reach the internet. Easy to overlook.

This meter runs 24/7 until you `eksctl delete cluster`. Delete it when you're not actively
using it.

### 4. Provision RDS PostgreSQL `$$`
- Provision **Amazon RDS for PostgreSQL** (managed, persistent, backups).
- Put it in the same VPC as EKS; security group allows the node group to reach 5432.
- Endpoint becomes `postgresql://bankuser:...@<rds-endpoint>:5432/bankdb`.

**What:** a managed PostgreSQL database running on its own AWS-managed machine, *outside*
the Kubernetes cluster.

**Why a separate machine, not a pod?** Pods are disposable — Kubernetes kills and
reschedules them freely, and anything written to a pod's local disk is lost when it
restarts. That's fine for stateless app containers but fatal for a database. RDS keeps your
data on durable storage with automated backups, so transactions survive pod/node restarts.

**Why "same VPC" and the 5432 rule:** the VPC is the private network. Putting RDS in the
same VPC as the nodes lets the app reach the DB over the internal network instead of the
public internet. The security group (a firewall) is locked down by default — you explicitly
open port 5432 (Postgres' port) *only* to the EKS node group, so nothing else can connect.
That endpoint string becomes the `DATABASE_URL` the app uses (step 5).

**You fill in / choose:**
- master **username** + **password** (you pick these)
- **db name** (e.g. `bankdb`) and instance size/class
- the **VPC** = the EKS cluster's VPC; add a security-group rule allowing the node group on
  5432
- AWS assigns the **endpoint host** — copy it for the `DATABASE_URL`

**Creates (in AWS):** an **RDS PostgreSQL instance** (its own managed machine, in the EKS
VPC), a **DB subnet group**, and a **security group** rule on 5432. It gets a DNS
**endpoint host** — nothing is created in the cluster.

**`$$` Cost:** free-tier-eligible for **12 months** if you pick a `db.t3.micro` /
`db.t4g.micro`, single-AZ, ≤20 GB storage. Beyond that window, a bigger class, Multi-AZ, or
more storage all bill per hour/GB. The instance bills whether or not it's queried.

### 5. Create Secrets
- A Kubernetes **Secret** for `DATABASE_URL` (the RDS endpoint) and `ANTHROPIC_API_KEY`.
- Better: **AWS Secrets Manager** + External Secrets Operator. Never bake into the image.

**What:** a Kubernetes object that holds sensitive values (DB password, API key) and
injects them into your pods as environment variables at runtime.

**Why:** the app needs the DB credentials and the Anthropic key, but those must never be
committed to git or baked into the image (anyone who pulls the image would get your
secrets). A Secret keeps them separate from code — the same image runs in dev, staging, and
prod, only the injected secrets differ. **AWS Secrets Manager + External Secrets** is the
stronger version: the real secret lives in AWS, gets rotated centrally, and is synced into
the cluster automatically, so no static secret sits in your YAML.

**You fill in:**
- `DATABASE_URL` → `postgresql://<user>:<password>@<rds-endpoint>:5432/<dbname>` (values from
  step 4)
- `ANTHROPIC_API_KEY` → your real key
- the Secret's name (referenced by the deployment in step 7)

**Creates:** a **Secret** object **in the cluster** (stored in etcd, namespaced) — *not* a
file and *not* in AWS. If you use Secrets Manager instead, the secret lives **in AWS** and
an ExternalSecret mirrors it into the cluster.

### 6. Create a ConfigMap
Non-secret config (e.g. `LLM_MODEL`) goes in a **ConfigMap**, referenced via `envFrom`.

**What:** like a Secret, but for *non-sensitive* configuration — plain settings such as
which LLM model to use, log level, or feature flags.

**Why separate from Secrets:** same principle (keep config out of the image so one image
works everywhere), but these values aren't secret, so they don't need encryption or
restricted access. Splitting secret vs. non-secret keeps it obvious what must be protected.
`envFrom` dumps every key in the ConfigMap into the pod as environment variables in one
shot, instead of listing each one.

**You fill in:** the non-secret key/values (e.g. `LLM_MODEL=claude-...`) and the ConfigMap's
name (referenced in step 7).

**Creates:** a **ConfigMap** object **in the cluster** (etcd, namespaced), alongside the
Secret from step 5.

### 7. Update the deployment manifest
- `image:` → ECR URI from step 2
- `DATABASE_URL`, `ANTHROPIC_API_KEY` → from the Secret; other config → from the ConfigMap
- add `readinessProbe` / `livenessProbe` on `/health`

**What:** the Deployment YAML is the recipe Kubernetes follows to run your app — which
image, how many copies (replicas), what env vars, and how to health-check them. Here you
point it at the new AWS pieces.

**Why each change:**
- `image:` → ECR URI — the minikube manifest referenced a local image name that AWS can't
  pull; now it points at the real ECR image from step 2.
- env from Secret/ConfigMap — wires the credentials (step 5) and config (step 6) into the
  running container.
- **probes** — Kubernetes can't *know* your app is healthy on its own. A `readinessProbe`
  tells it "don't send traffic until `/health` responds OK" (so users never hit a
  still-starting pod), and a `livenessProbe` tells it "if `/health` stops responding,
  restart this pod" (self-healing). Without them, Kubernetes assumes a running process =
  healthy, which isn't true if the app is wedged.

**You fill in (in the YAML):**
- `image:` → `673515369454.dkr.ecr.eu-north-1.amazonaws.com/bank-python:v1`
- the **Secret name** + **ConfigMap name** from steps 5–6
- the probe path (`/health`) and `containerPort`

**Creates:** nothing live yet — you're editing a **YAML file** in `k8s/` (e.g.
`k8s/deployment.yaml`) on your machine. It only takes effect on `kubectl apply` (step 10).

### 8. Remove the in-cluster Postgres manifests
Delete `postgres-deployment.yaml` / `postgres-service.yaml` — RDS replaces them.

**What:** delete the YAML that ran Postgres *as a pod* inside the cluster (the minikube
approach).

**Why:** step 4 moved the database to RDS, the durable managed option. If you left the old
Postgres pod running too, you'd have two databases — the app would talk to RDS while the
in-cluster one sat there empty and confusing, wasting resources. Removing it makes RDS the
single source of truth.

**You fill in:** nothing to enter — just delete the two files (and any matching
PVC/Secret left over from the in-cluster Postgres).

**Creates:** nothing — this *deletes* `k8s/postgres-*.yaml` files locally (and the
corresponding objects from the cluster on next apply).

### 9. Switch the Service to LoadBalancer `$$`
`NodePort` was minikube-style. On AWS:
- Service `type: LoadBalancer` → provisions an AWS NLB (simplest), **or**
- Ingress + AWS Load Balancer Controller → ALB, with HTTPS via an ACM cert + Route 53.

**What:** a Service is the stable network entry point to your pods (pods come and go with
changing IPs; the Service gives them one fixed address). Here you change *how* that entry
point is exposed to the outside world.

**Why the switch:** `NodePort` opens a port on each node's IP — fine for poking at minikube
locally, but it leaks node IPs and has no proper public address. `type: LoadBalancer` tells
AWS to spin up a real load balancer (NLB) that gives you one public URL and spreads
incoming traffic across all healthy pods on all nodes. The **Ingress + ALB** option is the
upgrade: it adds HTTPS (via an ACM certificate), a friendly domain (Route 53), and
path-based routing — worth it once the app is real, but the plain LoadBalancer is the
simplest thing that works.

**You fill in / choose:**
- pick **LoadBalancer** (simple) vs **Ingress + ALB** (HTTPS/domain)
- the Service `port` / `targetPort`
- if ALB: the **ACM certificate ARN** and the **Route 53 domain** name

**Creates:** an edit to the **Service YAML** in `k8s/` (local). On apply, Kubernetes asks
AWS to provision a **load balancer in AWS** (an NLB for `LoadBalancer`, or an ALB if you go
the Ingress route) with a public DNS address.

**`$$` Cost:** an ELB (ALB/NLB) bills ~**$16–20/month** plus data/LCU charges. The free tier
covers **750 hours/month of ALB or NLB for 12 months** — so one LB is ~free the first year,
then a steady monthly cost. The YAML edit itself is free; the charge starts when the LB is
provisioned on apply (step 10).

### 10. Apply the manifests
```bash
kubectl apply -f k8s/      # Secrets/ConfigMap first, then deployment, then service/ingress
```
**What:** sends all your YAML to the cluster. Kubernetes reads the desired state ("run 2
pods of image v1, with these secrets, behind a load balancer") and makes reality match.

**Why the order matters:** a pod references its Secret/ConfigMap at startup — if those
don't exist yet, the pod fails to start. So apply Secrets and ConfigMaps *first*, then the
Deployment (which consumes them), then the Service/Ingress (which routes to the now-running
pods). `kubectl apply` is *declarative* — re-running it only changes what differs, so it's
safe to run repeatedly.

**You fill in:** nothing — but make sure `k8s/` only contains the AWS manifests (no leftover
minikube/Postgres YAML) before applying.

**Creates (in the cluster):** the actual live objects — **Deployment** → **ReplicaSet** →
**Pods** (which pull `:v1` from ECR), the **Service** (→ an AWS load balancer), plus the
Secret/ConfigMap. This is the moment the YAML becomes running infrastructure.

### 11. Verify
```bash
kubectl get pods,svc,ingress
kubectl logs deploy/bank-python-deployment   # expect "Application startup complete"
curl http://<lb-address>/health
```
**What:** confirm the deploy actually worked, from three angles.

**Why each check:**
- `kubectl get pods,svc,ingress` — are the pods `Running` (not `CrashLoopBackOff` or
  `Pending`), and did the Service get an external address? This is the "is it alive?" view.
- `kubectl logs …` — the pod can be "Running" but the app inside still crashing on a bad
  DB URL or missing key. Seeing "Application startup complete" proves the app booted and
  connected to RDS.
- `curl http://<lb-address>/health` — the end-to-end test: traffic from the public internet
  → load balancer → a node → a pod → and back. If this returns OK, the whole chain works.

**You fill in:** `<lb-address>` → the external address from `kubectl get svc`/`ingress`
(`EXTERNAL-IP` / `ADDRESS` column).

**Creates:** nothing — read-only checks.

---

**Snowflake integration (steps 12–19) — dual-engine: RDS writes, Snowflake analytics reads.**
Snowflake is an OLAP warehouse — use it for analytical reads, **not** writes. RDS stays
the source of truth; Snowflake is a read replica fed by a sync job.

### 12. Add the Snowflake driver
Add `snowflake-sqlalchemy` to `requirements.txt`, rebuild the image, push a new tag (steps 1–2).

**What:** add the Python library that lets SQLAlchemy speak Snowflake's dialect, then bake
it into a new image version.

**Why:** SQLAlchemy is generic — it needs a driver per database to translate its calls into
the right wire protocol. Without `snowflake-sqlalchemy`, a `snowflake://...` URL just
errors. And because dependencies live *inside* the image, adding one means rebuilding and
pushing a fresh tag (e.g. `v2`); the old `v1` doesn't magically gain the driver.

**You fill in:** the new image tag (e.g. `v2`) to build/push after editing
`requirements.txt`.

**Creates:** an edited `requirements.txt` (local), and a new **image tag** `:v2` in the
ECR repo (in AWS).

### 13. Provision Snowflake `$$`
Create the database, schema, and a warehouse, plus a **read-only** role/user for the app
(least privilege — it must not be able to write).

**What:** set up the Snowflake side: a database + schema (where tables live) and a
*warehouse* (Snowflake's compute — the engine that actually runs your queries), plus a
dedicated login for the app that can only read.

**Why read-only / least privilege:** Snowflake here is an analytics *replica*, not the
source of truth — all real writes happen on RDS (step 17). If the app's Snowflake user
could write, a bug (or a malicious `/ask` query) could corrupt or diverge the analytics
copy. Granting only `SELECT` makes that impossible by design. This matters doubly for
banking data, where least-privilege access is a hard rule.

**You fill in / choose (in Snowflake):** database name, schema name, warehouse name +
size, and a **read-only role** + **user** (with a password or key-pair). Save all of these
for the `ANALYTICS_URL` in step 15.

**Creates (in Snowflake — not AWS, not the cluster):** a **database**, a **schema**, a
**warehouse** (compute), and a **role** + **user**.

**`$$` Cost (separate from AWS — not on the AWS free tier at all):** Snowflake bills
**credits** for warehouse compute whenever a query runs (an XS warehouse = 1 credit/hour,
billed per-second with a 60 s minimum), plus storage. Set **auto-suspend** (e.g. 60 s) so
the warehouse stops between queries. New accounts get a limited free trial credit.

### 14. Create the table in Snowflake
Create `transactions` (DDL, or `create_all` against the analytics engine). Same model,
different dialect.

**What:** create the `transactions` table in Snowflake so there's somewhere for the synced
rows (step 18) to land and for `/ask` to read from.

**Why "same model, different dialect":** the table mirrors the RDS one (same columns), but
Snowflake stores and types data differently under the hood (columnar, built for scanning
millions of rows). You reuse the same SQLAlchemy model definition; the Snowflake driver
translates it into Snowflake-flavored DDL. The shape matches so the sync can copy rows
1:1.

**You fill in:** nothing new — reuse the existing model; just target the analytics engine.

**Creates:** the **`transactions` table** inside the Snowflake database/schema from step 13
(empty until the sync runs).

### 15. Add the connection secret
Kubernetes Secret `ANALYTICS_URL`:
```
snowflake://<user>:<password>@<account>/<database>/<schema>?warehouse=<wh>&role=<role>
```
**What:** store the Snowflake connection string as a Kubernetes Secret named `ANALYTICS_URL`
(same pattern as `DATABASE_URL` in step 5).

**Why a separate `ANALYTICS_URL`:** the app now talks to *two* databases — RDS for writes
(`DATABASE_URL`) and Snowflake for analytics reads (`ANALYTICS_URL`). Keeping them as two
named secrets lets the code pick the right engine per operation (step 16) and lets you
point either at a different backend without touching the other. It's a secret because it
embeds the Snowflake password.

**You fill in (the URL placeholders, all from step 13):** `<user>`, `<password>`,
`<account>` (your Snowflake account identifier), `<database>`, `<schema>`, `<wh>`,
`<role>`.

**Creates:** a second **Secret** (`ANALYTICS_URL`) **in the cluster**, next to the step-5
Secret.

### 16. Wire up the second engine
In `app/database.py`, add an analytics engine that uses `ANALYTICS_URL` if set, else falls
back to the primary engine; point the `/ask` read tools at it:
```python
ANALYTICS_URL = os.getenv("ANALYTICS_URL")
analytics_engine = create_engine(ANALYTICS_URL, pool_pre_ping=True) if ANALYTICS_URL else engine
AnalyticsSession = sessionmaker(bind=analytics_engine, autoflush=False)
```
Route `_query_transactions` / `_query_balance` to `AnalyticsSession`.

**What:** give the app a *second* SQLAlchemy engine/session pointed at Snowflake, and send
the read-only `/ask` queries through it instead of through the RDS session.

**Why this exact shape:**
- `… if ANALYTICS_URL else engine` — the fallback. In local dev or Phase 1 there's no
  Snowflake, so the analytics session quietly reuses the primary engine. The code runs
  unchanged everywhere; only production sets `ANALYTICS_URL` to actually split the traffic.
- `pool_pre_ping=True` — Snowflake drops idle connections; this cheaply checks a connection
  is still alive before using it, avoiding "stale connection" errors.
- routing only `_query_*` to `AnalyticsSession` — reads go to the warehouse built for
  scanning; writes stay on RDS (next step). This is the read/write split.

**You fill in:** nothing manual — code only. It reads `ANALYTICS_URL` from the env
(step 15).

**Creates:** a code change in `app/database.py` (the `analytics_engine` / `AnalyticsSession`)
— ships in the next image build/push.

### 17. Keep writes on RDS
All writes **and** the account-exists check in `create_transfer` stay on `SessionLocal`
(RDS). Snowflake is read-only.

**What:** make sure every write path (and the validation that reads-before-writing, like
"does this account exist?") uses the RDS session, never the Snowflake one.

**Why:** RDS is the *source of truth* — the live, always-current, transactional database.
Snowflake is an eventually-consistent copy that lags behind by the sync interval (step 19).
If you checked "does the account exist?" against Snowflake, you might validate against stale
data and approve a bad transfer. Writes and correctness-critical checks must hit the
authoritative store; only tolerant analytics reads go to the replica.

**You fill in:** nothing — code only; just confirm no write path uses `AnalyticsSession`.

**Creates:** nothing new — a code change/verification in `app/main.py` (the write paths
stay on `SessionLocal`).

### 18. Add the sync job `$`
Load RDS → Snowflake on a schedule:
- Now: a `scripts/sync_to_snowflake.py` run as a Kubernetes **CronJob** (incremental by `created_at`).
- Later (on S3): **Snowpipe** auto-ingests files dropped in S3 for ~1-minute latency.

**What:** a recurring job that copies new rows from RDS into Snowflake so the analytics copy
stays reasonably fresh.

**Why a job at all:** Snowflake doesn't automatically know about RDS — they're two separate
systems. Something has to move the data. A Kubernetes **CronJob** runs your sync script on a
schedule (e.g. every few minutes), the cluster-native version of cron.

**Why "incremental by `created_at`":** re-copying the *entire* table every run gets slow and
wasteful as it grows. Tracking the latest `created_at` you've already synced lets each run
copy only the new rows since last time. **Snowpipe** (later) is the streaming upgrade: drop
files in S3 and Snowflake ingests them automatically within ~a minute, instead of batching
on a timer.

**You fill in:** the CronJob **schedule** (cron expr, e.g. `*/5 * * * *`) and the job's env
(both `DATABASE_URL` and `ANALYTICS_URL` secrets).

**Creates:** `scripts/sync_to_snowflake.py` + a CronJob YAML (local), and on apply a
**CronJob** object **in the cluster** that spins up a short-lived **Job/Pod** on each tick.

**`$` Cost:** the CronJob pod runs on nodes you already pay for (free incrementally), but
**every run wakes the Snowflake warehouse**, burning credits (step 13). A tight schedule
(e.g. every minute) keeps the warehouse busy and costs more — widen the interval and rely on
auto-suspend to keep it cheap.

### 19. Verify (mind the lag)
Write a row to RDS, run the sync, then confirm `/ask` analytics reflect it. Analytics are
eventually consistent — fresh up to the sync interval.

**What:** end-to-end test of the dual-engine setup — write to RDS, trigger the sync, then
ask `/ask` (which reads Snowflake) and confirm the new row shows up.

**Creates:** nothing — read-only checks (plus one test row in RDS that the sync copies to
Snowflake).

**Why "mind the lag":** unlike a single database where a write is instantly readable, here
there are two stores with a copy step between them. A row written to RDS *won't* appear in
`/ask` until the next sync runs — that delay (the sync interval) is the "eventual
consistency." Running the sync manually before checking removes that variable, so you're
testing the pipeline, not just waiting on the timer. This is expected behavior, not a bug:
analytics are fresh only up to the last sync.

**You fill in:** nothing — just run the sync manually once before checking `/ask`.

## End result — what you'll have

- A **public URL** (the load balancer address) serving the FastAPI app over the internet.
- The app running as **multiple pods** across EKS worker nodes — if one pod or node
  dies, Kubernetes reschedules it, so there's no single point of failure on the app tier.
- A **managed RDS PostgreSQL** database holding the `transactions` table, with
  persistence and automated backups — data survives pod/node restarts.
- The app **image versioned in ECR**, so deploys are repeatable and rollbacks are just
  pointing at a previous tag.
- **Secrets** (`ANTHROPIC_API_KEY`, DB password) kept out of code and YAML.

## What you'll be able to do

- Hit every REST endpoint (`/health`, `/transactions`, `/ask`) at `http://<lb-address>/...`
  from anywhere — e.g. drive it from Postman or a deployed UI.
- Use the LLM chat (`/ask`) and create transfers against the live RDS database.
- **Scale** by raising the pod replica count (or node count) to handle more load.
- **Update** by pushing a new image tag and re-applying the deployment (rolling update,
  no downtime).
- **Roll back** to a previous image tag if a release misbehaves.
- Inspect and operate the running system with `kubectl` (logs, pod status, restarts).

## Short version
**ECR (image) → EKS (cluster) → RDS (database, not in-cluster) → Secrets Manager (keys)
→ LoadBalancer/ALB (expose) → IRSA (S3 access).**

## Later / optional
- Observability (Phase 4): logs to Elasticsearch/Kibana or CloudWatch.
- Autoscaling: HPA + Cluster Autoscaler.
- IaC: move the above into Terraform for reproducibility.
