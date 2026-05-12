import os
import re
import json
import glob
from bs4 import BeautifulSoup, NavigableString, Tag

MIDASHI_LEVEL_MAP = {
    'o-midashi': 1, 'dogyo-o-midashi': 1, 'mado-o-midashi': 1,
    'naka-midashi': 2, 'dogyo-naka-midashi': 2, 'mado-naka-midashi': 2,
    'ko-midashi': 3, 'dogyo-ko-midashi': 3, 'mado-ko-midashi': 3,
}


def gaiji_to_unicode(filename):
    name = os.path.basename(filename)
    if name.endswith('.png'):
        name = name[:-4]
    parts = name.split('-')
    if len(parts) != 3:
        return None
    try:
        plane, row, cell = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if not (1 <= row <= 94 and 1 <= cell <= 94):
        return None
    try:
        if plane == 1:
            return bytes([row + 0xA0, cell + 0xA0]).decode('euc_jis_2004')
        elif plane == 2:
            return bytes([0x8F, row + 0xA0, cell + 0xA0]).decode('euc_jis_2004')
    except (UnicodeDecodeError, ValueError):
        return None
    return None


def _convert_nodes_to_paragraphs(nodes):
    ctx = BeautifulSoup('<div></div>', 'html.parser')
    container = ctx.div
    current_p = ctx.new_tag('p')

    def flush(cont, indent, align):
        nonlocal current_p
        if len(current_p.contents) > 0:
            classes = []
            if indent: classes.append(indent)
            if align: classes.append(align)
            if classes:
                current_p['class'] = list(set(current_p.get('class', []) + classes))
            cont.append(current_p)
            current_p = ctx.new_tag('p')

    def process_node(node, cont, current_indent=None, current_align=None):
        nonlocal current_p

        if isinstance(node, NavigableString):
            text = re.sub(r'[\r\n\t]+', '', str(node))
            if text:
                current_p.append(text)

        elif isinstance(node, Tag):
            if node.name == 'br':
                flush(cont, current_indent, current_align)

            elif node.name in ['div', 'blockquote', 'section']:
                indent_class = current_indent
                align_class = current_align

                for cls in node.get('class', []):
                    if cls.startswith('jisage_'):
                        indent_class = f"indent-{cls.split('_')[1]}"
                    elif cls.startswith('chitsuki_'):
                        align_class = "text-bottom"
                    elif 'page-break' in cls or 'pagebreak' in cls:
                        pb = ctx.new_tag('div', attrs={'class': 'page-break'})
                        cont.append(pb)

                margin_match = re.search(r'margin-left:\s*([0-9]+)em', node.get('style', ''))
                if margin_match:
                    indent_class = f"indent-{margin_match.group(1)}"

                flush(cont, current_indent, current_align)
                for child in list(node.children):
                    process_node(child, cont, current_indent=indent_class, current_align=align_class)
                flush(cont, indent_class, align_class)

            elif re.match(r'^h[1-6]$', node.name):
                flush(cont, current_indent, current_align)
                heading_p = ctx.new_tag('p')
                heading_classes = list(set(['text-heading', f"az-{node.name}"] + node.get('class', [])))
                if current_indent: heading_classes.append(current_indent)
                if current_align: heading_classes.append(current_align)
                heading_p['class'] = heading_classes
                for child in list(node.children):
                    heading_p.append(child.extract())
                cont.append(heading_p)

            elif node.name == 'p':
                flush(cont, current_indent, current_align)
                whitelist = [
                    'tatechuyoko', 'space-line', 'space-line-2',
                    'size-2x', 'size-3x', 'text-center', 'text-bottom', 'page-break'
                ]
                preserved = [cls for cls in node.get('class', []) if cls in whitelist]
                if preserved:
                    current_p['class'] = list(set(current_p.get('class', []) + preserved))
                for child in list(node.children):
                    process_node(child, cont, current_indent=current_indent, current_align=current_align)
                flush(cont, current_indent, current_align)

            else:
                whitelist = [
                    'tatechuyoko', 'space-line', 'space-line-2',
                    'size-2x', 'size-3x', 'text-center', 'text-bottom', 'page-break'
                ]
                preserved = [cls for cls in node.get('class', []) if cls in whitelist]
                if preserved:
                    node['class'] = preserved
                current_p.append(node)

    for node in nodes:
        process_node(node, container)

    if len(current_p.contents) > 0:
        container.append(current_p)

    for p in list(container.children):
        if p.name == 'p' and not p.get_text(strip=True) and not p.find('img'):
            p.decompose()
        else:
            break
    for p in reversed(list(container.children)):
        if p.name == 'p' and not p.get_text(strip=True) and not p.find('img'):
            p.decompose()
        else:
            break

    return container


def get_midashi_level(el):
    if not isinstance(el, Tag) or 'text-heading' not in el.get('class', []):
        return None
    for cls in el.get('class', []):
        if cls in MIDASHI_LEVEL_MAP:
            return MIDASHI_LEVEL_MAP[cls]
    return None


def process_aozora(input_filepath, output_dir):
    """
    origin.html を読み込み、title.html / content_n.html / bib.html / manifest.json を直接生成する。
    戻り値: list of (src, filename) for gaiji images requiring download
    """
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

    title_tag = soup.find('h1', class_='title')
    title = title_tag.get_text(strip=True) if title_tag else "無題"
    author_tag = soup.find('h2', class_='author')
    author = author_tag.get_text(strip=True) if author_tag else "作者不明"
    translator_tag = soup.find('h2', class_='translator')
    translator = translator_tag.get_text(strip=True) if translator_tag else None

    main_text = soup.find('div', class_='main_text')
    if not main_text:
        return []

    for rp in main_text.find_all('rp'):
        rp.decompose()
    for notes in main_text.find_all('span', class_='notes'):
        notes.decompose()

    for ruby in main_text.find_all('ruby'):
        rb = ruby.find('rb')
        rt = ruby.find('rt')
        if rb and rt and '※' in rb.get_text():
            hiragana = rt.get_text()
            next_sib = ruby.find_next_sibling()
            if next_sib and next_sib.name == 'span' and 'notes' in next_sib.get('class', []):
                next_sib.decompose()
            ruby.replace_with(hiragana)

    for font_tag in main_text.find_all('font'):
        font_tag.unwrap()

    for tag in main_text.find_all(True):
        if 'width' in tag.attrs:
            del tag['width']

    images_to_download = []
    for img in main_text.find_all('img'):
        src = img.get('src', '')
        if 'gaiji' in src:
            filename = os.path.basename(src)
            unicode_char = gaiji_to_unicode(filename)
            if unicode_char:
                img.replace_with(unicode_char)
            else:
                img['src'] = f"/api/assets/gaiji/{filename}"
                img['class'] = img.get('class', []) + ['gaiji']
                images_to_download.append((src, filename))

    bib_sections = []
    for div in soup.find_all('div', class_='bibliographical_information'):
        bib_sections.append(div.extract())

    main_container = _convert_nodes_to_paragraphs(list(main_text.children))

    bib_container = None
    if bib_sections:
        bib_nodes = []
        for bib in bib_sections:
            bib_nodes.extend(list(bib.children))
        bib_container = _convert_nodes_to_paragraphs(bib_nodes)

    # ---- タイトルページ ----

    title_html = f'<article class="ebook-content">\n<p class="ebook-title-main">{title}</p>\n</article>\n'
    with open(os.path.join(output_dir, "title.html"), 'w', encoding='utf-8') as f:
        f.write(title_html)
    title_chapter = {"index": -1, "file": "title.html", "title": title, "level": 0, "char_count": 0}

    chapters = []
    chapter_index = 0
    MAX_CHARS = 10000

    # ---- 分割ユーティリティ ----

    def count_chars(elements):
        return sum(len(el.get_text()) for el in elements if isinstance(el, Tag))

    def split_at_o_midashi(elements):
        sections, current = [], []
        for el in elements:
            el_level = get_midashi_level(el)
            if el_level == 1 and current:
                sections.append(current)
                current = []
            current.append(el)
        if current:
            sections.append(current)
        return sections if sections else [elements]

    def split_by_chars(elements, max_chars):
        chunks, current, current_chars = [], [], 0
        for el in elements:
            el_chars = len(el.get_text()) if isinstance(el, Tag) else 0
            if current_chars + el_chars > max_chars and current:
                chunks.append(current)
                current, current_chars = [], 0
            current.append(el)
            current_chars += el_chars
        if current:
            chunks.append(current)
        return chunks if chunks else [elements]

    def split_hierarchically(elements):
        sections = split_at_o_midashi(elements)
        result = []
        for section in sections:
            if count_chars(section) <= MAX_CHARS:
                result.append(section)
            else:
                result.extend(split_by_chars(section, MAX_CHARS))
        return result if result else [elements]

    def extract_heading_title(elements):
        for el in elements:
            if isinstance(el, Tag) and 'text-heading' in el.get('class', []):
                anchor = el.find(class_='midashi_anchor')
                if anchor:
                    return anchor.get_text(strip=True)
                return el.get_text(strip=True)
        return None

    def extract_first_midashi_level(elements):
        for el in elements:
            lv = get_midashi_level(el)
            if lv is not None:
                return lv
        return None

    def has_actual_content(elements):
        return any(
            isinstance(el, Tag) and (el.get_text(strip=True) or el.find('img'))
            for el in elements
        )

    def save_chapter(elements, index, filename=None, heading_title=None, heading_level=None):
        if not elements:
            return

        ctx = BeautifulSoup('<article class="ebook-content"></article>', 'html.parser')
        article = ctx.article
        for el in elements:
            article.append(el)

        if index == 0:
            for _ in range(2):
                space_p = ctx.new_tag('p', attrs={'class': 'space-line'})
                article.insert(0, space_p)

        for i, el in enumerate(article.find_all(['p', 'div'])):
            el['id'] = f"pos-{i}"

        if filename is None:
            filename = f"content_{index}.html"

        html_str = (
            str(ctx)
            .replace('</p>', '</p>\n')
            .replace('<article class="ebook-content">', '<article class="ebook-content">\n')
            .replace('</article>', '</article>\n')
        )
        html_str = re.sub(r'([。、])(」)', r'\1<span class="kern-punct">\2</span>', html_str)

        with open(os.path.join(output_dir, filename), 'w', encoding='utf-8') as f:
            f.write(html_str)

        char_count = sum(len(el.get_text()) for el in elements if isinstance(el, Tag))
        chapters.append({
            "index": index,
            "file": filename,
            "title": heading_title or "",
            "level": heading_level,
            "char_count": char_count,
        })

    # ---- 本文の章分割・保存 ----

    all_elements = main_container.find_all(['p', 'div'], recursive=False)
    for section in split_hierarchically(all_elements):
        if has_actual_content(section):
            save_chapter(
                section,
                chapter_index,
                heading_title=extract_heading_title(section),
                heading_level=extract_first_midashi_level(section),
            )
            chapter_index += 1

    # ---- ビブリオグラフィー ----

    if bib_container:
        for s in bib_container.find_all(string=re.compile(r'青空文庫作成ファイル：')):
            s.replace_with("")
        for s in bib_container.find_all(string=re.compile(r'このファイルは、インターネットの図書館')):
            s.replace_with("")
        for a in bib_container.find_all('a', href=re.compile(r'aozora\.gr\.jp')):
            if "青空文庫" in a.get_text():
                a.string = "青空文庫"
            next_node = a.next_sibling
            if next_node and isinstance(next_node, NavigableString) and "で作られました" in next_node:
                next_node.replace_with("で公開されているデータをもとに作成しました。")

        _tmp = BeautifulSoup('', 'html.parser')
        bib_heading = _tmp.new_tag('p', attrs={'class': ['text-heading', 'az-h4', 'naka-midashi']})
        bib_heading.string = "ビブリオグラフィー"
        bib_elements = [bib_heading] + bib_container.find_all(['p', 'div'], recursive=False)
        save_chapter(bib_elements, chapter_index, filename="bib.html", heading_title="ビブリオグラフィー", heading_level=2)

    # ---- manifest.json ----

    all_chapters = [title_chapter] + chapters
    manifest = {
        "title": title,
        "author": author,
        "translator": translator,
        "chapter_count": len(all_chapters),
        "chapters": all_chapters,
    }
    with open(os.path.join(output_dir, "manifest.json"), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return images_to_download


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='origin.html からコンテンツファイルを直接生成する')
    parser.add_argument('--n', type=int, default=0, help='処理する最大件数 (0は無制限)')
    parser.add_argument('--replace', action='store_true', help='すでにファイルがある場合でも上書きする')
    parser.add_argument('--id', type=int, help='特定の作品IDのみを処理する')
    args = parser.parse_args()

    data_dir = "backend/data"
    processed_count = 0

    if args.id:
        target_dirs = [os.path.join(data_dir, str(args.id))]
    else:
        target_dirs = [d for d in glob.glob(os.path.join(data_dir, "*")) if os.path.isdir(d) and os.path.basename(d).isdigit()]
        target_dirs.sort(key=lambda x: int(os.path.basename(x)))

    for d in target_dirs:
        if args.n > 0 and processed_count >= args.n:
            break

        work_id = os.path.basename(d)
        origin_path = os.path.join(d, "origin.html")
        manifest_path = os.path.join(d, "manifest.json")

        if not os.path.exists(origin_path):
            continue
        if os.path.exists(manifest_path) and not args.replace:
            continue

        print(f"[{processed_count+1}] 処理中 作品ID: {work_id} ...")
        try:
            for old_file in (glob.glob(os.path.join(d, 'content_*.html'))
                             + glob.glob(os.path.join(d, 'bib.html'))
                             + glob.glob(os.path.join(d, 'title.html'))):
                os.remove(old_file)
            process_aozora(origin_path, d)
            print(f"  => コンテンツファイルを生成しました")
            processed_count += 1
        except Exception as e:
            print(f"  => [エラー] 処理失敗: {e}")

    print(f"\n完了。処理した作品数: {processed_count} 件")
