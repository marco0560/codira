## [2.0.1](https://github.com/marco0560/codira/compare/v2.0.0...v2.0.1) (2026-04-11)


### Bug Fixes

* **dev:** support split package install roots ([8a9d4d3](https://github.com/marco0560/codira/commit/8a9d4d382e5128022493999c8bb0e65dd5ab6284))

# [2.0.0](https://github.com/marco0560/codira/compare/v1.13.1...v2.0.0) (2026-04-10)


### Features

* **release:** prepare coordinated v2 multirepo release train ([47f707d](https://github.com/marco0560/codira/commit/47f707dd69b568af95bbcfe70b7e23e241d0d232))


### BREAKING CHANGES

* **release:** codira v2 publishes the official analyzers and SQLite backend as separate first-party distributions and resolves the official runtime through installed package metadata.

## [1.13.1](https://github.com/marco0560/codira/compare/v1.13.0...v1.13.1) (2026-04-10)


### Bug Fixes

* **dev:** skip curated bundle in local source installs by default ([bbfd0bc](https://github.com/marco0560/codira/commit/bbfd0bc3b672d474a65c1c896caf54701df9302e))

# [1.13.0](https://github.com/marco0560/codira/compare/v1.12.1...v1.13.0) (2026-04-10)


### Bug Fixes

* **packaging:** decouple local installs from curated bundle pins ([151c38c](https://github.com/marco0560/codira/commit/151c38c9ddb39c4d2916c4f37e897a80a86fcfb8))


### Features

* **cli:** report installed plugin versions in -V output ([4bdc265](https://github.com/marco0560/codira/commit/4bdc265971d5dd201cf9534dab9454f06a87ac4b))

## [1.12.1](https://github.com/marco0560/codira/compare/v1.12.0...v1.12.1) (2026-04-10)


### Bug Fixes

* **tooling:** ignore generated artifacts in mypy checks ([d792173](https://github.com/marco0560/codira/commit/d792173bc910b50b3b316f228bb646349ccdef09))
* **version:** stop tracking generated scm version file ([071ab0e](https://github.com/marco0560/codira/commit/071ab0eaebf40e6ff419888967fcc9140211d0ee))

# [1.12.0](https://github.com/marco0560/codira/compare/v1.11.0...v1.12.0) (2026-04-10)


### Bug Fixes

* **packaging:** add explicit source-tree install helper flow ([b3872e6](https://github.com/marco0560/codira/commit/b3872e663fd5dc578d54cef50b22bd662ffc5545))
* **packaging:** align bundle TestPyPI rehearsal metadata ([08c0618](https://github.com/marco0560/codira/commit/08c06189cd026f84b431ed59743a5b940af9f9d5))
* **packaging:** declare root package readme metadata ([189bab6](https://github.com/marco0560/codira/commit/189bab6a4e1218e77e98dca702c9e465840f0220))
* **packaging:** mark core codira package as typed ([87475db](https://github.com/marco0560/codira/commit/87475dbf4ababc706845d98bf7b20872e40799e1))
* **packaging:** pin bundle first-party dependencies ([3466f56](https://github.com/marco0560/codira/commit/3466f56f7973f3ba70c7222ada92ecdf14355044))
* **split:** add pre-publish split repo validation contract ([f3d726a](https://github.com/marco0560/codira/commit/f3d726a223dce488e726a2eca13e616a0e343315))
* **split:** keep core repo root metadata and workflow files ([293db4b](https://github.com/marco0560/codira/commit/293db4b0d71c475d558f451d3c039da21011a3e6))
* **split:** retain core changelog in exported repo ([7a3635a](https://github.com/marco0560/codira/commit/7a3635a4fcf2094881fe5e48d9859d80d2fad2e1))


### Features

* **packaging:** extract json analyzer package ([f759122](https://github.com/marco0560/codira/commit/f75912210a2ef390bb061d63910b927e5bb05973)), closes [#12](https://github.com/marco0560/codira/issues/12)
* **packaging:** extract python analyzer package ([2d0920a](https://github.com/marco0560/codira/commit/2d0920abbed2715171238f592131606160fb0b84)), closes [#12](https://github.com/marco0560/codira/issues/12)
* **packaging:** extract sqlite backend package ([f0d0a26](https://github.com/marco0560/codira/commit/f0d0a2698a9eeba516ad07b4f2e2afe61babfc13))
* **packaging:** move sqlite backend implementation into package ([c99477e](https://github.com/marco0560/codira/commit/c99477ee016e8ecfc52794e021f7746d61255e53))
* **release:** add artifact build plan helper ([b20e396](https://github.com/marco0560/codira/commit/b20e396a306cb378f107e71a0f40b5384f0f8cb0))
* **release:** add installed-wheel rehearsal helper ([9ceefde](https://github.com/marco0560/codira/commit/9ceefde8013fd83b83386a8c5e615fa9ee4c2615))
* **tooling:** add first-party package build rehearsal ([52ad6f6](https://github.com/marco0560/codira/commit/52ad6f641004315da6a3fe8dd974922ed218838b))
* **tooling:** add future repository export rehearsal ([23bd422](https://github.com/marco0560/codira/commit/23bd422924d29a14cdb31520fccdb760ba8ecd9d))
* **tooling:** validate package boundaries with wheel builds ([04e6f4d](https://github.com/marco0560/codira/commit/04e6f4d5b7e631044c394d9e83fd6750f3740a9b))

# [1.11.0](https://github.com/marco0560/codira/compare/v1.10.0...v1.11.0) (2026-04-09)


### Features

* **json:** support structured JSON families ([ccc1ba6](https://github.com/marco0560/codira/commit/ccc1ba690fabc475522417c61c02b85e3d9b835d)), closes [#7](https://github.com/marco0560/codira/issues/7)

# [1.10.0](https://github.com/marco0560/codira/compare/v1.9.0...v1.10.0) (2026-04-09)


### Features

* **json:** add initial schema analyzer ([1bc0d6b](https://github.com/marco0560/codira/commit/1bc0d6b87f979052b12831dcb9802e8ebf6f6084))

# [1.9.0](https://github.com/marco0560/codira/compare/v1.8.0...v1.9.0) (2026-04-05)


### Features

* **cli:** add bounded calls traversal ([b08db50](https://github.com/marco0560/codira/commit/b08db5016a4b79752243548204259235fc7b0238))
* **cli:** add bounded refs traversal ([776f3da](https://github.com/marco0560/codira/commit/776f3da17873ad57bc9c8eaa8d4880fd27f8f16e))
* **cli:** add dot export for bounded graph trees ([b4b37c3](https://github.com/marco0560/codira/commit/b4b37c3b73f6dc3f46c2bef0c24c7177f4423a29))
* Merge branch 'issue/10-call-graph-retrieval-producer' ([cf0277b](https://github.com/marco0560/codira/commit/cf0277bda946e928f3bb45c9aa851ad477672e07)), closes [#10](https://github.com/marco0560/codira/issues/10)
* **query:** add bounded graph retrieval to context ([2bd8570](https://github.com/marco0560/codira/commit/2bd857029e39dc69679ab1e4332807c88432c87e))
* **query:** extract graph enrichment orchestration ([f7ff579](https://github.com/marco0560/codira/commit/f7ff579391a888e37bc9003bcd64b058f2151514))
* **query:** extract graph producers and support monorepo analyzer fallback ([ab00b5a](https://github.com/marco0560/codira/commit/ab00b5a20531873ba248ce6350bcc8941ef19ff3))

# [1.8.0](https://github.com/marco0560/codira/compare/v1.7.1...v1.8.0) (2026-04-03)


### Features

* **cli:** enrich docstring audit results ([684915e](https://github.com/marco0560/codira/commit/684915e6e2eefaf2078d7abbe065c9fa213edf41))

## [1.7.1](https://github.com/marco0560/codira/compare/v1.7.0...v1.7.1) (2026-04-03)


### Bug Fixes

* **docstrings:** skip shell audit issues ([48329f4](https://github.com/marco0560/codira/commit/48329f45f4a94c5a271ac3c319ef73f94ec845f7))

# [1.7.0](https://github.com/marco0560/codira/compare/v1.6.1...v1.7.0) (2026-04-03)


### Features

* **cli:** add JSON output for index command ([a77f10d](https://github.com/marco0560/codira/commit/a77f10da7c4c966ba3e6181371bcb12b60cc8307))

## [1.6.1](https://github.com/marco0560/codira/compare/v1.6.0...v1.6.1) (2026-04-03)


### Bug Fixes

* **docstrings:** make audit-docstrings language-aware for current analyzers ([a40e90b](https://github.com/marco0560/codira/commit/a40e90bf255ded6e56b39b70a1b6c1dc7cc522bf))

# [1.6.0](https://github.com/marco0560/codira/compare/v1.5.0...v1.6.0) (2026-04-03)


### Features

* **embeddings:** batch index-time embedding generation ([c9d339e](https://github.com/marco0560/codira/commit/c9d339eddf09e859f89184c7f183dbb0f1b6b544))

# [1.5.0](https://github.com/marco0560/codira/compare/v1.4.0...v1.5.0) (2026-04-03)


### Features

* **packaging:** deprecate stale extras and label plugin origin ([a3d7a49](https://github.com/marco0560/codira/commit/a3d7a49bc0af4f31907bb03b4166a7618784e8b2))
* **packaging:** extract official analyzer packages ([c4197f8](https://github.com/marco0560/codira/commit/c4197f87b88ef515bfa24b76814249d720a5a254))

# [1.4.0](https://github.com/marco0560/codira/compare/v1.3.0...v1.4.0) (2026-04-02)


### Features

* **core:** add capability-driven retrieval signal layer ([d78b6bb](https://github.com/marco0560/codira/commit/d78b6bb8070e6dcea67994541951cfcd79b4274c)), closes [#9](https://github.com/marco0560/codira/issues/9)

# [1.3.0](https://github.com/marco0560/codira/compare/v1.2.1...v1.3.0) (2026-04-02)


### Bug Fixes

* **bash:** deduplicate redefined shell functions before indexing ([878dcb1](https://github.com/marco0560/codira/commit/878dcb1904c3ab74c1f86f38ad098a52fea147da))
* **index:** deduplicate C declarations and collapse index tracebacks ([55cafe1](https://github.com/marco0560/codira/commit/55cafe19a1ba284dbd29d33c95b947d3546aa2c0))
* **index:** disambiguate duplicate C function stable IDs with a deterministic suffix ([d6661a7](https://github.com/marco0560/codira/commit/d6661a7d0ee6ccc2532f168a1031a069f6269772))
* **index:** preserve stable ids across C and Python edge cases ([3d66264](https://github.com/marco0560/codira/commit/3d6626421efca2b0b566003eaf02b8d1deb46a9a))


### Features

* **analyzer:** add call site extraction to bash analyzer ([d38d1cf](https://github.com/marco0560/codira/commit/d38d1cf9412e05c9e47b5c950ba95b9dd680d4eb))
* **analyzers:** add BashAnalyzer for shell function extraction ([fb76aea](https://github.com/marco0560/codira/commit/fb76aeaa9ed362c3a1c56798e4036e56f5b505d3))

## [1.2.1](https://github.com/marco0560/codira/compare/v1.2.0...v1.2.1) (2026-03-30)


### Bug Fixes

* **parser:** ignore nested helper control flow in docstring metadata ([5511edc](https://github.com/marco0560/codira/commit/5511edc62bea935943bc173753ef45c697a44cc6))

# [1.2.0](https://github.com/marco0560/codira/compare/v1.1.1...v1.2.0) (2026-03-30)


### Bug Fixes

* **index:** preserve freshness metadata across queries ([3d314ea](https://github.com/marco0560/codira/commit/3d314eab7c94ac62ae2ea9c4af059c948b7b8db0))


### Features

* **index:** serialize rebuilds across processes ([0875b3f](https://github.com/marco0560/codira/commit/0875b3fc6018580b92a17c41daa33621c3d71c19))

## [1.1.1](https://github.com/marco0560/codira/compare/v1.1.0...v1.1.1) (2026-03-29)


### Bug Fixes

* **semantic:** streamline first-party embedding setup ([331e730](https://github.com/marco0560/codira/commit/331e730f5bab9bd6ed0a21ad6ed47ccb7746ebba))

# [1.1.0](https://github.com/marco0560/codira/compare/v1.0.3...v1.1.0) (2026-03-29)


### Features

* **semantic:** introduce real persisted embeddings with durable symbol identity ([cdc56b7](https://github.com/marco0560/codira/commit/cdc56b701dda5376ae0baeeaf57e421f8dc0bd7f)), closes [#1](https://github.com/marco0560/codira/issues/1)

## [1.0.3](https://github.com/marco0560/codira/compare/v1.0.2...v1.0.3) (2026-03-29)


### Bug Fixes

* **mypy:** tolerate optional tree-sitter imports ([42e94a1](https://github.com/marco0560/codira/commit/42e94a1dd77e33e0138f7424e5d6350802b03340))

## [1.0.2](https://github.com/marco0560/codira/compare/v1.0.1...v1.0.2) (2026-03-29)


### Bug Fixes

* **indexer:** keep indexing through parser warnings and failures ([8b6a021](https://github.com/marco0560/codira/commit/8b6a0211bd1c7b20a270c7eb50bf612016721d7f)), closes [#3](https://github.com/marco0560/codira/issues/3)

## [1.0.1](https://github.com/marco0560/codira/compare/v1.0.0...v1.0.1) (2026-03-29)


### Bug Fixes

* **c-analyzer:** skip malformed macro pseudo-functions ([57c3cc2](https://github.com/marco0560/codira/commit/57c3cc20015082cb28aa864eaf2f666c1c534a2b))

# [1.0.0](https://github.com/marco0560/codira/compare/v0.34.0...v1.0.0) (2026-03-29)


### Features

* **release:** promote stable major versioning ([c64aac1](https://github.com/marco0560/codira/commit/c64aac139970a1ef725413940f91b207ba3e6ce7))


### BREAKING CHANGES

* **release:** semantic-release now promotes breaking changes on the pre-1.0 line to major releases, so the next breaking publish from main enters the 1.x series instead of remaining on 0.x.

# [0.34.0](https://github.com/marco0560/codira/compare/v0.33.1...v0.34.0) (2026-03-29)


### Features

* **adr-004:** complete multi-language plugin architecture ([57526cc](https://github.com/marco0560/codira/commit/57526ccfee03fa8416472fc7dde4c917a878416a)), closes [#2](https://github.com/marco0560/codira/issues/2)


### BREAKING CHANGES

* **adr-004:** codira now assumes the ADR-004 plugin architecture. Third-party analyzers must register through the codira.analyzers entry-point group, provide deterministic discovery_globs metadata, and participate in plugin-aware coverage and rebuild semantics. Optional C-family support is no longer part of the core install and must be installed via the dedicated analyzer dependency path.

## [0.33.1](https://github.com/marco0560/codira/compare/v0.33.0...v0.33.1) (2026-03-28)


### Bug Fixes

* **release:** publish github releases ([208ce21](https://github.com/marco0560/codira/commit/208ce212f39f028cdd0316809e400d9256873288))

# [0.33.0](https://github.com/marco0560/codira/compare/v0.32.0...v0.33.0) (2026-03-28)


### Features

* **query:** add json output for exact query subcommands ([f3dd5e5](https://github.com/marco0560/codira/commit/f3dd5e5b190748aab125e28437303b4cf1b7f529))

# [0.32.0](https://github.com/marco0560/codira/compare/v0.31.4...v0.32.0) (2026-03-27)


### Features

* **prefix:** add repo-root scoped query filtering ([3a64334](https://github.com/marco0560/codira/commit/3a64334212b190e7d6d1f67376a67b6592b77251))

## [0.31.4](https://github.com/marco0560/codira/compare/v0.31.3...v0.31.4) (2026-03-27)


### Bug Fixes

* **docstring:** enforce python result-section semantics ([16f0f81](https://github.com/marco0560/codira/commit/16f0f8132fb916f4e225b5a92765cf62dd567da8))

## [0.31.3](https://github.com/marco0560/codira/compare/v0.31.2...v0.31.3) (2026-03-27)


### Bug Fixes

* **docstring:** require Yields for generator audits ([3a87e66](https://github.com/marco0560/codira/commit/3a87e6693617dc82183e58c7dce936e50588cca3))

## [0.31.2](https://github.com/marco0560/codira/compare/v0.31.1...v0.31.2) (2026-03-26)


### Bug Fixes

* **parser:** preserve chained attribute call sites ([bb9383a](https://github.com/marco0560/codira/commit/bb9383aed1a1a756ad74a890a1a99253ab888944))

## [0.31.1](https://github.com/marco0560/codira/compare/v0.31.0...v0.31.1) (2026-03-26)


### Bug Fixes

* **build:** introduced development dependencies in pyproject.toml ([ec86e71](https://github.com/marco0560/codira/commit/ec86e716e0acf92af0c3ca552937c4aa0f9c9397))
* normalize windows path handling ([69c5259](https://github.com/marco0560/codira/commit/69c5259d148b58b3a90b30f209b1b0cb033a7aee))

# [0.31.0](https://github.com/marco0560/codira/compare/v0.30.0...v0.31.0) (2026-03-25)


### Features

* add incremental indexing ([acea3a9](https://github.com/marco0560/codira/commit/acea3a9874a1ea6d0134f021fbf8b5ac3d2902e6))

# [0.30.0](https://github.com/marco0560/codira/compare/v0.29.1...v0.30.0) (2026-03-25)


### Features

* add embedding backend metadata ([7c418e8](https://github.com/marco0560/codira/commit/7c418e8c24cea4feb0ea8a37f4677d774d84af9f))
* expand context with graph relations ([3aa0d85](https://github.com/marco0560/codira/commit/3aa0d85301d37c17c735f4cb25d4125eaff7cb84))

## [0.29.1](https://github.com/marco0560/codira/compare/v0.29.0...v0.29.1) (2026-03-25)


### Bug Fixes

* reject mixed context output modes ([1856d6f](https://github.com/marco0560/codira/commit/1856d6f626d16ddfa3d351aef8d39be5f8cd898e))

# [0.29.0](https://github.com/marco0560/codira/compare/v0.28.0...v0.29.0) (2026-03-25)


### Features

* add deterministic embedding retrieval ([18257a7](https://github.com/marco0560/codira/commit/18257a7893e2ccc2e3076df0122e08b1153866c0))

# [0.28.0](https://github.com/marco0560/codira/compare/v0.27.4...v0.28.0) (2026-03-25)


### Bug Fixes

* improve cli help output ([0be499f](https://github.com/marco0560/codira/commit/0be499f9023d17422df8dcd4579aab78bce9eb29))


### Features

* add static call graph indexing ([d83fe90](https://github.com/marco0560/codira/commit/d83fe904f1646d2b08cfe56e7e5806e4c172f827))
* index callable references ([ecf9c1a](https://github.com/marco0560/codira/commit/ecf9c1a289397828e9764ab6f10ce7b2df898c8f))

## [0.27.4](https://github.com/marco0560/codira/compare/v0.27.3...v0.27.4) (2026-03-25)


### Bug Fixes

* clarify ri-fix help ([380eac3](https://github.com/marco0560/codira/commit/380eac353042388a2e8ac82931046c398e1f119c))

## [0.27.3](https://github.com/marco0560/codira/compare/v0.27.2...v0.27.3) (2026-03-25)


### Bug Fixes

* describe context-for help ([76dd9fe](https://github.com/marco0560/codira/commit/76dd9fe671be43def184df88d7cea3c29519e358))

## [0.27.2](https://github.com/marco0560/codira/compare/v0.27.1...v0.27.2) (2026-03-24)


### Bug Fixes

* **prompt:** added prompts for roadmap enhancements ([51721e1](https://github.com/marco0560/codira/commit/51721e1dfa5b3982427231c9aba0484b8a5d4f70))

## [0.27.1](https://github.com/marco0560/codira/compare/v0.27.0...v0.27.1) (2026-03-24)


### Bug Fixes

* **prompt:** enhanced criteria ([9d76f6d](https://github.com/marco0560/codira/commit/9d76f6db0fe45566e0f22dc593238225512f6ff3))

# [0.27.0](https://github.com/marco0560/codira/compare/v0.26.0...v0.27.0) (2026-03-24)


### Features

* **docstrings:** harden NumPy docstring audit engine ([b4e7b2d](https://github.com/marco0560/codira/commit/b4e7b2df077f702755c44aacb361c4106a73b668))

# [0.26.0](https://github.com/marco0560/codira/compare/v0.25.1...v0.26.0) (2026-03-24)


### Features

* **context:** improve deterministic context rendering quality ([6957b2d](https://github.com/marco0560/codira/commit/6957b2d62d5809f481e8669834508358babd0d7d))

## [0.25.1](https://github.com/marco0560/codira/compare/v0.25.0...v0.25.1) (2026-03-24)


### Bug Fixes

* **retrieval:** stabilize deterministic channel merge behavior ([7a24686](https://github.com/marco0560/codira/commit/7a24686a46648859d936fc3a2a73bba7b7abca86))

# [0.25.0](https://github.com/marco0560/codira/compare/v0.24.1...v0.25.0) (2026-03-24)


### Features

* **release:** stabilize tagging and guard commit scopes ([762c5f9](https://github.com/marco0560/codira/commit/762c5f955292f91bbd70eaf210bacb93c49afd14))

## [0.24.1](https://github.com/marco0560/codira/compare/v0.24.0...v0.24.1) (2026-03-24)


### Bug Fixes

* **release:** add package-lock for npm ci ([3f1c8f8](https://github.com/marco0560/codira/commit/3f1c8f8df1f670c45811d520ef6f8745771c6d47))
* **release:** lock semantic-release toolchain for CI ([4d38c4d](https://github.com/marco0560/codira/commit/4d38c4df70b2e20860fd581f93ded50c570bad75))


### Features

* **context,json-schema:** introduce schema v1.1 validation and fix explain contract ([4423ab5](https://github.com/marco0560/codira/commit/4423ab5668861c1710781b06c97421c888706ddd))

# [0.24.0](https://github.com/marco0560/codira/compare/v0.23.0...v0.24.0) (2026-03-24)


### Features

* **query:** introduce rank-based multi-channel retrieval with independent semantic channel ([282fc1e](https://github.com/marco0560/codira/commit/282fc1e102e5a6a0c24b6e28998e41d2a61ac5f3))

# [0.23.0](https://github.com/marco0560/codira/compare/v0.22.2...v0.23.0) (2026-03-24)


### Features

* **retrieval:** introduce semantic channel (deterministic token-overlap) ([3a49623](https://github.com/marco0560/codira/commit/3a49623eb684241fdf1ece7ba0d403ef298ede86))

## [0.22.2](https://github.com/marco0560/codira/compare/v0.22.1...v0.22.2) (2026-03-23)


### Bug Fixes

* **context:** complete JSON explain mode and stabilize explain output ([9d0fcc9](https://github.com/marco0560/codira/commit/9d0fcc911cd6c3adaf4d9cd671d6331c0b12a702))

## [0.22.1](https://github.com/marco0560/codira/compare/v0.22.0...v0.22.1) (2026-03-23)


### Bug Fixes

* **context:** propagate as_json and as_prompt flags to renderer ([e3eccd6](https://github.com/marco0560/codira/commit/e3eccd62559c439cfb711594533b990ae2f3dd97))

# [0.22.0](https://github.com/marco0560/codira/compare/v0.21.0...v0.22.0) (2026-03-23)


### Features

* **explain:** add merge provenance and winner attribution to explain mode ([538dd1e](https://github.com/marco0560/codira/commit/538dd1e71f2823f6015bfb9c732cbe6bdab94aa4))

# [0.21.0](https://github.com/marco0560/codira/compare/v0.20.0...v0.21.0) (2026-03-23)


### Features

* **cli,context:** introduce explain mode flag and plumbing ([49d8381](https://github.com/marco0560/codira/commit/49d8381fbca7150c99bbaadf2654a55594667adc))
* **explain:** add routing diagnostics and per-channel results to context output ([2a667cf](https://github.com/marco0560/codira/commit/2a667cf0915e63273295a0f0e1b432644ff338b4))

# [0.20.0](https://github.com/marco0560/codira/compare/v0.19.0...v0.20.0) (2026-03-22)


### Features

* **retrieval:** introduce intent-based channel routing and remove symbol scoring bias ([0590958](https://github.com/marco0560/codira/commit/05909588e905c8fee9ba7beb8801aa003afd60c7))

# [0.19.0](https://github.com/marco0560/codira/compare/v0.18.0...v0.19.0) (2026-03-22)


### Features

* **retrieval:** route channels by intent and remove symbol scoring bias ([9b3c987](https://github.com/marco0560/codira/commit/9b3c987616c139cc95dff4f88dfda2e409b7d3a1))

# [0.18.0](https://github.com/marco0560/codira/compare/v0.17.0...v0.18.0) (2026-03-22)


### Features

* **retrieval:** activate test and script channels in pipeline (phase 1 completion) ([474ee2b](https://github.com/marco0560/codira/commit/474ee2bf2b8fc000b42bccc4f7bcfd1a6dd87094))

# [0.17.0](https://github.com/marco0560/codira/compare/v0.16.0...v0.17.0) (2026-03-22)


### Features

* **retrieval:** introduce multi-channel retrieval (phase 1, symbol channel extraction) ([5785474](https://github.com/marco0560/codira/commit/578547499878fa88bf34561d1901718e6daa3705))

# [0.16.0](https://github.com/marco0560/codira/compare/v0.15.0...v0.16.0) (2026-03-22)


### Features

* **query:** add script-intent symmetry in classifier and scoring ([182563d](https://github.com/marco0560/codira/commit/182563d6601bd5349676c08044ccd59d2f30b5dc))

# [0.15.0](https://github.com/marco0560/codira/compare/v0.14.0...v0.15.0) (2026-03-22)


### Features

* **query:** introduce QueryIntent classification, integrate intent-aware scoring ([c9b7e59](https://github.com/marco0560/codira/commit/c9b7e593df529126333b558428849469c762630f))

# [0.14.0](https://github.com/marco0560/codira/compare/v0.13.0...v0.14.0) (2026-03-22)


### Features

* **codira:** extract agent prompt rendering into prompts module ([534f63e](https://github.com/marco0560/codira/commit/534f63e92280a0151873956b1e0f7eba7b7cadb2))

# [0.13.0](https://github.com/marco0560/codira/compare/v0.12.2...v0.13.0) (2026-03-22)


### Features

* **codira:** unify retrieval pipeline with single final ranking/pruning stage ([cdc81a5](https://github.com/marco0560/codira/commit/cdc81a5efe7b084cfbbaa9e63651e2ee203b4b7c))

## [0.12.2](https://github.com/marco0560/codira/compare/v0.12.1...v0.12.2) (2026-03-21)


### Bug Fixes

* **query:** add fallback retrieval when strong token filtering yields no results ([2d0ca92](https://github.com/marco0560/codira/commit/2d0ca92a382dce80a5cbe1c34173ed9e75bf0607))

## [0.12.1](https://github.com/marco0560/codira/compare/v0.12.0...v0.12.1) (2026-03-21)


### Bug Fixes

* **query:** prevent empty retrieval results with deterministic fallback ([16551ed](https://github.com/marco0560/codira/commit/16551ed38f0a32b2bb86be17da5d2b163f7da636))

# [0.12.0](https://github.com/marco0560/codira/compare/v0.11.1...v0.12.0) (2026-03-21)


### Features

* **context:** stabilize retrieval quality, packaging, and cleanup behavior ([bc4fee7](https://github.com/marco0560/codira/commit/bc4fee741acf1e7a872c91cfa9ae9795902ee649))

## [0.11.1](https://github.com/marco0560/codira/compare/v0.11.0...v0.11.1) (2026-03-21)


### Bug Fixes

* **clean:** preserve generated version file and reduce retrieval noise ([f335dba](https://github.com/marco0560/codira/commit/f335dbaa84d135877d5bcd05dedc24c901b424f4))

# [0.11.0](https://github.com/marco0560/codira/compare/v0.10.1...v0.11.0) (2026-03-21)


### Features

* **build:** added automatic git tags-based version number ([eb2ef18](https://github.com/marco0560/codira/commit/eb2ef18bd203b73f12bd2f3a724756cc167332bd))

## [0.10.1](https://github.com/marco0560/codira/compare/v0.10.0...v0.10.1) (2026-03-21)


### Bug Fixes

* **build:** enforced codira version coherent with git tags ([2e2b598](https://github.com/marco0560/codira/commit/2e2b59895004ef66d08bf728a6e9ff8255ed62a7))

# [0.10.0](https://github.com/marco0560/codira/compare/v0.9.0...v0.10.0) (2026-03-21)


### Features

* **context:** add token-based cap to JSON context rendering ([8c5e816](https://github.com/marco0560/codira/commit/8c5e816f94f64e57f27f93da42bb837ed68d4212))

# [0.9.0](https://github.com/marco0560/codira/compare/v0.8.0...v0.9.0) (2026-03-21)


### Features

* **context:** add confidence scores to top matches ([d19f77a](https://github.com/marco0560/codira/commit/d19f77a2d46f5e7a620f831b48a066d59b055bf4))

# [0.8.0](https://github.com/marco0560/codira/compare/v0.7.0...v0.8.0) (2026-03-21)


### Features

* **context:** deduplicate symbols and references for cleaner agent context ([a555d8b](https://github.com/marco0560/codira/commit/a555d8b9fad847888f7e17d294e694edd717044f))

# [0.7.0](https://github.com/marco0560/codira/compare/v0.6.0...v0.7.0) (2026-03-21)


### Features

* **context:** add test-aware reference prioritization ([9c43f97](https://github.com/marco0560/codira/commit/9c43f97a29ac609f959cde45d4acfec891566220))

# [0.6.0](https://github.com/marco0560/codira/compare/v0.5.0...v0.6.0) (2026-03-21)


### Features

* **query:** add issue-driven context enrichment ([2dcefad](https://github.com/marco0560/codira/commit/2dcefadb998764ca99bdf446ce612d706db35fe0))

# [0.5.0](https://github.com/marco0560/codira/compare/v0.4.0...v0.5.0) (2026-03-21)


### Features

* **index:** add lightweight unresolved call graph extraction ([a51a558](https://github.com/marco0560/codira/commit/a51a558be4737d0ee5b9491beaec2c8ccfee799e))

# [0.4.0](https://github.com/marco0560/codira/compare/v0.3.0...v0.4.0) (2026-03-21)


### Features

* **agent:** add Codex-ready prompt output for context-for ([e56083a](https://github.com/marco0560/codira/commit/e56083ad04b4c04340b2491a8537e332a15be694))

# [0.3.0](https://github.com/marco0560/codira/compare/v0.2.0...v0.3.0) (2026-03-21)


### Features

* **context:** add structured JSON output and improve context quality ([f5c784a](https://github.com/marco0560/codira/commit/f5c784ac17884a51424a076b8cda673971499e1c))

# [0.2.0](https://github.com/marco0560/codira/compare/v0.1.0...v0.2.0) (2026-03-21)


### Features

* **context:** JSON output, schema contract, CLI integration, context pipeline hardening ([eb89b16](https://github.com/marco0560/codira/commit/eb89b1697cb586f7886e5ef6201ca2b71020f5ee))
* **context:** stabilize context_for pipeline and align query with indexing ([382200b](https://github.com/marco0560/codira/commit/382200b61f39577f5a87b3f5563b4e96bc9eacc7))
* enable semantic release pipeline ([435ba80](https://github.com/marco0560/codira/commit/435ba80729bf66c48a3b041320b224a8c4da6efd))
* **shcema:** added schema for json output ([a0b7176](https://github.com/marco0560/codira/commit/a0b717607658688c23149674f65d18d0f9768269))
* test release pipeline ([e7fea68](https://github.com/marco0560/codira/commit/e7fea686be35400ba08233226f6ece53e9c91db1))

# Changelog

All notable changes to this project will be documented in this file.
