const API_BASE = "http://127.0.0.1:8000/api";

let currentPage = 0;
let totalPages = 1;

document.addEventListener('DOMContentLoaded', async () => {
    const params = new URLSearchParams(window.location.search);
    const bookId = params.get('id');
    
    const readerTitle = document.getElementById('reader-title');
    const readerContent = document.getElementById('reader-content');
    const readerContainer = document.getElementById('reader-container');
    
    const btnNext = document.getElementById('btn-next');
    const btnPrev = document.getElementById('btn-prev');
    const pageIndicator = document.getElementById('page-indicator');
    
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
        
        // フォントや画像の読み込み待機後に総ページ数を計算する
        setTimeout(calculatePages, 300);
        
        // 画面リサイズ時にも再計算
        window.addEventListener('resize', () => {
            calculatePages();
        });
        
    } catch (err) {
        console.error(err);
        readerContent.innerHTML = `読込みに失敗しました (${err.message})<br><br>ファイルがダウンロードされていないか、存在しない可能性があります。一覧に戻り、「ダウンロード」を実行してください。`;
    }
    
    function calculatePages() {
        // vertical-rlでは幅が広がる。scrollWidthは全ページのピクセル長。
        // column-width: 90vw, column-gap: 10vw (計100vw = window.innerWidth)
        const totalWidth = readerContent.scrollWidth;
        const pageAdvance = window.innerWidth;
        
        // 総ページ数 (Math.roundで微細な誤差を吸収)
        totalPages = Math.round(totalWidth / pageAdvance);
        if (totalPages < 1) totalPages = 1;
        
        // 現在ページが総ページを超えないように補正
        if (currentPage >= totalPages) currentPage = totalPages - 1;
        
        updatePage();
    }
    
    function updatePage() {
        // コンテナが LTR（左から右）ベースのため、要素の左端（0px）が作品の「最後のページ」になっています。
        // 右端（最初のページ）を表示するには、全体の幅分マイナスへ移動させる必要があります。
        const pageAdvance = window.innerWidth;
        
        // 最初のページ (currentPage=0) で最もマイナスになり、
        // 最後のページ (currentPage=totalPages-1) で0になるように計算を反転
        const translateX = - (totalPages - 1 - currentPage) * pageAdvance;
        
        readerContent.style.transform = `translateX(${translateX}px)`;
        
        pageIndicator.textContent = `${currentPage + 1} / ${totalPages}`;
        
        btnPrev.disabled = (currentPage === 0);
        btnNext.disabled = (currentPage >= totalPages - 1);
    }
    
    btnNext.addEventListener('click', () => {
        if (currentPage < totalPages - 1) {
            currentPage++;
            updatePage();
        }
    });
    
    btnPrev.addEventListener('click', () => {
        if (currentPage > 0) {
            currentPage--;
            updatePage();
        }
    });

    // キーボード操作対応
    document.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowLeft') btnNext.click(); // 青空文庫は右から左に進むので、左矢印キー＝次ページ
        if (e.key === 'ArrowRight') btnPrev.click(); // 右矢印キー＝前ページ
    });
});
