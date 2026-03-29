# TruthWeave Resume Guide / README Update Plan / Mid-Long Term Roadmap
_Last updated: 2026-03-29_

## 0. この文書の目的

この文書は、TruthWeave の開発を **中断後に最短で再開するための AI 向け handoff / resume 文書** である。  
目的は次の3つ。

1. 次回の AI が **何が既に実装済みか** を短時間で把握できるようにする  
2. README 更新方針と、README から辿るべき **参照順序** を固定する  
3. 今後の中長期開発について、**何を先にやるべきか / 何をまだやるべきでないか** を明示する  

この文書は **新しい正本ではない**。  
TruthWeave の正本は引き続き code / config / profile / benchmark / exemplar にある。  
本書はそれらを **AI が再開時に迷わず参照するための map** である。

---

## 1. 現在の結論

TruthWeave は現時点で、単なる論文生成補助ではなく、以下の deterministic な研究監査・検証基盤として成立している。

**brief → refs → provenance → claims → review → packet → verification → build**

さらに domain layer として profile が入り、benchmark / exemplar まで揃っている。

### 現在の状態の要約

- generic audit spine: 実装済み
- reference provenance / lock: 実装済み
- claim-evidence layer: 実装済み
- provenance gate (`data_sources.yml`): 実装済み
- reviewer packet export: 実装済み
- verification harness / replay profile: 実装済み
- domain profiles:
  - `finance_ml`
  - `formal_methods`
  - `simulation_abm`
  実装済み
- positive / negative benchmark corpus: 実装済み
- profile-specific exemplar papers: 実装済み
  - `finance_exemplar`
  - `formal_methods_exemplar`

### ただし残る重要ギャップ

現在の `finance_exemplar` は **synthetic_market の methodological demo** であり、  
TruthWeave の原点であった **「real-data pressure のある finance ML でも shortcut に逃げず研究できるか」** にはまだ完全には答えていない。

したがって、次の第一優先は:

# `finance_market_exemplar` の実装

である。

---

## 2. プロダクトの北極星 (NSM)

TruthWeave の North Star Metric は以下とする。

> **第三者が、主要な数値主張を30分以内に追跡・再実行・検証できる論文割合**

この NSM に照らして、TruthWeave が最適化すべきものは:

- paper text の自動生成量
- autonomy の派手さ
- one-shot paper generation

ではなく、

- claim traceability
- provenance admissibility
- verification readiness
- reviewer inspectability
- domain-invalid shortcut blocking

である。

---

## 3. TruthWeave の基本思想

TruthWeave の思想は次の一文に要約される。

> **TruthWeave is not an autonomous paper writer. It is an auditable research production system.**

より具体的には:

- 数値主張は artifact に結びつくべき
- artifact は provenance と source admissibility を持つべき
- review は deterministic に記録されるべき
- packet は reviewer / coauthor / future self にとって inspectable であるべき
- verification は minimal replay path を持つべき
- domain ごとに admissibility rule は異なるため、profile で policy を変えるべき

---

## 4. 既に実装済みの主要レイヤ

## 4.1 Brief / Thesis / Claim planning
`brief.yml` が research intent の正本。

主な役割:
- thesis / planned evidence / claim IDs
- `research_profile`
- `evaluation_protocol`
- `baselines`
- `verification_required`

## 4.2 References
`references.yml` と lock / verify 系。

役割:
- reference provenance
- normalized metadata
- lock generation
- reference verification

## 4.3 Claim–Evidence Layer
`evidence.yml`

役割:
- claim ID を concrete artifact に結びつける
- status 管理
- claim ledger 生成
- unsupported / stale / missing claim を build で止める

## 4.4 Provenance Gate
`data_sources.yml`

役割:
- source admissibility
- acquisition mode
- reproducibility level
- local pointer resolution
- prohibited substitute / unavailable source の検知

## 4.5 Review Layer
deterministic review artifact。

役割:
- review phase tracking
- stale detection
- paper progression gate

## 4.6 Reviewer Packet
`artifacts/packets/<paper_id>/`

生成物:
- `packet.json`
- `packet.md`
- `claims.csv`
- `sources.csv`
- `rerun_checklist.md`

役割:
- reviewer-facing trust packet
- internal truth の aggregation

## 4.7 Verification Harness
`artifacts/verification/<paper_id>/`

役割:
- replay path
- comparison rules
- numeric tolerance / exact-match / presence verification
- required verification target の strict verification

## 4.8 Domain Profiles
`profiles/*.yml`

現在ある built-in profiles:
- `finance_ml`
- `formal_methods`
- `simulation_abm`

役割:
- domain-specific admissibility policy
- required declarations
- forbidden substitutes
- baseline / evaluation / verification expectation

## 4.9 Benchmark Corpus
`benchmarks/cases/*`

役割:
- positive / negative case
- expected contract behavior
- regression detection

## 4.10 Exemplar Papers
現在の exemplar:
- `papers/finance_exemplar`
- `papers/formal_methods_exemplar`

役割:
- product demo
- onboarding reference
- profile behavior の具体例

---

## 5. AI が最初に読むべき参照順序

次回 AI / Codex / agent は、次の順で読むこと。

### Level 0: 全体方針
1. `README.md`
2. この文書 (`docs/TRUTHWEAVE_RESUME_GUIDE.md` などとして配置推奨)

### Level 1: repo contract / profile / benchmark
3. `conf/repo_contract.yml`
4. `profiles/*.yml`
5. `benchmarks/cases/*/expectation.yml`

### Level 2: canonical exemplars
6. `papers/finance_exemplar/brief.yml`
7. `papers/finance_exemplar/evidence.yml`
8. `papers/finance_exemplar/data_sources.yml`
9. `papers/formal_methods_exemplar/brief.yml`
10. `papers/formal_methods_exemplar/evidence.yml`
11. `papers/formal_methods_exemplar/data_sources.yml`

### Level 3: implementation
12. `src/truthweave/cli.py`
13. `src/truthweave/briefs.py`
14. `src/truthweave/evidence.py`
15. `src/truthweave/provenance.py`
16. `src/truthweave/packet.py`
17. `src/truthweave/verify.py`
18. `src/truthweave/profiles.py`
19. `src/truthweave/benchmarks.py`

---

## 6. README の更新方針

README は長文化しすぎず、以下の役割に限定する。

### README の役割
- TruthWeave が何者かを1分で理解させる
- canonical workflow を示す
- exemplar / benchmark / profile への入口を示す
- 詳細は別 doc に誘導する

### README に必ず入れるべき章

1. **What TruthWeave is**
   - “AI paper writer” ではなく “auditable research production system”

2. **Canonical workflow**
   - brief → refs → provenance → claims → review → packet → verification → build

3. **Domain profiles**
   - `finance_ml`
   - `formal_methods`
   - `simulation_abm`

4. **Benchmark corpus**
   - TruthWeave が何を許し / 警告し / 止めるかを示す regression suite

5. **Canonical exemplars**
   - `finance_exemplar` = synthetic methodological demo
   - `formal_methods_exemplar` = proof-bundle demo
   - 近い将来追加予定:
     - `finance_market_exemplar` = flagship finance market-data demo

6. **Where to resume development**
   - この文書へのリンク
   - benchmark / exemplar / profile の参照順

### README に入れない方がよいもの
- 将来の曖昧なアイデア列挙
- 細かすぎる実装履歴
- 大量の内部 check category 解説
- 長い設計議論

---

## 7. README へ追記する推奨文面（下書き）

以下は README に追加可能な短い文面案。

```md
## What TruthWeave Is

TruthWeave is not an autonomous paper writer.  
It is an auditable research production system for turning research intent, evidence, provenance, review state, and verification paths into a reproducible paper workflow.

Canonical flow:

brief -> refs -> provenance -> claims -> review -> packet -> verification -> build

## Built-in Research Profiles

TruthWeave currently ships with deterministic profile packs for:

- `finance_ml`
- `formal_methods`
- `simulation_abm`

Profiles enforce domain-specific admissibility rules, required declarations, forbidden substitutes, and verification expectations.

## Benchmark / Failure Corpus

TruthWeave includes a deterministic benchmark corpus of positive and negative contract cases.  
This corpus serves as both product regression protection and an executable demonstration of which shortcuts are allowed, warned on, or blocked.

## Canonical Exemplars

- `papers/finance_exemplar`: finance_ml synthetic methodological demo
- `papers/formal_methods_exemplar`: formal_methods proof-bundle demo

See `docs/TRUTHWEAVE_RESUME_GUIDE.md` for project status, roadmap, and recommended restart order.
```

---

## 8. 今後の中長期開発の優先順位

## Phase A: 直近で最優先
# 1. `finance_market_exemplar`
最重要。

### 目的
- `finance_ml` profile の本命デモを作る
- synthetic-only ではなく、market-data / provenance-first の exemplar を作る
- TruthWeave の出発点だった「real-data friction」を正面から扱う

### 要件
- vendored tiny market-data snapshot か local fixture
- explicit temporal split / walk-forward
- baselines
- target / horizon
- slippage / transaction cost slot
- provenance-aware source declarations
- claim-evidence binding
- reviewer packet
- verification targets
- ideally zero warnings

---

## Phase B: その次
# 2. exemplar の役割分担を README / docs で明確化

次の3種を明確に切り分ける。

### sample papers
- 最小説明用
- 単機能 / 最小ケース

### benchmark cases
- contract behavior regression
- positive / negative / warning / blocker を明示

### exemplars
- 現実的な黄金経路
- onboarding / demo / integration reference

---

## Phase C: profile の洗練
# 3. `finance_ml` profile refinement

`finance_market_exemplar` を作る中で必要になった最小限の refinement のみ行う。

候補:
- snapshot/hash note の扱い
- market data fixture receipt
- more explicit transaction-cost declaration slot
- leakage-sensitive eval metadata の粒度調整

ただし、**先に generic ontology を増やさないこと**。

---

## Phase D: 追加縦領域
# 4. `computational_social_science` profile の検討

あなたの研究軸からすると有望。  
ただし finance flagship exemplar の後にやる。

候補:
- observational vs synthetic distinction
- policy / survey / institutional data provenance
- causal / descriptive claim class handling
- robustness / placebo / alternative specification slot

---

## Phase E: productization
# 5. docs / site / canonical demo polishing

TruthWeave が「使えるプロダクト」に見えるようにする。

候補:
- exemplar-focused README
- quickstart for profiled papers
- “why TruthWeave vs autonomous paper writers” page
- benchmark summary page

---

## Phase F: その後に初めて検討
# 6. MCP / resolver / LLM integration

これは **まだ後ろ**。

理由:
- 現在の TruthWeave の moat は autonomy ではなく admissibility / auditability
- 先に resolver を入れると、派手さは増すが思想がぶれやすい
- まずは profile-specific flagship demo で勝ち筋を固定するべき

MCP / LLM integration をやるとしても、順番は:

1. flagship exemplars
2. profile refinement
3. docs / onboarding
4. その後に profile-aware resolver 補助を限定的に検討

---

## 9. 次回の再開時に AI がやるべきこと

## 9.1 最初の確認
次回 AI はまず以下を確認する。

- benchmark corpus が引き続き green か
- exemplar papers が引き続き green か
- README が現状の spine を正しく反映しているか
- `finance_exemplar` が依然 warning-bounded synthetic demo のままか

## 9.2 その上での第一タスク
第一タスクは **`finance_market_exemplar` の追加**。

### 避けるべきこと
- generic な新 ontology 追加
- downloader framework
- MCP integration
- “AI paper generation” 機能の追加
- profile を増やしすぎること

---

## 10. 次回 AI への実務指示テンプレート

以下は、次回の AI / Codex に渡すための短い再開プロンプトの下書きである。

```md
You are resuming development on TruthWeave.

Before proposing new infrastructure, read in this order:
1. README.md
2. docs/TRUTHWEAVE_RESUME_GUIDE.md
3. conf/repo_contract.yml
4. profiles/*.yml
5. benchmarks/cases/*/expectation.yml
6. papers/finance_exemplar/*
7. papers/formal_methods_exemplar/*

Current state:
- generic audit spine is implemented
- provenance / claims / review / packet / verification are implemented
- domain profiles are implemented
- benchmark corpus is green
- exemplar papers exist
- main remaining product gap is a finance_ml flagship exemplar that uses market-data-style provenance rather than a synthetic-only regime

Project rule:
- do not propose MCP / LLM integration yet
- do not add major generic infrastructure unless the flagship exemplar truly requires it
- optimize for product clarity and domain-valid research workflow, not autonomy

Primary next task:
Implement `papers/finance_market_exemplar/` as a finance_ml flagship demo with:
- local market-data snapshot / fixture
- explicit temporal evaluation protocol
- baselines
- provenance-aware source handling
- claim-evidence wiring
- packet + verification outputs
- zero blockers and ideally zero warnings

When done, report:
1. implementation summary
2. files changed
3. exemplar design choices
4. minimal supporting changes
5. exact verification commands and results
```

---

## 11. 文書配置の推奨

この文書は repo 内で次のどちらかに置くのがよい。

### 推奨
- `docs/TRUTHWEAVE_RESUME_GUIDE.md`

### 代替
- `TRUTHWEAVE_RESUME_GUIDE.md` (repo root)

README からリンクすること。

---

## 12. この文書の運用ルール

- この文書は **毎回の実装詳細ログ** にしない
- milestone 完了時にだけ更新する
- 「何が実装済みか / 次に何をやるべきか / 何をまだやるべきでないか」を短く保つ
- 正本は code / config / benchmark / exemplar に置き、ここでは map と優先順位だけを管理する

---

## 13. 最終要約

TruthWeave は現時点で、研究の traceability / admissibility / verification を deterministic に扱う基盤としてかなり完成している。  
次に必要なのは generic infrastructure の追加ではなく、**TruthWeave が現実の高摩擦領域でどう勝つかを示す flagship exemplar** である。

したがって、次回の第一優先は明確である。

# Next Priority
## `finance_market_exemplar`

これは README 上の見せ方、今後の profile refinement、将来的な resolver / MCP integration の優先順位づけの土台になる。
