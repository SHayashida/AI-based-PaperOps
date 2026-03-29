# TruthWeave Template v1

[![CI](https://github.com/SHayashida/TruthWeave/actions/workflows/ci.yml/badge.svg)](https://github.com/SHayashida/TruthWeave/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

学術論文のための再現可能な研究ワークフローテンプレート。実験のトレーサビリティ、論文メトリクスの自動同期、手動での数値更新漏れの防止を実現します。

[English README is here](README.md)

## クイックスタート

```bash
uv sync
uv run truthweave run exp=example
uv run truthweave discover
uv run truthweave build-paper-assets --paper example
uv run truthweave check --paper example
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

### サンプルpaperが2つある理由

このテンプレートは、役割の異なる2つのサンプルpaperを意図的に同梱しています。

- `example`: クイックスタートで使う最小の単一paperサンプル
- `demo_paper`: 複数paper運用（`discover`、Makefileの `*-all` ターゲット、paper横断チェック）を確認するための2本目

2つを同梱することで、クローン直後に次の両方を検証できます。

1. 単一paperの導入フロー（`--paper example`）
2. 複数paperの運用フロー（`make assets-all`、`make paper-all`、`make check-all`）

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
