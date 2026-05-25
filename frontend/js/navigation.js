import { state } from './state.js';
import { renderPages } from './renderer.js';

export function changePage(newPage) {
    if (state.currentPage === newPage) return;

    state.elements.textContainers.forEach(container => container.classList.add('fade-out'));

    setTimeout(() => {
        state.currentPage = newPage;
        renderPages();

        requestAnimationFrame(() => {
            state.elements.textContainers.forEach(container => container.classList.remove('fade-out'));
        });
    }, 200);
}

export function setupNavigation() {
    const { elements } = state;

    if (elements.btnPrev) {
        elements.btnPrev.addEventListener('click', () => {
            if (state.isMobile) {
                if (state.currentPage > 0) changePage(state.currentPage - 1);
            } else {
                if (state.currentPage - 2 >= 0) changePage(state.currentPage - 2);
                else if (state.currentPage > 0) changePage(0);
            }
        });
    }

    if (elements.btnNext) {
        elements.btnNext.addEventListener('click', () => {
            const step = state.isMobile ? 1 : 2;
            if (state.currentPage + step < state.globalTotalPages) changePage(state.currentPage + step);
        });
    }

    if (elements.pageInput) {
        elements.pageInput.addEventListener('change', (e) => {
            let val = parseInt(e.target.value, 10);
            if (isNaN(val)) val = state.currentPage + 1;
            if (val < 1) val = 1;
            if (val > state.globalTotalPages) val = state.globalTotalPages;

            let targetPage = val - 1;
            if (!state.isMobile && targetPage % 2 !== 0) targetPage = Math.max(0, targetPage - 1);
            changePage(targetPage);
            e.target.value = targetPage + 1;
        });
    }

    if (elements.foreEdgeRight) {
        elements.foreEdgeRight.addEventListener('click', (e) => {
            if (state.currentPage <= 0) return;
            const rect = elements.foreEdgeRight.getBoundingClientRect();
            const x = rect.right - e.clientX;
            const ratio = Math.max(0, Math.min(1, x / rect.width));
            let targetPage = Math.floor(ratio * state.currentPage);
            if (targetPage % 2 !== 0) targetPage = Math.max(0, targetPage - 1);
            changePage(targetPage);
        });
    }

    if (elements.foreEdgeLeft) {
        elements.foreEdgeLeft.addEventListener('click', (e) => {
            const pagesRemaining = state.globalTotalPages - (state.currentPage + 2);
            if (pagesRemaining <= 0) return;
            const rect = elements.foreEdgeLeft.getBoundingClientRect();
            const x = rect.right - e.clientX;
            const ratio = Math.max(0, Math.min(1, x / rect.width));
            let targetPage = (state.currentPage + 2) + Math.floor(ratio * pagesRemaining);
            if (targetPage >= state.globalTotalPages) targetPage = state.globalTotalPages - 1;
            if (targetPage % 2 !== 0) targetPage = Math.min(state.globalTotalPages - 1, targetPage - 1);
            changePage(targetPage);
        });
    }

    document.addEventListener('keydown', (e) => {
        const step = state.isMobile ? 1 : 2;
        if (e.key === 'ArrowLeft' || e.key === 'Enter') {
            if (state.currentPage + step < state.globalTotalPages) changePage(state.currentPage + step);
        } else if (e.key === 'ArrowRight') {
            if (state.currentPage - step >= 0) changePage(state.currentPage - step);
            else if (state.currentPage > 0) changePage(0);
        }
    });

    // タッチスワイプ＆タップナビゲーション
    let touchStartX = 0;
    let touchStartY = 0;
    document.addEventListener('touchstart', (e) => {
        touchStartX = e.touches[0].clientX;
        touchStartY = e.touches[0].clientY;
    }, { passive: true });
    document.addEventListener('touchend', (e) => {
        // コントロールバー上のタッチは無視
        if (e.target.closest('.controls-bar')) return;

        const diffX = touchStartX - e.changedTouches[0].clientX;
        const diffY = touchStartY - e.changedTouches[0].clientY;
        const step = state.isMobile ? 1 : 2;

        // スワイプ判定（移動量が大きい場合）
        if (Math.abs(diffX) >= 50 && Math.abs(diffX) > Math.abs(diffY)) {
            if (diffX > 0) {
                if (state.currentPage + step < state.globalTotalPages) changePage(state.currentPage + step);
            } else {
                if (state.currentPage - step >= 0) changePage(state.currentPage - step);
                else if (state.currentPage > 0) changePage(0);
            }
            return;
        }

        // タップ判定（ほぼ動いていない場合）
        if (Math.abs(diffX) < 10 && Math.abs(diffY) < 10) {
            const tapX = e.changedTouches[0].clientX;
            const halfWidth = window.innerWidth / 2;
            if (tapX < halfWidth) {
                // 左タップ → 次ページ
                if (state.currentPage + step < state.globalTotalPages) changePage(state.currentPage + step);
            } else {
                // 右タップ → 前ページ
                if (state.currentPage - step >= 0) changePage(state.currentPage - step);
                else if (state.currentPage > 0) changePage(0);
            }
        }
    });
}
