# infra

Local setup for `apps/extraction-pipeline`, for whichever host runs it.
One `Containerfile` builds the image, and one `Makefile` drives it per
runtime.

| `RUNTIME` | Host | What runs it |
|---|---|---|
| `apple` | macOS 26 on Apple silicon (default on macOS) | Apple [`container`](https://github.com/apple/container): image builds and one-off runs, plus a persistent **container machine** as the dev box |
| `kata` | Linux with KVM (default elsewhere) | Same image under Kata (`nerdctl --runtime io.containerd.kata.v2`) |
| `oci` | Anything with docker/podman/nerdctl | Same image, the engine's default runtime (CI, no Kata) |
| `native` | Any host with Python 3.11+ and rsync | A `.venv` in the app directory, no container |

```sh
make -C infra help          # targets for the detected RUNTIME
make -C infra doctor        # check the host has what RUNTIME needs
make -C infra setup         # build the image (native: create .venv)
make -C infra test
make -C infra run SRC=~/docs ARGS="snapshot /source"
make -C infra run ARGS="report"
```

Override anything on the command line, e.g. `RUNTIME=oci OCI=podman`, or
`KATA_RUNTIME=kata` for podman under Kata.

## Mounts

- `WORK` (default `apps/extraction-pipeline/work/`, gitignored) is mounted
  read-write at `/work`. All pipeline state lives there.
- `SRC` is mounted read-only at `/source` when set. Point `snapshot` and
  `index` at `/source`.
- `LANGEXTRACT_API_KEY` is passed through from the host if set.
- `--model-url` must be reachable from inside the VM. `localhost` is the VM
  itself, not your Mac or Linux host.

## Apple container machine

The machine boots from the same image, so dependencies are in `/opt/venv`.
The code is not copied into it. The machine mounts your home directory at
the same path, so it runs your live checkout; keep the repo under `$HOME`.
Anything you install inside the machine survives `machine-stop`.

```sh
make -C infra apple-system    # once: start services, install the kernel
make -C infra machine         # build the image, create the machine
make -C infra machine-test
make -C infra machine-run ARGS="report"
make -C infra machine-shell
make -C infra machine-deps    # after editing requirements.txt
make -C infra machine-rm      # start over
```

## Not yet tried

Nothing here has run on a real Apple machine or Kata host yet. Likely
first snags:

- Whether `container machine create` accepts this image as-is. Machines
  boot the image's init system, and `python:*-slim` ships none.
- rsync `-aAX` into a bind mount (ACLs and xattrs over virtiofs).
- File ownership in `WORK` when written from inside the VM.
