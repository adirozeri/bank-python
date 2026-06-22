# Minikube Practice Summary: Deploying bank-python with Postgres

This document covers everything done in this session, from checking prerequisites through deploying a two pod application (FastAPI app plus Postgres database) on a local Minikube cluster.

## 1. Checking Prerequisites

Before installing anything, we verified the machine could actually run Minikube.

```bash
nproc
```
Prints the number of CPU cores available. Minikube needs at least 2, the machine had 4.

```bash
free -h
```
Shows total, used, and available RAM in human readable units (GB/MB). Minikube's default cluster allocation is around 2 to 4GB, so enough free memory matters.

```bash
df -h /
```
Shows disk space on the root filesystem in human readable form. Needed a few GB free for the Minikube node image plus container images.

```bash
uname -m
```
Prints the CPU architecture. `x86_64` confirms the standard amd64 binaries are the correct ones to download (as opposed to `aarch64` for ARM machines).

```bash
which curl
```
Confirms `curl` is installed, since it is needed to download the Minikube and kubectl binaries.

```bash
docker --version
docker ps
```
Confirms Docker is installed and that the current user can actually talk to the Docker daemon. `docker ps` failed initially with a permission denied error.

### The Docker Permission Issue

Docker's daemon listens on a Unix socket at `/var/run/docker.sock`. That socket is owned by root and a group called `docker`. Only root or members of the `docker` group can talk to it, this is a deliberate security boundary, since anyone who can talk to the Docker daemon can effectively gain root level access to the host (containers can be configured to access the host filesystem).

```bash
sudo usermod -aG docker $USER
```
Adds the current user to the `docker` group. This does not take effect immediately in an already running shell, because group membership is read once at login time and baked into that shell's process.

```bash
newgrp docker
```
Starts a new shell with the `docker` group applied immediately, without requiring a full logout. This is a temporary fix scoped to that one terminal session only. Any brand new terminal opened later will not have this until a full logout and login (or reboot) happens, since that is when the login session re-reads group membership.

After running `newgrp docker`, `docker ps` worked without `sudo`.

## 2. Installing Minikube and kubectl

```bash
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
```
Downloads the Minikube binary for Linux amd64. `-L` follows redirects (the "latest" URL redirects to a specific versioned file). `-O` saves the file using its original filename in the current directory.

```bash
sudo install minikube-linux-amd64 /usr/local/bin/minikube
```
`install` is a coreutils program (same family as `cp`, `mv`, `chmod`) that copies a file to a destination and sets its permissions in a single step, originally built for use in software build scripts (`make install`). This copies the downloaded binary into `/usr/local/bin` (a directory already on the system `PATH`) and names it `minikube`, while also setting the executable permission bit. `sudo` is required because `/usr/local/bin` is owned by root.

For a single self contained binary like this, that copy plus permission step is the entire "installation," there is no daemon to register, no config files to generate, and no service to start. The moment the file exists on the `PATH` with execute permission, typing `minikube` from any directory finds and runs it.

```bash
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
```
Two curl calls nested together. The inner one (`curl -L -s https://dl.k8s.io/release/stable.txt`) fetches a plain text file containing the current stable Kubernetes version string (e.g. `v1.31.0`), `-s` suppresses progress output so only the version string is captured. That output is substituted into the outer URL via `$(...)`, so the outer `curl -LO` downloads the kubectl binary matching whatever is currently the stable release.

```bash
sudo install kubectl /usr/local/bin/kubectl
```
Same idea as the Minikube install, copies the downloaded `kubectl` binary into `/usr/local/bin` so it is runnable from anywhere.

## 3. Starting the Cluster

```bash
minikube start --driver=docker
```

This single command does a lot. Conceptually:

1. **Driver check**: confirms `--driver=docker` was requested and checks that the Docker daemon is reachable through `/var/run/docker.sock`.
2. **Image pull**: downloads the "kicbase" image (a Linux system with Kubernetes pre baked in) if not already cached, plus a "preload" bundle of commonly needed Kubernetes component images bundled together for faster startup.
3. **Container creation**: Docker creates and starts one container from that kicbase image, capped at a default of 2 CPUs and ~3900MB RAM. This container acts as the entire Kubernetes node.
4. **Bootstrapping**: internally uses `kubeadm` to initialize the node, generate certificates, and start the control plane processes (`etcd`, `kube-apiserver`, `kube-scheduler`, `kube-controller-manager`), plus `kubelet` (the agent that manages pods on the node).
5. **Networking setup**: configures a bridge CNI (Container Networking Interface) so pods can get IP addresses and communicate.
6. **kubectl configuration**: writes/updates `~/.kube/config` so that `kubectl` automatically knows the address and credentials for this new cluster, setting it as the "current context."
7. **Addons**: enables `storage-provisioner` and `default-storageclass` by default.

### Understanding the Docker-in-Docker Layering

With `--driver=docker`, Minikube does not create a real virtual machine. Instead it creates one Docker container that itself contains an entire fake "machine":

```
Your laptop (Ubuntu)
   Docker daemon (the one checked with docker ps)
         ONE container, named "minikube"
               This container = the Kubernetes "node"
               Inside this node, running as processes/containers:
                   etcd
                   kube-apiserver
                   kube-scheduler
                   kube-controller-manager
                   kubelet
                   its own inner Docker daemon
                         this is what runs application pods later
```

That outer container behaves, from Kubernetes' own perspective, as if it were a separate physical machine, it does not know it is itself just a container on the real machine.

Because there is only one node in this setup, that single container is doing double duty: it is both the **control plane** (running `kube-apiserver`, `etcd`, `kube-scheduler`, the cluster's "brain") and the **worker** (the node that actually runs application pods). In a real production cluster these roles are usually split across dedicated control plane nodes and separate worker nodes, but for a local single node Minikube cluster, one node plays both parts.

Since pods run inside that *inner* Docker daemon (nested inside the minikube container), building an image normally with `docker build` on the laptop would not be visible to Kubernetes, the inner Docker daemon has a completely separate image store. This is why `eval $(minikube docker-env)` is used later, it points the current shell's `docker` commands at Minikube's internal Docker daemon instead of the laptop's normal one.

Verifying the cluster came up:

```bash
kubectl get nodes
```
Confirmed one node in `Ready` status.

## 4. Kubernetes Core Concepts (as discussed)

- **Cluster**: one or more nodes plus the relationships/state between them. With a single node Minikube setup, that one node *is* the entire cluster.
- **Node**: a machine (real, virtual, or in this case a Docker container) that can run pods.
- **Pod**: the smallest deployable unit in Kubernetes, wraps one or more tightly coupled containers.
- **Control plane components**: `kube-apiserver` (front door, every `kubectl` command talks to this), `etcd` (database storing all cluster state), `kube-scheduler` (decides which node a new pod should run on), `kube-controller-manager` (background reconciliation loops, e.g. restarting crashed pods).
- **Worker nodes**: run the actual application pods, receiving instructions from the API server via their local `kubelet`.

In this Minikube setup, the single node was labeled the "primary control-plane node" in the startup output, meaning it runs the control plane *and* serves as the only available place to run pods.

## 5. Preparing the Application for Containerization

The app (`bank-python`) originally used SQLite with an environment driven connection string:

```python
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./bank.db")
```

A prompt was given to Claude Code to:
- Add Postgres support (`psycopg2-binary`) to `requirements.txt`, alongside catching a missing transitive dependency (`langchain-anthropic`) that would have crashed the container on startup.
- Make `connect_args` in `app/database.py` conditional on whether the URL is SQLite or not, so SQLite specific options (`check_same_thread: False`) are not applied to Postgres.
- Add `pool_pre_ping=True` to the SQLAlchemy engine, which validates a connection before use, preventing stale connection errors when Postgres drops idle connections (common in Kubernetes environments).
- Create a `Dockerfile` and `.dockerignore` for the app.
- Keep `DATABASE_URL` purely environment driven, no hardcoded Postgres string anywhere in the code.

Key correction Claude Code made: the brief assumed `uvicorn main:app`, but the actual FastAPI object lives at `app.main:app` (no root level `main.py`). Using the wrong module path would have caused `ModuleNotFoundError` inside the container.

It also flagged that the app needs **two** environment variables at runtime, not just `DATABASE_URL`: also `ANTHROPIC_API_KEY`, since `app/llm.py` imports `langchain_anthropic` at module load time.

## 6. Building the Docker Image Inside Minikube

```bash
eval $(minikube docker-env)
```
Redirects the current shell's `docker` command to talk to the Docker daemon running *inside* the Minikube node container, instead of the laptop's normal Docker daemon. This only applies to the current shell session, a new terminal would need to re-run this.

```bash
cd ~/projects/bank-python
docker build -t bank-python:latest .
```
Builds the image using the Dockerfile in the current directory, tagging it `bank-python:latest`. Because the prior `eval` redirected Docker, this image is built directly inside Minikube's internal Docker daemon, exactly where Kubernetes will look for it later.

`docker build` builds a Docker image from the Dockerfile in the current directory.

`-t bank-python:latest` tags (names) the resulting image as `bank-python` with tag `latest`.

`.` is the build context, the current directory, telling Docker where to find the Dockerfile and any files it needs to copy (like `requirements.txt` and your source code).

Since this ran after `eval $(minikube docker-env)`, the image gets built inside Minikube's internal Docker daemon rather than your laptop's, so Kubernetes can find it directly without needing to pull it from anywhere.


Verified with:
```bash
docker images | grep bank-python
```
Confirmed an image named `bank-python:latest`, about 228MB, was present.

Important nuance: this build only creates an **image** (a static template), not a running container. Nothing is executing yet at this point, `docker ps` would still show nothing related to this image.

## 7. The Kubernetes YAML Manifests

Four objects were created: a Deployment and a Service for Postgres, and a Deployment and a Service for bank-python.

### postgres-deployment.yaml

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: postgres-deployment
spec:
  replicas: 1
  selector:
    matchLabels:
      app: postgres
  template:
    metadata:
      labels:
        app: postgres
    spec:
      containers:
        - name: postgres
          image: postgres:16
          ports:
            - containerPort: 5432
          env:
            - name: POSTGRES_USER
              value: "bankuser"
            - name: POSTGRES_PASSWORD
              value: "bankpass"
            - name: POSTGRES_DB
              value: "bankdb"
```

`replicas: 1` runs exactly one pod, appropriate for a single instance database (running multiple independent Postgres pods would each have their own separate storage and would not share data). `selector.matchLabels` and `template.metadata.labels` both carry `app: postgres`, this is how the Deployment identifies which pods belong to it, and it is the same label the matching Service will use to find these pods. There is no persistent volume attached here, meaning any data is lost if this pod is deleted or restarted, acceptable for practicing the mechanics, but the first thing to fix (with a PersistentVolumeClaim) for anything real.

### postgres-service.yaml

```yaml
apiVersion: v1
kind: Service
metadata:
  name: postgres-service
spec:
  selector:
    app: postgres
  ports:
    - port: 5432
      targetPort: 5432
```

No `type` is specified, so this defaults to `ClusterIP`, meaning it is only reachable from inside the cluster, appropriate for a database that should never be exposed externally. The `selector: app: postgres` routes traffic to whichever pod currently carries that label, regardless of which specific pod instance it is (pods can be replaced, restarted, or get new IPs, the Service abstracts that away). Other pods in the cluster can now reach Postgres using the hostname `postgres-service`, Kubernetes runs an internal DNS that resolves Service names automatically.

### bank-python-deployment.yaml

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: bank-python-deployment
spec:
  replicas: 1
  selector:
    matchLabels:
      app: bank-python
  template:
    metadata:
      labels:
        app: bank-python
    spec:
      containers:
        - name: bank-python
          image: bank-python:latest
          imagePullPolicy: Never
          ports:
            - containerPort: 8000
          env:
            - name: DATABASE_URL
              value: "postgresql://bankuser:bankpass@postgres-service:5432/bankdb"
            - name: ANTHROPIC_API_KEY
              value: "your-key-here"
```

`imagePullPolicy: Never` tells Kubernetes not to attempt pulling this image from any external registry, since it was built directly inside Minikube's internal Docker daemon and already exists locally there. Without this setting, Kubernetes would default to trying to pull from a registry and fail, since this image was never pushed anywhere.

The `DATABASE_URL` hostname is `postgres-service`, not an IP address, this is the Service DNS name from the previous file doing its job, the app finds the database by a stable name rather than a changeable pod IP.

### bank-python-service.yaml

```yaml
apiVersion: v1
kind: Service
metadata:
  name: bank-python-service
spec:
  type: NodePort
  selector:
    app: bank-python
  ports:
    - port: 8000
      targetPort: 8000
      nodePort: 30080
```

`type: NodePort` makes this Service reachable from outside the cluster, from the laptop's browser or `curl`, on a fixed port (`30080` here), unlike the Postgres Service which only needed to be reachable from other pods inside the cluster.

## 8. How Deployments Work

A **Deployment** is a Kubernetes object whose entire job is to keep a specified number of identical pod replicas running and healthy, automatically, without manual intervention. It does this through a continuous reconciliation loop:

1. The Deployment spec declares a desired state: "I want N pods running, using this exact pod template (image, ports, env vars, labels)."
2. The `kube-controller-manager` (a control plane component) constantly compares that desired state against the actual state of the cluster.
3. If a pod crashes, gets deleted, or the node it was on disappears, the controller notices the actual count has dropped below the desired count and creates a new pod from the same template to make up the difference.
4. If the Deployment's pod template itself changes (a new image tag, for example) and `kubectl apply` pushes that change, the Deployment performs a rolling update: gradually creating new pods with the new template and terminating old ones, rather than an abrupt full replacement, so the application stays available throughout.

A Deployment never directly "is" a pod, it sits one level above pods, owning and managing them indirectly. In between, there is actually a hidden object called a ReplicaSet that the Deployment creates and manages, the ReplicaSet is what directly owns the pods, but in normal day to day use this is mostly invisible, working with `kubectl get deployments` is enough.

This is precisely why `kubectl get deployments` showed `READY: 1/1` for both: the Deployment declared it wanted 1 pod, and the controller confirmed exactly 1 matching, healthy pod currently exists.

## 9. Applying the Manifests

```bash
kubectl apply -f k8s/postgres-deployment.yaml
kubectl apply -f k8s/postgres-service.yaml
kubectl apply -f k8s/bank-python-deployment.yaml
kubectl apply -f k8s/bank-python-service.yaml
```

`kubectl apply -f <file>` reads a YAML file and either creates the resource described in it (if it does not yet exist) or updates it to match (if it already exists). Postgres was applied first specifically so it would be available before bank-python's pod tried to connect to it on startup.

`kubectl apply` is declarative and safe to re run, applying the same unchanged file again simply reports `unchanged`, it does not duplicate or break anything.

To reset and reapply a specific object cleanly:

```bash
kubectl delete -f <file>
kubectl apply -f <file>
```

`kubectl delete -f <file>` reads the file and deletes exactly the resource kind and name defined inside it, useful for guaranteeing you are removing/recreating precisely the right object rather than relying on memory of what was previously typed.

## 10. Verifying the Deployment

```bash
kubectl get deployments
```
Shows `READY`, `UP-TO-DATE`, and `AVAILABLE` counts per Deployment. Both `bank-python-deployment` and `postgres-deployment` showed `1/1`, meaning the desired pod count matched the actual healthy pod count for each.

```bash
kubectl get services
```
Showed `postgres-service` as `ClusterIP` (internal only) and `bank-python-service` as `NodePort` with mapping `8000:30080/TCP` (internal port 8000, externally reachable via node port 30080). A third Service, `kubernetes`, always exists by default and is how pods communicate with the API server itself.

```bash
kubectl get pods
```
Showed both pods with `STATUS: Running` and `READY: 1/1`, with `RESTARTS: 0`, indicating neither pod crashed.

```bash
kubectl logs deployment/bank-python-deployment
```
Showed Uvicorn starting cleanly and binding to `0.0.0.0:8000`, with "Application startup complete," indicating the app connected to Postgres successfully (a failed DB connection would typically show a traceback during this startup phase).

## 11. Reaching the App From Outside the Cluster

```bash
minikube service bank-python-service --url
```
Asks Minikube to compute and print the correct URL to reach a NodePort service from outside the cluster. With the Docker driver, the node's IP is not necessarily the laptop's own IP directly, Minikube handles that translation.

```bash
curl http://192.168.49.2:30080/docs
```
Returned `{"detail":"Not Found"}`. Despite looking like an error, this actually confirmed the entire chain was working end to end: the request traveled from the laptop, through the NodePort, into the cluster, to the bank-python pod, and FastAPI itself responded with its own JSON 404 handler. The 404 was specific to the `/docs` route not existing (likely disabled in the `FastAPI()` constructor, e.g. `docs_url=None`), not a sign of any networking or deployment failure.

## 12. Summary of What Now Exists

- A local single node Kubernetes cluster, running as one Docker container (`minikube`) on the laptop, that container itself serving as both control plane and worker node.
- A Postgres pod (`postgres-deployment`), reachable internally only, via `postgres-service:5432`.
- A bank-python pod (`bank-python-deployment`), built from an image created directly inside Minikube's internal Docker daemon, reachable externally via `bank-python-service` on node port `30080`.
- Both pods communicating successfully: the app connected to the database on startup without errors.
- Four YAML manifest files on disk under `k8s/`, fully reproducible with `kubectl apply -f k8s/<file>.yaml`.

## 13. Known Simplifications (Worth Revisiting Later)

- Secrets (`ANTHROPIC_API_KEY`, the Postgres password) are stored as plain environment variables directly in the YAML, fine for local practice, but not appropriate for anything real, since the values are visible in plaintext to anyone who can read the YAML file or run `kubectl describe pod`. A Kubernetes `Secret` object would be the correct mechanism for this.
- The Postgres pod has no `PersistentVolumeClaim`, so all data is lost if that pod is ever deleted or rescheduled.
- `Base.metadata.create_all` is being used to create tables on app startup rather than a proper migration tool (Alembic), fine for now, but worth revisiting before this resembles a production setup.