縦書き電子書籍ビューア：グリッドシステム実装プラン (grid_viewer_plan.md)
1. 核心コンセプト：版面（はんづら）の再定義
Webの「流動的なレイアウト」を捨て、**「デバイスの画面高（vh）に基づいた固定グリッド」**を導入します。これにより、iPadやPCなど異なる端末でも、1ページの行数と文字数を一定に保ちます。

2. グリッド計算ロジック
以下の変数をCSSカスタムプロパティ（Variable）で管理し、数学的にレイアウトを決定します。

変数名	定義	計算式（例）
--page-height	版面の有効な縦幅	80vh
--lines-per-page	1ページの行数	15
--chars-per-line	1行の文字数	20
--font-size	基本文字サイズ	var(--page-height) / var(--chars-per-line)
--line-width	行送り（文字+行間）	var(--font-size) * 1.8

3. CSS グリッド・コア・スタイル
CSS
:root {
  --page-height: 80vh;
  --lines-per-page: 15;
  --chars-per-line: 20;
  --font-size: calc(var(--page-height) / var(--chars-per-line));
  --line-width: calc(var(--font-size) * 1.8);
}

.viewer-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  height: 100vh;
  background-color: #fcfaf2; /* 和紙のような地色 */
}

/* 本文エリア：版面 */
.page-main {
  writing-mode: vertical-rl;
  height: var(--page-height);
  width: calc(var(--line-width) * var(--lines-per-page));
  
  font-family: "Noto Serif JP", serif;
  font-size: var(--font-size);
  line-height: 1.8;
  
  /* 均等割付と禁則処理 */
  text-align: justify;
  text-justify: inter-character;
  line-break: strict;
  
  /* ページ分割（多段組） */
  column-width: calc(var(--line-width) * var(--lines-per-page));
  column-gap: 40px;
  overflow: hidden;
}

/* ルビの制御 */
rt {
  font-size: 0.5em;
  line-height: 1;
  font-family: inherit;
}

4. 「柱（はしら）」とタイトルの配置
本文の上下（天・地）に作品情報を固定し、読書中のコンテキストを維持します。

HTML
<div class="page-container">
  <header class="page-header">
    <span class="book-title">作品名：走れメロス</span>
  </header>

  <main class="page-main">
    </main>

  <footer class="page-footer">
    <span class="author-name">太宰治</span>
    <span class="page-count">12 / 45</span>
  </footer>
</div>

5. 実装上の重要テクニック
① HTMLのクレンジング（FastAPI側）
青空文庫のXHTMLから不要なスタイルを剥ぎ取り、純粋な構造のみをNext.jsへ渡します。

font, center, br タグの除去。

全角スペース（字下げ）の維持。

img タグの src をローカルパスへ置換。

② 禁則処理の「追い込み・追い出し」
text-align: justify を使うことで、句読点が行頭に来るのを防ぐためにブラウザが自動的に字間を調整し、グリッドの端がガタガタになるのを防ぎます。

③ ページ遷移の計算
JavaScriptで .page-main の scrollWidth を取得し、それを「1ページの横幅（--line-width × 行数）」で割ることで、総ページ数を動的に算出します。

6. 今後の拡張：PWAとオフライン対応
next-pwa を導入し、一度開いた本をキャッシュ。

iPadの「ホーム画面に追加」に対応し、フルスクリーンでの没入感を向上させる。