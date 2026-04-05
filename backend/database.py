import sqlite3
import pandas as pd
import os

# 設定
CSV_FILE = 'backend/aozora_list_extended.csv'
DB_FILE = 'backend/aozora.db'
DATA_DIR = 'backend/data/'

def create_index():
    print("CSVを読み込んでいます...")
    # 拡張版CSV（人物詳細あり）を想定
    try:
        df = pd.read_csv(CSV_FILE, encoding='shift_jis')
    except:
        df = pd.read_csv(CSV_FILE, encoding='utf-8')

    # 1. すべての作品IDを取得し、各作品の著作権状態を判定
    print("作品の著作権フラグを集計中...")
    
    # 作品IDごとに「作品著作権フラグ」が"あり"のものが一つでもあるかを判定した Series を作成
    copyright_protected = df.groupby('作品ID')['作品著作権フラグ'].apply(lambda x: (x == 'あり').any())
    all_work_ids = df['作品ID'].unique()

    # 2. データベース準備
    os.makedirs('backend', exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('DROP TABLE IF EXISTS books')
    cursor.execute('''
    CREATE TABLE books (
        id INTEGER PRIMARY KEY,
        title TEXT,
        author TEXT,
        translator TEXT,
        card_url TEXT,
        text_url TEXT,
        xhtml_url TEXT,
        local_path TEXT,
        is_downloaded INTEGER DEFAULT 0,
        has_copyright INTEGER DEFAULT 0
    )
    ''')

    # 3. 作品をDBに登録
    print(f"全作品 {len(all_work_ids)} 件を登録しています...")
    
    for work_id in all_work_ids:
        # その作品の全行を取得
        work_rows = df[df['作品ID'] == work_id]
        first_row = work_rows.iloc[0] # 基本情報は最初の行から取得
        
        title = first_row['作品名']
        
        # 著者と翻訳者を抽出
        authors = work_rows[work_rows['役割フラグ'] == '著者']
        author_names = "／".join((authors['姓'] + authors['名']).fillna(''))
        
        translators = work_rows[work_rows['役割フラグ'] == '翻訳者']
        translator_names = "／".join((translators['姓'] + translators['名']).fillna(''))
        
        card_url = first_row['図書カードURL']
        text_url = first_row['テキストファイルURL']
        xhtml_url = first_row['XHTML/HTMLファイルURL']
        
        # ローカルファイルの存在確認
        local_path = f"{work_id}"
        is_downloaded = 1 if os.path.exists(os.path.join(DATA_DIR, local_path)) else 0

        has_copyright = 1 if copyright_protected.get(work_id, False) else 0

        cursor.execute('''
        INSERT INTO books (id, title, author, translator, card_url, text_url, xhtml_url, local_path, is_downloaded, has_copyright)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (int(work_id), title, author_names, translator_names, card_url, text_url, xhtml_url, local_path, is_downloaded, has_copyright))

    conn.commit()
    conn.close()
    print(f"完了！ {DB_FILE} が作成されました。")

if __name__ == '__main__':
    create_index()