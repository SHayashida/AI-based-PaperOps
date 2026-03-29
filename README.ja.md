# TruthWeave

[![CI](https://github.com/SHayashida/TruthWeave/actions/workflows/ci.yml/badge.svg)](https://github.com/SHayashida/TruthWeave/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**追跡可能な主張、許容可能なソース、実行可能な検証経路を扱うための、監査可能な研究プロダクションシステム。**

TruthWeave は論文リポジトリを audit spine に変えます。`brief.yml` に研究意図を置き、`data_sources.yml` に出典許容性を置き、`evidence.yml` に claim と artifact の結び付きを置き、reviewer packet と deterministic な verification 出力まで同じリポジトリ内で管理します。目的は、自律生成ではなく、検査・再実行・引き継ぎができる研究ワークフローを作ることです。

[`ショーケース動画を見る`](docs/assets/truthweave-showcase.mp4) · [`最初に見る場所`](#最初に見る場所) · [`Finance exemplar`](papers/finance_exemplar/) · [`Formal methods exemplar`](papers/formal_methods_exemplar/) · [`Resume guide`](docs/TRUTHWEAVE_RESUME_GUIDE.md)

<p align="center">
  <a href="docs/assets/truthweave-showcase.mp4">
    <img src="docs/assets/truthweave-showcase.png" alt="TruthWeave showcase concept preview" width="960" />
  </a>
</p>
<p align="center">
  <sub>ショーケース用の concept preview です。画像をクリックすると短い動画を開きます。</sub>
</p>
<p align="center">
  <sub>Audit spine • provenance gate • reviewer packet • verification harness • domain profiles</sub>
</p>

[English README is here](README.md)

## TruthWeave とは

TruthWeave は、ワンプロンプトで論文を自律生成するためのツールではありません。何を主張したのか、どのソースが admissible なのか、どの evidence に紐づくのか、レビュー時に何を見るべきか、主要 claim をどう replay するのかを、明示的な contract として扱うためのシステムです。

## なぜ TruthWeave が必要か

多くの AI 論文ワークフローは autonomy を優先します。TruthWeave は **最大限の自律性ではなく、admissibility と verification を優先** します。traceable claims、source provenance、deterministic checks、reviewer-facing packet、実行可能な verification path、domain-specific policy enforcement を、属人的な運用ではなくリポジトリの中に残すためです。

## Canonical Workflow

```text
brief -> refs -> provenance -> claims -> review -> packet -> verification -> build
```

この流れにより、論文本文、証拠、再実行経路を prose だけの引き継ぎにせず、同じ audit trail 上で揃えられます。

## 最初に見る場所

プロダクトの価値を最短で理解するなら、まず次を見てください。

- **benchmark / failure corpus**: [`benchmarks/cases/`](benchmarks/cases/) と [`artifacts/benchmarks/benchmark_report.md`](artifacts/benchmarks/benchmark_report.md)。positive case、negative case、blocked shortcut を executable contract test として確認できます。
- **finance exemplar**: [`papers/finance_exemplar/`](papers/finance_exemplar/)、[`packet.md`](artifacts/packets/finance_exemplar/packet.md)、[`verification_report.md`](artifacts/verification/finance_exemplar/verification_report.md)。時間分割、admissibility rule、packet export、verification path を持つ finance ML workflow の実例です。
- **formal methods exemplar**: [`papers/formal_methods_exemplar/`](papers/formal_methods_exemplar/)、[`packet.md`](artifacts/packets/formal_methods_exemplar/packet.md)、[`verification_report.md`](artifacts/verification/formal_methods_exemplar/verification_report.md)。proof bundle 宣言と exact/file-presence verification の実例です。
- **resume / development guide**: [`docs/TRUTHWEAVE_RESUME_GUIDE.md`](docs/TRUTHWEAVE_RESUME_GUIDE.md)。 contributor や coding agent が途中再開・引き継ぎを行うための正本ガイドです。

まず 1 つ実行するなら、`uv run truthweave benchmark-contracts --format md` または `make exemplars` が最短です。

## Built-in Profiles

TruthWeave には `finance_ml`、`formal_methods`、`simulation_abm` の built-in profile があります。これらは domain ごとの admissibility rule、forbidden substitute、必須宣言、評価要件、verification expectation を強制し、同じワークフローに異なる研究 contract を載せられるようにします。

## 何が「既に動く」証拠か

このリポジトリには、構想だけではなく、価値を確認できる具体資産が既に入っています。

- [`benchmarks/cases/`](benchmarks/cases/) 配下の deterministic benchmark corpus
- [`artifacts/packets/`](artifacts/packets/) 配下の reviewer packet export
- [`artifacts/verification/`](artifacts/verification/) 配下の verification harness と replay 出力
- [`papers/finance_exemplar/`](papers/finance_exemplar/) と [`papers/formal_methods_exemplar/`](papers/formal_methods_exemplar/) の canonical exemplars
- [`artifacts/profiles/`](artifacts/profiles/) 配下の profile report

## 誰のためのものか

TruthWeave は、再現性、監査可能な claims、研究 contract、domain-valid な evidence、引き継ぎ可能な paper workflow を重視する研究者・研究チーム・エンジニアリング寄りの論文運用向けです。ワンプロンプトの自律論文生成だけを求める用途が主眼ではありません。

## クイックスタート

```bash
uv sync
uv run truthweave validate-brief --paper example
uv run truthweave validate-profile --paper example
uv run truthweave validate-provenance --paper example
uv run truthweave run exp=example
uv run truthweave discover
uv run truthweave build-paper-assets --paper example
uv run truthweave sync-refs --paper example
uv run truthweave validate-evidence --paper example
uv run truthweave provenance-report --paper example --format md
uv run truthweave claim-report --paper example --format md
uv run truthweave review-thread --paper example --phase draft_reviewed --format md
uv run truthweave reviewer-packet --paper example --format md
uv run truthweave verify-paper --paper example --format md
uv run truthweave profile-report --paper example --format md
uv run truthweave check --paper example
uv run truthweave benchmark-contracts --format md
```

## 概要

TruthWeaveは学術論文執筆のための構造化されたワークフローを強制します：

```
Experiment (conf/exp + src/truthweave/experiments)
  -> runs/
  -> artifacts/
  -> papers/<paper_id>/auto
  -> PDF
```

### 同梱されている4つのデモ paper

このリポジトリには、役割の異なる 4 つの paper が意図的に同梱されています。

- `example`: クイックスタートで使う最小の単一 paper サンプル
- `demo_paper`: 複数 paper 運用（`discover`、Makefile の `*-all` ターゲット、paper 横断チェック）を確認するための軽量サンプル
- `finance_exemplar`: 明示的な temporal protocol、baseline、admissibility 宣言、packet export、verification target を含む finance ML profile デモ
- `formal_methods_exemplar`: proof bundle 宣言、exact-match / file-presence verification、packet export、profile enforcement を含む formal methods profile デモ

4 つを同梱することで、次の 3 つをすぐ確認できます。

1. 単一 paper の導入フロー（`--paper example`）
2. 複数 paper の運用フロー（`make assets-all`、`make check-all`）
3. profile-specific exemplar の参照導線（`make exemplars`）

## 主要ワークフロー

### 新しい論文の追加

```bash
uv run truthweave create-paper <paper_id>
# 既存の論文からコピーする場合:
uv run truthweave create-paper <paper_id> --from <base_paper_id>
```

投稿先固有の `.cls`/`.sty` ファイルは `papers/<paper_id>/styles/` に配置してください。

### 新しい実験の追加

```bash
uv run truthweave create-exp <exp_name>
```

**AI連携用テンプレート**（編集可能ファイルを制限）:

```
このリポジトリの構成は固定です。
編集して良いファイル:
- conf/exp/<exp_name>.yaml
- src/truthweave/experiments/<exp_name>.py
それ以外のファイル/ディレクトリは作成・変更しないでください。
```

実験を実行:

```bash
uv run truthweave run exp=<exp_name>
```

### データセットの追加

```bash
uv run truthweave create-dataset <dataset_id>
```

生データは `data/raw/<dataset_id>/` に配置してください。

### 解析・図表の追加

```bash
uv run truthweave create-analysis <analysis_name>
make analysis NAME=<analysis_name>
# または直接実行:
uv run python -m truthweave.analysis.<analysis_name>
```

### 論文アセットのビルド

メトリクス、図、表を論文に同期:

```bash
uv run truthweave build-paper-assets --paper <paper_id>
```

論文は `\input{auto/variables.tex}` を使用し、数値をハードコードせずマクロ参照する必要があります。

### PDFのビルド

```bash
uv run truthweave build-paper --paper <paper_id>
```

`latexmk` などの LaTeX ツールが必要です。

### コミット前チェック

```bash
uv run truthweave check --paper <paper_id> --mode dev
uv run truthweave check --paper <paper_id> --mode ci
```

- **dev モード**: STRUCTURE/PAPER_NUMBERS は警告のみ
- **ci モード**: STRUCTURE/PAPER_NUMBERS で失敗扱い

## トラブルシューティング

| 症状 | 原因 | 解決策 |
| --- | --- | --- |
| MANIFEST が stale | アセット未更新 | `uv run truthweave build-paper-assets --paper <paper_id>` |
| No runs found | 実験未実行 | `uv run truthweave run exp=<exp_name>` |
| Structure check fail | 配置ルール違反 | スキャフォールドコマンドで再構築 |
| Manual inline numbers detected | `.tex` にハードコード数値 | マクロへ置換、または `% truthweave-allow-number` を追記 |

## 論文ワークフロー

- 論文は `papers/<paper_id>/` 配下に `truthweave.yml` 設定ファイルとともに配置
- `truthweave discover` が `truthweave.yml` を検出し、`artifacts/manifests/papers_index.json` を生成
- `truthweave build-paper-assets --paper <paper_id>` が `papers/<paper_id>/auto/variables.tex` と `papers/<paper_id>/auto/MANIFEST.json` を生成
- `truthweave build-paper --paper <paper_id>` が `truthweave.yml` のエンジン設定で LaTeX 論文をビルド
- Make ターゲット: `make assets PAPER=<paper_id>`, `make paper PAPER=<paper_id>`, `make assets-all`, `make paper-all`

## ワークフロー概要: 実験追加

1. `uv run truthweave create-exp myexp`
2. 作成されたファイル**のみ**をAIに編集させる
3. `uv run truthweave run exp=myexp`

## ワークフロー概要: 解析追加

1. `uv run truthweave create-analysis my_analysis`
2. 作成されたファイル**のみ**をAIに編集させる
3. `make analysis NAME=my_analysis`

## ワークフロー概要: データセット追加

1. `uv run truthweave create-dataset mydata`
2. `data/raw/mydata/` に生ファイルを配置

## Codex/AIエージェント スキル

このリポジトリは `.codex/skills/` にAIエージェント（Codex、GitHub Copilot等）用の構造化スキルを含んでいます：

### 利用可能なスキル

#### `truthweave-build-assets`
- **目的**: paper_id に対して論文アセット（図表・変数）を決定的に再ビルド
- **使用法**: AIが論文出力を再生成する際に自動起動
- **主要コマンド**: `uv run truthweave build-paper-assets --paper <paper_id>`
- **制約**: `papers/<paper_id>/auto/` を手動編集してはいけない

#### `truthweave-check`
- **目的**: TruthWeave CI チェックを実行し、失敗を診断、修正を提案
- **使用法**: バリデーションとトラブルシューティング時に自動起動
- **主要コマンド**: `uv run truthweave check --paper <paper_id> --mode ci`
- **機能**: 古いアセット、不足メタデータ、構造違反を検知

### スキルのメンテナンス

スキルを追加・変更するには:

1. `.codex/skills/<skill_name>/SKILL.md` でスキルを作成/編集
2. フロントマターフォーマットに従う:
   ```yaml
   ---
   name: skill-name
   description: Brief description
   ---
   ```
3. 以下を含める: Inputs、Rules、Output format、Remediation playbook
4. スキルは自動的にAIエージェントで利用可能になる

詳細は [AGENTS.md](AGENTS.md) のエージェント契約と編集制約を参照してください。

## AI プロンプトテンプレート

AIエージェントと連携する際:

```
このリポジトリを編集しています。
編集して良いファイル:
- <スキャフォールド出力で表示されたパスのリスト>
新しいディレクトリは作成しないでください。CIが失敗します。
```

## チェックモード

- `truthweave check` はデフォルトで **dev モード**（STRUCTURE/PAPER_NUMBERS は警告のみ）
- `truthweave check --mode ci` は STRUCTURE/PAPER_NUMBERS を失敗扱い

## 複数論文ワークフロー（最短経路）

```bash
uv run truthweave create-paper demo_paper
uv run truthweave run exp=example
uv run truthweave build-paper-assets --paper demo_paper
uv run truthweave build-paper --paper demo_paper
uv run truthweave check --paper demo_paper
make assets-all
make paper-all
make check-all
```

## パイプライン設定

`conf/pipeline.yaml` が最新のrunとアセットへのソースフローを定義します。

## ライセンス

詳細は [LICENSE](LICENSE) ファイルを参照してください。
