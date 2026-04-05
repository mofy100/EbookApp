import { state } from './state.js';
import { getGlobalPageLocation } from './layout.js';

export function renderPages() {
    const { elements } = state;
    if (state.globalTotalPages === 0 || state.chunks.length === 0) return;

    const locRight = getGlobalPageLocation(state.currentPage);
    const locLeft = getGlobalPageLocation(state.currentPage + 1);

    const containerRight = elements.textContainers[0];
    const containerLeft = elements.textContainers.length > 1 ? elements.textContainers[1] : null;

    // 右ページ
    if (containerRight.dataset.chunkIndex !== String(locRight.chunkIndex)) {
        containerRight.innerHTML = state.chunks[locRight.chunkIndex];
        containerRight.dataset.chunkIndex = locRight.chunkIndex;
        applyPageBreaks(containerRight);
        // applyHighlights(containerRight); // 将来的に追加
    }
    containerRight.style.transform = `translateX(${locRight.localPage * state.pageWidth + state.textAlignmentOffset}px)`;

    // 左ページ
    if (containerLeft) {
        if (state.currentPage + 1 < state.globalTotalPages) {
            if (containerLeft.dataset.chunkIndex !== String(locLeft.chunkIndex)) {
                containerLeft.innerHTML = state.chunks[locLeft.chunkIndex];
                containerLeft.dataset.chunkIndex = locLeft.chunkIndex;
                applyPageBreaks(containerLeft);
                // applyHighlights(containerLeft);
            }
            containerLeft.style.transform = `translateX(${locLeft.localPage * state.pageWidth + state.textAlignmentOffset}px)`;
            containerLeft.style.visibility = 'visible';
        } else {
            containerLeft.style.visibility = 'hidden';
        }
    }

    const physicalRight = state.currentPage + 1;
    const physicalLeft = state.currentPage + 2;

    if (elements.titleRight) elements.titleRight.textContent = state.chunkTitles[locRight.chunkIndex] || state.bookData.title || '';
    if (elements.pageNumRight) elements.pageNumRight.textContent = physicalRight;

    if (elements.titleLeft) {
        elements.titleLeft.textContent = (physicalRight === state.globalTotalPages) ? "" : (state.chunkTitles[locLeft.chunkIndex] || state.bookData.title || '');
    }
    if (elements.pageNumLeft) {
        elements.pageNumLeft.textContent = (physicalRight === state.globalTotalPages) ? '' : physicalLeft;
    }

    const leftDisplayNum = Math.min(physicalLeft, state.globalTotalPages);
    if (elements.pageInput) elements.pageInput.value = physicalRight;
    if (elements.pageTotal) {
        elements.pageTotal.textContent = (physicalRight === state.globalTotalPages) ? ` / ${state.globalTotalPages}` : `〜${leftDisplayNum} / ${state.globalTotalPages}`;
    }

    // 小口（本の厚み）の更新
    if (elements.foreEdgeRight && elements.foreEdgeLeft) {
        const pagesRemaining = Math.max(0, state.globalTotalPages - (state.currentPage + 2));
        elements.foreEdgeRight.style.width = `${state.currentPage * state.widthPerPage}px`;
        elements.foreEdgeLeft.style.width = `${pagesRemaining * state.widthPerPage}px`;
    }
}

export function applyPageBreaks(container) {
    const breaks = container.querySelectorAll('.page-break');
    breaks.forEach(pb => {
        pb.style.marginRight = '0';
        const rect = pb.getBoundingClientRect();
        const containerRect = container.getBoundingClientRect();
        const currentX = containerRect.right - rect.right;
        const remainder = currentX % state.pageWidth;
        if (remainder > 0) pb.style.marginRight = `${state.pageWidth - remainder}px`;
    });
}
