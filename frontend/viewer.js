const API_BASE = "http://127.0.0.1:8000/api";

document.addEventListener('DOMContentLoaded', async () => {
    const textContainers = document.querySelectorAll('.text-container');
    const textWindow = document.querySelector('.page-right .text-window') || document.querySelector('.text-window');
    const pagePaper = document.querySelector('.page-paper');

    const btnNext = document.getElementById('btn-next');
    const btnPrev = document.getElementById('btn-prev');
    const btnToggleMode = document.getElementById('btn-toggle-mode');

    const pageInput = document.getElementById('page-input');
    const pageTotal = document.getElementById('page-total');

    const foreEdgeRight = document.getElementById('fore-edge-right');
    const foreEdgeLeft = document.getElementById('fore-edge-left');

    let currentPage = 0;
    let totalPages = 0;
    let isSingleMode = false;
    let pageWidth = 0;
    let textAlignmentOffset = 0; // 行内での左揃え（ルビを右に詰める）のための補正値
    let bookData = {}; // ここで定義して他関数からも参照可能にする
    const widthPerPage = 0.1; // ページ1枚あたりの厚み(px)

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
        bookData = await res.json();

        const htmlContent = bookData.content;
        const bookTitle = bookData.title || '電子書籍';

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
        if (pageTotal) pageTotal.textContent = "読み込みエラー";
    }

    function updateLayout() {
        const allWindows = document.querySelectorAll('.page-right .text-window, .page-left .text-window, .single-mode .text-window');
        if (!textWindow) return;

        const oldPageWidth = pageWidth;
        const currentPixelOffset = currentPage * (oldPageWidth || 1);

        allWindows.forEach(win => {
            if (win) win.style.width = '';
        });

        let availableWidth = textWindow.clientWidth;

        const computedStyle = window.getComputedStyle(textContainers[0]);
        let lineHeight = parseFloat(computedStyle.lineHeight);
        let fontSize = parseFloat(computedStyle.fontSize);

        if (isNaN(lineHeight)) {
            lineHeight = fontSize * 1.5;
        }

        // 行ボックスの中で、本文は中央寄せになるため、左右に (lineHeight - fontSize)/2 の隙間ができる。
        // 本文を左寄せ（縦書きでは左端）にし、右にできたスペースにルビをすっぽり収めるため、
        // ページ全体をこの隙間分だけ左方向（マイナス）へずらす計算。
        textAlignmentOffset = - (lineHeight - fontSize) / 2;

        // ページ1枚あたりの厚みを考慮して紙のサイズを割り振る
        const paper = document.querySelector('.page-paper');
        const paperWidth = paper ? paper.clientWidth : window.innerWidth * 0.9;

        // paper内部の有効幅（padding等の遊びを設けない）
        availableWidth = paperWidth;

        const totalThickness = totalPages * widthPerPage;

        // 1ページあたりのコンテナの最大幅（小口分を引いて2等分）
        const maxPageContainerWidth = (availableWidth - totalThickness) / 2;

        // テキストウィンドウ自体の幅（コンテナ幅からページのpadding合計45pxを差し引く）
        const calculatedTextWindowWidth = maxPageContainerWidth - 45;

        // 文字数に合わせた最適な幅（ラインハイトの倍数）
        const optimalWidth = Math.floor(calculatedTextWindowWidth / lineHeight) * lineHeight;

        // CSS変数に設定
        document.documentElement.style.setProperty('--text-window-width', `${optimalWidth}px`);

        // 最適化された幅に合わせてページコンテナの幅も再定義
        // optimalWidth+45 ではなく maxPageContainerWidth を使うことで、
        // 余ったスペースをページの余白として吸収し、端の隙間をなくす
        const finalPageWidth = maxPageContainerWidth;

        const pages = document.querySelectorAll('.page-right, .page-left');
        pages.forEach(p => {
            if (p) p.style.flex = `0 0 ${finalPageWidth}px`;
        });

        allWindows.forEach(win => {
            if (win) win.style.width = `${optimalWidth}px`;
        });

        pageWidth = optimalWidth;

        /* 改ページ（.page-break）の動的補正 */
        textContainers.forEach(container => {
            const breaks = container.querySelectorAll('.page-break');
            breaks.forEach(pb => {
                pb.style.marginRight = '0'; // 一旦リセット
            });

            // レイアウト確定を待つため少し遅延させて計算
            setTimeout(() => {
                const containerRect = container.getBoundingClientRect();
                breaks.forEach(pb => {
                    const rect = pb.getBoundingClientRect();
                    // コンテナの右端からの距離（xオフセット）を計算
                    // vertical-rl では右端が 0
                    const currentX = containerRect.right - rect.right;

                    // 次のページの開始位置までの不足分を計算
                    const remainder = currentX % pageWidth;
                    if (remainder > 0) {
                        const neededGap = pageWidth - remainder;
                        pb.style.marginRight = `${neededGap}px`;
                    }
                });

                // マージン付与後に再度ページ数を計算
                const scrollWidth = container.scrollWidth;
                totalPages = Math.ceil(scrollWidth / pageWidth);
                if (currentPage >= totalPages) {
                    currentPage = Math.max(0, totalPages - (isSingleMode ? 1 : 2));
                }
                renderPages();
            }, 0);
        });

        /* column-widthをCSSの変数に任せ、JS側でのクリアを停止します */

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

        // ページ移動に加え、左寄せ補正オフセットを足すことでルビの空白問題と端の切り取りを防ぐ
        containerRight.style.transform = `translateX(${currentPage * pageWidth + textAlignmentOffset}px)`;

        if (containerLeft && !isSingleMode) {
            containerLeft.style.transform = `translateX(${(currentPage + 1) * pageWidth + textAlignmentOffset}px)`;
        }

        /* 最初の3ページ分（白紙、タイトル、白紙）にはページ番号をわりあてない */
        const PAGE_START_OFFSET = 3;
        const pageNumRight = document.getElementById('page-number-right');
        const pageNumLeft = document.getElementById('page-number-left');
        const titleRight = document.getElementById('page-title-right');
        const titleLeft = document.getElementById('page-title-left');

        const physicalRight = currentPage + 1;
        const physicalLeft = currentPage + 2;

        const displayRight = physicalRight - PAGE_START_OFFSET;
        const displayLeft = physicalLeft - PAGE_START_OFFSET;

        // 右側のページ表示
        if (titleRight) {
            titleRight.textContent = (physicalRight <= PAGE_START_OFFSET) ? "" : (bookData.title || '電子書籍');
        }
        if (pageNumRight) {
            pageNumRight.textContent = (displayRight >= 1) ? displayRight : "";
        }

        if (isSingleMode) {
            if (pageInput) pageInput.value = Math.max(1, displayRight);
            if (pageTotal) pageTotal.textContent = ` / ${totalPages - PAGE_START_OFFSET}`;
        } else {
            // 左側のページ表示（見開きのみ）
            if (titleLeft) {
                titleLeft.textContent = (physicalLeft <= PAGE_START_OFFSET || physicalRight === totalPages) ? "" : (bookData.title || '電子書籍');
            }

            if (pageNumLeft) {
                if (physicalRight === totalPages || displayLeft < 1) {
                    pageNumLeft.textContent = '';
                } else {
                    pageNumLeft.textContent = displayLeft;
                }
            }

            const leftDisplayNum = Math.min(displayLeft, totalPages - PAGE_START_OFFSET);
            if (pageInput) pageInput.value = Math.max(1, displayRight);
            if (pageTotal) pageTotal.textContent = `〜${Math.max(1, leftDisplayNum)} / ${totalPages - PAGE_START_OFFSET}`;
        }

        // 小口（本の厚み）の更新
        if (foreEdgeRight && foreEdgeLeft && !isSingleMode) {
            const pagesRemaining = Math.max(0, totalPages - (currentPage + 2));
            const rightWidth = currentPage * widthPerPage;
            foreEdgeRight.style.width = `${rightWidth}px`;
            const leftWidth = pagesRemaining * widthPerPage;
            foreEdgeLeft.style.width = `${leftWidth}px`;
        } else if (foreEdgeRight && foreEdgeLeft) {
            foreEdgeRight.style.width = '0';
            foreEdgeLeft.style.width = '0';
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

    // 小口クリックでのジャンプ
    if (foreEdgeRight) {
        foreEdgeRight.addEventListener('click', (e) => {
            if (currentPage <= 0) return;
            const rect = foreEdgeRight.getBoundingClientRect();
            const y = e.clientY - rect.top;
            const ratio = y / rect.height;
            let targetPage = Math.floor(ratio * currentPage);

            // 見開きモード時の偶数ページ補正
            if (!isSingleMode && targetPage % 2 !== 0) {
                targetPage = Math.max(0, targetPage - 1);
            }
            changePage(targetPage);
        });
    }

    if (foreEdgeLeft) {
        foreEdgeLeft.addEventListener('click', (e) => {
            const pagesRemaining = totalPages - (currentPage + 2);
            if (pagesRemaining <= 0) return;

            const rect = foreEdgeLeft.getBoundingClientRect();
            const y = e.clientY - rect.top;
            const ratio = y / rect.height;
            let targetPage = (currentPage + 2) + Math.floor(ratio * pagesRemaining);

            // 最後のページを超えないように
            if (targetPage >= totalPages) targetPage = totalPages - 1;

            // 見開きモード時の奇数ページ補正
            if (!isSingleMode && targetPage % 2 !== 0) {
                targetPage = Math.min(totalPages - 1, targetPage - 1);
            }
            changePage(targetPage);
        });
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

    // ページ番号入力によるジャンプ
    if (pageInput) {
        pageInput.addEventListener('change', (e) => {
            let val = parseInt(e.target.value, 10);
            if (isNaN(val)) {
                val = currentPage + 1; // 無効な値なら元に戻す
            }
            // 範囲外の補正
            if (val < 1) val = 1;
            if (val > totalPages) val = totalPages;

            // currentPageは0オリジンなので-1する
            let targetPage = val - 1;

            // 見開きモード時の奇数ページ補正（右寄せ）
            if (!isSingleMode && targetPage % 2 !== 0) {
                targetPage = Math.max(0, targetPage - 1);
            }

            changePage(targetPage);
            // 表示の即時反映（renderPageはフェードの合間に呼ばれるため、入力欄の数字だけ直しておく）
            e.target.value = targetPage + 1;
        });
    }

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
