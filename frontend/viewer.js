const API_BASE = "http://127.0.0.1:8000/api";

document.addEventListener('DOMContentLoaded', async () => {
    const textContainers = document.querySelectorAll('.text-container');
    const textWindow = document.querySelector('.page-right .text-window') || document.querySelector('.text-window');
    const pagePaper = document.querySelector('.page-paper');

    const btnNext = document.getElementById('btn-next');
    const btnPrev = document.getElementById('btn-prev');

    const pageInput = document.getElementById('page-input');
    const pageTotal = document.getElementById('page-total');

    const titleRight = document.getElementById('page-title-right');
    const titleLeft = document.getElementById('page-title-left');
    const pageNumRight = document.getElementById('page-number-right');
    const pageNumLeft = document.getElementById('page-number-left');

    const foreEdgeRight = document.getElementById('fore-edge-right');
    const foreEdgeLeft = document.getElementById('fore-edge-left');

    let currentPage = 0;
    let globalTotalPages = 0;
    let pageWidth = 0;
    let textAlignmentOffset = 0; // 行内での左揃え（ルビを右に詰める）のための補正値
    let bookData = {}; // manifest情報の格納用
    let chunks = []; // 各各チャンクのHTML文字列の配列
    let chunkPageCounts = []; // 各チャンクのページ数の配列
    let chunkTitles = []; // 各チャンクから抽出した見出し（柱として使用）
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
        // 1. マニフェストの取得
        const manifestRes = await fetch(`${API_BASE}/books/${bookId}/manifest`);
        if (!manifestRes.ok) throw new Error('Failed to load manifest');
        bookData = await manifestRes.json();

        const bookTitle = bookData.title || '電子書籍';
        document.title = `${bookTitle} - 青空文庫リーダー`;

        const titleRight = document.getElementById('page-title-right');
        const titleLeft = document.getElementById('page-title-left');
        if (titleRight) titleRight.textContent = bookTitle;
        if (titleLeft) titleLeft.textContent = bookTitle;

        // 2. 各チャンクの取得
        const chunkPromises = bookData.chapters.map(chapter =>
            fetch(`${API_BASE}/books/${bookId}/chunk/${chapter.file}`).then(res => res.json())
        );

        const chunkResults = await Promise.all(chunkPromises);
        chunks = chunkResults.map(res => res.content);

        // 3. 計測用コンテナの作成
        createMeasurer();

        setTimeout(updateLayout, 100);

    } catch (err) {
        console.error("コンテンツの読み込みに失敗しました:", err);
        textContainers.forEach(container => {
            container.innerHTML = `<p>読込みに失敗しました (${err.message})<br><br>ファイルがダウンロードされていないか、存在しない可能性があります。一覧に戻り、「ダウンロード」を実行してください。</p>`;
        });
        if (pageTotal) pageTotal.textContent = "読み込みエラー";
    }

    function createMeasurer() {
        if (document.getElementById('offscreen-measurer')) return;
        const measurer = document.createElement('div');
        measurer.id = 'offscreen-measurer';
        measurer.style.cssText = `
            position: absolute;
            visibility: hidden;
            z-index: -1000;
            top: 0;
            left: 0;
            pointer-events: none;
            width: 0;
            height: 0;
            overflow: hidden;
        `;
        // text-window と text-container を模倣する構造を作成
        measurer.innerHTML = `
            <div class="text-window" style="position: relative;">
                <div class="text-container" style="position: absolute;"></div>
            </div>
        `;
        document.body.appendChild(measurer);
    }

    function getGlobalPageLocation(globalPage) {
        let accumulated = 0;
        for (let i = 0; i < chunkPageCounts.length; i++) {
            const count = chunkPageCounts[i];
            if (globalPage < accumulated + count) {
                return {
                    chunkIndex: i,
                    localPage: globalPage - accumulated
                };
            }
            accumulated += count;
        }
        // 範囲外の場合は最後のチャンクの最後
        if (chunkPageCounts.length > 0) {
            const lastIdx = chunkPageCounts.length - 1;
            return {
                chunkIndex: lastIdx,
                localPage: Math.max(0, chunkPageCounts[lastIdx] - 1)
            };
        }
        return { chunkIndex: 0, localPage: 0 };
    }

    function updateLayout() {
        const allWindows = document.querySelectorAll('.page-right .text-window, .page-left .text-window');
        if (!textWindow) return;

        const oldPageWidth = pageWidth;
        const currentPixelOffset = currentPage * (oldPageWidth || 1);

        allWindows.forEach(win => {
            if (win) win.style.width = '';
        });

        let availableWidth = textWindow.parentElement.clientWidth; // textWindow自身の幅は optimalWidth になるため親（page-right等）から取る

        const computedStyle = window.getComputedStyle(textContainers[0]);
        let lineHeight = parseFloat(computedStyle.lineHeight);
        let fontSize = parseFloat(computedStyle.fontSize);
        if (isNaN(lineHeight)) lineHeight = fontSize * 1.5;

        textAlignmentOffset = - (lineHeight - fontSize) / 2;

        const paper = document.querySelector('.page-paper');
        const paperWidth = paper ? paper.clientWidth : window.innerWidth * 0.9;
        availableWidth = paperWidth;

        const totalThickness = globalTotalPages * widthPerPage;
        const maxPageContainerWidth = (availableWidth - totalThickness) / 2;
        const calculatedTextWindowWidth = maxPageContainerWidth - 45;
        const optimalWidth = Math.floor(calculatedTextWindowWidth / lineHeight) * lineHeight;

        document.documentElement.style.setProperty('--text-window-width', `${optimalWidth}px`);
        const finalPageWidth = maxPageContainerWidth;

        const pages = document.querySelectorAll('.page-right, .page-left');
        pages.forEach(p => {
            if (p) p.style.flex = `0 0 ${finalPageWidth}px`;
        });

        allWindows.forEach(win => {
            if (win) win.style.width = `${optimalWidth}px`;
        });

        pageWidth = optimalWidth;

        // --- 各チャンクのページ数計測と見出し抽出 ---
        const measurer = document.getElementById('offscreen-measurer');
        const mWindow = measurer.querySelector('.text-window');
        const mContainer = measurer.querySelector('.text-container');

        // 計測用ウィンドウの高さを同期（CSS変数で管理されているはずだが明示的にセット）
        mWindow.style.height = `${textWindow.clientHeight}px`;
        mWindow.style.width = `${pageWidth}px`;

        chunkPageCounts = [];
        chunkTitles = [];
        chunks.forEach((html, idx) => {
            mContainer.innerHTML = html;

            // 各チャンクの最初の見出しを抽出（章タイトルとして使用）
            const firstHeading = mContainer.querySelector('h1, h2, h3, h4, .az-h1, .az-h2, .az-h3, .az-h4, .ebook-title-main');
            chunkTitles.push(firstHeading ? firstHeading.textContent.trim() : (bookData.title || '電子書籍'));

            // 改ページ補正（計測用にも適用）
            const breaks = mContainer.querySelectorAll('.page-break');
            breaks.forEach(pb => {
                pb.style.marginRight = '0';
                const rect = pb.getBoundingClientRect();
                const containerRect = mContainer.getBoundingClientRect();
                const currentX = containerRect.right - rect.right;
                const remainder = currentX % pageWidth;
                if (remainder > 0) {
                    pb.style.marginRight = `${pageWidth - remainder}px`;
                }
            });

            const scrollWidth = mContainer.scrollWidth;
            const count = Math.ceil(scrollWidth / pageWidth);
            chunkPageCounts.push(count);
        });

        globalTotalPages = chunkPageCounts.reduce((a, b) => a + b, 0);

        if (oldPageWidth > 0 && oldPageWidth !== pageWidth) {
            currentPage = Math.floor(currentPixelOffset / pageWidth);
        }

        if (currentPage >= globalTotalPages) {
            currentPage = Math.max(0, globalTotalPages - 2);
        }
        if (currentPage % 2 !== 0) {
            currentPage = Math.max(0, currentPage - 1);
        }

        renderPages();
    }

    function renderPages() {
        if (globalTotalPages === 0 || chunks.length === 0) return;

        const locRight = getGlobalPageLocation(currentPage);
        const locLeft = getGlobalPageLocation(currentPage + 1);

        const containerRight = textContainers[0];
        const containerLeft = textContainers.length > 1 ? textContainers[1] : null;

        // 右ページのコンテンツセットと位置合わせ
        if (containerRight.dataset.chunkIndex !== String(locRight.chunkIndex)) {
            containerRight.innerHTML = chunks[locRight.chunkIndex];
            containerRight.dataset.chunkIndex = locRight.chunkIndex;
            applyPageBreaks(containerRight);
        }
        containerRight.style.transform = `translateX(${locRight.localPage * pageWidth + textAlignmentOffset}px)`;

        // 左ページのコンテンツセットと位置合わせ
        if (containerLeft) {
            if (currentPage + 1 < globalTotalPages) {
                if (containerLeft.dataset.chunkIndex !== String(locLeft.chunkIndex)) {
                    containerLeft.innerHTML = chunks[locLeft.chunkIndex];
                    containerLeft.dataset.chunkIndex = locLeft.chunkIndex;
                    applyPageBreaks(containerLeft);
                }
                containerLeft.style.transform = `translateX(${locLeft.localPage * pageWidth + textAlignmentOffset}px)`;
                containerLeft.style.visibility = 'visible';
            } else {
                containerLeft.style.visibility = 'hidden';
            }
        }

        const physicalRight = currentPage + 1;
        const physicalLeft = currentPage + 2;

        // 右側のページ表示（柱とノンブル）
        if (titleRight) {
            titleRight.textContent = chunkTitles[locRight.chunkIndex] || bookData.title || '';
        }
        if (pageNumRight) {
            pageNumRight.textContent = physicalRight;
        }

        // 左側のページ表示（柱とノンブル - 見開きのみ）
        if (titleLeft) {
            // 左ページが存在しない（最終ページが右で終わる）場合は空
            titleLeft.textContent = (physicalRight === globalTotalPages) ? "" : (chunkTitles[locLeft.chunkIndex] || bookData.title || '');
        }

        if (pageNumLeft) {
            if (physicalRight === globalTotalPages) {
                pageNumLeft.textContent = '';
            } else {
                pageNumLeft.textContent = physicalLeft;
            }
        }

        const leftDisplayNum = Math.min(physicalLeft, globalTotalPages);
        if (pageInput) pageInput.value = physicalRight;
        if (pageTotal) pageTotal.textContent = (physicalRight === globalTotalPages) ? ` / ${globalTotalPages}` : `〜${leftDisplayNum} / ${globalTotalPages}`;

        // 小口（本の厚み）の更新
        if (foreEdgeRight && foreEdgeLeft) {
            const pagesRemaining = Math.max(0, globalTotalPages - (currentPage + 2));
            const rightWidth = currentPage * widthPerPage;
            foreEdgeRight.style.width = `${rightWidth}px`;
            const leftWidth = pagesRemaining * widthPerPage;
            foreEdgeLeft.style.width = `${leftWidth}px`;
        }
    }

    function applyPageBreaks(container) {
        const breaks = container.querySelectorAll('.page-break');
        breaks.forEach(pb => {
            pb.style.marginRight = '0';
            const rect = pb.getBoundingClientRect();
            const containerRect = container.getBoundingClientRect();
            const currentX = containerRect.right - rect.right;
            const remainder = currentX % pageWidth;
            if (remainder > 0) {
                pb.style.marginRight = `${pageWidth - remainder}px`;
            }
        });
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
            // ! YではなくXです
            const rect = foreEdgeRight.getBoundingClientRect();
            const x = rect.right - e.clientX;
            const ratio = Math.max(0, Math.min(1, x / rect.width));
            console.log("clientX", e.clientX, "rect.left", rect.left, "rect.width", rect.width, "x", x, "ratio", ratio);
            let targetPage = Math.floor(ratio * currentPage);

            // 見開きモード時の偶数ページ補正
            if (targetPage % 2 !== 0) {
                targetPage = Math.max(0, targetPage - 1);
            }
            changePage(targetPage);
        });
    }

    if (foreEdgeLeft) {
        foreEdgeLeft.addEventListener('click', (e) => {
            const pagesRemaining = globalTotalPages - (currentPage + 2);
            if (pagesRemaining <= 0) return;

            const rect = foreEdgeLeft.getBoundingClientRect();
            const x = rect.right - e.clientX;
            const ratio = Math.max(0, Math.min(1, x / rect.width));
            console.log("clientX", e.clientX, "rect.left", rect.left, "rect.width", rect.width, "x", x, "ratio", ratio);
            let targetPage = (currentPage + 2) + Math.floor(ratio * pagesRemaining);

            // 最後のページを超えないように
            if (targetPage >= globalTotalPages) targetPage = globalTotalPages - 1;

            // 見開きモード時の奇数ページ補正
            if (targetPage % 2 !== 0) {
                targetPage = Math.min(globalTotalPages - 1, targetPage - 1);
            }
            changePage(targetPage);
        });
    }

    btnPrev.addEventListener('click', () => {
        const step = 2;
        if (currentPage - step >= 0) {
            changePage(currentPage - step);
        } else if (currentPage > 0) {
            changePage(0);
        }
    });

    btnNext.addEventListener('click', () => {
        const step = 2;
        if (currentPage + step < globalTotalPages) {
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
            if (val > globalTotalPages) val = globalTotalPages;

            // currentPageは0オリジンなので-1する
            let targetPage = val - 1;

            // 見開きモード時の奇数ページ補正（右寄せ）
            if (targetPage % 2 !== 0) {
                targetPage = Math.max(0, targetPage - 1);
            }

            changePage(targetPage);
            // 表示の即時反映（renderPageはフェードの合間に呼ばれるため、入力欄の数字だけ直しておく）
            e.target.value = targetPage + 1;
        });
    }

    document.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowLeft' || e.key === 'Enter') {
            const step = 2;
            if (currentPage + step < globalTotalPages) {
                changePage(currentPage + step);
            }
        }
        else if (e.key === 'ArrowRight') {
            const step = 2;
            if (currentPage - step >= 0) {
                changePage(currentPage - step);
            } else if (currentPage > 0) {
                changePage(0);
            }
        }
    });

    // 単一ページ表示関連の処理は削除されました

    let resizeTimer;
    const resizeObserver = new ResizeObserver(() => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(updateLayout, 150);
    });

    if (pagePaper) {
        resizeObserver.observe(pagePaper);
    }
});
