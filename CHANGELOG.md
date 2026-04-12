# Changelog

## 1.0.0 - 2026-04-11

### Added

- Publish the first public `codira` package set:
  - `codira`
  - `codira-analyzer-python`
  - `codira-analyzer-json`
  - `codira-analyzer-c`
  - `codira-analyzer-bash`
  - `codira-backend-sqlite`
  - `codira-bundle-official`
- Provide the `codira` CLI with the mnemonic command set:
  `index`, `cov`, `sym`, `emb`, `calls`, `refs`, `audit`, `ctx`, and
  `plugins`.
- Support installed first-party analyzer and backend discovery through
  `codira.analyzers` and `codira.backends` entry points.
- Provide the official bundle install target:
  `pip install codira-bundle-official`.

### Changed

- Rename the project from the historical working name `repoindex` to
  `codira`.
- Rename public Python packages, plugin packages, command names, state
  directory paths, environment variables, and plugin entry-point groups to the
  `codira` identity.
- Start the public `codira` release line at `1.0.0`.

### Notes

- The old `repoindex` repository remains public and archived for historical
  reference.
- The old `repoindex` package line is not a compatibility surface for
  `codira`.
