const box = document.getElementById('vertical-box');
const btnNext = document.getElementById('btn-next');
const btnPrev = document.getElementById('btn-prev');
const pageInfo = document.getElementById('page-info');

let currentPage = 0;
let totalPages = 1;
let pageAdvance = 0;

function updateLayout() {
    // CSS変数からページ幅と隙間のサイズを取得
    const style = getComputedStyle(document.documentElement);
    const pageWidth = parseFloat(style.getPropertyValue('--page-width')) || 0;
    const pageGap = parseFloat(style.getPropertyValue('--page-gap')) || 0;
    
    // 1回スライドする距離
    pageAdvance = pageWidth + pageGap;

    // コンテンツの総幅（何ページ分生成されたか）
    const scrollWidth = box.scrollWidth;
    
    // 総ページ数の計算（最後のページには隙間がつかない場合があるため丸める）
    totalPages = Math.round((scrollWidth + pageGap) / pageAdvance);
    if (totalPages < 1) totalPages = 1;

    // 万が一ページ上限を超えていたら補正
    if (currentPage >= totalPages) currentPage = totalPages - 1;

    renderPage();
}

function renderPage() {
    // 右->左 の縦書きで、左側に何個分のカラムがあるか＝ (totalPages - 1 - currentPage)
    const columnIndexFromLeft = totalPages - 1 - currentPage;
    const xOffset = columnIndexFromLeft * pageAdvance;

    // X座標をマイナスにして、対象のカラムを「窓枠」の左端（0px）に持ってくる
    const translateX = -xOffset;
    
    box.style.transform = `translateX(${translateX}px)`;
    pageInfo.textContent = `${currentPage + 1} / ${totalPages}`;
    
    btnPrev.disabled = (currentPage === 0);
    btnNext.disabled = (currentPage >= totalPages - 1);
}

btnNext.addEventListener('click', () => {
    if (currentPage < totalPages - 1) {
        currentPage++;
        renderPage();
    }
});

btnPrev.addEventListener('click', () => {
    if (currentPage > 0) {
        currentPage--;
        renderPage();
    }
});

// 読み込み時とウィンドウリサイズ時にレイアウトを再計算
window.addEventListener('load', () => {
    // 念のためフォントレンダリング待ちで少し遅らせる
    setTimeout(updateLayout, 100);
});
window.addEventListener('resize', updateLayout);
