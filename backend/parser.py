import os
import re
import json
import glob
from bs4 import BeautifulSoup, NavigableString, Tag

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
        elif any(x in cls for x in ['page-break', 'pagebreak', 'ext-pagebreak']):
            standard.append("page-break")
        
        # 5. ホワイトリスト（そのまま通すもの）
        elif cls in ['tatechuyoko', 'space-line', 'space-line-2', 'size-2x', 'size-3x', 'text-center', 'text-bottom', 'text-notes']:
            standard.append(cls)
            
        # 6. 見出しなどの構造
        elif cls in ['title', 'author', 'dai-midashi', 'naka-midashi', 'sho-midashi']:
            standard.append(f"az-{cls}")
    
    return list(set(standard))

def parse_aozora_html(input_filepath, output_dir):
    """
    青空文庫のオリジナルHTMLを読み込み、章ごとに分割された <p> タグ主体の HTML ファイルを作成する。
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
        with open(input_filepath, 'r', encoding='utf-8', errors='ignore') as f:
            html_content = f.read()

    soup = BeautifulSoup(html_content, 'html.parser')

    # 1. メタデータの抽出
    title_tag = soup.find('h1', class_='title')
    title = title_tag.get_text(strip=True) if title_tag else "無題"
    author_tag = soup.find('h2', class_='author')
    author = author_tag.get_text(strip=True) if author_tag else "作者不明"

    # 2. content_0.html (タイトル・著者) の作成
    content_0_soup = BeautifulSoup('<article class="ebook-content title-page"></article>', 'html.parser')
    p_title = content_0_soup.new_tag('p', attrs={'class': 'ebook-title-main'})
    p_title.string = title
    p_author = content_0_soup.new_tag('p', attrs={'class': 'ebook-author-main'})
    p_author.string = author
    content_0_soup.article.append(p_title)
    content_0_soup.article.append(p_author)
    
    content_0_html = str(content_0_soup).replace('</p>', '</p>\n').replace('<article class="ebook-content">', '<article class="ebook-content">\n').replace('</article>', '</article>\n')
    with open(os.path.join(output_dir, "content_0.html"), 'w', encoding='utf-8') as f:
        f.write(content_0_html)

    # 3. 本文のクレンジング
    main_text = soup.find('div', class_='main_text')
    if not main_text:
        return []

    for rp in main_text.find_all('rp'):
        rp.decompose()
    for font_tag in main_text.find_all('font'):
        font_tag.unwrap()
    for div in main_text.find_all('div', class_=['bibliographical_information', 'notation_notes']):
        div.decompose()
    for tag in main_text.find_all(True):
        if 'width' in tag.attrs:
            del tag['width']

    images_to_download = []
    for img in main_text.find_all('img'):
        src = img.get('src', '')
        if 'gaiji' in src:
            filename = os.path.basename(src)
            img['src'] = f"/api/assets/gaiji/{filename}"
            img['class'] = img.get('class', []) + ['gaiji']
            images_to_download.append((src, filename))

    # 4. 章分割の実行
    chapters = []
    chapter_index = 1

    def save_chapter(nodes, index):
        if not nodes: return
        chapter_soup = BeautifulSoup('<article class="ebook-content"></article>', 'html.parser')
        article = chapter_soup.article
        
        current_p = chapter_soup.new_tag('p')
        
        def process_node(node, container, current_indent=None, current_align=None):
            nonlocal current_p
            
            if isinstance(node, NavigableString):
                text = str(node)
                # 生HTML内の改行コードを除去（ブラウザの半角スペース化を防ぐ）
                text = re.sub(r'[\r\n\t]+', '', text)
                if text:
                    current_p.append(text)
                    
            elif isinstance(node, Tag):
                if node.name == 'br':
                    # 青空文庫における br は段落の切れ目
                    if len(current_p.contents) > 0:
                        # 分割される前の段落にも現在の継承クラスを付与
                        classes = []
                        if current_indent: classes.append(current_indent)
                        if current_align: classes.append(current_align)
                        if classes:
                            current_p['class'] = list(set(current_p.get('class', []) + classes))
                        container.append(current_p)
                    current_p = chapter_soup.new_tag('p')
                    
                elif node.name in ['div', 'blockquote', 'section']:
                    # ブロック要素（字下げなどのコンテナ）
                    indent_class = current_indent
                    align_class = current_align
                    
                    classes = node.get('class', [])
                    for cls in classes:
                        if cls.startswith('jisage_'):
                            num = cls.split('_')[1]
                            indent_class = f"indent-{num}"
                        elif cls.startswith('chitsuki_'):
                            align_class = "text-bottom"
                        elif 'page-break' in cls or 'pagebreak' in cls:
                            # 改ページを検出し、独立した div.page-break を挿入
                            pb = chapter_soup.new_tag('div', attrs={'class': 'page-break'})
                            container.append(pb)
                    
                    # インラインスタイルの字下げ検知 (margin-left: Xem)
                    style = node.get('style', '')
                    margin_match = re.search(r'margin-left:\s*([0-9]+)em', style)
                    if margin_match:
                        indent_class = f"indent-{margin_match.group(1)}"
                    
                    # divに入る前に現在の段落を確定させる
                    if len(current_p.contents) > 0:
                        classes = []
                        if current_indent: classes.append(current_indent)
                        if current_align: classes.append(current_align)
                        if classes:
                            current_p['class'] = list(set(current_p.get('class', []) + classes))
                        container.append(current_p)
                        current_p = chapter_soup.new_tag('p')
                    
                    # 子ノードを再帰的に処理（新しいインデント/配置情報を渡す）
                    for child in list(node.children):
                        process_node(child, container, current_indent=indent_class, current_align=align_class)
                    
                    # divが終わった後も段落を確定させる
                    if len(current_p.contents) > 0:
                        classes = []
                        if indent_class: classes.append(indent_class)
                        if align_class: classes.append(align_class)
                        if classes:
                            current_p['class'] = list(set(current_p.get('class', []) + classes))
                        container.append(current_p)
                        current_p = chapter_soup.new_tag('p')
                        
                elif re.match(r'^h[1-6]$', node.name):
                    # 見出しの前に段落があれば確定
                    if len(current_p.contents) > 0:
                        classes = []
                        if current_indent: classes.append(current_indent)
                        if current_align: classes.append(current_align)
                        if classes:
                            current_p['class'] = list(set(current_p.get('class', []) + classes))
                        container.append(current_p)
                        current_p = chapter_soup.new_tag('p')
                    
                    # 見出しをpタグに変換し、クラスを付与
                    heading_p = chapter_soup.new_tag('p')
                    # もとのクラスを保持しつつ text-heading などを追加
                    heading_classes = ['text-heading', f"az-{node.name}"] + node.get('class', [])
                    if current_indent: heading_classes.append(current_indent)
                    if current_align: heading_classes.append(current_align)
                    heading_p['class'] = list(set(heading_classes))
                    
                    for child in list(node.children):
                        heading_p.append(child.extract())
                    container.append(heading_p)
                    
                elif node.name == 'p':
                    # 既存の段落があれば確定させて新しい段落を開始（段落同士の合体を防ぐ）
                    if len(current_p.contents) > 0:
                        classes = []
                        if current_indent: classes.append(current_indent)
                        if current_align: classes.append(current_align)
                        if classes:
                            current_p['class'] = list(set(current_p.get('class', []) + classes))
                        container.append(current_p)
                        current_p = chapter_soup.new_tag('p')

                    # オリジナルに P が含まれる場合、中身を抜き出して新しくなった current_p に追加
                    # クラスも極力引き継ぐ
                    existing_classes = node.get('class', [])
                    whitelist = [
                        'tatechuyoko', 'space-line', 'space-line-2', 
                        'size-2x', 'size-3x', 'text-center', 'text-bottom', 'page-break'
                    ]
                    preserved_classes = [cls for cls in existing_classes if cls in whitelist]
                    if preserved_classes:
                        current_p['class'] = list(set(current_p.get('class', []) + preserved_classes))

                    for child in list(node.children):
                        process_node(child, container, current_indent=current_indent, current_align=current_align)
                    
                    # P要素の処理が終わったので、ここでも確定させる
                    if len(current_p.contents) > 0:
                        classes = []
                        if current_indent: classes.append(current_indent)
                        if current_align: classes.append(current_align)
                        if classes:
                            current_p['class'] = list(set(current_p.get('class', []) + classes))
                        container.append(current_p)
                        current_p = chapter_soup.new_tag('p')

                else:
                    # 縦中横などのインライン要素、または未知の要素
                    # クラス保持（ホワイトリスト形式）
                    existing_classes = node.get('class', [])
                    whitelist = [
                        'tatechuyoko', 
                        'space-line', 'space-line-2', 
                        'size-2x', 'size-3x', 
                        'text-center', 'text-bottom',
                        'page-break'
                    ]
                    preserved_classes = [cls for cls in existing_classes if cls in whitelist]
                    if preserved_classes:
                        node['class'] = preserved_classes
                    current_p.append(node)

        for node in nodes:
            process_node(node, article)
        
        if len(current_p.contents) > 0:
            article.append(current_p)

        # 不要な先頭の空の段落を削除
        for p in list(article.children):
            if p.name == 'p' and not p.get_text(strip=True) and not p.find('img'):
                p.decompose()
            else:
                break
                
        # 同様に末尾の段落も削除
        for p in reversed(list(article.children)):
            if p.name == 'p' and not p.get_text(strip=True) and not p.find('img'):
                p.decompose()
            else:
                break

        filename = f"content_{index}.html"
        html_str = str(chapter_soup).replace('</p>', '</p>\n').replace('<article class="ebook-content">', '<article class="ebook-content">\n').replace('</article>', '</article>\n')
        with open(os.path.join(output_dir, filename), 'w', encoding='utf-8') as f:
            f.write(html_str)
        chapters.append({"index": index, "file": filename})

    def is_func_heading(node):
        if not isinstance(node, Tag): return False
        # 直接のタグ名チェック
        if re.match(r'^h[1-6]$', node.name): return True
        # クラス名チェック
        std = get_standard_classes(node.get('class', []))
        if any(x in std for x in ['az-dai-midashi', 'az-naka-midashi', 'az-sho-midashi']):
            return True
        # 子要素に含むかチェック
        if node.find(['h1','h2','h3','h4','h5','h6', 'h7']): return True # Aozora uses h4 mostly
        if node.find(class_=re.compile(r'midashi')): return True
        return False

    def has_actual_content(nodes):
        for node in nodes:
            if isinstance(node, NavigableString) and str(node).strip(): return True
            if isinstance(node, Tag):
                if node.get_text(strip=True): return True
                if node.find('img'): return True
        return False

    # Heading detection and split
    temp_nodes = []
    for child in list(main_text.children):
        if is_func_heading(child) and temp_nodes:
            if has_actual_content(temp_nodes):
                save_chapter(temp_nodes, chapter_index)
                chapter_index += 1
                temp_nodes = []
        
        temp_nodes.append(child)
    
    if temp_nodes:
        save_chapter(temp_nodes, chapter_index)

    # 5. manifest.json の作成
    manifest = {
        "title": title,
        "author": author,
        "chapter_count": len(chapters) + 1,
        "chapters": [{"index": 0, "file": "content_0.html"}] + chapters
    }
    with open(os.path.join(output_dir, "manifest.json"), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return images_to_download

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='origin.html を読み込み、章分割された content_n.html を生成する')
    parser.add_argument('--n', type=int, default=0, help='処理する最大件数 (0は無制限)')
    parser.add_argument('--replace', action='store_true', help='すでにファイルがある場合でも上書きする')
    parser.add_argument('--id', type=int, help='特定の作品IDのみを処理する')
    args = parser.parse_args()
    
    data_dir = "backend/data"
    parsed_count = 0
    
    if args.id:
        target_dirs = [os.path.join(data_dir, str(args.id))]
    else:
        target_dirs = [d for d in glob.glob(os.path.join(data_dir, "*")) if os.path.isdir(d) and os.path.basename(d).isdigit()]
        target_dirs.sort(key=lambda x: int(os.path.basename(x)))

    for d in target_dirs:
        if args.n > 0 and parsed_count >= args.n:
            break
            
        work_id = os.path.basename(d)
        origin_path = os.path.join(d, "origin.html")
        manifest_path = os.path.join(d, "manifest.json")
        
        if not os.path.exists(origin_path):
            continue
                
        if os.path.exists(manifest_path) and not args.replace:
            continue
            
        print(f"[{parsed_count+1}] Parsing 作品ID: {work_id} ...")
        try:
            parse_aozora_html(origin_path, d)
            print(f"  => 分割ファイルを生成しました")
            parsed_count += 1
        except Exception as e:
            print(f"  => [エラー] パース失敗: {e}")
            
    print(f"\n完了。処理した作品数: {parsed_count} 件")
