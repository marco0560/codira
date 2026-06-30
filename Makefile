UV := uv

MANIFEST ?= benchmarks/bk-cpp.local.json
NAME ?= repo
GUIDELINES_NAME ?= guidelines
RUNS ?=
WARMUP ?=
QUERY ?=
TOOL ?=
TAG ?=
REPO ?=
DEST ?=
BASE ?=
HEAD ?=
ARGS ?=

.DEFAULT_GOAL := .help

.PHONY: .help help
.PHONY: audit
.PHONY: benchmark-campaign benchmark-embedding-startup benchmark-index benchmark-release bootstrap bootstrap-dev build-first-party-packages build-release-artifacts
.PHONY: calibrate-embeddings-config changelog-guard check check-commit-messages clean-repo clean-repo-dry clean-repo-script configure-index-backend coverage-summary
.PHONY: demo docs-build
.PHONY: fix future-repo-export
.PHONY: gen-issues gen-miles gen-zip-common generate-github-snapshot
.PHONY: install-first-party-packages install-repo-config install-repo-git-config
.PHONY: lg
.PHONY: new-decision new-decision-alias
.PHONY: provision-embedding-model
.PHONY: re-clean rehearse-release-installs rel release-audit release-audit-script release-check release-rel-script release-system-selfcheck ri-fix run-manifest-baseline run-repo-tool run-with-repo-python
.PHONY: safe-push
.PHONY: tag-guard txz
.PHONY: validate-repo validate-semgrep-rules verify-exported-split-repos

.help: ## Show the list of supported Make targets
	@echo
	@echo "    Allowed targets are:"
	@grep -E '^[.a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "	\033[36m%-32s\033[0m %s\n", $$1, $$2}'
	@echo

help: .help ## Alias for .help

audit: ## Run scripts/audit.py; pass ARGS='--deep' for deep mode
	@$(UV) run python -m scripts.audit $(ARGS)
	@$(UV) run codira audit

benchmark-campaign: ## Run benchmark campaign; set MANIFEST and optional ARGS
	@$(UV) run python scripts/benchmark_campaign.py $(MANIFEST) $(ARGS)

benchmark-embedding-startup: ## Measure semantic startup costs; pass ARGS as needed
	@$(UV) run python scripts/benchmark_embedding_startup.py $(ARGS)

benchmark-index: ## Run one instrumented index benchmark; pass ARGS as needed
	@$(UV) run python scripts/benchmark_index.py $(ARGS)

benchmark-release: ## Run release Hyperfine benchmark plan; pass ARGS='--dry-run' to inspect
	@$(UV) run python scripts/benchmark_release.py $(ARGS)

calibrate-embeddings-config: ## Print hardware-calibrated [embeddings] config block
	@$(UV) run codira calibrate embeddings --print $(ARGS)

bootstrap-dev: ## Run repository bootstrap script
	@$(UV) run python scripts/bootstrap_dev_environment.py $(ARGS)

build-first-party-packages: ## Build/check first-party package wheels
	@$(UV) run python scripts/build_first_party_packages.py $(ARGS)

build-release-artifacts: ## Build/check release artifacts
	@$(UV) run python scripts/build_release_artifacts.py $(ARGS)

changelog-guard: ## Validate CHANGELOG.md against reachable release tag
	@$(UV) run python -m scripts.changelog_guard

check-commit-messages: ## Validate commit headers; set BASE and HEAD or pass ARGS
	@$(UV) run python scripts/check_commit_messages.py $(if $(BASE),--base $(BASE),) $(if $(HEAD),--head $(HEAD),) $(ARGS)

clean-repo-script: ## Run scripts/clean_repo.py directly
	@$(UV) run python scripts/clean_repo.py $(ARGS)

configure-index-backend: ## Configure index backend; pass ARGS such as '--backend sqlite'
	@$(UV) run python scripts/configure_index_backend.py $(ARGS)

coverage-summary: ## Render compact coverage summary from .coverage-report.json
	@$(UV) run python scripts/coverage_summary.py

demo: ## Run the Codira demo script
	@$(UV) run python scripts/demo.py $(ARGS)

future-repo-export: ## Export split repo; set REPO=<name> DEST=<path>
	@test -n "$(REPO)" || { echo "REPO is required"; exit 2; }
	@test -n "$(DEST)" || { echo "DEST is required"; exit 2; }
	@$(UV) run python scripts/future_repo_export.py $(REPO) $(DEST) $(ARGS)

generate-github-snapshot: ## Generate GitHub snapshot; pass ARGS='issues --output issues.json'
	@$(UV) run python scripts/generate_github_snapshot.py $(ARGS)

install-first-party-packages: ## Install editable first-party packages
	@$(UV) run python scripts/install_first_party_packages.py $(ARGS)

install-repo-git-config: ## Install repo-local Git config and aliases
	@$(UV) run python scripts/install_repo_git_config.py

new-decision: ## Create a new ADR; pass ARGS='--dry-run' to preview
	@$(UV) run python scripts/new_decision.py $(ARGS)

provision-embedding-model: ## Prefetch or verify local embedding model
	@$(UV) run python scripts/provision_embedding_model.py

rehearse-release-installs: ## Rehearse installed-wheel release validation
	@$(UV) run python scripts/rehearse_release_installs.py $(ARGS)

release-audit-script: ## Run scripts/release_audit.py directly
	@$(UV) run python -m scripts.release_audit

release-rel-script: ## Run scripts/release_rel.py directly
	@$(UV) run python -m scripts.release_rel

release-system-selfcheck: ## Run release tooling self-check
	@$(UV) run python -m scripts.release_system_selfcheck

ri-fix: ## Build a Codex prompt from codira ctx; set QUERY='...'
	@test -n "$(QUERY)" || { echo "QUERY is required"; exit 2; }
	@$(UV) run python scripts/ri_fix.py "$(QUERY)"

run-manifest-baseline: ## Run paired SQLite/DuckDB baseline; set MANIFEST or ARGS
	@$(UV) run python -m scripts.run_manifest_baseline $(MANIFEST) $(ARGS)

run-repo-tool: ## Run wrapped repo tool; set TOOL=<tool> and ARGS
	@test -n "$(TOOL)" || { echo "TOOL is required"; exit 2; }
	@$(UV) run python scripts/run_repo_tool.py $(TOOL) $(ARGS)

run-with-repo-python: ## Run Python args through repo interpreter; set ARGS
	@test -n "$(ARGS)" || { echo "ARGS is required"; exit 2; }
	@$(UV) run python -m scripts.run_with_repo_python $(ARGS)

tag-guard: ## Validate release tag format; set TAG=vX.Y.Z
	@test -n "$(TAG)" || { echo "TAG is required"; exit 2; }
	@$(UV) run python -m scripts.tag_guard $(TAG)

validate-repo: ## Run standard repository validation
	@$(UV) run python scripts/validate_repo.py $(ARGS)

validate-semgrep-rules: ## Validate repository Semgrep fixture expectations
	@$(UV) run python scripts/validate_semgrep_rules.py

verify-exported-split-repos: ## Verify exported split repositories; pass ARGS as needed
	@$(UV) run python scripts/verify_exported_split_repos.py $(ARGS)

lg: ## Git alias: log --oneline --graph --decorate -50
	@git log --oneline --graph --decorate -50 $(ARGS)

check: ## Git alias: run standard repository validation
	@$(UV) run python scripts/validate_repo.py $(ARGS)

fix: ## Git alias: ruff check --fix then ruff format through run_repo_tool.py
	@$(UV) run python scripts/run_repo_tool.py ruff check . --fix
	@$(UV) run python scripts/run_repo_tool.py ruff format .

clean-repo: ## Git alias: clean ignored repository artifacts
	@$(UV) run python scripts/clean_repo.py

clean-repo-dry: ## Git alias: preview ignored repository artifact cleanup
	@$(UV) run python scripts/clean_repo.py --dry-run

re-clean: ## Git alias: clean repo, refresh snapshots, and build repo archive
	@$(MAKE) clean-repo
	@$(MAKE) gen-issues
	@$(MAKE) gen-miles
	@$(MAKE) txz NAME=$(NAME)

bootstrap: ## Git alias: bootstrap development environment
	@$(UV) run python scripts/bootstrap_dev_environment.py $(ARGS)

new-decision-alias: ## Git alias: create a new ADR
	@$(UV) run python scripts/new_decision.py $(ARGS)

install-repo-config: ## Git alias: install repo-local Git config
	@$(UV) run python scripts/install_repo_git_config.py

docs-build: ## Git alias: build MkDocs documentation strictly
	@$(UV) run mkdocs build --strict

gen-issues: ## Git alias: write issues.json snapshot
	@$(UV) run python scripts/generate_github_snapshot.py issues --output issues.json

gen-miles: ## Git alias: write milestones.json snapshot
	@$(UV) run python scripts/generate_github_snapshot.py milestones --output milestones.json

txz: ## Git alias: archive tracked files plus snapshots; set NAME=repo
	@name="$(NAME)"; tmp="$$(mktemp -d)"; trap 'rm -rf "$$tmp"' EXIT; mkdir -p "$$tmp/repo"; { git ls-files -z; printf "%s\0" issues.json milestones.json; } | XZ_OPT="-9e -T0" tar --null -T - -cJf "$$PWD/$$name.tar.xz" --transform='s,^,repo/,'

gen-zip-common: ## Git alias: archive shared external ChatGPT guideline files; set GUIDELINES_NAME
	@name="$(GUIDELINES_NAME)"; tmp="$$(mktemp -d)"; trap 'rm -rf "$$tmp"' EXIT; mkdir -p "$$tmp/$$name"; [ -f "$$HOME/OneDrive/Documenti/Fontshow/Comuni/chatgpt_guidelines.md" ] && cp -f "$$HOME/OneDrive/Documenti/Fontshow/Comuni/chatgpt_guidelines.md" "$$tmp/$$name/" || true; [ -f "$$HOME/OneDrive/Documenti/Fontshow/Comuni/patch_discipline.md" ] && cp -f "$$HOME/OneDrive/Documenti/Fontshow/Comuni/patch_discipline.md" "$$tmp/$$name/" || true; [ -f "$$HOME/OneDrive/Documenti/Fontshow/Comuni/anti-hallucination.md" ] && cp -f "$$HOME/OneDrive/Documenti/Fontshow/Comuni/anti-hallucination.md" "$$tmp/$$name/" || true; XZ_OPT="-9e -T0" tar --sort=name --mtime="UTC 1970-01-01" --owner=0 --group=0 --numeric-owner -C "$$tmp" -cJf "$$PWD/$$name.tar.xz" "$$name"

release-audit: ## Git alias: run conservative release audit
	@$(UV) run python -m scripts.release_audit

release-check: ## Git alias: run release system self-check
	@$(UV) run python -m scripts.release_system_selfcheck

rel: ## Git alias: run guarded release push path
	@$(UV) run python -m scripts.release_rel

safe-push: ## Git alias: release audit, fetch, ff-only pull, then push
	@$(UV) run python -m scripts.release_audit
	@git fetch
	@git pull --ff-only
	@git push
