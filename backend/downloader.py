import sqlite3
import requests
import time
import os
import zipfile
import io
import glob
from urllib.parse import urljoin
from backend.parser import parse_aozora_html

# 設定
DB_FILE = 'backend/aozora.db'
DATA_DIR = 'backend/data/'
GAIJI_DIR = 'backend/data/gaiji/'

def download_and_extract_zip(url, extract_to):
    """
    指定されたURLからZIPファイルをダウンロードし、指定ディレクトリに展開する。
    テキストファイル (.txt) の場合は、Shift-JISからUTF-8に変換して保存する。
    """
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # メモリ上でZIPを展開
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            for info in z.infolist():
                # まず通常通りファイルとして展開
                extracted_path = z.extract(info, extract_to)
                
                # テキスト・HTMLファイルの場合はShift-JISからUTF-8へ変換
                is_text = extracted_path.lower().endswith('.txt') or extracted_path.lower().endswith('.html') or extracted_path.lower().endswith('.htm')
                if is_text:
                    try:
                        with open(extracted_path, 'r', encoding='shift_jis') as f:
                            content = f.read()
                        
                        # HTMLファイルの文字コード指定タグも書き換えておく
                        if extracted_path.lower().endswith('.html') or extracted_path.lower().endswith('.htm'):
                            content = content.replace('Shift_JIS', 'UTF-8').replace('shift_jis', 'utf-8')
                            
                        # 上書き保存
                        with open(extracted_path, 'w', encoding='utf-8') as f:
                            f.write(content)
                    except UnicodeDecodeError:
                        # 万が一Shift-JISでデコードできない場合はそのままにする
                        pass
                        
        return True
    except Exception as e:
        print(f"[エラー] {url} の展開中に問題が発生しました: {e}")
        return False

def download_text_file(url, extract_to):
    """
    指定されたURLから直接テキストファイル(.txt等)をダウンロードし、保存する
    """
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # 青空文庫はShift-JISが多いため、エンコーディングを推定してUTF-8として保存
        response.encoding = response.apparent_encoding
        
        filename = url.split('/')[-1]
        if not filename:
            filename = "downloaded.txt"
            
        filepath = os.path.join(extract_to, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(response.text)
            
        return True
    except Exception as e:
        print(f"[エラー] {url} のテキストファイル保存中に問題が発生しました: {e}")
        return False

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(GAIJI_DIR, exist_ok=True)
    
    print("データベースを読み込んでいます...")
    
    # SQLiteから検索
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # 著作権がない(has_copyright == 0) かつ XHTMLのURLが存在する作品のみ抽出
    cursor.execute('''
        SELECT id, xhtml_url FROM books 
        WHERE has_copyright = 0 AND xhtml_url IS NOT NULL AND xhtml_url != ""
    ''')
    targets = cursor.fetchall()
    conn.close()
    
    total = len(targets)
    print(f"ダウンロード対象作品候補: {total} 件 (著作権フリーのみ)")
    
    max_download = 10
    downloaded_count = 0
    
    for i, (work_id, xhtml_url) in enumerate(targets, 1):
        if downloaded_count >= max_download:
            break

        # 保存先ディレクトリ (例: backend/data/123/)
        extract_path = os.path.join(DATA_DIR, str(work_id))
        
        # すでにディレクトリが存在していて中身がある場合はレジュームとしてスキップ
        if os.path.exists(extract_path) and len(os.listdir(extract_path)) > 0:
            print(f"[{i}/{total}] 既に展開済みのためスキップ: 作品ID {work_id}")
            continue
            
        print(f"[{i}/{total}] ダウンロード中({work_id})")
        os.makedirs(extract_path, exist_ok=True)
        
        def process_url(u):
            if not u: return False
            u_str = str(u)
            if u_str.endswith('.zip'):
                return download_and_extract_zip(u_str, extract_path)
            elif u_str.endswith('.html') or u_str.endswith('.htm'):
                return download_text_file(u_str, extract_path)
            else:
                print(f"  -> スキップ (非対応の拡張子): {u_str}")
                return False

        success = False
        if xhtml_url:
            print(f"  -> XHTML取得: {xhtml_url}")
            if process_url(xhtml_url):
                success = True

        if success:
            downloaded_count += 1
            print(f"  => ダウンロード成功: {work_id}")
            
            # パース処理を実行
            html_files = glob.glob(os.path.join(extract_path, '*.html')) + glob.glob(os.path.join(extract_path, '*.htm'))
            html_files = [f for f in html_files if not f.endswith('parsed.html')]
            
            if html_files:
                target_html = html_files[0]
                parsed_html = os.path.join(extract_path, 'parsed.html')
                print(f"  -> 専用HTMLへの変換を開始: {target_html}")
                try:
                    images_to_download = parse_aozora_html(target_html, parsed_html)
                    print(f"  => 変換成功: parsed.html を生成しました")
                    
                    # 外字画像のダウンロード
                    if images_to_download:
                        print(f"  -> 外字画像のダウンロード開始 ({len(images_to_download)}件)")
                        for src, filename in images_to_download:
                            gaiji_path = os.path.join(GAIJI_DIR, filename)
                            if not os.path.exists(gaiji_path):
                                img_url = urljoin(xhtml_url, src)
                                try:
                                    img_res = requests.get(img_url, timeout=10)
                                    img_res.raise_for_status()
                                    with open(gaiji_path, 'wb') as img_f:
                                        img_f.write(img_res.content)
                                    print(f"    - 画像保存成功: {filename}")
                                    time.sleep(0.5) # サーバー負荷低減
                                except Exception as e:
                                    print(f"    - 画像取得失敗: {img_url} ({e})")
                except Exception as e:
                    print(f"  => 変換失敗: {e}")
        else:
            # 空のディレクトリを消しておく
            if len(os.listdir(extract_path)) == 0:
                os.rmdir(extract_path)
            continue
            
        # 【重要】サーバーへの負荷軽減のために必ず1秒待機する
        time.sleep(1)
        
    print(f"\n全ての処理が完了しました。今回新規ダウンロードした作品数: {downloaded_count} 件")

if __name__ == '__main__':
    main()
