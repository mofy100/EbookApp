import requests

url = "https://www.aozora.gr.jp/cards/001257/files/59898_70731.html"

try:
    # 1. データの取得
    response = requests.get(url)
    
    # 2. ステータスコードのチェック（200番台なら成功）
    response.raise_for_status()
    
    # 3. 文字化け対策（青空文庫はShift-JISが多いため、適切に設定）
    response.encoding = response.apparent_encoding 
    
    # 4. ファイルに保存
    with open("sample.html", "w", encoding="utf-8") as f:
        f.write(response.text)
        
    print("ダウンロードが完了しました。")

except requests.exceptions.RequestException as e:
    print(f"エラーが発生しました: {e}")