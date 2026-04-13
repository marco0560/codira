## [1.1.7](https://github.com/marco0560/codira/compare/v1.1.6...v1.1.7) (2026-04-13)


### Bug Fixes

* **docs:** restore generated site navigation ([aab26df](https://github.com/marco0560/codira/commit/aab26df349c43ee433fa5a6bf213b77e5122ec74))

## [1.1.6](https://github.com/marco0560/codira/compare/v1.1.5...v1.1.6) (2026-04-13)


### Bug Fixes

* **ci:** made poetry play nice with scm-tools ([ba22c8f](https://github.com/marco0560/codira/commit/ba22c8fae2d4f89eeeab1380f3646cb8418305b9))
* **tests:** update dependency versions in test ([8e6d29e](https://github.com/marco0560/codira/commit/8e6d29e41e7f85ce0063b5cef28133700ffe52d3))

## [1.1.5](https://github.com/marco0560/codira/compare/v1.1.4...v1.1.5) (2026-04-13)


### Bug Fixes

* **ci:** fetch tags for editable package versions ([1664f42](https://github.com/marco0560/codira/commit/1664f4276b7a484d05be06bb1edb1dc029a020e4))

## [1.1.4](https://github.com/marco0560/codira/compare/v1.1.3...v1.1.4) (2026-04-13)


### Bug Fixes

* **ci:** keep core checkout installed during package setup ([5b6281f](https://github.com/marco0560/codira/commit/5b6281f2d147ae51c951eee40fdaf5745472ed99))

## [1.1.3](https://github.com/marco0560/codira/compare/v1.1.2...v1.1.3) (2026-04-12)


### Bug Fixes

* **ci:** tighten versioning configuration ([c38c777](https://github.com/marco0560/codira/commit/c38c777a23fa5524ed7b3b7341225d13f2194b13))
* **dev:** typo in script ([9dc1990](https://github.com/marco0560/codira/commit/9dc19905bc4833f31afba83cd8778c092192ae7f))

## [1.1.2](https://github.com/marco0560/codira/compare/v1.1.1...v1.1.2) (2026-04-12)


### Bug Fixes

* **ci:** update pyproject.toml for versioning and packaging ([d570b87](https://github.com/marco0560/codira/commit/d570b876ccb8ae9bcac6449eeaa0aad65d4fc926))

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
