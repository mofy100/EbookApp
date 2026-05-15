import sqlite3
import pandas as pd
import os
import re

# aozora.dbが存在しない場合、最初にこれを実行する。
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

    # 同じタイトルで複数の文字遣い種別がある場合、最新の公開日のものだけ残す
    work_meta = df.drop_duplicates(subset=['作品ID'])[['作品ID', '作品名', '文字遣い種別', '公開日']].copy()
    work_meta['公開日'] = pd.to_datetime(work_meta['公開日'], errors='coerce')

    title_kind_counts = work_meta.groupby('作品名')['文字遣い種別'].nunique()
    multi_kind_titles = title_kind_counts[title_kind_counts > 1].index

    kana_rank = {'新字新仮名': 0, '新字旧仮名': 1, '旧字新仮名': 2, '旧字旧仮名': 3}
    multi = work_meta[work_meta['作品名'].isin(multi_kind_titles)].copy()
    multi['文字遣い順位'] = multi['文字遣い種別'].map(kana_rank).fillna(99)
    newest_of_multi = (
        multi
        .sort_values(['公開日', '文字遣い順位'], ascending=[False, True])
        .drop_duplicates(subset=['作品名'], keep='first')
    )
    single_kind = work_meta[~work_meta['作品名'].isin(multi_kind_titles)]

    selected_ids = set(newest_of_multi['作品ID']) | set(single_kind['作品ID'])
    df = df[df['作品ID'].isin(selected_ids)]
    print(f"重複処理後: {len(selected_ids)} 作品")

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
        has_copyright INTEGER DEFAULT 0,
        publication_year INTEGER
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

        local_path = f"{work_id}"
        has_copyright = 1 if copyright_protected.get(work_id, False) else 0

        shoshu = first_row['初出']
        pub_year = None
        if pd.notna(shoshu):
            m = re.search(r'(\d{4})', str(shoshu))
            if m:
                pub_year = int(m.group(1))

        cursor.execute('''
        INSERT INTO books (id, title, author, translator, card_url, text_url, xhtml_url, local_path, has_copyright, publication_year)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (int(work_id), title, author_names, translator_names, card_url, text_url, xhtml_url, local_path, has_copyright, pub_year))

    conn.commit()
    conn.close()
    print(f"完了！ {DB_FILE} が作成されました。")

def create_authors():
    print("著者テーブルを構築中...")
    try:
        df = pd.read_csv(CSV_FILE, encoding='shift_jis')
    except:
        df = pd.read_csv(CSV_FILE, encoding='utf-8')

    persons = df.drop_duplicates(subset=['人物ID'])[
        ['人物ID', '姓', '名', '姓読み', '名読み', '生年月日', '没年月日']
    ].copy()

    def extract_year(val):
        if pd.isna(val):
            return None
        m = re.search(r'(\d{4})', str(val))
        return int(m.group(1)) if m else None

    def guess_nationality(last_name):
        if pd.isna(last_name):
            return None
        # カタカナのみで構成されていれば外国人（国籍は別途補完）
        if re.fullmatch(r'[゠-ヿ・\s]+', str(last_name)):
            return None
        return '日本'

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('DROP TABLE IF EXISTS authors')
    cursor.execute('''
    CREATE TABLE authors (
        id INTEGER PRIMARY KEY,
        last_name TEXT,
        first_name TEXT,
        last_name_kana TEXT,
        first_name_kana TEXT,
        birth_year INTEGER,
        death_year INTEGER,
        nationality TEXT
    )
    ''')

    for _, row in persons.iterrows():
        cursor.execute('''
        INSERT INTO authors (id, last_name, first_name, last_name_kana, first_name_kana, birth_year, death_year, nationality)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            int(row['人物ID']),
            row['姓'] if pd.notna(row['姓']) else None,
            row['名'] if pd.notna(row['名']) else None,
            row['姓読み'] if pd.notna(row['姓読み']) else None,
            row['名読み'] if pd.notna(row['名読み']) else None,
            extract_year(row['生年月日']),
            extract_year(row['没年月日']),
            guess_nationality(row['姓']),
        ))

    conn.commit()
    conn.close()
    print(f"完了！ {len(persons)} 人の著者を登録しました。")


if __name__ == '__main__':
    create_index()