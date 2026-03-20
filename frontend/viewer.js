const API_BASE = "http://127.0.0.1:8000/api";

document.addEventListener('DOMContentLoaded', async () => {
    const params = new URLSearchParams(window.location.search);
    const bookId = params.get('id');
    
    const readerTitle = document.getElementById('reader-title');
    const readerContent = document.getElementById('reader-content');
    const readerContainer = document.getElementById('reader-container');
    
    if (!bookId) {
        readerContent.innerHTML = '作品IDが指定されていません。検索画面から作品を選択してください。';
        readerTitle.textContent = 'エラー';
        return;
    }
    
    document.title = `読書中 (ID: ${bookId})`;
    
    try {
        const res = await fetch(`${API_BASE}/books/${bookId}/text`);
        if (!res.ok) throw new Error('Failed to load text');
        const data = await res.json();
        
        const htmlContent = data.content;
        document.title = `${data.title} - 青空文庫リーダー`;
        readerTitle.textContent = data.title;
        readerContent.innerHTML = htmlContent;
        
        // 読み込み直後にテキストの先頭（右端）へスクロール位置を合わせる
        setTimeout(() => {
            readerContainer.scrollLeft = 0; // RTLコンテナでは 0 が右端(文頭)となる
        }, 100);
        
    } catch (err) {
        console.error(err);
        readerContent.innerHTML = `読込みに失敗しました (${err.message})<br><br>ファイルがダウンロードされていないか、存在しない可能性があります。一覧に戻り、「ダウンロード」を実行してください。`;
    }
});
