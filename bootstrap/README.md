# Homelab setup toolkit

A setup tool for hosts, applications and scheduled backup/notification jobs, and the existing GitOps
manifests as the source of application configuration. Introduced 2026-11-05.
No LLM, cloud assistant or new Python framework is needed to run it.

**Validation status (2026-11-05):** Local safety tests passed, along with Bash
syntax checks and workstation CLI/interactive-menu smoke tests. Cluster/host
mutations were mocked. Fresh Debian installation, worker join, real Secret updates and
Argo installation still require operator validation, preferably on a disposable
VM/namespace first. This toolkit is not yet a proven full-cluster rebuild tool.

Routine diagnosis uses raw commands in the operational runbooks. Read-only checks
here support setup; this is not a general troubleshooting console.

## Start safely

From the repository root:

```bash
bash bootstrap/bootstrap.sh --help
bash bootstrap/bootstrap.sh host check
bash bootstrap/bootstrap.sh app list
bash bootstrap/bootstrap.sh app guide nextcloud
bash bootstrap/bootstrap.sh
```

No arguments opens the menu in a terminal; noninteractive execution prints help.
The menu begins with a local read-only host check. `NO_COLOR=1` disables colour.
Use Python 3.10+; app manifest parsing needs PyYAML (Debian `python3-yaml`,
Arch/Omarchy `python-yaml`). Local host check/list/help do not need kubectl or
cluster access. Install dependencies using your OS package manager; the toolkit
does not alter an Omarchy workstation's package/system configuration.

For cluster operations use a working kubectl/kubeconfig, or on a k3s server:

```bash
bash bootstrap/bootstrap.sh --kubectl 'sudo k3s kubectl' argo check
bash bootstrap/bootstrap.sh --kubectl 'sudo k3s kubectl' app check nextcloud
bash bootstrap/bootstrap.sh --kubectl 'sudo k3s kubectl' app check nextcloud --inside
```

`--context NAME` selects a kubeconfig context. The toolkit prints the target
context/API before cluster operations. `--kubectl` is split into arguments without
a shell; do not supply pipes/redirections. Worker nodes usually do not have an
admin kubeconfig: perform cluster checks from the control plane/workstation.

## Command boundaries

| Command | Effect |
|---|---|
| `host check` | Read local OS, tools, swap state and GPU-device permissions |
| `app list`, `app guide NAME` | Offline repository inventory and Argo walkthrough |
| `argo check`, `app check NAME`, `app verify NAME` | Read cluster state; verify waits for rollouts, never triggers one |
| `app check nextcloud --inside` | Read-only file/access checks inside the existing Nextcloud container as www-data |
| `host packages [--ssh]` | Debian/root only; install missing packages, potentially starting package-provided services |
| `host control-plane --node-name NAME` | Fresh Debian/root only; install/start a new standalone k3s server |
| `host worker --node-name NAME --server https://HOST:6443` | Fresh Debian/root only; install/start agent using hidden join-token prompt |
| `host features [--with-qbittorrent]` | Debian/root only; BBR/sysctl prerequisite configuration, no k3s restart |
| `argo install` | Install pinned Argo with cluster-wide RBAC into a new namespace; no apps or external exposure |
| `argo access` | Print localhost access instructions; no changes |
| `app storage NAME` | Create missing namespace/PV/PVC objects only; never create NAS directories or overwrite existing objects |
| `app secrets NAME [--replace]` | Create missing required keys; explicit replacement rotates existing keys without restarting pods |
| `app stage database-backups` | First installation only: create missing backup/monitor resources with all schedules suspended; refuse existing CronJobs or Argo ownership |
| `app register NAME` | Create a missing canonical Argo Application; existing objects are never overwritten |

All mutation commands require a terminal confirmation. Prefix with `--dry-run`
to preview, for example `bootstrap.sh --dry-run app secrets nzbget`.
Dry run still performs read-only checks; it cannot bypass missing dependencies,
cluster access or fresh-host safety guards. Global flags go before subcommands.
No `--yes` bypass is provided. There is no automatic rollback after partial
failure: the error identifies the failed step; inspect state before retrying.

## Existing node and active streams

Start with checks only. Fresh-install commands refuse when any k3s binary,
configuration or node state is present. They are **not upgrade or recovery commands**.
Installing prerequisites may run package hooks. Node-feature configuration leaves
service restart pending for a maintenance window. The toolkit does not change
network addresses, disable swap, reboot, move GPU devices, install GPU drivers,
or restart existing workloads. App registration can start workloads if its
canonical sync policy is automatic; the walkthrough displays that policy first.

## Fresh control plane / worker

Review `versions.json`: it pins the observed control-plane version and Argo
version, not automatically the newest releases. Worker join uses the same k3s
pin; review compatibility with the actual server before joining. Existing worker
version skew is not changed by this toolkit. Do not select an existing node name.

1. Prepare Debian, unique hostname/IP, working DNS/time and firewall access.
2. Run `sudo bash bootstrap/bootstrap.sh host packages` (add `--ssh` if desired).
3. Review/disable swap persistently outside this toolkit; installation refuses
   active swap. Securely prepare the existing server's join token for a worker.
4. Run the appropriate `host control-plane` or `host worker` command.
   Installer downloads over HTTPS; the k3s release is pinned but the upstream
   installer script itself is fetched at execution time. Failed installs leave
   state for inspection instead of automatically deleting or reinstalling it.
5. Server installation waits for the exact named node's Ready condition. Worker
   service startup alone is not proof of Ready: verify on the control plane.
6. Configure optional `host features`; schedule the required k3s restart. This
   implementation does not optimize away a restart by running features before
   installation. GPU group IDs must be observed on the actual worker.
7. Run `argo install` against the new control plane, then `argo check`.

The worker token is stored in `/etc/rancher/k3s/join-token`, mode 600, referenced
by the root-only k3s configuration. It is never passed in command arguments.
The toolkit does not copy the administrative kubeconfig into user accounts.
Configure secure workstation access deliberately; never commit kubeconfigs.

## Application walkthrough

The toolkit discovers app directories and uses checked-in Application YAML when
available. For apps without a canonical Application file, `guide` suggests manual
settings but `register` refuses; add/review a definition first. It does not silently
create a second owner for a manually registered app.

Typical existing-state setup:

```bash
bash bootstrap/bootstrap.sh app guide nextcloud
bash bootstrap/bootstrap.sh --kubectl 'sudo k3s kubectl' app storage nextcloud
bash bootstrap/bootstrap.sh --kubectl 'sudo k3s kubectl' app secrets nextcloud
bash bootstrap/bootstrap.sh --kubectl 'sudo k3s kubectl' app check nextcloud
# Then either follow the manual Argo walkthrough or explicitly register:
bash bootstrap/bootstrap.sh --kubectl 'sudo k3s kubectl' app register nextcloud
# Review and Sync in Argo when the policy is manual, then:
bash bootstrap/bootstrap.sh --kubectl 'sudo k3s kubectl' app verify nextcloud
```

Registration does not silently change existing Application settings, sync an
existing app, or enable pruning. It detects another app using the same repository
path; Argo's FailOnSharedResource is still the protection against resource-level
overlap from different paths. Compare local checkout to the pushed Git revision:
local preparation checks are not proof that Argo is rendering the same commit.

Storage preparation creates Kubernetes objects from current manifests only.
Exports/directories, ACLs and private data must already be prepared on the NAS.
A Bound PVC is not proof that its path is accessible as the application user.
Nextcloud supports checking an **existing restored installation**; fresh application
initialization is not implemented. Preserve config.php, the required override,
matching database and .ncdata marker. See [recovery prerequisites](../docs/operations/application-state-recovery.md).

## Backup and Discord setup

`database-backups` is an infrastructure entry in `app list`, backed by
`cluster/infrastructure/backups`. No workload YAML is copied into bootstrap.

```bash
bash bootstrap/bootstrap.sh app guide database-backups
bash bootstrap/bootstrap.sh --kubectl 'sudo k3s kubectl' app storage database-backups
bash bootstrap/bootstrap.sh --kubectl 'sudo k3s kubectl' app secrets database-backups
bash bootstrap/bootstrap.sh --kubectl 'sudo k3s kubectl' app stage database-backups
```

For a **new** installation, prepare the NAS first, create credentials and stage
suspended schedules. Follow the [backup runbook](../cluster/infrastructure/backups/README.md)
for manual jobs, Discord activation and the manual-sync Argo registration.
The Secret prompt includes three database credential sets and the Discord webhook.
Explicit keys in Secret volume `items` are supported alongside `secretKeyRef`.

For the **existing** installed system, do not rerun stage: use reviewed manifest
updates through its deployment owner. Stage does not modify existing schedules,
restart services, run exports or send messages. It refuses partial existing
non-storage resources instead of overwriting them; inspect failures with kubectl.
Initial staging is tested with mocks, not yet operator-tested on a fresh cluster.
TrueNAS snapshot creation and off-machine replication remain external setup.

## Secrets

Required Secret keys are derived from secretKeyRef entries in rendered app
manifests. TLS Secrets managed by cert-manager are not manually generated.
Existing required keys are kept unless `--replace` is explicitly supplied.
Values are entered twice without echo, sent to kubectl through stdin, and read
back for an in-memory comparison. They are never printed or written to a
local temporary file. Secret-operation error payloads are suppressed because
API errors may echo values. Do not run under a debugger or terminal input recorder.

Existing controller-managed, immutable or non-Opaque Secrets are refused.
Updates preserve unrelated keys/metadata and use a resourceVersion test to reject
concurrent changes. Updating a Secret does not rotate an upstream credential or
restart a consumer: coordinate both sides and the maintenance window yourself.
Whole-secret references without declared keys need a documented schema instead
of guessed inputs. Hardcoded credentials in legacy manifests remain publication
review work; this command does not automatically migrate or rotate them.

## Layout and tests

- `bootstrap.sh`: small Bash entry point.
- `toolkit.py`: menu and CLI routing.
- `lib/common.py`: UI, bounded command runner and Kubernetes client.
- `lib/host.py`: host checks and guarded provisioning.
- `lib/argo.py`: pinned installation, checks and access guidance.
- `lib/apps.py`: manifest-driven guides, storage, Secrets and registration.
- `configure-traefik-bbr.sh`: retained proven sysctl helper.
- `*-application.yaml`: canonical app registrations, not duplicated workloads.
  These intentionally remain beside the toolkit; workload YAML stays in `cluster/apps/`.
- `edge-applications.yaml`: registration for the existing parent Application.
- `tests/`: local safety/behavior tests with no real cluster writes.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s bootstrap/tests -v
bash -n bootstrap/bootstrap.sh bootstrap/configure-traefik-bbr.sh
```

Operator test sequence: workstation help/check/list/guide → existing-node
host/Argo/app checks → dry-run storage/Secrets/registration → isolated real Secret
exercise → disposable Debian control plane/worker install. Record results before
claiming a workflow is live-tested. No Emby mutation is part of this test sequence.

References: [k3s install options](https://docs.k3s.io/reference/env-variables),
[k3s configuration](https://docs.k3s.io/installation/configuration),
[Argo declarative setup](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/).
