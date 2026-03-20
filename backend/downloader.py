import sqlite3
import requests
import time
import os
import zipfile
import io

# 設定
DB_FILE = 'backend/aozora.db'
DATA_DIR = 'backend/data/'

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
                
                # テキストファイルの場合はShift-JISからUTF-8へ変換
                if extracted_path.lower().endswith('.txt'):
                    try:
                        with open(extracted_path, 'r', encoding='shift_jis') as f:
                            content = f.read()
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
    
    print("データベースを読み込んでいます...")
    
    # SQLiteから検索
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # 著作権がない(has_copyright == 0) かつ URLが存在する作品のみ抽出
    cursor.execute('''
        SELECT id, text_url FROM books 
        WHERE has_copyright = 0 AND text_url IS NOT NULL AND text_url != ""
    ''')
    targets = cursor.fetchall()
    conn.close()
    
    total = len(targets)
    print(f"ダウンロード対象作品候補: {total} 件 (著作権フリーのみ)")
    
    max_download = 10
    downloaded_count = 0
    
    for i, (work_id, url) in enumerate(targets, 1):
        if downloaded_count >= max_download:
            break

        url_str = str(url)
        
        # 保存先ディレクトリ (例: backend/data/123/)
        extract_path = os.path.join(DATA_DIR, str(work_id))
        
        # すでにディレクトリが存在していて中身がある場合はレジュームとしてスキップ
        if os.path.exists(extract_path) and len(os.listdir(extract_path)) > 0:
            print(f"[{i}/{total}] 既に展開済みのためスキップ: 作品ID {work_id}")
            continue
            
        print(f"[{i}/{total}] ダウンロード中({work_id}): {url_str}")
        
        # 展開先の各作品用ディレクトリを作成
        os.makedirs(extract_path, exist_ok=True)
        
        # ファイルの拡張子によって処理を分岐
        success = False
        if url_str.endswith('.zip'):
            success = download_and_extract_zip(url_str, extract_path)
        elif url_str.endswith('.txt') or url_str.endswith('.html'):
            success = download_text_file(url_str, extract_path)
        else:
            print(f"[{i}/{total}] スキップ (非対応の拡張子): {url_str}")
            # 空のディレクトリを消しておく
            if len(os.listdir(extract_path)) == 0:
                os.rmdir(extract_path)
            continue
        
        if success:
            downloaded_count += 1
            print(f"ダウンロード成功: {work_id}")
            
        # 【重要】サーバーへの負荷軽減のために必ず1秒待機する
        time.sleep(1)
        
    print(f"\n全ての処理が完了しました。今回新規ダウンロードした作品数: {downloaded_count} 件")

if __name__ == '__main__':
    main()
