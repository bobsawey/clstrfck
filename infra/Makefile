# Local setup for apps/extraction-pipeline, for whichever host runs it.
#
#   RUNTIME=apple   macOS on Apple silicon. Apple `container` builds and runs
#                   the image; a persistent container machine (machine-*)
#                   is the day-to-day dev box.
#   RUNTIME=kata    Linux host. Same image, run VM-isolated under Kata
#                   (default engine nerdctl + containerd shim).
#   RUNTIME=oci     Any OCI engine with its default runtime (docker, podman,
#                   nerdctl). CI, or a Linux box without Kata.
#   RUNTIME=native  Plain venv on the host, no container.
#
# RUNTIME defaults to apple on macOS and kata elsewhere. Works from anywhere:
#   make -C infra help        or        make -f infra/Makefile help

REPO := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))..)
APP  := $(REPO)/apps/extraction-pipeline

ifeq ($(shell uname -s),Darwin)
RUNTIME ?= apple
else
RUNTIME ?= kata
endif

IMAGE         ?= clstrfck/extraction-pipeline
TAG           ?= dev
IMAGE_REF     := $(IMAGE):$(TAG)
CONTAINERFILE ?= $(REPO)/infra/Containerfile

# Pipeline state. Gitignored (work/), mounted at /work in the container.
WORK ?= $(APP)/work
# Optional source tree to snapshot, mounted read-only at /source.
SRC  ?=
# Pipeline arguments after --work-dir, e.g. ARGS="snapshot /source".
ARGS ?= --help

MACHINE        ?= clstrfck
MACHINE_CPUS   ?= 4
MACHINE_MEMORY ?= 8G

KATA_RUNTIME ?= io.containerd.kata.v2
VENV         ?= $(APP)/.venv
PYTHON       ?= python3

ifeq ($(RUNTIME),apple)
OCI ?= container
else ifeq ($(RUNTIME),kata)
OCI ?= nerdctl
RUN_FLAGS += --runtime $(KATA_RUNTIME)
USER_FLAGS ?= --user $(shell id -u):$(shell id -g)
else ifeq ($(RUNTIME),oci)
OCI ?= docker
USER_FLAGS ?= --user $(shell id -u):$(shell id -g)
else ifneq ($(RUNTIME),native)
$(error RUNTIME must be apple, kata, oci or native (got "$(RUNTIME)"))
endif

# Interactive TTY only when there is one, so the progress keys work at a
# terminal and piped/CI runs stay plain.
TTY        := $(shell [ -t 0 ] && echo -it)
MOUNT_WORK  = --mount type=bind,source=$(abspath $(WORK)),target=/work
comma      := ,
# zsh (the macOS default) leaves SRC=~/... unexpanded, so expand ~ here.
SRC_PATH    = $(abspath $(patsubst ~%,$(HOME)%,$(SRC)))
MOUNT_SRC   = $(if $(SRC),--mount type=bind$(comma)source=$(SRC_PATH)$(comma)target=/source$(comma)readonly)
PASS_ENV    = -e LANGEXTRACT_API_KEY
PYTEST      = python -m pytest tests -q -p no:cacheprovider

.DEFAULT_GOAL := help
.PHONY: help doctor setup image test run shell \
        apple-system machine machine-deps machine-shell machine-test \
        machine-run machine-stop machine-rm machine-logs

help: ## List targets
	@echo "RUNTIME=$(RUNTIME)  (override: make RUNTIME=apple|kata|oci|native <target>)"
	@echo
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | \
		awk -F':.*## ' '{ printf "  %-14s %s\n", $$1, $$2 }'

doctor: ## Check this host has what RUNTIME needs
	@echo "RUNTIME=$(RUNTIME)  repo=$(REPO)"
ifeq ($(RUNTIME),apple)
	@[ "$$(uname -m)" = arm64 ] || echo "!! not Apple silicon: Apple container needs arm64"
	@echo "macOS $$(sw_vers -productVersion) (container needs 26+)"
	@command -v container >/dev/null || { echo "!! container CLI missing: install the .pkg from github.com/apple/container/releases"; exit 1; }
	@container --version
	@container system status >/dev/null 2>&1 && echo "container services running" || echo "!! services stopped: make apple-system"
	@case "$(REPO)" in "$$HOME"/*) ;; *) echo "!! repo is outside \$$HOME: the machine's home mount won't see it";; esac
else ifeq ($(RUNTIME),native)
	@$(PYTHON) -c 'import sys; assert sys.version_info >= (3, 11), sys.version' && $(PYTHON) --version
	@command -v rsync >/dev/null && echo "rsync ok" || echo "!! rsync missing (stage 0 snapshot needs it)"
else
	@command -v $(OCI) >/dev/null || { echo "!! $(OCI) missing (set OCI=...)"; exit 1; }
	@$(OCI) --version
endif
ifeq ($(RUNTIME),kata)
	@[ -e /dev/kvm ] && echo "/dev/kvm present" || echo "!! no /dev/kvm: Kata needs hardware virtualization"
	@command -v containerd-shim-kata-v2 >/dev/null && echo "kata shim ok" || echo "!! containerd-shim-kata-v2 not on PATH"
endif

setup: ## Build the image (native: create .venv, install requirements)
test: ## Run the test suite (in the image, or the .venv for native)
run: ## Run the pipeline: make run SRC=~/docs ARGS="snapshot /source"

ifeq ($(RUNTIME),native)

setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/pip install -r $(APP)/requirements.txt

test:
	cd $(APP) && $(VENV)/bin/$(PYTEST)

run:
	@mkdir -p $(WORK)
	cd $(APP) && $(VENV)/bin/python pipeline.py --work-dir $(abspath $(WORK)) $(ARGS)

else

setup: image

image: ## Build the image from infra/Containerfile
	$(OCI) build -t $(IMAGE_REF) -f $(CONTAINERFILE) $(APP)

test:
	$(OCI) run --rm $(RUN_FLAGS) $(USER_FLAGS) $(IMAGE_REF) $(PYTEST)

run:
	@mkdir -p $(WORK)
	$(OCI) run --rm $(TTY) $(RUN_FLAGS) $(USER_FLAGS) $(MOUNT_WORK) $(MOUNT_SRC) $(PASS_ENV) \
		$(IMAGE_REF) python pipeline.py --work-dir /work $(ARGS)

shell: ## Interactive shell in the image, with /work (and /source) mounted
	@mkdir -p $(WORK)
	$(OCI) run --rm -it $(RUN_FLAGS) $(USER_FLAGS) $(MOUNT_WORK) $(MOUNT_SRC) $(PASS_ENV) \
		$(IMAGE_REF) bash

endif

# --- Apple container machine: persistent dev box ---------------------------
# Built from the same image, so deps live in /opt/venv. Code is NOT copied
# in: the machine mounts your home directory read-write at the same path, so
# it runs the live checkout (the repo must live under $HOME). Filesystem
# changes inside the machine persist across stops.

apple-system: ## Start Apple container services (installs the kernel on first run)
	container system start --enable-kernel-install

machine: image ## Create the persistent dev machine from the image
	container machine create --name $(MACHINE) \
		--cpus $(MACHINE_CPUS) --memory $(MACHINE_MEMORY) $(IMAGE_REF)

machine-deps: ## Reinstall requirements in the machine (after editing requirements.txt)
	container machine run -n $(MACHINE) --root \
		/opt/venv/bin/pip install -r $(APP)/requirements.txt

machine-shell: ## Login shell in the machine, at the repo root
	container machine run -n $(MACHINE) -w $(REPO)

machine-test: ## Run the test suite in the machine against the live checkout
	container machine run -n $(MACHINE) -w $(APP) /opt/venv/bin/$(PYTEST)

machine-run: ## Run the pipeline in the machine: make machine-run ARGS="report"
	@mkdir -p $(WORK)
	container machine run -n $(MACHINE) $(TTY) -w $(APP) \
		/opt/venv/bin/python pipeline.py --work-dir $(abspath $(WORK)) $(ARGS)

machine-logs: ## Show the machine's boot log
	container machine logs --boot $(MACHINE)

machine-stop: ## Stop the machine (state persists)
	container machine stop $(MACHINE)

machine-rm: ## Delete the machine and everything installed in it
	container machine delete $(MACHINE)
