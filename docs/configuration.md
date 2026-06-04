# Configuration

Codira can run without a config file. Runtime commands create a default
user-level config on first use when the platform user config directory is
writable, and users can create or inspect config files explicitly with:

```bash
codira config init
codira config dump
codira config explain embeddings.batch_size
codira config validate
```

## Precedence

Effective configuration is resolved in this order:

```text
CLI flags
-> CODIRA_* environment variables
-> repository config: .codira/config.toml
-> user config: platform user config directory
-> system config: platform system config directory
-> built-in defaults
```

Repository config lives at `.codira/config.toml`. The file can be committed,
while normal `.codira` index artifacts remain ignored.

## Generated Config

The default generated file is:

```toml
config_version = 1

[backend]
name = "sqlite"

[plugins]
disable_third_party = false
disabled_analyzers = []

[embeddings]
enabled = true
model = "sentence-transformers/all-MiniLM-L6-v2"
version = "1"
dimension = 384
device = "cpu"
batch_size = 32
torch_num_threads = 0
torch_num_interop_threads = 0
```

`torch_num_threads = 0` and `torch_num_interop_threads = 0` mean Codira leaves
Torch defaults unchanged.

## Profiles

`codira config init --profile default` writes conservative defaults.

`codira config init --profile low-memory` lowers the embedding batch size and
sets conservative Torch thread counts.

`codira config init --profile gpu` selects a GPU-oriented device and larger
batch size. It does not auto-detect hardware.

## Environment Overrides

Existing process-local environment overrides still work and take precedence
over config files:

| Variable | Config key |
| --- | --- |
| `CODIRA_INDEX_BACKEND` | `backend.name` |
| `CODIRA_DISABLE_THIRD_PARTY_PLUGINS` | `plugins.disable_third_party` |
| `CODIRA_EMBED_BATCH_SIZE` | `embeddings.batch_size` |
| `CODIRA_EMBED_DEVICE` | `embeddings.device` |
| `CODIRA_TORCH_NUM_THREADS` | `embeddings.torch_num_threads` |
| `CODIRA_TORCH_NUM_INTEROP_THREADS` | `embeddings.torch_num_interop_threads` |

## Validation

Config validation is strict. Unknown keys, invalid types, invalid enum values,
and invalid numeric ranges fail before runtime work proceeds.
