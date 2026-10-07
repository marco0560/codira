# Vector-store authority: campagna rebased 2026-07-19

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-07-19-vector-store-authority-rebased-campaign.md`
(SHA-256 `452c719307ce5d30b8cf7931f8372039cf9930409e4ddbd7968769933034032b`).

Some original evidence is unavailable in this checkout. The missing paths
are listed below; those observations have not been independently revalidated.
Do not treat this archive as a fully reproducible current benchmark.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/benchmarks/vector-store-authority-rebased-20260718T175643Z/` | unavailable historical path |


## Decisione

**No-go per l'integrazione in `main` nello stato attuale.**

Il batching elimina il blocco funzionale che aveva interrotto la prima campagna:
tutte le otto campagne ripetute e gli otto smoke di indice completo terminano
senza errori. Il candidato introduce pero regressioni sostanziali in
combinazioni supportate. La piu netta e `vector_store=sqlite`, backend
strutturale DuckDB: la query media su CPython passa da 4.77 s a 29.59 s (+520%)
e il costo operativo pesato da 231.60 s a 689.07 s (+198%).

SQLite/SQLite resta vicino alla baseline (+6.6% sul costo pesato medio dei tre
repository), ma non basta: la modifica dichiara supporto per entrambi i vector
store e le combinazioni miste fanno parte della matrice.

## Scope e parita

| Item | Main | Candidato |
|---|---|---|
| Commit | `0a9f1f86b68572f06578833426c1420fb9a4aabf` | `5e30bb39d93ba816c5b7b55fab3cc135d64064d2` |
| Codira | `1.49.0` | `1.49.0.post1.dev1` |
| Vector stores / backend strutturali | SQLite, DuckDB | SQLite, DuckDB |
| Embedding | ONNX BGE small en v1.5, CPU | identico |
| Modello e tokenizer | `.codira/models/bge-small-en-v1.5/` | identici |
| Ripetizioni | 5, warmup 1 | identiche |

Il candidato contiene `bcd6f47 refactor(embeddings): make vector stores authoritative`
e `5e30bb3 fix(embeddings): batch vector cache lookups`. Le versioni dei plugin
backend cambiano insieme al branch: i delta misurano l'intera proposta, non il
solo helper di batching.

Macchina: Intel i7-8700K (6 core / 12 thread), Linux 6.18.38 Gentoo, 46 GiB
RAM. ONNX `CPUExecutionProvider`, float32, normalizzazione attiva, batch 4;
il runner ha usato batch embedding 32, 10 thread Torch e 1 interop thread.

## Integrita

- Otto `failure-summary.json`: `failure_count = 0` in tutti i casi.
- Tutti i campioni Hyperfine hanno `exit_codes = [0]`.
- Otto smoke `benchmark_index.py --full`: nessun campo `error`.
- Non ricompare `sqlite3.OperationalError: too many SQL variables` nel caso
  DuckDB strutturale + vector store SQLite su CPython.

Il `--dry-run` risolve le selezioni creando indici: e costoso, ma non e una
misura Hyperfine. Gli indici ricreabili vengono rimossi dopo questo report.

## Delta candidato rispetto a main

Costo pesato: `full_index + 3 * partial_index + 20 * query_mean`; piu basso e
meglio. Percentuali positive sono regressioni.

| Vector store | Backend | Repository | Full | Partial | Query | Costo |
|---|---|---|---:|---:|---:|---:|
| SQLite | SQLite | Codira | -6.7% | -12.5% | +5.1% | -0.9% |
| SQLite | SQLite | Redis | +3.2% | +0.7% | +6.3% | +4.9% |
| SQLite | SQLite | CPython | +11.1% | -4.2% | +1.9% | +6.6% |
| SQLite | DuckDB | Codira | -33.1% | -9.8% | +14.7% | -0.9% |
| SQLite | DuckDB | Redis | -29.1% | +3.2% | +175.1% | +109.6% |
| SQLite | DuckDB | CPython | -29.6% | +3.2% | +519.9% | +197.5% |
| DuckDB | SQLite | Codira | +39.9% | -1.9% | +7.3% | +20.0% |
| DuckDB | SQLite | Redis | +62.3% | -7.8% | +28.0% | +40.3% |
| DuckDB | SQLite | CPython | +121.8% | +2.1% | -17.6% | +65.9% |
| DuckDB | DuckDB | Codira | -16.8% | +13.3% | +19.5% | +8.6% |
| DuckDB | DuckDB | Redis | -13.1% | +3.1% | +83.2% | +49.8% |
| DuckDB | DuckDB | CPython | -20.4% | -3.8% | -4.3% | -13.7% |

## Interpretazione

1. Il batching risolve la correttezza.
2. SQLite/SQLite e sostanzialmente stabile: costo medio 138.19 s -> 146.29 s
   (+5.9%).
3. SQLite vector store + DuckDB strutturale e il principale no-go: full index
   piu veloce, ma query su Redis e CPython molto piu lente; costo +110--198%.
4. DuckDB vector store + SQLite strutturale regredisce sistematicamente:
   costo +20--66%, con full index CPython +122%.
5. DuckDB/DuckDB non e una vittoria generale: CPython migliora (-13.7%), ma
   Redis peggiora (+49.8%) e Codira (+8.6%).

Non e corretto attribuire i delta al solo vector store: il branch cambia anche
autorita e ciclo di persistenza delle embedding. Il prossimo passo e profilare
le combinazioni miste separando lookup cache, flush/write e aperture di
connessione durante `ctx` e `emb`.

## Causa radice della regressione

L'indagine successiva conferma due regressioni architetturali indipendenti.

### 1. Vector store SQLite: ricerca semantica lineare in Python

Il candidato devia `EmbeddingRetrievalProducer` e la ricerca della
documentazione da `IndexBackend` a `semantic.search`, che chiama sempre
`VectorStore.similarity_scores`. La nuova implementazione SQLite esegue:

1. `SELECT stable_id, vector FROM vectors` per tutti i vettori del tipo;
2. deserializzazione di ogni blob da 384 float;
3. dot product Python e ordinamento completo dei risultati.

In `main`, con backend strutturale DuckDB, la query equivalente veniva eseguita
da DuckDB con `list_dot_product`, soglia e ordinamento nel database. Il cambio
spiega la regressione selettiva SQLite-vector/DuckDB-structural: sul profilo
CPython il candidato esegue 183.5 milioni di chiamate in 128.4 s contro 9.8
milioni in 7.1 s per main; `SQLiteVectorStore.similarity_scores` e il suo loop
di dot product sono un hot path misurato. Il valore Hyperfine di `ctx` e 29.59
s contro 4.77 s (+520%).

L'autorita del vector store non richiede che la similarita sia calcolata in
Python. Il contratto deve mantenere la proprieta dei vettori nel vector store,
ma ogni implementazione deve fornire un percorso di scoring nativo o bulk.
Per SQLite, una semplice scansione BLOB+Python non soddisfa il budget di
latenza per repository grandi.

### 2. DuckDB vector store con backend SQLite: materializzazione per batch

Nel backend SQLite, ogni `_flush_prepared_embedding_rows` chiama in sequenza
`store_cached_vectors`, `store_vectors` e `delete_pending_vectors` del vector
store. Con DuckDB ciascuna operazione apre una connessione, costruisce tabelle
Arrow e scrive nel database del vector store. Il percorso viene ripetuto per
ogni batch di embedding, anche in un full reindex con cache calda.

Su CPython i due run riusano esattamente 99.123 embedding e ne ricalcolano zero.
Nonostante cio il candidato passa da 15.60 s a 362.42 s nel timing diagnostico
embedding e da 129.77 s a 431.35 s nel timing indexing. Il backend strutturale
DuckDB ha gia un percorso specializzato `materialize_full_index` che trasferisce
cache e vettori in un'unica transazione Arrow; il backend SQLite non lo usa.
Questo spiega perche DuckDB-vector/DuckDB-structural non mostra lo stesso
peggioramento di full index, mentre DuckDB-vector/SQLite-structural arriva a
+122% su CPython.

## Condizioni per riaprire il merge

1. Implementare scoring efficiente nel vector store SQLite (SQL/estensione
   vettoriale oppure batch numerico nativo), con test e benchmark CPython che
   dimostrino di non regredire rispetto alla baseline DuckDB strutturale.
2. Estendere il contratto VectorStore con una materializzazione full-index
   bulk/atomica e usarla anche dal backend SQLite; non e accettabile aprire e
   riscrivere DuckDB per ogni batch quando tutti i vettori sono riusati.
3. Ripetere la matrice 2x2. Gate proposto: nessun delta di costo pesato oltre
   +10% su ciascun repository e nessuna regressione query oltre +15% nei
   percorsi supportati.

## Artefatti mantenuti e validazione

Sono mantenuti manifest, configurazioni ONNX, `campaign-plan.json`,
`failure-summary.json`, `*-hyperfine.json`, `*-utility-summary.json`,
`*-index-phases.json`, log e profili in
`.artifacts/benchmarks/vector-store-authority-rebased-20260718T175643Z/`.
Indici, smoke diretti e worktree temporanei sono ricreabili e vengono rimossi.

La campagna e la validazione runtime: 8/8 matrici senza fallimenti e cinque
campioni Hyperfine per comando. `uv run python scripts/validate_repo.py` era
gia passato sul commit candidato prima della campagna; non e rieseguito per il
solo report e la pulizia di file ignorati.
