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

    // 左ページ（デスクトップのみ）
    if (containerLeft && !state.isMobile) {
        if (state.currentPage + 1 < state.globalTotalPages) {
            if (containerLeft.dataset.chunkIndex !== String(locLeft.chunkIndex)) {
                containerLeft.innerHTML = state.chunks[locLeft.chunkIndex];
                containerLeft.dataset.chunkIndex = locLeft.chunkIndex;
                applyPageBreaks(containerLeft);
            }
            containerLeft.style.transform = `translateX(${locLeft.localPage * state.pageWidth + state.textAlignmentOffset}px)`;
            containerLeft.style.visibility = 'visible';
        } else {
            containerLeft.style.visibility = 'hidden';
        }
    }

    const physicalRight = state.currentPage + 1;
    const physicalLeft = state.currentPage + 2;

    if (elements.titleRight) elements.titleRight.textContent = state.bookData.title || '';
    if (elements.pageNumRight) elements.pageNumRight.textContent = physicalRight;

    if (!state.isMobile) {
        if (elements.titleLeft) {
            elements.titleLeft.textContent = (physicalRight === state.globalTotalPages) ? "" : (state.bookData.title || '');
        }
        if (elements.pageNumLeft) {
            elements.pageNumLeft.textContent = (physicalRight === state.globalTotalPages) ? '' : physicalLeft;
        }
    }

    if (elements.pageInput) elements.pageInput.value = physicalRight;
    if (elements.pageTotal) {
        if (state.isMobile) {
            elements.pageTotal.textContent = ` / ${state.globalTotalPages}`;
        } else {
            const leftDisplayNum = Math.min(physicalLeft, state.globalTotalPages);
            elements.pageTotal.textContent = (physicalRight === state.globalTotalPages) ? ` / ${state.globalTotalPages}` : `〜${leftDisplayNum} / ${state.globalTotalPages}`;
        }
    }

    // 小口（本の厚み）の左右分配
    if (elements.foreEdgeRight && elements.foreEdgeLeft && state.totalForeEdge > 0) {
        const allChunksLoaded = state.chunks.length >= (state.bookData.chapters || []).length;
        if (!allChunksLoaded || state.globalTotalPages === 0) {
            elements.foreEdgeRight.style.width = '0px';
            elements.foreEdgeLeft.style.width = `${state.totalForeEdge}px`;
        } else {
            const ratio = state.currentPage / state.globalTotalPages;
            elements.foreEdgeRight.style.width = `${state.totalForeEdge * ratio}px`;
            elements.foreEdgeLeft.style.width = `${state.totalForeEdge * (1 - ratio)}px`;
        }
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
