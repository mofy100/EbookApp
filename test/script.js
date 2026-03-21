document.addEventListener('DOMContentLoaded', () => {
    const textContainers = document.querySelectorAll('.text-container');
    const textWindow = document.querySelector('.page-right .text-window') || document.querySelector('.text-window');
    const pagePaper = document.querySelector('.page-paper');

    const btnNext = document.getElementById('btn-next');
    const btnPrev = document.getElementById('btn-prev');
    const btnToggleMode = document.getElementById('btn-toggle-mode');
    const pageInfo = document.getElementById('page-info');

    let currentPage = 0; // 右ページのインデックス (見開きなら左は+1)
    let totalPages = 0;
    let isSingleMode = false;
    let pageWidth = 0;

    // text.htmlからコンテンツを取得して挿入
    fetch('text.html')
        .then(response => response.text())
        .then(html => {
            textContainers.forEach(container => {
                container.innerHTML = html;
            });
            // 少し待ってからレイアウト計算を開始
            setTimeout(updateLayout, 100);
        })
        .catch(err => {
            console.error("コンテンツの読み込みに失敗しました:", err);
            pageInfo.textContent = "読み込みエラー";
        });

    function updateLayout() {
        const allWindows = document.querySelectorAll('.page-right .text-window, .page-left .text-window, .single-mode .text-window');
        if (!textWindow) return;

        // 直前のページ幅と現在のオフセット位置（ピクセル）を保持
        const oldPageWidth = pageWidth;
        const currentPixelOffset = currentPage * (oldPageWidth || 1);

        // 1. まず利用可能な最大幅を計算するために一旦100%に戻す
        allWindows.forEach(win => {
            if (win) win.style.width = '100%';
        });

        // 2. この時のウィンドウ幅を取得
        const availableWidth = textWindow.clientWidth;

        // 3. 行の高さ（line-height）を取得（文字サイズ × line-height-ratio がピクセルで返る）
        const computedStyle = window.getComputedStyle(textContainers[0]);
        let lineHeight = parseFloat(computedStyle.lineHeight);

        if (isNaN(lineHeight)) {
            // fallback
            const fontSize = parseFloat(computedStyle.fontSize);
            lineHeight = fontSize * 1.5;
        }

        // 4. ウィンドウ幅をline-heightの倍数に丸めて(余りを省く)、文字が半端に切れるのを防ぐ
        const optimalWidth = Math.floor(availableWidth / lineHeight) * lineHeight;

        // 5. 計算した最適な幅を適用する
        allWindows.forEach(win => {
            if (win) win.style.width = `${optimalWidth}px`;
        });

        pageWidth = optimalWidth;
        console.log("pageWidth", pageWidth, "lineHeight", lineHeight);

        textContainers.forEach(container => {
            // カラム設定は縦書きレイアウトを破壊する可能性があるため削除
            container.style.columnWidth = '';
            container.style.columnGap = '';
        });

        // 6. ウィンドウ幅が変わった場合、今まで見ていた場所（オフセットピクセル）に一番近い新ページを計算
        if (oldPageWidth > 0 && oldPageWidth !== pageWidth) {
            currentPage = Math.floor(currentPixelOffset / pageWidth);
        }

        // setTimeoutを使用して、DOMの計算が完了するのを待つ
        setTimeout(() => {
            // 全体の幅(scrollWidth)を1ページの幅(pageWidth)で割ることで総ページ数を算出
            const scrollWidth = textContainers[0].scrollWidth;
            totalPages = Math.ceil(scrollWidth / pageWidth);

            // リサイズ時に現在のページが最大ページ数を超えないように補正
            if (currentPage >= totalPages) {
                currentPage = Math.max(0, totalPages - (isSingleMode ? 1 : 2));
            }
            // 見開きモードの際は偶数ページから始まるように補正（右が偶数・左が奇数）
            if (!isSingleMode && currentPage % 2 !== 0) {
                currentPage = Math.max(0, currentPage - 1);
            }

            renderPages();
        }, 100); // 描画待ち時間
    }

    function renderPages() {
        if (totalPages === 0) return;

        // Container[0]: page-right 用, Container[1]: page-left 用
        const containerRight = textContainers[0];
        const containerLeft = textContainers.length > 1 ? textContainers[1] : null;

        // *重要*
        // writing-mode: vertical-rl では、コンテナは position: absolute; right: 0; で右端を基準に固定されているため、
        // translateXの値を「プラス」にするほど、左にはみ出していたコンテンツが右へスライドし、視界に入ってきます。
        // オフセット = ページ数 * 1ページの幅
        containerRight.style.transform = `translateX(${currentPage * pageWidth}px)`;
        console.log("transform", currentPage * pageWidth);

        if (containerLeft && !isSingleMode) {
            containerLeft.style.transform = `translateX(${(currentPage + 1) * pageWidth}px)`;
        }

        // ページ番号の更新
        if (isSingleMode) {
            pageInfo.textContent = `${currentPage + 1} / ${totalPages}`;
        } else {
            const rightNum = currentPage + 1;
            const leftNum = Math.min(currentPage + 2, totalPages);
            pageInfo.textContent = `${rightNum}-${leftNum} / ${totalPages}`;
        }
    }

    // ページを切り替える共通関数（フェードの効果をつける）
    function changePage(newPage) {
        if (currentPage === newPage) return;

        // 1. フェードアウトを開始
        textContainers.forEach(container => container.classList.add('fade-out'));

        // 2. フェードアウトしきったタイミング（0.2秒後）で中身をすり替え、フェードイン
        setTimeout(() => {
            currentPage = newPage;
            renderPages(); // transform: translateX が一瞬で切り替わる
            
            // 少しだけ待ってから透明度を元に戻す（フェードイン）
            requestAnimationFrame(() => {
                textContainers.forEach(container => container.classList.remove('fade-out'));
            });
        }, 200);
    }

    // 前のページへ戻る (右に進む: 読書順の逆方向)
    btnPrev.addEventListener('click', () => {
        const step = isSingleMode ? 1 : 2;
        if (currentPage - step >= 0) {
            changePage(currentPage - step);
        } else if (currentPage > 0) {
            changePage(0);
        }
    });

    // 次のページへ進む (左に進む: 読書順)
    btnNext.addEventListener('click', () => {
        const step = isSingleMode ? 1 : 2;
        if (currentPage + step < totalPages) {
            changePage(currentPage + step);
        }
    });

    // キーボード操作によるページめくり
    document.addEventListener('keydown', (e) => {
        // 次のページへ進む (←キー、Enterキー)
        if (e.key === 'ArrowLeft' || e.key === 'Enter') {
            const step = isSingleMode ? 1 : 2;
            if (currentPage + step < totalPages) {
                changePage(currentPage + step);
            }
        }
        // 前のページへ戻る (→キー)
        else if (e.key === 'ArrowRight') {
            const step = isSingleMode ? 1 : 2;
            if (currentPage - step >= 0) {
                changePage(currentPage - step);
            } else if (currentPage > 0) {
                changePage(0);
            }
        }
    });

    // 見開き / 単一モードの切り替え
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

    // リサイズ監視（ウィンドウサイズ変更時に自動再計算）
    let resizeTimer;
    const resizeObserver = new ResizeObserver(() => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(updateLayout, 150);
    });

    if (pagePaper) {
        resizeObserver.observe(pagePaper);
    }
});
