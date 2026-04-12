## [1.1.1](https://github.com/marco0560/codira/compare/v1.1.0...v1.1.1) (2026-04-12)


### Bug Fixes

* **coverage:** ignore py.typed files in coverage audit ([1edba6c](https://github.com/marco0560/codira/commit/1edba6c5a79e96846f74f8f79911c821be970fac))
* **indexer:** ignore .py.typed files in coverage audit ([7128c75](https://github.com/marco0560/codira/commit/7128c75929d9752b6c5df36bb4192dc61e44da24))

# [1.1.0](https://github.com/marco0560/codira/compare/v1.0.2...v1.1.0) (2026-04-12)


### Features

* **ci:** update sentence-transformers dependency to 5.4 ([0999d50](https://github.com/marco0560/codira/commit/0999d50d4e7346492cbeeaf3411380bb63e8cdaa))

## [1.0.2](https://github.com/marco0560/codira/compare/v1.0.1...v1.0.2) (2026-04-12)


### Bug Fixes

* **dev:** moved to poetry, fixed git aliases, added audit script ([4749487](https://github.com/marco0560/codira/commit/4749487d13298e75b882d2a7dd820e468abe25c1))

## [1.0.1](https://github.com/marco0560/codira/compare/v1.0.0...v1.0.1) (2026-04-12)


### Bug Fixes

* **version:** avoid generated module import in source checkouts ([137c239](https://github.com/marco0560/codira/commit/137c23943beca998ad2fcfe8f6365348234be403))

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
