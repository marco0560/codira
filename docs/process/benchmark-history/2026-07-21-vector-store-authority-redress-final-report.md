# Report finale: vector-store authority redress

## Archive status — 2026-10-07

This is a historical report. Measurements and decisions describe the original
run and revision; recommendations and commands are not current operating
instructions. Path corrections below change navigation, not measurements.
The original ignored report remains unchanged at `.artifacts/analysis/2026-07-21-vector-store-authority-redress-final-report.md`
(SHA-256 `3c38268b4e2a90fb5d2335562e252412486b291c8419b46cdad8f47326cea7b9`).

The explicit artifact/input paths were checked in this checkout. Availability
does not establish that old measurements apply to the current version.

See the [report archive index](index.md) for coverage and remaining gaps.

| Artifact or input reference | Current availability |
| --- | --- |
| `.artifacts/benchmarks/experiments/vector-store/vector-store-authority-redress-20260720T134502Z` | available |


Data: 2026-07-21<br>
Campagna: `vector-store-authority-redress-20260720T134502Z`<br>
Candidato: `a4478ba` (`refactor/vector-store-authority`)<br>
Baseline: `0a9f1f8` e `931d636` (`main`)

## Esito

**MERGE CONSIGLIATO**, previo normale rebase del branch su `main`.

La matrice e completa: otto celle su otto, tutte con `failure_count: 0`.
Il candidato elimina inoltre il precedente errore di SQLite/`sqlite-vec` sui
KNN di cardinalita eccessiva tramite una finestra di candidati configurabile.

Il secondo commit di `main` (`931d636`) e stato trattato come equivalente alla
baseline `0a9f1f8`: modifica solo `AGENTS.md` e `CHANGELOG.md`, quindi non
interessa i percorsi di indicizzazione o retrieval misurati.

## Parita della misura

- Stesse tre dimensioni: Codira (piccolo), Redis (medio), CPython (grande).
- Stesso embedding ONNX su CPU; batch effettivo 32, sei thread Torch effettivi.
- Stessi backend strutturali (`sqlite`, `duckdb`) e stessi vector store
  (`sqlite`, `duckdb`) in entrambe le revisioni.
- Ogni cella include indice completo, aggiornamento parziale e comandi di
  lettura; lo score usa i pesi `1 : 3 : 20`.
- `timings.total`/indice completo e `timings.embeddings` non sono sommati:
  sono misure diverse.

## Risultati misurati

Le variazioni sono candidato rispetto a `main`; valori negativi sono migliori.
Lo score di utilita combina indice completo, indice parziale e letture.

| Vector store | Backend strutturale | Repository | Indice completo | Query medie | Score di utilita |
|---|---|---:|---:|---:|---:|
| SQLite | SQLite | Codira | +6.1% | +20.9% | +6.6% |
| SQLite | SQLite | Redis | -14.1% | +1.4% | -13.6% |
| SQLite | SQLite | CPython | -12.6% | -48.6% | -14.1% |
| SQLite | DuckDB | Codira | -7.4% | -17.0% | -8.0% |
| SQLite | DuckDB | Redis | -4.3% | +2.1% | -4.0% |
| SQLite | DuckDB | CPython | -4.5% | -4.8% | -4.5% |
| DuckDB | SQLite | Codira | +4.5% | +27.4% | +5.4% |
| DuckDB | SQLite | Redis | -22.6% | +40.1% | -20.7% |
| DuckDB | SQLite | CPython | -5.8% | -35.4% | -6.8% |
| DuckDB | DuckDB | Codira | -20.4% | +25.0% | -18.6% |
| DuckDB | DuckDB | Redis | -8.7% | +78.8% | -5.6% |
| DuckDB | DuckDB | CPython | -16.3% | -3.2% | -16.0% |

## Lettura

1. Il risultato importante e sulle basi medio/grandi: il candidato migliora
   lo score in tutte le otto celle Redis/CPython, da -4.0% a -20.7%.
2. Le due regressioni sono limitate al repository piccolo con SQLite come
   backend strutturale: +6.6% di score con vector store SQLite e +5.4% con
   vector store DuckDB. Non ribaltano il risultato sui carichi rappresentativi.
3. Il profilo della baseline SQLite su CPython mostra il collo di bottiglia
   precedente: `embedding_candidates` richiede 11.11 s e `_dot_similarity`
   viene invocata 99,123 volte (8.71 s cumulativi). Nel candidato con vector
   store SQLite non compare quel ciclo di similarity Python; il retrieval
   vettoriale viene limitato prima dei filtri strutturali/prefix.
4. La campagna non dimostra che ogni singolo comando di lettura migliori:
   alcune medie query oscillano sui repository piccoli o medi. Dimostra invece
   che il compromesso complessivo, ponderato per l'uso frequente delle letture,
   migliora senza errori e con un guadagno netto sui repository grandi.

## Decisione e prossimi passi

- Integrare `refactor/vector-store-authority` dopo rebase su `main`.
- Rieseguire i test e la validazione di repository sul commit rebased; questa
  campagna e una prova prestazionale, non sostituisce la validazione finale.
- Non e necessario un altro benchmark di gating: i risultati sono completi e
  coerenti. Un'eventuale misura successiva deve concentrarsi soltanto sulle
  due regressioni del repository piccolo, se diventano percepibili nell'uso.

## Artefatti consultati

- `campaign-status.tsv`
- Otto `failure-summary.json`, `campaign-plan.json` e `profile-summary.json`
- 24 `*-utility-summary.json`, 24 JSON Hyperfine e 24 JSON delle fasi indice
- Manifest `main.json` e `candidate.json`


## Evidence location verified on 2026-10-07

The retained campaign root is `.artifacts/benchmarks/experiments/vector-store/vector-store-authority-redress-20260720T134502Z`.
