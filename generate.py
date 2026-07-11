#!/usr/bin/env python3
"""
暮らしのやり方ガイド ― 夜間自動記事生成エンジン

毎晩 GitHub Actions から呼び出され、未執筆のキーワードを数件ぶん
Claude（Sonnet 4.6）に執筆させ、静的サイト(docs/)を作り直します。

使い方:
  python generate.py            # 本番(Claude APIで執筆)。ANTHROPIC_API_KEY が必要
  python generate.py --demo     # APIを使わずサンプル記事を1本作る(動作確認用・無料)
  python generate.py --build-only  # 既存記事からサイトだけ作り直す
"""

import argparse
import datetime
import html
import json
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
ARTICLES = BASE / "articles"
DOCS = BASE / "docs"

# ---- 記事の構造をAIに守らせるためのスキーマ ----
ARTICLE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "body_html": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        # 検索のリッチ表示(HowTo)用: 手順を name/text で構造化
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["name", "text"],
                "additionalProperties": False,
            },
        },
        # 検索のリッチ表示(FAQ)用: よくある質問
        "faqs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "a": {"type": "string"},
                },
                "required": ["q", "a"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "description", "body_html", "tags", "steps", "faqs"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "あなたは日本の生活情報メディアの編集ライターです。"
    "読者は『その作業をやったことがない初心者』。検索して来た人が、"
    "記事を読み終えたら自分で実行できるように、やさしく具体的に書きます。\n"
    "ルール:\n"
    "- 事実に基づき、安全に配慮する。危険な薬剤の混合(塩素系×酸性など)は必ず注意喚起する。\n"
    "- 医療・健康・お金に関わる断定はせず、必要なら専門家への相談を促す。\n"
    "- 文章は丁寧語。1記事1500〜2500文字程度。\n"
    "- body_html は <h2><h3><p><ul><li><ol> のみで構成。"
    "導入→手順→コツ→よくある失敗→まとめ、の流れを意識する。\n"
    "- title は32文字以内で検索キーワードを含める。description は記事要約120文字程度。\n"
    "- steps には本文の手順を3〜7個、name(手順名・短く)とtext(具体的な説明・1〜2文)で入れる。"
    "Googleの検索リッチ表示に使うので、実際にその通りやれば完了する順序で書く。\n"
    "- faqs には読者がよく検索する疑問を2〜4個、q(質問)とa(80〜150文字の回答)で入れる。"
)


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def generate_with_claude(query, model):
    """Claude APIで1記事ぶんのデータを作って返す。"""
    import anthropic

    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY を環境変数から読む
    user_prompt = (
        f"検索キーワード「{query}」で訪れた読者に向けた、実用的なHow-to記事を書いてください。"
    )
    resp = client.messages.create(
        model=model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        output_config={"format": {"type": "json_schema", "schema": ARTICLE_SCHEMA}},
    )
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def demo_article(query):
    """API無しの動作確認用。固定文のサンプル記事。"""
    return {
        "title": f"{query}【サンプル記事】",
        "description": f"これは {query} のサンプル記事です。動作確認のために自動生成されました。",
        "body_html": (
            "<h2>はじめに</h2>"
            "<p>これは Claude API を使わずに作成したサンプル記事です。"
            "サイトの見た目や仕組みを確認するために表示しています。</p>"
            "<h2>本番では</h2>"
            "<p>ANTHROPIC_API_KEY を設定して <code>python generate.py</code> を実行すると、"
            "ここに実際のやり方ガイドが自動で書き込まれます。</p>"
            "<h2>まとめ</h2>"
            "<p>仕組みが動いていれば成功です。次は本番モードを試してみましょう。</p>"
        ),
        "tags": ["サンプル"],
        "steps": [
            {"name": "準備する", "text": "必要な道具をそろえます。"},
            {"name": "実行する", "text": "手順どおりに作業します。"},
            {"name": "仕上げる", "text": "最後に確認して完了です。"},
        ],
        "faqs": [
            {"q": "これはサンプルですか？", "a": "はい。動作確認用の固定サンプル記事です。"},
        ],
    }


def build_article_record(kw, content):
    today = datetime.date.today().isoformat()
    slug = f"post-{kw['id']:03d}"
    return {
        "id": kw["id"],
        "slug": slug,
        "query": kw["query"],
        "title": content["title"],
        "description": content["description"],
        "body_html": content["body_html"],
        "tags": content.get("tags", []),
        "steps": content.get("steps", []),
        "faqs": content.get("faqs", []),
        "date": today,
    }


# ----------------- サイト生成 -----------------

def jsonld(obj):
    """構造化データを<script>タグ文字列にして返す。"""
    return ('<script type="application/ld+json">'
            + json.dumps(obj, ensure_ascii=False)
            + "</script>\n")


def ga4_snippet(config):
    """GA4計測タグ。config.json の ga_measurement_id が空なら何も出さない。"""
    gid = config.get("ga_measurement_id", "")
    if not gid:
        return ""
    safe_gid = html.escape(gid)
    return (
        f'<script async src="https://www.googletagmanager.com/gtag/js?id={safe_gid}"></script>\n'
        "<script>\n"
        "window.dataLayer = window.dataLayer || [];\n"
        "function gtag(){dataLayer.push(arguments);}\n"
        "gtag('js', new Date());\n"
        f"gtag('config', '{safe_gid}');\n"
        "</script>\n"
    )


def page_shell(config, title, description, inner, canonical, head_extra=""):
    site = config["site_title"]
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description)}">
<meta name="robots" content="index,follow">
<link rel="canonical" href="{html.escape(canonical)}">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(description)}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{html.escape(site)}">
<link rel="stylesheet" href="style.css">
{ga4_snippet(config)}{head_extra}<!-- AdSense用: 審査通過後にここへ広告コードを貼る -->
</head>
<body>
<header class="site-header">
  <a class="site-title" href="index.html">{html.escape(site)}</a>
  <p class="site-tagline">{html.escape(config['site_description'])}</p>
</header>
<main class="container">
{inner}
</main>
<footer class="site-footer">
  <p>この記事はAIによる自動生成を含みます。内容には注意していますが、最終的なご判断はご自身でお願いします。</p>
  <p>&copy; {datetime.date.today().year} {html.escape(site)}</p>
</footer>
</body>
</html>
"""


def related_articles(art, arts, limit=4):
    """同じタグを多く共有する記事を優先し、足りなければ新着で補う。"""
    others = [a for a in arts if a["slug"] != art["slug"]]
    my_tags = set(art.get("tags", []))

    def score(a):
        return len(my_tags & set(a.get("tags", [])))

    others.sort(key=lambda a: (score(a), a["date"], a["id"]), reverse=True)
    return others[:limit]


def render_faq_section(faqs):
    if not faqs:
        return ""
    items = "".join(
        f"<details class='faq-item'><summary>{html.escape(f['q'])}</summary>"
        f"<p>{html.escape(f['a'])}</p></details>"
        for f in faqs
    )
    return f"<section class='faq'><h2>よくある質問</h2>{items}</section>"


def render_related_section(related):
    if not related:
        return ""
    links = "".join(
        f"<li><a href='{a['slug']}.html'>{html.escape(a['title'])}</a></li>"
        for a in related
    )
    return f"<nav class='related'><h2>あわせて読みたい</h2><ul>{links}</ul></nav>"


def article_structured_data(config, art, url):
    """記事ページに埋め込む構造化データ(Article/HowTo/FAQ)をまとめて返す。"""
    site = config["site_title"]
    blocks = [jsonld({
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": art["title"],
        "description": art["description"],
        "datePublished": art["date"],
        "dateModified": art["date"],
        "author": {"@type": "Organization", "name": config.get("author", site)},
        "publisher": {"@type": "Organization", "name": site},
        "mainEntityOfPage": url,
        "inLanguage": "ja",
    })]
    steps = art.get("steps") or []
    if steps:
        blocks.append(jsonld({
            "@context": "https://schema.org",
            "@type": "HowTo",
            "name": art["title"],
            "description": art["description"],
            "step": [
                {"@type": "HowToStep", "position": i + 1,
                 "name": s["name"], "text": s["text"]}
                for i, s in enumerate(steps)
            ],
        }))
    faqs = art.get("faqs") or []
    if faqs:
        blocks.append(jsonld({
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": f["q"],
                 "acceptedAnswer": {"@type": "Answer", "text": f["a"]}}
                for f in faqs
            ],
        }))
    return "".join(blocks)


def render_article_page(config, art, arts):
    url = f"{config['site_url']}/{art['slug']}.html"
    tags = "".join(f'<span class="tag">{html.escape(t)}</span>' for t in art["tags"])
    faq_html = render_faq_section(art.get("faqs"))
    related_html = render_related_section(related_articles(art, arts))
    inner = f"""
<article>
  <p class="crumb"><a href="index.html">トップ</a> ＞ 記事</p>
  <h1>{html.escape(art['title'])}</h1>
  <p class="meta">公開日: {art['date']}</p>
  <div class="tags">{tags}</div>
  <div class="article-body">
  {art['body_html']}
  </div>
  {faq_html}
  {related_html}
  <p class="back"><a href="index.html">← 一覧へ戻る</a></p>
</article>
"""
    head_extra = article_structured_data(config, art, url)
    return page_shell(config, art["title"], art["description"], inner, url, head_extra)


def render_index(config, arts):
    items = ""
    for a in sorted(arts, key=lambda x: (x["date"], x["id"]), reverse=True):
        items += f"""
  <li class="card">
    <a href="{a['slug']}.html">
      <span class="card-title">{html.escape(a['title'])}</span>
      <span class="card-desc">{html.escape(a['description'])}</span>
      <span class="card-date">{a['date']}</span>
    </a>
  </li>"""
    inner = f"""
<h1 class="index-h1">{html.escape(config['site_title'])}</h1>
<p class="index-lead">{html.escape(config['site_description'])}</p>
<ul class="card-list">{items}
</ul>
<p class="count">現在 {len(arts)} 記事を公開中（毎晩自動更新）</p>
"""
    head_extra = jsonld({
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": config["site_title"],
        "description": config["site_description"],
        "url": config["site_url"] + "/",
        "inLanguage": "ja",
    })
    return page_shell(config, config["site_title"], config["site_description"],
                      inner, config["site_url"] + "/", head_extra)


def render_sitemap(config, arts):
    urls = [f"  <url><loc>{config['site_url']}/</loc></url>"]
    for a in arts:
        urls.append(
            f"  <url><loc>{config['site_url']}/{a['slug']}.html</loc>"
            f"<lastmod>{a['date']}</lastmod></url>"
        )
    body = "\n".join(urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{body}\n</urlset>\n")


STYLE = """:root{--bg:#faf8f4;--ink:#2b2b2b;--accent:#c4622d;--card:#fff;--line:#e7e0d4}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,"Hiragino Kaku Gothic ProN","Yu Gothic",sans-serif;
background:var(--bg);color:var(--ink);line-height:1.8}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.site-header{background:#fff;border-bottom:1px solid var(--line);padding:18px 20px;text-align:center}
.site-title{font-size:1.3rem;font-weight:700;color:var(--ink)}
.site-tagline{margin:6px 0 0;font-size:.8rem;color:#777}
.container{max-width:720px;margin:0 auto;padding:24px 18px}
.index-h1{font-size:1.5rem}.index-lead{color:#555}
.card-list{list-style:none;padding:0;margin:0;display:grid;gap:14px}
.card a{display:block;background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:16px 18px;color:var(--ink)}
.card a:hover{border-color:var(--accent);text-decoration:none}
.card-title{display:block;font-weight:700;font-size:1.05rem}
.card-desc{display:block;color:#666;font-size:.85rem;margin:6px 0}
.card-date{display:block;color:#aaa;font-size:.75rem}
.count{color:#999;font-size:.8rem;text-align:center;margin-top:24px}
article h1{font-size:1.5rem;line-height:1.4}
.crumb{font-size:.8rem;color:#999}.meta{color:#999;font-size:.8rem}
.tags{margin:8px 0 20px}.tag{display:inline-block;background:#f0e9dd;color:#8a6a45;
font-size:.72rem;padding:3px 8px;border-radius:20px;margin-right:6px}
.article-body h2{border-left:5px solid var(--accent);padding-left:12px;margin-top:34px;font-size:1.2rem}
.article-body h3{margin-top:24px;font-size:1.05rem}
.article-body ul,.article-body ol{padding-left:1.4em}
.back{margin-top:40px}
.faq{margin-top:40px}.faq h2{border-left:5px solid var(--accent);padding-left:12px;font-size:1.2rem}
.faq-item{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:10px 0}
.faq-item summary{font-weight:700;cursor:pointer}
.faq-item p{margin:10px 0 0;color:#555}
.related{margin-top:40px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 20px}
.related h2{font-size:1.1rem;margin-top:0}
.related ul{margin:0;padding-left:1.2em}.related li{margin:6px 0}
.site-footer{border-top:1px solid var(--line);padding:24px 18px;text-align:center;color:#999;font-size:.78rem}
"""


def build_site(config):
    arts = [load_json(p, None) for p in sorted(ARTICLES.glob("post-*.json"))]
    arts = [a for a in arts if a]
    DOCS.mkdir(exist_ok=True)
    (DOCS / "style.css").write_text(STYLE, encoding="utf-8")
    (DOCS / "index.html").write_text(render_index(config, arts), encoding="utf-8")
    (DOCS / "sitemap.xml").write_text(render_sitemap(config, arts), encoding="utf-8")
    (DOCS / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {config['site_url']}/sitemap.xml\n",
        encoding="utf-8")
    for a in arts:
        (DOCS / f"{a['slug']}.html").write_text(
            render_article_page(config, a, arts), encoding="utf-8")
    print(f"[build] サイトを生成: {len(arts)} 記事")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="API無しでサンプル記事を作る")
    parser.add_argument("--build-only", action="store_true", help="サイトだけ作り直す")
    args = parser.parse_args()

    config = load_json(DATA / "config.json", {})
    ARTICLES.mkdir(parents=True, exist_ok=True)  # 空だとGitに無い場合があるので必ず用意
    if args.build_only:
        build_site(config)
        return

    keywords = load_json(DATA / "keywords.json", [])
    todo = [k for k in keywords if k.get("status") == "todo"]
    n = 1 if args.demo else config.get("articles_per_run", 3)
    targets = todo[:n]

    if not targets:
        print("[info] 未執筆のキーワードがありません。data/keywords.json に追加してください。")
        build_site(config)
        return

    for kw in targets:
        print(f"[write] 執筆中: {kw['query']}")
        try:
            content = demo_article(kw["query"]) if args.demo \
                else generate_with_claude(kw["query"], config.get("model", "claude-sonnet-4-6"))
        except Exception as e:  # noqa: BLE001
            print(f"[error] 失敗: {kw['query']} -> {e}", file=sys.stderr)
            continue
        record = build_article_record(kw, content)
        write_json(ARTICLES / f"{record['slug']}.json", record)
        kw["status"] = "done"
        print(f"[ok] 完成: {record['title']}")

    write_json(DATA / "keywords.json", keywords)
    build_site(config)
    print("[done] 完了。")


if __name__ == "__main__":
    main()
