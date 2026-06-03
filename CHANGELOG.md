## [1.42.2](https://github.com/marco0560/codira/compare/v1.42.1...v1.42.2) (2026-06-03)


### Bug Fixes

* **cli:** help was absent in capability contracts ([68c0125](https://github.com/marco0560/codira/commit/68c0125663eeb55fa835baa160472b1f1e823686))

## [1.42.1](https://github.com/marco0560/codira/compare/v1.42.0...v1.42.1) (2026-06-03)


### Bug Fixes

* **bootstrap:** update uv uninstall command ([8210b90](https://github.com/marco0560/codira/commit/8210b90b96488a29573dcaad3cd6b61df9764a90))

# [1.42.0](https://github.com/marco0560/codira/compare/v1.41.0...v1.42.0) (2026-06-03)


### Bug Fixes

* **schema:** declare docs capability channel ([affa206](https://github.com/marco0560/codira/commit/affa2068940bb64bc9d50c367e9aac60be600f3a))


### Features

* **analyzer:** add documentation source extraction ([85bb995](https://github.com/marco0560/codira/commit/85bb995d37c165468adf09d554b75ced2f18714f))
* **analyzer:** add text documentation analyzer ([e71623b](https://github.com/marco0560/codira/commit/e71623bbfc796adf878beac71c571c80676b1e9f))
* **analyzer:** index doxygen documentation artifacts ([3b93c02](https://github.com/marco0560/codira/commit/3b93c02bf09bce1e933dc8be2b970cd3eab67bc4))
* **backend:** persist documentation embeddings ([b10cce9](https://github.com/marco0560/codira/commit/b10cce923522edc8897c486ae7c8d36195444ca8))
* **cli:** add docs retrieval command ([4bc6a17](https://github.com/marco0560/codira/commit/4bc6a17f342a2c6876087ee5a2e10b1cb5fd53d8))
* **context:** add docs retrieval channel ([426b22a](https://github.com/marco0560/codira/commit/426b22a36f8accaeee5c404ce919107b1ae2b53b))
* **context:** add docs v2 ranking safeguards ([7fe1858](https://github.com/marco0560/codira/commit/7fe18583773ba6a3f9efddc7248eeda26ee446a9))
* **context:** add documentation retrieval channel ([f9cff90](https://github.com/marco0560/codira/commit/f9cff90a13bf8629e64d2b9b652b9dc1023353fb)), closes [#3](https://github.com/marco0560/codira/issues/3) [#3](https://github.com/marco0560/codira/issues/3)
* **context:** boost docs path documentation ([cb23611](https://github.com/marco0560/codira/commit/cb236117e85a43f650a6a76e7ebb88ba1101b0d9)), closes [#3](https://github.com/marco0560/codira/issues/3)
* **contracts:** add documentation artifact model ([8951bda](https://github.com/marco0560/codira/commit/8951bdaba6a7654b46fe2641914451108b87d5ad)), closes [#3](https://github.com/marco0560/codira/issues/3)

# [1.41.0](https://github.com/marco0560/codira/compare/v1.40.1...v1.41.0) (2026-06-02)


### Features

* **query:** complete signal aggregation migration ([82a9e8d](https://github.com/marco0560/codira/commit/82a9e8d19c909da120ece8ce5614dd34ce7bb6e0)), closes [#32](https://github.com/marco0560/codira/issues/32)
* **query:** merge signal aggregation migration ([247ec7c](https://github.com/marco0560/codira/commit/247ec7ccde0a3efbb54cb8c57de890d83717b5fe)), closes [#32](https://github.com/marco0560/codira/issues/32)

## [1.40.1](https://github.com/marco0560/codira/compare/v1.40.0...v1.40.1) (2026-06-01)


### Bug Fixes

* **dev:** paginate GitHub snapshot aliases ([9b8f043](https://github.com/marco0560/codira/commit/9b8f043dad206885201893d026f79beed5bd823a)), closes [#29](https://github.com/marco0560/codira/issues/29)

# [1.40.0](https://github.com/marco0560/codira/compare/v1.28.0...v1.40.0) (2026-05-31)


### Release

* **package:** align core, plugin, backend, and bundle release metadata at 1.40.0

# [1.28.0](https://github.com/marco0560/codira/compare/v1.27.0...v1.28.0) (2026-05-31)


### Bug Fixes

* **storage:** rebuild stale schema indexes ([0d916b7](https://github.com/marco0560/codira/commit/0d916b710a626f6c7aa6b622f8aca1d48ab5d0bc))


### Features

* **analyzer:** label unresolved relation targets ([98ee863](https://github.com/marco0560/codira/commit/98ee863d1f96fd8f2e83de4965a3cc4f34e5a852))
* **analyzer:** merge unresolved target labels ([0dde33e](https://github.com/marco0560/codira/commit/0dde33e3a7a67dce874d6bf21da8a7e5367cb8fd)), closes [#31](https://github.com/marco0560/codira/issues/31)

# [1.27.0](https://github.com/marco0560/codira/compare/v1.26.1...v1.27.0) (2026-05-31)


### Features

* **dev:** rename baseline script and add manifest argument ([5ef6c5d](https://github.com/marco0560/codira/commit/5ef6c5d347b31c602b1b305de9f0c3ae18e0f4f5))

## [1.26.1](https://github.com/marco0560/codira/compare/v1.26.0...v1.26.1) (2026-05-31)


### Bug Fixes

* **package:** handle benchmark indexing edge cases ([0c83ccc](https://github.com/marco0560/codira/commit/0c83ccce993cb05e4fd51ece85e748e01fb997ac))

# [1.26.0](https://github.com/marco0560/codira/compare/v1.25.0...v1.26.0) (2026-05-28)


### Bug Fixes

* **backend:** DuckDB now rebuilds derived graph tables ([3606042](https://github.com/marco0560/codira/commit/36060425a906fa154779bdd22cc7447823de1fe8))
* **cli:** Invalid --path values now fail with a message ([b62d4aa](https://github.com/marco0560/codira/commit/b62d4aaf3280eb818f374767bcf718ef045065d4))
* **indexer:** reuse backend warm-planning connection ([45cfc60](https://github.com/marco0560/codira/commit/45cfc6098a30c34cf9de3268f61e4551584f361b))


### Features

* **backend:** harden backend storage boundaries ([062f080](https://github.com/marco0560/codira/commit/062f080b525b6df7f76a1426cb22e55ad9d4fa82))
* **backend:** refactor index sessions and validation tooling ([c7c3ff1](https://github.com/marco0560/codira/commit/c7c3ff166ed8355a01540c97dd28a6d30a28072f))


### Performance Improvements

* **backend:** batch DuckDB relationship writes ([f393e57](https://github.com/marco0560/codira/commit/f393e5798a475c06bdc10a15a718a313dc3a1b97))
* **backend:** batch DuckDB structural writes ([0bc74a7](https://github.com/marco0560/codira/commit/0bc74a7dab11aa00184dbea43e68246a5c72981d)), closes [#30](https://github.com/marco0560/codira/issues/30)
* **backend:** complete DuckDB backend performance work ([e72e57d](https://github.com/marco0560/codira/commit/e72e57d2f78b7eeac4329a7d85c46bb86024e751)), closes [#30](https://github.com/marco0560/codira/issues/30) [#30](https://github.com/marco0560/codira/issues/30)
* **backend:** index DuckDB symbol detail lookups ([7e0a257](https://github.com/marco0560/codira/commit/7e0a257bb8ed43bdf0cfb1a889930a1516988602))
* **backend:** score DuckDB embeddings in SQL ([9172664](https://github.com/marco0560/codira/commit/9172664fdc0b5185608a29a8bf356e8713b9b58a))
* **backend:** stabilize benchmark runtime measurements ([46d9fa4](https://github.com/marco0560/codira/commit/46d9fa49bf408dd760d23ac3dabe3a4632498856))
* **backend:** stabilize DuckDB reused embedding counts ([12c118d](https://github.com/marco0560/codira/commit/12c118de23fbe02bd1956d964ab01080f8df7013)), closes [#30](https://github.com/marco0560/codira/issues/30)
* **backend:** tune DuckDB warm and graph lookups ([4c5ed48](https://github.com/marco0560/codira/commit/4c5ed48cbca110c490857a6efdf7d43ef67a4a81))
* **cli:** skip backend freshness reads for queries ([ce9d784](https://github.com/marco0560/codira/commit/ce9d7847cc62dbacd97719d4cddb3c1a53476b68)), closes [#30](https://github.com/marco0560/codira/issues/30)
* **context:** narrow docstring issue lookups ([b17cfde](https://github.com/marco0560/codira/commit/b17cfde5d473adbfcec663acd37194e7ea47767f)), closes [#30](https://github.com/marco0560/codira/issues/30)
* **embeddings:** batch session embedding writes ([879689e](https://github.com/marco0560/codira/commit/879689e25a7e3c5077c6d66bfe1a9dbd309f7095))
* **indexer:** skip rebuild after failure-only runs ([8b4aaec](https://github.com/marco0560/codira/commit/8b4aaecb87e51abe44da11c33c99f97507dfa266))
* **semantic:** raise default embedding batch size ([9182584](https://github.com/marco0560/codira/commit/91825847d419f7bfb667a160ea527133f8a6d94a)), closes [#30](https://github.com/marco0560/codira/issues/30)

# [1.25.0](https://github.com/marco0560/codira/compare/v1.24.2...v1.25.0) (2026-05-20)


### Features

* **analyzer:** add first-party c++ analyzer ([195b8ee](https://github.com/marco0560/codira/commit/195b8eeca19fd1962f356657173807ab29aba737))
* **analyzer:** merge c++ analyzer branch ([adc67a7](https://github.com/marco0560/codira/commit/adc67a7261dab050d45cca296be1ee0659588337))

## [1.24.2](https://github.com/marco0560/codira/compare/v1.24.1...v1.24.2) (2026-05-18)


### Bug Fixes

* **dev:** eliminated null-byte artifact that failed github action ([2ce1c7f](https://github.com/marco0560/codira/commit/2ce1c7f5ec976c971265fb763c1c525194c11b92))

## [1.24.1](https://github.com/marco0560/codira/compare/v1.24.0...v1.24.1) (2026-05-17)


### Bug Fixes

* **cli:** mark the active backend in plugin reports ([9e52022](https://github.com/marco0560/codira/commit/9e52022994ec557d8418b35d55bea2126d5cf33a))

# [1.24.0](https://github.com/marco0560/codira/compare/v1.23.7...v1.24.0) (2026-05-17)


### Bug Fixes

* **dev:** resolve semgrep from repo interpreter env ([0a0118f](https://github.com/marco0560/codira/commit/0a0118fa2945d9034b6ccb95ed198adbc5094cc2))
* **tests:** keep wheel discovery build offline-safe ([24a684b](https://github.com/marco0560/codira/commit/24a684bf58198a0c039a66136f54b48ba95c6a02))


### Features

* **config:** add allowlisted semgrep architecture guardrails ([f3ff8cd](https://github.com/marco0560/codira/commit/f3ff8cd01746382e1565de514da9862166f433ae))
* **config:** complete phase 3 semgrep policy integration ([91b0c3c](https://github.com/marco0560/codira/commit/91b0c3c9aae61c8373dcbdc761f90880fc3ad03f))
* **config:** integrate semgrep into repository validation ([c162061](https://github.com/marco0560/codira/commit/c162061b3beaa3b951bb9b269260a2a13a32a2fe)), closes [#13](https://github.com/marco0560/codira/issues/13)
* **config:** introduce initial semgrep architecture rules ([40c332a](https://github.com/marco0560/codira/commit/40c332ad228f6881e38c76869ea7a8c5aaff0ad4)), closes [#13](https://github.com/marco0560/codira/issues/13)
* **config:** route semgrep state through repo tool runner ([877748d](https://github.com/marco0560/codira/commit/877748da9334d40d561ef3a9e80750369de471e8))
* **config:** simplify repo tool runner and coverage reporting ([54b98c5](https://github.com/marco0560/codira/commit/54b98c51989c1fb24317e68be6e11194f9d36b79)), closes [#13](https://github.com/marco0560/codira/issues/13)
* **dev:** integrate semgrep guardrails ([bc71818](https://github.com/marco0560/codira/commit/bc71818f317106a65dc06d4b56c8df25fba4343e)), closes [#13](https://github.com/marco0560/codira/issues/13)

## [1.23.7](https://github.com/marco0560/codira/compare/v1.23.6...v1.23.7) (2026-05-16)


### Bug Fixes

* **contracts:** harden analyzer and backend typing invariants ([331f352](https://github.com/marco0560/codira/commit/331f3524d233549aa70bf0a189cd1ce3948d2c73))

## [1.23.6](https://github.com/marco0560/codira/compare/v1.23.5...v1.23.6) (2026-05-09)


### Bug Fixes

* **tests:** fixed test for ci environment not providing pip ([90e4428](https://github.com/marco0560/codira/commit/90e4428fa754543361bb1bf47739d84c05bc22e2))

## [1.23.5](https://github.com/marco0560/codira/compare/v1.23.4...v1.23.5) (2026-05-09)


### Bug Fixes

* **backend:** restore DuckDB parity with SQLite index behavior ([a46a9db](https://github.com/marco0560/codira/commit/a46a9db9a428c39fe9f01db67618375c592d07a9)), closes [#10](https://github.com/marco0560/codira/issues/10)

## [1.23.4](https://github.com/marco0560/codira/compare/v1.23.3...v1.23.4) (2026-05-09)


### Bug Fixes

* **backend:** replace DuckDB savepoints with shared transactions ([2193b60](https://github.com/marco0560/codira/commit/2193b60b3db2e9213c1dfd7886b8176ea07ae7e7)), closes [#10](https://github.com/marco0560/codira/issues/10)

## [1.23.3](https://github.com/marco0560/codira/compare/v1.23.2...v1.23.3) (2026-05-09)


### Bug Fixes

* **dev:** make repo tooling backend-aware and uv-native ([0c3090a](https://github.com/marco0560/codira/commit/0c3090ac6601348c36d24642f55ee3faf46d8a93))

## [1.23.2](https://github.com/marco0560/codira/compare/v1.23.1...v1.23.2) (2026-05-09)


### Bug Fixes

* **ci:** make repo validation uv-native ([306849e](https://github.com/marco0560/codira/commit/306849e7bce83f4ed614b07dd51772487a9cd540))

## [1.23.1](https://github.com/marco0560/codira/compare/v1.23.0...v1.23.1) (2026-05-09)


### Bug Fixes

* **dev:** protected from clean-repo deletion the benchmarks directory ([911ccf5](https://github.com/marco0560/codira/commit/911ccf560f14038e5ab3df03c367cb1761d7237d))

# [1.23.0](https://github.com/marco0560/codira/compare/v1.22.1...v1.23.0) (2026-05-09)


### Features

* **backend:** implement duckdb backend lifecycle ([835d2d6](https://github.com/marco0560/codira/commit/835d2d6f4065a059bed1b7b7e6cbf9d1eb4724de))
* **backend:** integrate duckdb activation path ([0efb1f8](https://github.com/marco0560/codira/commit/0efb1f8638bf9bbb5eecf45abbf2847f3f2066f0))
* **backend:** scaffold duckdb backend package ([d18b0bc](https://github.com/marco0560/codira/commit/d18b0bcee62f1bfc01d43dccecb7a6d7b91e0c0a))

## [1.22.1](https://github.com/marco0560/codira/compare/v1.22.0...v1.22.1) (2026-05-03)


### Bug Fixes

* **dev:** aligned git alias generation and test to current repo config ([2c3ee94](https://github.com/marco0560/codira/commit/2c3ee9431fccd3c66de10629a317d0402aac51a1))

# [1.22.0](https://github.com/marco0560/codira/compare/v1.21.8...v1.22.0) (2026-05-03)


### Features

* **query:** persist ctx reference scan rows ([325491f](https://github.com/marco0560/codira/commit/325491f28764588fa3886fbada641df80f55fe90))

## [1.21.8](https://github.com/marco0560/codira/compare/v1.21.7...v1.21.8) (2026-05-03)


### Bug Fixes

* **dev:** aligned AGENTS file to repo structure ([b32cb32](https://github.com/marco0560/codira/commit/b32cb3220df6aa6ea0c0238861041e5fe823f396))

## [1.21.7](https://github.com/marco0560/codira/compare/v1.21.6...v1.21.7) (2026-05-02)


### Bug Fixes

* **indexer:** clarify uncovered analyzer coverage message ([b8c01d2](https://github.com/marco0560/codira/commit/b8c01d22f90a225118cbe816582ed6715772f378))

## [1.21.6](https://github.com/marco0560/codira/compare/v1.21.5...v1.21.6) (2026-05-02)


### Performance Improvements

* **embeddings:** dedupe repeated embedding payloads ([e90c441](https://github.com/marco0560/codira/commit/e90c441658849e7fe6f1be88614e07bdf913dca0))

## [1.21.5](https://github.com/marco0560/codira/compare/v1.21.4...v1.21.5) (2026-05-02)


### Performance Improvements

* **analyzer:** short-circuit JSON analyzer admission ([6039f22](https://github.com/marco0560/codira/commit/6039f22d4f3e835b4d28e6c121696fab6241ff65))

## [1.21.4](https://github.com/marco0560/codira/compare/v1.21.3...v1.21.4) (2026-05-02)


### Performance Improvements

* **query:** bound graph expansion seed fanout ([17bc237](https://github.com/marco0560/codira/commit/17bc237106e7babd10461e817d5bb7319a81fa77))

## [1.21.3](https://github.com/marco0560/codira/compare/v1.21.2...v1.21.3) (2026-05-02)


### Performance Improvements

* **context:** cache reference scan file views ([d5d2a59](https://github.com/marco0560/codira/commit/d5d2a592381e4036dda230ffb62bf07c38191661))

## [1.21.2](https://github.com/marco0560/codira/compare/v1.21.1...v1.21.2) (2026-05-02)


### Performance Improvements

* **semantic:** cache embedding startup helpers ([8998959](https://github.com/marco0560/codira/commit/89989599edec00d49484cb1d06afca570c448ced))

## [1.21.1](https://github.com/marco0560/codira/compare/v1.21.0...v1.21.1) (2026-05-02)


### Performance Improvements

* **registry:** cache plugin discovery snapshots ([8556093](https://github.com/marco0560/codira/commit/85560939f68ed0f138209065c6d44233a469c420))

# [1.21.0](https://github.com/marco0560/codira/compare/v1.20.0...v1.21.0) (2026-05-01)


### Features

* **dev:** adapt benchmark campaign commands per repo ([53fa36f](https://github.com/marco0560/codira/commit/53fa36fd1ab62b2deb566789dd9b7bb0cd69036b))

# [1.20.0](https://github.com/marco0560/codira/compare/v1.19.4...v1.20.0) (2026-05-01)


### Features

* **dev:** extend benchmark campaign command matrix ([a8bcab4](https://github.com/marco0560/codira/commit/a8bcab42193046652ec7ad61ae98334042ecbf77))

## [1.19.4](https://github.com/marco0560/codira/compare/v1.19.3...v1.19.4) (2026-05-01)


### Bug Fixes

* **dev:** harden benchmark campaign startup checks ([7b61f70](https://github.com/marco0560/codira/commit/7b61f70d9b22cdf67f2f3e37ae38f5131bf34182))

## [1.19.3](https://github.com/marco0560/codira/compare/v1.19.2...v1.19.3) (2026-04-30)


### Bug Fixes

* **dev:** capture black wrapper output ([e1a8c4e](https://github.com/marco0560/codira/commit/e1a8c4ede6c30bcc0275280e2e8729f7966ca3f7))

## [1.19.2](https://github.com/marco0560/codira/compare/v1.19.1...v1.19.2) (2026-04-30)


### Bug Fixes

* **dev:** route phase benchmarks through output dir ([004fc51](https://github.com/marco0560/codira/commit/004fc51d7c19c15c94ce93dbd25730b0ac2b081e))

## [1.19.1](https://github.com/marco0560/codira/compare/v1.19.0...v1.19.1) (2026-04-30)


### Bug Fixes

* **dev:** isolate benchmark campaign indexes ([09c5c8c](https://github.com/marco0560/codira/commit/09c5c8cffdf54f6b8b025d3c7ffe8b1a869afebd))

# [1.19.0](https://github.com/marco0560/codira/compare/v1.18.3...v1.19.0) (2026-04-30)


### Features

* **dev:** add benchmark campaign tooling ([a71b6f7](https://github.com/marco0560/codira/commit/a71b6f79ef6b5dc5e3ee73b49162b7fc97ab2753)), closes [#23](https://github.com/marco0560/codira/issues/23)

## [1.18.3](https://github.com/marco0560/codira/compare/v1.18.2...v1.18.3) (2026-04-26)


### Bug Fixes

* **git:** make aliases portable ([4af0eae](https://github.com/marco0560/codira/commit/4af0eaebe8a71761637582d3e304a03664a8dfa5))

## [1.18.2](https://github.com/marco0560/codira/compare/v1.18.1...v1.18.2) (2026-04-26)


### Bug Fixes

* **bootstrap:** align validation wrapper ([2b5f914](https://github.com/marco0560/codira/commit/2b5f91436d3dc02aa294aa7a82a673a44772b9f5))

## [1.18.1](https://github.com/marco0560/codira/compare/v1.18.0...v1.18.1) (2026-04-26)


### Bug Fixes

* **dev:** route validation temp state safely ([15a6740](https://github.com/marco0560/codira/commit/15a674003648c60e27e9515316b76c388c3896e9))

# [1.18.0](https://github.com/marco0560/codira/compare/v1.17.1...v1.18.0) (2026-04-25)


### Features

* **dev:** use symlist in demo workflow ([424e526](https://github.com/marco0560/codira/commit/424e526f800768a1efafe934979c25bb2e90b4cc))

## [1.17.1](https://github.com/marco0560/codira/compare/v1.17.0...v1.17.1) (2026-04-25)


### Bug Fixes

* **cli:** fixed symbol inventory output formatting ([be922cc](https://github.com/marco0560/codira/commit/be922ccae580bb4cede1bc2b29ce57bbb6e38252))

# [1.17.0](https://github.com/marco0560/codira/compare/v1.16.1...v1.17.0) (2026-04-25)


### Bug Fixes

* **config:** exclude node_modules from pytest ([5e6c673](https://github.com/marco0560/codira/commit/5e6c673561602dd8858e8ffa88add4565dbc4abc))


### Features

* **ci:** centralize dev tooling via run_repo_tool and isolate tool state ([68efe8f](https://github.com/marco0560/codira/commit/68efe8fe3cb25bc0637648b43d366518d26950f3)), closes [#19](https://github.com/marco0560/codira/issues/19)
* **cli:** add symlist symbol inventory ([d1a0794](https://github.com/marco0560/codira/commit/d1a07940bf4c9081d1e16ad1ec5456f49b9c2ad2)), closes [#26](https://github.com/marco0560/codira/issues/26)

## [1.16.1](https://github.com/marco0560/codira/compare/v1.16.0...v1.16.1) (2026-04-23)


### Bug Fixes

* **dev:** normalize path handling for local tooling and queries ([3106495](https://github.com/marco0560/codira/commit/3106495599a3c9d1ece41f7d9f03da23b9ba3fa2))

# [1.16.0](https://github.com/marco0560/codira/compare/v1.15.0...v1.16.0) (2026-04-22)


### Features

* **cli:** decouple target and output directories ([8c0ee11](https://github.com/marco0560/codira/commit/8c0ee1117a9a6c1c44a2de430d49450a51643f33)), closes [#19](https://github.com/marco0560/codira/issues/19) [#19](https://github.com/marco0560/codira/issues/19)

# [1.15.0](https://github.com/marco0560/codira/compare/v1.14.0...v1.15.0) (2026-04-22)


### Features

* **analyzer:** broaden C constant symbols ([53f0e51](https://github.com/marco0560/codira/commit/53f0e511c61287790fa9cfc5a03ae148d59b66f6)), closes [#25](https://github.com/marco0560/codira/issues/25)

# [1.14.0](https://github.com/marco0560/codira/compare/v1.13.0...v1.14.0) (2026-04-22)


### Features

* **analyzer:** add bounded C static const declarations ([3450897](https://github.com/marco0560/codira/commit/3450897018d6ce2a24b25a75bddb0f4b925db70e)), closes [#25](https://github.com/marco0560/codira/issues/25)

# [1.13.0](https://github.com/marco0560/codira/compare/v1.12.0...v1.13.0) (2026-04-22)


### Features

* **analyzer:** add C macro declarations ([71e133a](https://github.com/marco0560/codira/commit/71e133afaeaae7f1ae03565118e5f9682e34229b)), closes [#21](https://github.com/marco0560/codira/issues/21)

# [1.12.0](https://github.com/marco0560/codira/compare/v1.11.0...v1.12.0) (2026-04-22)


### Features

* **cli:** add Python constant JSON detail ([d9eda30](https://github.com/marco0560/codira/commit/d9eda30da9c7b81e76ea7f2b8d2744c5f1aa0db2))

# [1.11.0](https://github.com/marco0560/codira/compare/v1.10.0...v1.11.0) (2026-04-22)


### Features

* **analyzer:** add Python named constants ([b4442bc](https://github.com/marco0560/codira/commit/b4442bc3968cbc260434e32a4d4b3e3364974bb5))

# [1.10.0](https://github.com/marco0560/codira/compare/v1.9.0...v1.10.0) (2026-04-22)


### Features

* **analyzer:** add C union declarations ([bc93022](https://github.com/marco0560/codira/commit/bc93022313363282805c9820dab43d20bbc526a2))

# [1.9.0](https://github.com/marco0560/codira/compare/v1.8.0...v1.9.0) (2026-04-22)


### Features

* **analyzer:** add C enum member metadata ([0cfca75](https://github.com/marco0560/codira/commit/0cfca75b0a1049843e8594177e319273d03fac3c))

# [1.8.0](https://github.com/marco0560/codira/compare/v1.7.0...v1.8.0) (2026-04-22)


### Features

* **analyzer:** add python type alias declarations ([45931ec](https://github.com/marco0560/codira/commit/45931ec33135275cf6c3ebc1e12915cf88865567)), closes [#21](https://github.com/marco0560/codira/issues/21) [#21](https://github.com/marco0560/codira/issues/21)

# [1.7.0](https://github.com/marco0560/codira/compare/v1.6.0...v1.7.0) (2026-04-21)


### Features

* **contracts:** attach overload metadata to callables ([d2bce4e](https://github.com/marco0560/codira/commit/d2bce4e5c53798084d42043d3dc07ff624359222)), closes [#21](https://github.com/marco0560/codira/issues/21) [#21](https://github.com/marco0560/codira/issues/21)
* **query:** add overload evidence to ctx ranking ([a5c733d](https://github.com/marco0560/codira/commit/a5c733d78c3c57e65628f9bf1b6f4855c90a5bca)), closes [#21](https://github.com/marco0560/codira/issues/21)

# [1.6.0](https://github.com/marco0560/codira/compare/v1.5.2...v1.6.0) (2026-04-20)


### Bug Fixes

* **scanner:** ignore typing overload stubs ([0146173](https://github.com/marco0560/codira/commit/0146173c494356e012da737c7911b99967c98295))


### Features

* **release:** add hyperfine benchmark plan ([c1ddb36](https://github.com/marco0560/codira/commit/c1ddb3652c8494f076090773729856f00714607b)), closes [#16](https://github.com/marco0560/codira/issues/16)

## [1.5.2](https://github.com/marco0560/codira/compare/v1.5.1...v1.5.2) (2026-04-19)


### Bug Fixes

* **ci:** added retry to dependancy installation in CI workflow ([533d692](https://github.com/marco0560/codira/commit/533d6924452ac815346e6725cece541f46d5be37))

## [1.5.1](https://github.com/marco0560/codira/compare/v1.5.0...v1.5.1) (2026-04-18)


### Bug Fixes

* **package:** align monorepo plugin metadata ([7317657](https://github.com/marco0560/codira/commit/7317657baee562bcf8cbf8aedcf6eb1b12b462f5))

# [1.5.0](https://github.com/marco0560/codira/compare/v1.4.0...v1.5.0) (2026-04-18)


### Features

* **contracts:** add capability contract export ([b34abdf](https://github.com/marco0560/codira/commit/b34abdf7dc9577018584ace649c1276a42428248)), closes [#7](https://github.com/marco0560/codira/issues/7)
* **contracts:** add capability contract export ([3322ad6](https://github.com/marco0560/codira/commit/3322ad6f2f743395470b737197381b9d02c934fc)), closes [#7](https://github.com/marco0560/codira/issues/7)
* **contracts:** degrade missing capability declarations ([f214fa0](https://github.com/marco0560/codira/commit/f214fa00366a5e768059aa59568d5ec2af660e69))

# [1.4.0](https://github.com/marco0560/codira/compare/v1.3.2...v1.4.0) (2026-04-18)


### Features

* **tests:** introduce memory backend for testing ([30e2142](https://github.com/marco0560/codira/commit/30e2142c47a363abe6d31e0407f428278daafbb5)), closes [#9](https://github.com/marco0560/codira/issues/9)

## [1.3.2](https://github.com/marco0560/codira/compare/v1.3.1...v1.3.2) (2026-04-17)


### Bug Fixes

* **package:** align sqlite backend package release ([231e23e](https://github.com/marco0560/codira/commit/231e23e9ae806c99b0c4a13a02412972d54458c4))

## [1.3.1](https://github.com/marco0560/codira/compare/v1.3.0...v1.3.1) (2026-04-16)


### Bug Fixes

* **dev:** limit log alias to 50 commits to avoid noise ([55ed049](https://github.com/marco0560/codira/commit/55ed049c6a423c71a1a6ab72e75b86f81c73bd7c))

# [1.3.0](https://github.com/marco0560/codira/compare/v1.2.0...v1.3.0) (2026-04-16)


### Features

* **backend:** decouple backend from sqlite ([743fd1d](https://github.com/marco0560/codira/commit/743fd1d1b20fdb12eb68245ae69c240d0286f633)), closes [#8](https://github.com/marco0560/codira/issues/8)

# [1.2.0](https://github.com/marco0560/codira/compare/v1.1.7...v1.2.0) (2026-04-14)


### Features

* **cli:** add audit aggregation functionality only in non-JSON mode ([0028d67](https://github.com/marco0560/codira/commit/0028d6718f5d3d78955c084c9043833bf04a24c3))

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
