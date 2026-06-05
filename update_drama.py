"""
海外ドラマまとめサイト 週次自動更新スクリプト
毎週月曜日にGitHub Actionsから実行される
"""

import anthropic
import requests
import datetime
import os
import re
import json
from bs4 import BeautifulSoup

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

TODAY = datetime.date.today()
TODAY_STR = TODAY.strftime("%Y年%m月%d日")
MONTH_STR = TODAY.strftime("%Y年%m月")


def fetch_rt_trending():
    """Rotten Tomatoesから話題の海外ドラマ情報を取得"""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    results = []

    # 犯罪・ミステリー・スリラー系
    urls = [
        "https://www.rottentomatoes.com/browse/tv_series_browse/genres:mystery_and_thriller~sort:popular",
        "https://www.rottentomatoes.com/browse/tv_series_browse/genres:crime~sort:popular",
        "https://www.rottentomatoes.com/browse/tv_series_browse/genres:sci_fi~sort:popular",
        "https://www.rottentomatoes.com/browse/tv_series_browse/genres:action~sort:popular",
    ]

    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "html.parser")

            # RTページのJSONデータを取得
            for script in soup.find_all("script", type="application/json"):
                try:
                    data = json.loads(script.string)
                    # RT内部JSONからshow情報を探索
                    shows_raw = _extract_shows_from_json(data)
                    results.extend(shows_raw)
                except Exception:
                    pass

            # JSON取得できなかった場合はOGタイトルなどでフォールバック
            if not results:
                og_title = soup.find("meta", property="og:title")
                if og_title:
                    results.append({"title": og_title.get("content", "")})

        except Exception as e:
            print(f"RT fetch warning ({url}): {e}")
            continue

    # 重複除去
    seen = set()
    unique = []
    for item in results:
        key = item.get("title", "")
        if key and key not in seen:
            seen.add(key)
            unique.append(item)

    return unique[:40]  # 最大40件返す


def _extract_shows_from_json(data, depth=0):
    """RT内部JSONからshowデータを再帰的に抽出"""
    shows = []
    if depth > 8:
        return shows
    if isinstance(data, dict):
        # RTのshow項目の特徴的なキー群を確認
        if "title" in data and "tomatoIcon" in data:
            shows.append({
                "title": data.get("title", ""),
                "score": data.get("tomatoScore", {}).get("value", ""),
                "year": data.get("startYear", ""),
            })
        for v in data.values():
            shows.extend(_extract_shows_from_json(v, depth + 1))
    elif isinstance(data, list):
        for item in data:
            shows.extend(_extract_shows_from_json(item, depth + 1))
    return shows


def read_current_html():
    """現在のindex.htmlを読み込む（テンプレートとして使用）"""
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def generate_updated_html(rt_data: list, current_html: str) -> str:
    """Claude APIを使って更新済みHTMLを生成"""

    rt_info = ""
    if rt_data:
        rt_info = "## Rotten Tomatoesから取得した話題作リスト（参考情報）:\n"
        for i, show in enumerate(rt_data[:30], 1):
            rt_info += f"{i}. {show.get('title','')} (スコア: {show.get('score','不明')}, {show.get('year','')}\n"
    else:
        rt_info = "（RT自動取得データなし — 学習データと最新情報から判断してください）"

    prompt = f"""あなたは「次に観たい海外ドラマ」という日本語まとめサイトの週次更新担当です。
今日は {TODAY_STR} です。

## 更新作業の指示

以下のHTMLテンプレートを参考に、今週分の最新版HTMLを生成してください。
**CSSやJavaScript、ヘッダー・ナビ・フッターのデザインは一切変更せず、カード内の作品データのみを更新します。**

## 選定基準
- ジャンル：サスペンス / SF / 犯罪ドラマ / 刑事・探偵 / アクション / ドキュメンタリー
- 恋愛・ロマンス系は必ず除外
- Rotten Tomatoes批評家スコアが高い順を優先
- 10作品を選ぶ（新しい作品優先、継続中の話題作も可）
- 前週と全く同じリストにならないよう、少なくとも3〜5作品は入れ替える

## 各カードに必要な情報
1. 作品タイトル（英語）
2. 日本語タイトルまたは読み方（年）
3. ジャンル（data-genre属性: suspense / sf / crime / detective / action）
4. Rotten Tomatoesスコア（%）
5. あらすじ（日本語2〜3文、魅力が伝わる文章で）
6. YouTubeトレーラーのビデオID（公式トレーラーのIDを正確に）
7. 日本配信サービス名と日本語サイトへの直リンクURL
8. 日本配信開始月（例: 2026年1月〜）
9. ジャンルタグ（span.tagで2〜3個）

## 配信バッジのクラスと対応色
- Netflix → class="netflix"
- Amazon Prime Video → class="prime"
- Disney+ → class="disney"
- Apple TV+ → class="apple"
- Paramount+ → class="paramount"
- U-NEXT → class="unext"

## 日本版配信URLの優先度
1. amazon.co.jp のURLを最優先（Prime Videoの場合）
2. disneyplus.com/ja-jp の日本版URL（Disney+の場合）
3. video.unext.jp の日本版URL（U-NEXTの場合）
4. tv.apple.com/jp の日本版URL（Apple TV+の場合）
5. 日本未確認の場合は paramountplus.com など公式URLで代替

## YouTubeサムネイルURL形式
img src="https://img.youtube.com/vi/[VIDEO_ID]/mqdefault.jpg"
→ VIDEO_IDが正確でないと画像が表示されないため、公式トレーラーのIDを慎重に確認してください

## ヘッダーの更新日
header内の更新日テキストを「{TODAY_STR}更新」に変更してください

{rt_info}

## 現在のHTMLテンプレート（このデザイン・構造を完全に維持すること）:
```html
{current_html}
```

## 出力形式
<!DOCTYPE html> から </html> までの完全なHTMLのみを出力してください。
コードブロック記法（```）は不要です。他の説明文も不要です。HTMLのみ出力してください。
"""

    print(f"Claude APIを呼び出し中... ({TODAY_STR})")

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=12000,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text

    # HTMLのみ抽出（余分なテキストを除去）
    if "<!DOCTYPE html>" in raw:
        start = raw.index("<!DOCTYPE html>")
        html = raw[start:]
        # 末尾の余分なテキスト除去
        if "</html>" in html:
            end = html.rindex("</html>") + len("</html>")
            html = html[:end]
        return html
    else:
        print("警告: HTMLが正しく抽出できませんでした。元のHTMLを保持します。")
        return current_html


def save_html(html: str):
    """HTMLをindex.htmlに保存"""
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"index.html を更新しました ({TODAY_STR})")


def main():
    print(f"=== 海外ドラマまとめ 週次更新 === {TODAY_STR}")

    # 1. RT からトレンドデータを取得
    print("Rotten Tomatoesからデータ取得中...")
    rt_data = fetch_rt_trending()
    print(f"  取得: {len(rt_data)}件")

    # 2. 現在のHTMLを読み込む
    print("現在のHTMLを読み込み中...")
    current_html = read_current_html()
    if not current_html:
        print("警告: index.htmlが見つかりません。新規作成します。")

    # 3. Claude APIで更新HTMLを生成
    print("Claude APIでHTML生成中...")
    updated_html = generate_updated_html(rt_data, current_html)

    # 4. 保存
    save_html(updated_html)
    print("完了！")


if __name__ == "__main__":
    main()
