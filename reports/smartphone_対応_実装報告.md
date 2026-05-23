# スマートフォン対応 実装報告

対象ブランチ: `feature/smartphone`

---

## 概要

PC横長画面を前提としていた `index.html`（書籍一覧）と `viewer.html`（本文閲覧）を、スマートフォン（画面幅767px以下）でも快適に使えるよう改修した。

---

## 1. index.html（書籍一覧画面）のスマートフォン対応

### 方針

3カラム固定レイアウト（書籍リスト / 詳細パネル / タグフィルター）を、スマートフォンでは「1画面1パネル」方式に切り替える。

- デフォルト: 書籍リストを全幅表示
- 作品タップ: 詳細パネルが全画面オーバーレイで前面に出る
- 「絞り込む」ボタン: タグフィルターが全画面オーバーレイで前面に出る

### 修正ファイルと箇所

#### `frontend/index.html`（バージョン v3→v4）

- **検索バー内**に `<button id="filter-open-btn">絞り込む</button>` を追加（モバイル専用）
- **`#detail-panel` 先頭**に `<button id="mobile-back-btn">← 一覧に戻る</button>` を追加（モバイル専用）
- **`#tag-filter-header` 内**のボタン群を `.tag-filter-header-actions` でラップし、`<button id="filter-close-btn">✕</button>` を追加（モバイル専用）

#### `frontend/index.css`（バージョン v3→v4）

- **`.tag-filter-header-actions`** にフレックスレイアウトを追加（クリア・閉じるボタンを横並びに）
- **モバイル専用要素のデフォルト非表示**設定を追加（`#mobile-back-btn`, `#filter-open-btn`, `#filter-close-btn`）
- **`@media (max-width: 767px)` ブロック**を末尾に追加:
  - `.list-column` を全幅化
  - `#detail-panel` を `position: fixed; inset: 0` のフルスクリーンオーバーレイ化（`body.mobile-detail-open` 時に表示）
  - `#tag-filter-column` を `position: fixed; inset: 0` のフルスクリーンオーバーレイ化（`body.mobile-filter-open` 時に表示）
  - フィルター内はヘッダーを固定し、チップエリアのみスクロール
  - 「絞り込む」ボタンを検索バーの2行目に配置

#### `frontend/js/app.js`（バージョン v3→v4）

- **要素参照追加**: `mobileBackBtn`, `filterOpenBtn`, `filterCloseBtn`
- **イベントリスナー追加**:
  - 「← 一覧に戻る」: `body` から `mobile-detail-open` を除去
  - 「絞り込む」: `body` に `mobile-filter-open` を付与
  - 「✕」: `body` から `mobile-filter-open` を除去
- **`selectBook()` 内**: `window.innerWidth < 768` のとき `body` に `mobile-detail-open` を付与
- **`updateFilterHeader()` 内**: `filterOpenBtn` のテキストとスタイルをフィルター選択件数に連動して更新

---

## 2. viewer.html（本文閲覧画面）のスマートフォン対応

### 方針

見開き2ページ表示（右ページ + 左ページ）を、スマートフォンでは単一ページ表示に切り替える。レイアウト計算・ページ送りロジック・ナビゲーションをすべて単一ページ前提に切り替え、タッチスワイプ操作を追加する。

### 修正ファイルと箇所

#### `frontend/viewer.html`（バージョン v2→v3）

- CSS バージョン番号を更新するのみ（HTML構造の変更なし）

#### `frontend/viewer.css`（バージョン v2→v3）

- **`@media (max-width: 767px)` ブロック**を末尾に追加:
  - `.page-left`, `.fore-edge` を `display: none`（左ページ・小口を非表示）
  - `.page-right` を `flex: 1` で全幅化、パディング縮小
  - `.book-frame` の幅を `95vw`、高さを `calc(100vh - 100px)` に変更
  - `.screen-container` のパディングを縮小
  - コントロールバーを `flex-wrap: wrap` で折り返し、`#back-button` を1行目に単独配置

#### `frontend/js/state.js`

- **`state` オブジェクト**に `isMobile: false` フィールドを追加
- **`updateIsMobile()` 関数**を追加（`window.innerWidth < 768` で判定）

#### `frontend/js/layout.js`

- **`updateLayout()` 内のページ幅計算**を分岐:
  - デスクトップ: 従来通り `(paperWidth - foreEdge) / 2`
  - モバイル: `paperWidth`（full幅、fore-edge=0）
- **ページ要素への `flex` 設定**を分岐:
  - モバイル: `.page-right` の `flex` をリセットし、CSS `flex: 1` に委ねる
- **偶数ページ強制補正** (`currentPage % 2 !== 0`) を `!state.isMobile` の条件付きに変更

#### `frontend/js/renderer.js`

- **左ページ描画ブロック**に `&& !state.isMobile` を追加し、モバイルでは左ページのDOM操作をスキップ
- **左ページのタイトル・ページ番号更新**を `!state.isMobile` 条件付きに変更
- **`pageTotal` の表示形式**を分岐:
  - モバイル: `/ N`（シンプル形式）
  - デスクトップ: 従来の `〜M / N` 形式

#### `frontend/js/navigation.js`

- **`btnPrev` クリック**: モバイルは `-1`、デスクトップは `-2`
- **`btnNext` クリック**: モバイルは `+1`、デスクトップは `+2`
- **`pageInput` の `change` イベント**: モバイルは偶数丸めをスキップ
- **キーボードナビゲーション** (`ArrowLeft`/`ArrowRight`): `step` 変数で `1` か `2` かを切り替え
- **タッチスワイプ処理を追加**:
  - `touchstart` でX座標を記録
  - `touchend` で差分50px超のとき: 左スワイプ→次ページ、右スワイプ→前ページ

#### `frontend/js/viewer.js`

- **`import` 文**に `updateIsMobile` を追加
- **初期化時** (`DOMContentLoaded`): `initElements()` 直後に `updateIsMobile()` を呼び出し
- **`ResizeObserver` コールバック**: `updateLayout()` 前に `updateIsMobile()` を呼び出し

---

## 動作まとめ

| 画面 | デスクトップ | スマートフォン |
|------|-------------|----------------|
| index: レイアウト | 3カラム（リスト/詳細/フィルター） | リストのみ全幅 |
| index: 詳細表示 | 中央カラムに常時表示 | タップで全画面オーバーレイ |
| index: タグフィルター | 右カラムに常時表示 | 「絞り込む」ボタンで全画面オーバーレイ |
| viewer: ページ表示 | 見開き2ページ | 単一ページ全幅 |
| viewer: ページ送り | ±2ページ / キーボード | ±1ページ / スワイプ / キーボード |
| viewer: 小口・左ページ | 表示あり | 非表示 |
