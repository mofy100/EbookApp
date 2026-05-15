import sqlite3
import pandas as pd
import os
import re

CSV_FILE = 'backend/aozora_list_extended.csv'
DB_FILE = 'backend/aozora.db'

def _load_csv() -> pd.DataFrame:
    try:
        return pd.read_csv(CSV_FILE, encoding='shift_jis')
    except UnicodeDecodeError:
        return pd.read_csv(CSV_FILE, encoding='utf-8')


def _extract_year(val) -> int | None:
    if pd.isna(val):
        return None
    m = re.search(r'(\d{4})', str(val))
    return int(m.group(1)) if m else None


def create_authors(conn: sqlite3.Connection):
    print("著者テーブルを構築中...")
    df = _load_csv()

    persons = df.drop_duplicates(subset=['人物ID'])[
        ['人物ID', '姓', '名', '姓読み', '名読み', '生年月日', '没年月日']
    ].copy()

    def guess_nationality(last_name):
        if pd.isna(last_name):
            return None
        if re.fullmatch(r'[゠-ヿ・\s]+', str(last_name)):
            return None
        return '日本'

    cursor = conn.cursor()
    cursor.execute('DROP TABLE IF EXISTS authors')
    cursor.execute('''
        CREATE TABLE authors (
            id             INTEGER PRIMARY KEY,
            last_name      TEXT,
            first_name     TEXT,
            last_name_kana TEXT,
            first_name_kana TEXT,
            birth_year     INTEGER,
            death_year     INTEGER,
            nationality    TEXT
        )
    ''')

    for _, row in persons.iterrows():
        cursor.execute('''
            INSERT INTO authors
                (id, last_name, first_name, last_name_kana, first_name_kana,
                 birth_year, death_year, nationality)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            int(row['人物ID']),
            row['姓']   if pd.notna(row['姓'])   else None,
            row['名']   if pd.notna(row['名'])   else None,
            row['姓読み'] if pd.notna(row['姓読み']) else None,
            row['名読み'] if pd.notna(row['名読み']) else None,
            _extract_year(row['生年月日']),
            _extract_year(row['没年月日']),
            guess_nationality(row['姓']),
        ))

    conn.commit()
    print(f"  => {len(persons)} 人を登録しました")


def create_index(conn: sqlite3.Connection):
    print("booksテーブルを構築中...")
    df = _load_csv()

    # 文字遣い種別が複数ある作品は最新・新字新仮名を優先して1件に絞る
    work_meta = df.drop_duplicates(subset=['作品ID'])[
        ['作品ID', '作品名', '文字遣い種別', '公開日']
    ].copy()
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
    print(f"  重複処理後: {len(selected_ids)} 作品")

    # 著作権ありの作品IDを除外
    copyright_ids = set(
        df[df['作品著作権フラグ'] == 'あり']['作品ID']
    )
    free_ids = selected_ids - copyright_ids
    df = df[df['作品ID'].isin(free_ids)]
    print(f"  著作権なし: {len(free_ids)} 作品")

    cursor = conn.cursor()
    cursor.execute('DROP TABLE IF EXISTS books')
    cursor.execute('''
        CREATE TABLE books (
            book_id          INTEGER PRIMARY KEY,
            title            TEXT NOT NULL,
            author           TEXT,
            translator       TEXT,
            author_id        INTEGER REFERENCES authors(id),
            translator_id    INTEGER REFERENCES authors(id),
            publication_year INTEGER
        )
    ''')

    inserted = 0
    for work_id in free_ids:
        work_rows = df[df['作品ID'] == work_id]
        if work_rows.empty:
            continue
        first_row = work_rows.iloc[0]
        title = first_row['作品名']

        author_rows = work_rows[work_rows['役割フラグ'] == '著者']
        author_name = '／'.join((author_rows['姓'].fillna('') + author_rows['名'].fillna('')))
        author_id = int(author_rows.iloc[0]['人物ID']) if not author_rows.empty else None

        trans_rows = work_rows[work_rows['役割フラグ'] == '翻訳者']
        translator_name = '／'.join((trans_rows['姓'].fillna('') + trans_rows['名'].fillna(''))) or None
        translator_id = int(trans_rows.iloc[0]['人物ID']) if not trans_rows.empty else None

        pub_year = _extract_year(first_row['初出'])

        cursor.execute('''
            INSERT INTO books
                (book_id, title, author, translator, author_id, translator_id, publication_year)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            int(work_id), title,
            author_name or None, translator_name,
            author_id, translator_id,
            pub_year,
        ))
        inserted += 1

    conn.commit()
    print(f"  => {inserted} 作品を登録しました")


def create_book_tags(conn: sqlite3.Connection):
    cursor = conn.cursor()
    cursor.execute('DROP TABLE IF EXISTS book_tags')
    cursor.execute('''
        CREATE TABLE book_tags (
            book_id INTEGER NOT NULL,
            tag     TEXT    NOT NULL,
            PRIMARY KEY (book_id, tag),
            FOREIGN KEY (book_id) REFERENCES books(book_id)
        )
    ''')
    cursor.execute('CREATE INDEX idx_book_tags_tag ON book_tags(tag)')
    conn.commit()
    print("book_tagsテーブルを作成しました")


if __name__ == '__main__':
    os.makedirs('backend', exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    try:
        create_authors(conn)
        create_index(conn)
        create_book_tags(conn)
    finally:
        conn.close()
    print(f"\n完了: {DB_FILE}")
