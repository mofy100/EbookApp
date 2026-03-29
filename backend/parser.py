import os
import re
from bs4 import BeautifulSoup, NavigableString, Tag

def parse_aozora_html(input_filepath, output_filepath):
    """
    青空文庫のオリジナルHTMLを読み込み、アプリ専用のクリーンなE-book DOM (HTML)に変換して保存する。
    画像(外字)のダウンロードが必要な場合は、そのパスのリストを返す。
    """
    # エンコーディングの試行
    html_content = None
    for enc in ['utf-8', 'cp932', 'euc_jp']:
        try:
            with open(input_filepath, 'r', encoding=enc) as f:
                html_content = f.read()
            break
        except UnicodeDecodeError:
            continue
    
    if html_content is None:
        # 最終手段としてエラーを無視して読み込む
        with open(input_filepath, 'r', encoding='utf-8', errors='ignore') as f:
            html_content = f.read()

    # BeautifulSoupでパース（lxmlが利用可能ならlxmlを使用）
    soup = BeautifulSoup(html_content, 'html.parser')

    # 1. メタデータの抽出
    title_tag = soup.find('h1', class_='title')
    title = title_tag.get_text(strip=True) if title_tag else "無題"

    author_tag = soup.find('h2', class_='author')
    author = author_tag.get_text(strip=True) if author_tag else "作者不明"

    # 2. 新しい DOM の構築準備
    new_soup = BeautifulSoup('<article class="ebook-content"></article>', 'html.parser')
    article = new_soup.article

    header = new_soup.new_tag('header', attrs={'class': 'ebook-header'})
    h1 = new_soup.new_tag('h1', attrs={'class': 'ebook-title-main'})
    h1.string = title
    h2 = new_soup.new_tag('h2', attrs={'class': 'ebook-author-main'})
    h2.string = author
    header.append(h1)
    header.append(h2)
    article.append(header)

    body = new_soup.new_tag('div', attrs={'class': 'ebook-body'})
    article.append(body)

    # 3. オリジナル本文領域の取得とクレンジング
    main_text = soup.find('div', class_='main_text')
    if not main_text:
        return []

    # <rp> タグ（ルビ非対応用括弧）を完全削除
    for rp in main_text.find_all('rp'):
        rp.decompose()
        
    # <font> タグを削除（中身のテキストは残す）
    for font_tag in main_text.find_all('font'):
        font_tag.unwrap()

    # 末尾の不要な注記ブロックを削除
    for div in main_text.find_all('div', class_=['bibliographical_information', 'notation_notes']):
        div.decompose()
        
    # width指定の削除
    for tag in main_text.find_all(True):
        if 'width' in tag.attrs:
            del tag['width']

    # 画像のパス抽出と書き換え
    images_to_download = []
    for img in main_text.find_all('img'):
        src = img.get('src', '')
        if 'gaiji' in src:
            filename = os.path.basename(src)
            img['src'] = f"/api/assets/gaiji/{filename}"
            img['class'] = img.get('class', []) + ['gaiji']
            images_to_download.append((src, filename))

    # 4. 本文の <p> タグ化と階層化
    current_p = new_soup.new_tag('p')
    
    def get_standard_classes(aozora_classes):
        """
        青空文庫のクラス名を標準レイアウトクラスに変換する
        """
        standard = []
        for cls in aozora_classes:
            # 1. 字下げ (jisage_X -> indent-X)
            if cls.startswith('jisage_'):
                num = cls.split('_')[1]
                standard.append(f"indent-{num}")
            
            # 2. 地付き (chitsuki_X -> text-bottom)
            elif cls.startswith('chitsuki_'):
                standard.append("text-bottom")
                
            # 3. 字詰め (jizume_X -> jizume-X)
            elif cls.startswith('jizume_'):
                num = cls.split('_')[1]
                standard.append(f"jizume-{num}")

            # 4. 改ページ (page-break)
            elif 'page-break' in cls or 'pagebreak' in cls or 'ext-pagebreak' in cls:
                standard.append("page-break")
            
            # 5. ホワイトリスト（そのまま通すもの）
            elif cls in ['tatechuyoko', 'space-line', 'space-line-2', 'size-2x', 'size-3x', 'text-center', 'text-bottom', 'text-notes']:
                standard.append(cls)
                
            # 6. 見出しなどの構造
            elif cls in ['title', 'author', 'dai-midashi', 'naka-midashi', 'sho-midashi']:
                standard.append(f"az-{cls}")
        
        return list(set(standard))

    def flush_paragraph(container, indent=None, align=None, extra_classes=None):
        """
        現在の段落(current_p)を確定してコンテナに追加し、新しい段落を開始する
        """
        nonlocal current_p
        if len(current_p.contents) > 0:
            classes = get_standard_classes(current_p.get('class', []))
            if indent: classes.append(indent)
            if align: classes.append(align)
            if extra_classes: classes.extend(extra_classes)
            
            if classes:
                current_p['class'] = list(set(classes))
            container.append(current_p)
            current_p = new_soup.new_tag('p')

    def process_node(node, container, current_indent=None, current_align=None):
        nonlocal current_p # Test Edit
        
        if isinstance(node, NavigableString):
            text = str(node)
            text = re.sub(r'[\r\n\t]+', '', text)
            if text:
                current_p.append(text)
                
        elif isinstance(node, Tag):
            # 特殊なクラスを持つ要素（改ページなど）の処理
            node_classes = node.get('class', [])
            std_classes = get_standard_classes(node_classes)

            if "page-break" in std_classes:
                flush_paragraph(container, current_indent, current_align)
                pb = new_soup.new_tag('div', attrs={'class': 'page-break'})
                container.append(pb)
                return

            if node.name == 'br':
                # 単一の br は改行（段落の終了）として扱う
                flush_paragraph(container, current_indent, current_align)
                
            elif node.name in ['div', 'blockquote', 'section']:
                # ブロック要素の開始前に現在の段落をフラッシュ
                flush_paragraph(container, current_indent, current_align)

                # 新しいコンテキスト（インデント等）の抽出
                new_indent = current_indent
                new_align = current_align
                extra_classes = []
                
                for cls in std_classes:
                    if cls.startswith('indent-'): new_indent = cls
                    elif cls == 'text-bottom': new_align = cls
                    elif cls.startswith('jizume-'): extra_classes.append(cls)

                # インラインスタイルの字下げ検知
                style = node.get('style', '')
                margin_match = re.search(r'margin-left:\s*([0-9]+)em', style)
                if margin_match:
                    new_indent = f"indent-{margin_match.group(1)}"
                
                # 子ノードを再帰的に処理
                for child in list(node.children):
                    process_node(child, container, current_indent=new_indent, current_align=new_align)
                
                # ブロック終了後のフラッシュ（検出した追加クラスも付与）
                flush_paragraph(container, new_indent, new_align, extra_classes=extra_classes)
                
            elif re.match(r'^h[1-6]$', node.name) or 'az-dai-midashi' in std_classes or 'az-naka-midashi' in std_classes:
                # 見出し処理
                flush_paragraph(container, current_indent, current_align)
                
                heading_p = new_soup.new_tag('p')
                h_classes = ['text-heading'] + std_classes
                if current_indent: h_classes.append(current_indent)
                if current_align: h_classes.append(current_align)
                heading_p['class'] = list(set(h_classes))
                
                for child in node.children:
                    heading_p.append(child.extract())
                container.append(heading_p)
                
            elif node.name == 'p':
                if len(current_p.contents) > 0:
                    flush_paragraph(container, current_indent, current_align)
                
                # ホワイトリストに基づきクラスを引き継ぐ
                if std_classes:
                    current_p['class'] = std_classes
                
                for child in list(node.children):
                    process_node(child, container, current_indent=current_indent, current_align=current_align)
                
                flush_paragraph(container, current_indent, current_align)
                
            else:
                # 縦中横や外字、その他のインライン要素
                if std_classes:
                    # インライン要素が標準クラスを持つ場合は付与
                    node['class'] = std_classes
                current_p.append(node)

    # original の main_text の子要素を順に処理
    for child in list(main_text.children):
        process_node(child, body)
        
    flush_paragraph(body)

    # 整形したHTMLを出力（エディタで見やすいようにブロック要素の後に改行を加える）
    html_str = str(new_soup)
    for tag in ['</p>', '</header>', '</div>', '</article>']:
        html_str = html_str.replace(tag, tag + '\n')

    with open(output_filepath, 'w', encoding='utf-8') as f:
        f.write(html_str)

    return images_to_download

if __name__ == "__main__":
    import argparse
    import glob
    
    parser = argparse.ArgumentParser(description='origin.html を読み込み、標準化された content.html に変換する')
    parser.add_argument('--n', type=int, default=0, help='処理する最大件数 (0は無制限)')
    parser.add_argument('--replace', action='store_true', help='すでに content.html がある場合でも上書きする')
    parser.add_argument('--id', type=int, help='特定の作品IDのみを処理する')
    args = parser.parse_args()

    # 個別の入出力指定がある場合はそれを使用（以前の互換性のため）
    # ただし、現在の argparse と競合しないように調整が必要
    
    data_dir = "backend/data"
    parsed_count = 0
    
    # 処理対象のディレクトリを特定
    if args.id:
        target_dirs = [os.path.join(data_dir, str(args.id))]
    else:
        # data/1, data/2... などの数字のディレクトリをすべて取得
        target_dirs = [d for d in glob.glob(os.path.join(data_dir, "*")) if os.path.isdir(d) and os.path.basename(d).isdigit()]
        # 数値順にソート（一応）
        target_dirs.sort(key=lambda x: int(os.path.basename(x)))

    for d in target_dirs:
        if args.n > 0 and parsed_count >= args.n:
            break
            
        work_id = os.path.basename(d)
        origin_path = os.path.join(d, "origin.html")
        content_path = os.path.join(d, "content.html")
        
        # 特殊対応：以前の parsed.html がある場合のリネーム（移行措置）
        old_parsed_path = os.path.join(d, "parsed.html")
        if os.path.exists(old_parsed_path) and not os.path.exists(content_path):
            os.rename(old_parsed_path, content_path)

        if not os.path.exists(origin_path):
            # もし origin.html がないが、元のHTMLっぽファイルがある場合はリネームを試みる
            html_files = [f for f in glob.glob(os.path.join(d, "*.html")) if "content" not in f and "parsed" not in f and "test" not in f]
            if html_files:
                os.rename(html_files[0], origin_path)
            else:
                continue
                
        # すでに content.html があり、かつ replace フラグがない場合はスキップ
        if os.path.exists(content_path) and not args.replace:
            continue
            
        print(f"[{parsed_count+1}] Parsing 作品ID: {work_id} ...")
        try:
            parse_aozora_html(origin_path, content_path)
            print(f"  => content.html を生成しました")
            parsed_count += 1
        except Exception as e:
            print(f"  => [エラー] パース失敗: {e}")
            
    print(f"\n完了。処理した作品数: {parsed_count} 件")
