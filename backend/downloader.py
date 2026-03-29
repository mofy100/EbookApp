import sqlite3
import requests
import time
import os
import zipfile
import io
import glob
from urllib.parse import urljoin

# 設定
DB_FILE = 'backend/aozora.db'
DATA_DIR = 'backend/data'
GAIJI_DIR = 'backend/data/gaiji'

def decode_content(content_bytes):
    """
    バイト列を適切なエンコーディングで文字列に変換する。
    UTF-8, CP932 (Shift-JIS拡張), EUC-JPを順に試行する。
    """
    for enc in ['utf-8', 'cp932', 'euc_jp']:
        try:
            return content_bytes.decode(enc), enc
        except UnicodeDecodeError:
            continue
    # 全て失敗した場合は、エラーを無視してデコードを試みる
    return content_bytes.decode('utf-8', errors='ignore'), 'utf-8'

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
                    with open(extracted_path, 'rb') as f:
                        raw_content = f.read()
                    
                    content, detected_enc = decode_content(raw_content)
                    
                    # HTMLファイルの文字コード指定タグも書き換えておく
                    if extracted_path.lower().endswith('.html') or extracted_path.lower().endswith('.htm'):
                        content = content.replace('Shift_JIS', 'UTF-8').replace('shift_jis', 'utf-8')
                        content = content.replace('EUC-JP', 'UTF-8').replace('euc-jp', 'utf-8')
                        
                    # 上書き保存
                    with open(extracted_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                        
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
        
        # エンコーディングを判定してデコード
        content, detected_enc = decode_content(response.content)
        
        # HTMLの場合はメタタグを置換
        if url.lower().endswith('.html') or url.lower().endswith('.htm'):
            content = content.replace('Shift_JIS', 'UTF-8').replace('shift_jis', 'utf-8')
            content = content.replace('EUC-JP', 'UTF-8').replace('euc-jp', 'utf-8')

        filename = url.split('/')[-1]
        if not filename:
            filename = "downloaded.txt"
            
        filepath = os.path.join(extract_to, filename)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
            
        return True
    except Exception as e:
        print(f"[エラー] {url} のテキストファイル保存中に問題が発生しました: {e}")
        return False

def main():
    import argparse
    parser = argparse.ArgumentParser(description='青空文庫から作品をダウンロードし、origin.htmlとして保存する')
    parser.add_argument('--n', type=int, default=10, help='ダウンロードする件数')
    args = parser.parse_args()

    try:
        os.makedirs(DATA_DIR, exist_ok=True)
    except:
        pass
        
    try:
        os.makedirs(GAIJI_DIR, exist_ok=True)
    except:
        pass
    
    print("データベースを読み込んでいます...")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, xhtml_url FROM books 
        WHERE has_copyright = 0 AND xhtml_url IS NOT NULL AND xhtml_url != ""
    ''')
    targets = cursor.fetchall()
    conn.close()
    
    total = len(targets)
    print(f"ダウンロード対象作品候補: {total} 件")
    
    downloaded_count = 0
    for i, (work_id, xhtml_url) in enumerate(targets, 1):
        if downloaded_count >= args.n:
            break

        extract_path = os.path.join(DATA_DIR, str(work_id))
        origin_file = os.path.join(extract_path, 'origin.html')
        
        # すでに origin.html が存在する場合はスキップ
        if os.path.exists(origin_file):
            continue
            
        print(f"[{downloaded_count+1}/{args.n}] ダウンロード中 (作品ID: {work_id})")
        try:
            os.makedirs(extract_path, exist_ok=True)
        except:
            pass
        
        success = False
        if xhtml_url.endswith('.zip'):
            success = download_and_extract_zip(xhtml_url, extract_path)
        elif xhtml_url.endswith('.html') or xhtml_url.endswith('.htm'):
            success = download_text_file(xhtml_url, extract_path)

        if success:
            # ダウンロードされたファイルを origin.html にリネーム
            html_files = glob.glob(os.path.join(extract_path, '*.html')) + glob.glob(os.path.join(extract_path, '*.htm'))
            html_files = [f for f in html_files if os.path.basename(f) != 'origin.html' and 'parsed' not in f and 'content.html' not in f]
            
            if html_files:
                target_html = html_files[0]
                # すでに origin.html が存在しないことは確認済みだが、念のため
                if not os.path.exists(origin_file):
                    os.rename(target_html, origin_file)
                
                # 他の不要なHTMLファイルを削除（ZIP内に複数ある場合など）
                for f in html_files:
                    if os.path.exists(f) and f != origin_file:
                        try:
                            os.remove(f)
                        except:
                            pass
                
                downloaded_count += 1
                print(f"  => origin.html として保存完了")
            else:
                print(f"  => [警告] HTMLファイルが見つかりませんでした")
        else:
            # 空のディレクトリを消しておく
            if os.path.exists(extract_path) and len(os.listdir(extract_path)) == 0:
                os.rmdir(extract_path)
            print(f"  => [エラー] ダウンロード失敗")

        # サーバー負荷軽減のため待機
        time.sleep(1)
        
    print(f"\n完了。今回新規ダウンロードした作品数: {downloaded_count} 件")

if __name__ == '__main__':
    main()
