# 暮らしのやり方ガイド ― 寝てる間に育つ自動記事サイト

毎晩あなたが寝ている間に、GitHubのサーバーが自動で起動し、Claude（AI）が
生活How-to記事を執筆 → サイトに公開していきます。PCの電源を切っていてもOK。
起きるたびに記事が増え、コミット履歴に「夜間に働いた証拠」が積み上がります。

```
毎晩 深夜2時
  → GitHub Actions が自動起動（PC不要・無料）
  → Claude API が記事を数本"執筆"（有料・1記事 約0.06ドル）
  → docs/ に静的サイトを再生成
  → GitHub に自動コミット → GitHub Pages で公開
```

将来、検索流入が育ったら AdSense / アフィリエイトで収益化します。

---

## 仕組み（ファイルの役割）

| 場所 | 役割 |
|------|------|
| `data/keywords.json` | 書きたい検索キーワードのリスト（ここを増やせばネタが続く） |
| `data/config.json` | サイト名・URL・1晩あたりの本数など設定 |
| `generate.py` | 本体。未執筆キーワードをAIに書かせ、サイトを生成 |
| `articles/` | 生成された記事データ（元データ） |
| `docs/` | 公開される静的サイト（GitHub Pagesがここを配信） |
| `.github/workflows/nightly.yml` | 毎晩の自動実行設定 |

---

## はじめての準備（順番にやればOK）

### 0. まず手元で"見た目"を確認（APIキー不要・無料）

`! python projects/kurashi-guide/generate.py --demo`

→ サンプル記事が1本でき、`docs/index.html` が作られます。
エクスプローラーで `projects/kurashi-guide/docs/index.html` をダブルクリックすると
ブラウザでサイトのデザインを確認できます。

> 確認できたら、`articles/post-001.json` を削除し、`data/keywords.json` の
> id:1 の `"status"` を `"todo"` に戻しておきましょう（サンプルを消して本番に備える）。

### 1. Anthropic（Claude）のAPIキーを取得

1. https://console.anthropic.com にアクセスしてアカウント作成
2. 支払い設定（少額チャージでOK。月数ドルしか使いません）
3. 「API Keys」で新しいキーを発行し、`sk-ant-...` をコピー

### 2. GitHubにリポジトリを作って push

このフォルダ（`kurashi-guide`）を新しいGitHubリポジトリとして公開します。
詳しいコマンドは別途ご案内します（あなたはGitが使えるので大丈夫）。

### 3. APIキーをGitHubに登録（コードに直接書かない）

GitHubのリポジトリ画面で:
`Settings` → `Secrets and variables` → `Actions` → `New repository secret`
- Name: `ANTHROPIC_API_KEY`
- Secret: さきほどの `sk-ant-...`

### 4. GitHub Pages を有効化

`Settings` → `Pages` →
- Source: `Deploy from a branch`
- Branch: `main` / フォルダ `/docs` を選んで Save

数分後、`https://（ユーザー名）.github.io/kurashi-guide/` で公開されます。

### 5. サイトURLを設定に反映

`data/config.json` の `site_url` を、上で決まった公開URLに書き換えて push。
（例: `https://yourname.github.io/kurashi-guide`）

### 6. 動作テスト

GitHubの `Actions` タブ → 「夜間に記事を自動生成」→ `Run workflow` を手動実行。
緑のチェックがつき、記事が増えれば成功です。あとは毎晩自動で動きます。

---

## 記事のネタを増やすには

`data/keywords.json` に追記するだけ:

```json
{ "id": 19, "query": "傘の撥水を復活させる方法", "status": "todo" }
```

idは重複しない番号にしてください。`status` は必ず `"todo"`。

## コストの調整

`data/config.json` の `articles_per_run`（1晩の本数）で調整。
- `model` を `"claude-haiku-4-5"` にすると最安（品質はやや下がる）
- `"claude-opus-4-8"` にすると最高品質（コスト高め）
