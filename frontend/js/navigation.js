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
            if (state.currentPage - 2 >= 0) changePage(state.currentPage - 2);
            else if (state.currentPage > 0) changePage(0);
        });
    }

    if (elements.btnNext) {
        elements.btnNext.addEventListener('click', () => {
            if (state.currentPage + 2 < state.globalTotalPages) changePage(state.currentPage + 2);
        });
    }

    if (elements.pageInput) {
        elements.pageInput.addEventListener('change', (e) => {
            let val = parseInt(e.target.value, 10);
            if (isNaN(val)) val = state.currentPage + 1;
            if (val < 1) val = 1;
            if (val > state.globalTotalPages) val = state.globalTotalPages;

            let targetPage = val - 1;
            if (targetPage % 2 !== 0) targetPage = Math.max(0, targetPage - 1);
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
        if (e.key === 'ArrowLeft' || e.key === 'Enter') {
            if (state.currentPage + 2 < state.globalTotalPages) changePage(state.currentPage + 2);
        } else if (e.key === 'ArrowRight') {
            if (state.currentPage - 2 >= 0) changePage(state.currentPage - 2);
            else if (state.currentPage > 0) changePage(0);
        }
    });
}
