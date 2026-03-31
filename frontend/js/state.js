export const API_BASE = "http://127.0.0.1:8000/api";

export const state = {
    bookId: null,
    bookData: {},
    chunks: [],
    chunkPageCounts: [],
    chunkTitles: [],
    currentPage: 0,
    globalTotalPages: 0,
    pageWidth: 0,
    textAlignmentOffset: 0,
    widthPerPage: 0.1, // ページ1枚あたりの厚み(px)
    
    // DOM要素のキャッシュ
    elements: {
        textContainers: [],
        textWindow: null,
        pagePaper: null,
        btnNext: null,
        btnPrev: null,
        pageInput: null,
        pageTotal: null,
        titleRight: null,
        titleLeft: null,
        pageNumRight: null,
        pageNumLeft: null,
        foreEdgeRight: null,
        foreEdgeLeft: null
    }
};

export function initElements() {
    state.elements.textContainers = document.querySelectorAll('.text-container');
    state.elements.textWindow = document.querySelector('.page-right .text-window') || document.querySelector('.text-window');
    state.elements.pagePaper = document.querySelector('.page-paper');
    state.elements.btnNext = document.getElementById('btn-next');
    state.elements.btnPrev = document.getElementById('btn-prev');
    state.elements.pageInput = document.getElementById('page-input');
    state.elements.pageTotal = document.getElementById('page-total');
    state.elements.titleRight = document.getElementById('page-title-right');
    state.elements.titleLeft = document.getElementById('page-title-left');
    state.elements.pageNumRight = document.getElementById('page-number-right');
    state.elements.pageNumLeft = document.getElementById('page-number-left');
    state.elements.foreEdgeRight = document.getElementById('fore-edge-right');
    state.elements.foreEdgeLeft = document.getElementById('fore-edge-left');
}
