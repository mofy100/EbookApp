const API_BASE = "http://127.0.0.1:8000/api";

document.addEventListener('DOMContentLoaded', async () => {
    const textContainers = document.querySelectorAll('.text-container');
    const textWindow = document.querySelector('.page-right .text-window') || document.querySelector('.text-window');
    const pagePaper = document.querySelector('.page-paper');

    const btnNext = document.getElementById('btn-next');
    const btnPrev = document.getElementById('btn-prev');
    const btnToggleMode = document.getElementById('btn-toggle-mode');
    const pageInfo = document.getElementById('page-info');

    let currentPage = 0;
    let totalPages = 0;
    let isSingleMode = false;
    let pageWidth = 0;

    const params = new URLSearchParams(window.location.search);
    const bookId = params.get('id');

    if (!bookId) {
        textContainers.forEach(container => {
            container.innerHTML = '<p>作品IDが指定されていません。検索画面から作品を選択してください。</p>';
        });
        const titleRight = document.getElementById('page-title-right');
        const titleLeft = document.getElementById('page-title-left');
        if (titleRight) titleRight.textContent = 'エラー';
        if (titleLeft) titleLeft.textContent = 'エラー';
        return;
    }

    document.title = `読書中 (ID: ${bookId})`;

    try {
        const res = await fetch(`${API_BASE}/books/${bookId}/text`);
        if (!res.ok) throw new Error('Failed to load text');
        const data = await res.json();

        const htmlContent = data.content;
        const bookTitle = data.title || '電子書籍';
        
        document.title = `${bookTitle} - 青空文庫リーダー`;

        const titleRight = document.getElementById('page-title-right');
        const titleLeft = document.getElementById('page-title-left');
        if (titleRight) titleRight.textContent = bookTitle;
        if (titleLeft) titleLeft.textContent = bookTitle;

        textContainers.forEach(container => {
            container.innerHTML = htmlContent;
        });
        
        setTimeout(updateLayout, 100);

    } catch (err) {
        console.error("コンテンツの読み込みに失敗しました:", err);
        textContainers.forEach(container => {
            container.innerHTML = `<p>読込みに失敗しました (${err.message})<br><br>ファイルがダウンロードされていないか、存在しない可能性があります。一覧に戻り、「ダウンロード」を実行してください。</p>`;
        });
        if (pageInfo) pageInfo.textContent = "読み込みエラー";
    }

    function updateLayout() {
        const allWindows = document.querySelectorAll('.page-right .text-window, .page-left .text-window, .single-mode .text-window');
        if (!textWindow) return;

        const oldPageWidth = pageWidth;
        const currentPixelOffset = currentPage * (oldPageWidth || 1);

        allWindows.forEach(win => {
            if (win) win.style.width = ''; 
        });

        const availableWidth = textWindow.clientWidth;

        const computedStyle = window.getComputedStyle(textContainers[0]);
        let lineHeight = parseFloat(computedStyle.lineHeight);

        if (isNaN(lineHeight)) {
            const fontSize = parseFloat(computedStyle.fontSize);
            lineHeight = fontSize * 1.5;
        }

        const optimalWidth = Math.floor(availableWidth / lineHeight) * lineHeight;

        allWindows.forEach(win => {
            if (win) win.style.width = `${optimalWidth}px`;
        });

        pageWidth = optimalWidth;

        textContainers.forEach(container => {
            container.style.columnWidth = '';
            container.style.columnGap = '';
        });

        if (oldPageWidth > 0 && oldPageWidth !== pageWidth) {
            currentPage = Math.floor(currentPixelOffset / pageWidth);
        }

        setTimeout(() => {
            const scrollWidth = textContainers[0].scrollWidth;
            totalPages = Math.ceil(scrollWidth / pageWidth);

            if (currentPage >= totalPages) {
                currentPage = Math.max(0, totalPages - (isSingleMode ? 1 : 2));
            }
            if (!isSingleMode && currentPage % 2 !== 0) {
                currentPage = Math.max(0, currentPage - 1);
            }

            renderPages();
        }, 100);
    }

    function renderPages() {
        if (totalPages === 0) return;

        const containerRight = textContainers[0];
        const containerLeft = textContainers.length > 1 ? textContainers[1] : null;

        containerRight.style.transform = `translateX(${currentPage * pageWidth}px)`;

        if (containerLeft && !isSingleMode) {
            containerLeft.style.transform = `translateX(${(currentPage + 1) * pageWidth}px)`;
        }

        const pageNumRight = document.getElementById('page-number-right');
        const pageNumLeft = document.getElementById('page-number-left');

        if (isSingleMode) {
            if (pageInfo) pageInfo.textContent = `${currentPage + 1} / ${totalPages}`;
            if (pageNumRight) pageNumRight.textContent = currentPage + 1;
        } else {
            const rightNum = currentPage + 1;
            const leftNum = Math.min(currentPage + 2, totalPages);
            if (pageInfo) pageInfo.textContent = `${rightNum}-${leftNum} / ${totalPages}`;
            
            if (pageNumRight) pageNumRight.textContent = rightNum;
            if (pageNumLeft) {
                if (rightNum === totalPages) {
                    pageNumLeft.textContent = '';
                } else {
                    pageNumLeft.textContent = leftNum;
                }
            }
        }
    }

    function changePage(newPage) {
        if (currentPage === newPage) return;

        textContainers.forEach(container => container.classList.add('fade-out'));

        setTimeout(() => {
            currentPage = newPage;
            renderPages(); 
            
            requestAnimationFrame(() => {
                textContainers.forEach(container => container.classList.remove('fade-out'));
            });
        }, 200);
    }

    btnPrev.addEventListener('click', () => {
        const step = isSingleMode ? 1 : 2;
        if (currentPage - step >= 0) {
            changePage(currentPage - step);
        } else if (currentPage > 0) {
            changePage(0);
        }
    });

    btnNext.addEventListener('click', () => {
        const step = isSingleMode ? 1 : 2;
        if (currentPage + step < totalPages) {
            changePage(currentPage + step);
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowLeft' || e.key === 'Enter') {
            const step = isSingleMode ? 1 : 2;
            if (currentPage + step < totalPages) {
                changePage(currentPage + step);
            }
        }
        else if (e.key === 'ArrowRight') {
            const step = isSingleMode ? 1 : 2;
            if (currentPage - step >= 0) {
                changePage(currentPage - step);
            } else if (currentPage > 0) {
                changePage(0);
            }
        }
    });

    btnToggleMode.addEventListener('click', () => {
        isSingleMode = !isSingleMode;
        if (isSingleMode) {
            pagePaper.classList.add('single-mode');
            btnToggleMode.textContent = '見開き表示';
        } else {
            pagePaper.classList.remove('single-mode');
            btnToggleMode.textContent = '単一ページ表示';
            if (currentPage % 2 !== 0) {
                currentPage = Math.max(0, currentPage - 1);
            }
        }
        updateLayout();
    });

    let resizeTimer;
    const resizeObserver = new ResizeObserver(() => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(updateLayout, 150);
    });

    if (pagePaper) {
        resizeObserver.observe(pagePaper);
    }
});
