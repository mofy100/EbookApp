import os
import re
from bs4 import BeautifulSoup, NavigableString, Tag

def parse_aozora_html(input_filepath, output_filepath):
    """
    青空文庫のオリジナルHTMLを読み込み、アプリ専用のクリーンなE-book DOM (HTML)に変換して保存する。
    画像(外字)のダウンロードが必要な場合は、そのパスのリストを返す。
    """
    if not os.path.exists(input_filepath):
        return []

    with open(input_filepath, 'r', encoding='utf-8') as f:
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
    
    def process_node(node, container, current_indent=None, current_align=None):
        nonlocal current_p
        
        if isinstance(node, NavigableString):
            text = str(node)
            # 生HTML内の改行コードを除去（ブラウザの半角スペース化を防ぐ）
            text = re.sub(r'[\r\n]+', '', text)
            if text:
                current_p.append(text)
                
        elif isinstance(node, Tag):
            if node.name == 'br':
                # 青空文庫における br は段落の切れ目
                if len(current_p.contents) > 0:
                    if current_indent:
                        current_p['class'] = current_p.get('class', []) + [current_indent]
                    if current_align:
                        current_p['class'] = current_p.get('class', []) + [current_align]
                    container.append(current_p)
                current_p = new_soup.new_tag('p')
                
            elif node.name == 'div':
                # divはブロック要素（字下げなどのコンテナ）
                indent_class = None
                align_class = None
                classes = node.get('class', [])
                for cls in classes:
                    if cls.startswith('jisage_'):
                        num = cls.split('_')[1]
                        indent_class = f"indent-{num}"
                    elif cls == 'chitsuki_1' or cls == 'chitsuki_2':
                        align_class = "align-end"
                
                # インラインスタイルの字下げ検知 (margin-left: Xem)
                style = node.get('style', '')
                margin_match = re.search(r'margin-left:\s*([0-9]+)em', style)
                if margin_match:
                    indent_class = f"indent-{margin_match.group(1)}"
                
                # divに入る前に現在の段落を確定させる
                if len(current_p.contents) > 0:
                    container.append(current_p)
                    current_p = new_soup.new_tag('p')
                
                # 子ノードを再帰的に処理
                for child in list(node.children):
                    process_node(child, container, current_indent=indent_class, current_align=align_class)
                
                # divが終わった後も段落を確定させる
                if len(current_p.contents) > 0:
                    if indent_class:
                        current_p['class'] = current_p.get('class', []) + [indent_class]
                    if align_class:
                        current_p['class'] = current_p.get('class', []) + [align_class]
                    container.append(current_p)
                    current_p = new_soup.new_tag('p')
                    
            elif re.match(r'^h[1-6]$', node.name):
                if len(current_p.contents) > 0:
                    container.append(current_p)
                    current_p = new_soup.new_tag('p')
                node.name = 'p'
                node['class'] = node.get('class', []) + ['text-heading']
                container.append(node)
                
            else:
                # 縦中横などのインライン要素
                if node.get('class') and 'tatechuyoko' in node.get('class'):
                    node['class'] = ['tatechuyoko']
                current_p.append(node)

    # original の main_text の子要素を順に処理
    for child in list(main_text.children):
        process_node(child, body)
        
    if len(current_p.contents) > 0:
        body.append(current_p)

    # 整形したHTMLを出力
    with open(output_filepath, 'w', encoding='utf-8') as f:
        f.write(str(new_soup))

    return images_to_download

if __name__ == "__main__":
    # 単体テスト用
    target = "backend/data/2/2_20959.html"
    parsed_target = "backend/data/2/2_20959_parsed.html"
    print(f"Parsing {target} ...")
    images = parse_aozora_html(target, parsed_target)
    print(f"Parse complete. Generated {parsed_target}")
    if images:
        print(f"Gaiji images to download: {len(images)}")
