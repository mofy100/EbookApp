import { state } from './state.js';

export function createMeasurer() {
    if (document.getElementById('offscreen-measurer')) return;
    const measurer = document.createElement('div');
    measurer.id = 'offscreen-measurer';
    measurer.style.cssText = `
        position: absolute; visibility: hidden; z-index: -1000;
        top: 0; left: 0; pointer-events: none; width: 0; height: 0; overflow: hidden;
    `;
    measurer.innerHTML = `
        <div class="text-window" style="position: relative;">
            <div class="text-container" style="position: absolute;"></div>
        </div>
    `;
    document.body.appendChild(measurer);
}

export function getGlobalPageLocation(globalPage) {
    let accumulated = 0;
    for (let i = 0; i < state.chunkPageCounts.length; i++) {
        const count = state.chunkPageCounts[i];
        if (globalPage < accumulated + count) {
            return {
                chunkIndex: i,
                localPage: globalPage - accumulated
            };
        }
        accumulated += count;
    }
    if (state.chunkPageCounts.length > 0) {
        const lastIdx = state.chunkPageCounts.length - 1;
        return {
            chunkIndex: lastIdx,
            localPage: Math.max(0, state.chunkPageCounts[lastIdx] - 1)
        };
    }
    return { chunkIndex: 0, localPage: 0 };
}

export function updateLayout(renderPagesCallback) {
    const tLayout = performance.now();
    const { elements } = state;
    if (!elements.textWindow) return;

    const oldPageWidth = state.pageWidth;
    const currentPixelOffset = state.currentPage * (oldPageWidth || 1);

    const allWindows = document.querySelectorAll('.page-right .text-window, .page-left .text-window');
    allWindows.forEach(win => { if (win) win.style.width = ''; });

    const computedStyle = getComputedStyle(elements.textContainers[0]);
    let lineHeight = parseFloat(computedStyle.lineHeight);
    let fontSize = parseFloat(computedStyle.fontSize);
    if (isNaN(lineHeight)) lineHeight = fontSize * 1.5;

    state.textAlignmentOffset = - (lineHeight - fontSize) / 2;

    /* 小口の合計幅はCSSの--fore-edge-totalから取得（固定） */
    const paperWidth = elements.pagePaper ? elements.pagePaper.clientWidth : window.innerWidth * 0.9;
    const foreEdgeTotalRatio = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--fore-edge-total')) / 100;
    state.totalForeEdge = paperWidth * foreEdgeTotalRatio;
    const maxPageContainerWidth = (paperWidth - state.totalForeEdge) / 2;
    /* pageのpaddingを考慮して、text-windowの幅を計算 */
    const pageRight = document.querySelector('.page-right');
    const pageRightPadding = parseFloat(getComputedStyle(pageRight).paddingLeft) + parseFloat(getComputedStyle(pageRight).paddingRight);
    const calculatedTextWindowWidth = maxPageContainerWidth - pageRightPadding;
    /* text-windowの幅が、lineHeightの整数倍になるように */
    const optimalWidth = Math.floor(calculatedTextWindowWidth / lineHeight) * lineHeight;

    document.documentElement.style.setProperty('--text-window-width', `${optimalWidth}px`);
    const finalPageWidth = maxPageContainerWidth;

    const pages = document.querySelectorAll('.page-right, .page-left');
    pages.forEach(p => { if (p) p.style.flex = `0 0 ${finalPageWidth}px`; });
    allWindows.forEach(win => { if (win) win.style.width = `${optimalWidth}px`; });

    state.pageWidth = optimalWidth;

    /* windowの高さは、文字サイズの整数倍になるように調整 */
    const windowHeight = elements.textWindow.clientHeight;
    const optimalHeight = Math.floor(windowHeight / lineHeight) * lineHeight;
    state.pageHeight = optimalHeight;

    // --- 各チャンクのページ数計測 ---
    const measurer = document.getElementById('offscreen-measurer');
    const mWindow = measurer.querySelector('.text-window');
    const mContainer = measurer.querySelector('.text-container');

    mWindow.style.height = `${state.pageHeight}px`;
    mWindow.style.width = `${state.pageWidth}px`;

    state.chunkPageCounts = [];
    state.chunkTitles = [];
    const tMeasure = performance.now();
    state.chunks.forEach((html, i) => {
        const tChunk = performance.now();
        mContainer.innerHTML = html;
        const tInnerHTML = performance.now();

        const firstHeading = mContainer.querySelector('h1, h2, h3, h4, .az-h1, .az-h2, .az-h3, .az-h4, .ebook-title-main');
        state.chunkTitles.push(firstHeading ? firstHeading.textContent.trim() : (state.bookData.title || '電子書籍'));

        // 改ページ補正
        const breaks = mContainer.querySelectorAll('.page-break');
        breaks.forEach(pb => {
            pb.style.marginRight = '0';
            const rect = pb.getBoundingClientRect();
            const containerRect = mContainer.getBoundingClientRect();
            const currentX = containerRect.right - rect.right;
            const remainder = currentX % state.pageWidth;
            if (remainder > 0) pb.style.marginRight = `${state.pageWidth - remainder}px`;
        });

        const scrollWidth = mContainer.scrollWidth;
        state.chunkPageCounts.push(Math.ceil(scrollWidth / state.pageWidth));

        const ms = (performance.now() - tChunk).toFixed(1);
        const msHTML = (performance.now() - tInnerHTML).toFixed(1);
        console.log(`[layout] chunk[${i}] 計測: ${ms}ms (innerHTML後: ${msHTML}ms, page-break×${breaks.length}, pages=${state.chunkPageCounts[i]})`);
    });
    console.log(`[layout] 全chunk計測合計: ${(performance.now() - tMeasure).toFixed(1)}ms`);

    state.globalTotalPages = state.chunkPageCounts.reduce((a, b) => a + b, 0);

    if (oldPageWidth > 0 && oldPageWidth !== state.pageWidth) {
        state.currentPage = Math.floor(currentPixelOffset / state.pageWidth);
    }

    if (state.currentPage >= state.globalTotalPages) {
        state.currentPage = Math.max(0, state.globalTotalPages - 2);
    }
    if (state.currentPage % 2 !== 0) {
        state.currentPage = Math.max(0, state.currentPage - 1);
    }

    if (renderPagesCallback) renderPagesCallback();
    console.log(`[layout] updateLayout合計: ${(performance.now() - tLayout).toFixed(1)}ms`);
}
