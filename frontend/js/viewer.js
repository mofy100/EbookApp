import { state, initElements, updateIsMobile } from './state.js';
import { fetchManifest, fetchChunk } from './api.js';
import { createMeasurer, updateLayout } from './layout.js';
import { renderPages } from './renderer.js';
import { setupNavigation } from './navigation.js';

function mark(label, since) {
    const ms = (performance.now() - since).toFixed(1);
    console.log(`[viewer] ${label}: ${ms}ms`);
}

document.addEventListener('DOMContentLoaded', async () => {
    const t0 = performance.now();
    console.log('[viewer] DOMContentLoaded');

    // 1. 各要素の初期化
    initElements();
    updateIsMobile();

    const params = new URLSearchParams(window.location.search);
    state.bookId = params.get('id');

    if (!state.bookId) {
        state.elements.textContainers.forEach(container => {
            container.innerHTML = '<p>作品IDが指定されていません。検索画面から作品を選択してください。</p>';
        });
        if (state.elements.titleRight) state.elements.titleRight.textContent = 'エラー';
        return;
    }

    document.title = `読書中 (ID: ${state.bookId})`;

    try {
        // 1. マニフェスト取得
        const t1 = performance.now();
        state.bookData = await fetchManifest(state.bookId);
        mark('fetchManifest', t1);

        const bookTitle = state.bookData.title || '電子書籍';
        document.title = `${bookTitle} - ボケット文学`;
        if (state.elements.titleRight) state.elements.titleRight.textContent = bookTitle;
        if (state.elements.titleLeft) state.elements.titleLeft.textContent = bookTitle;

        const chapters = state.bookData.chapters;

        // フェーズ1: 最初のチャンクだけ取得して即描画
        const t2 = performance.now();
        const firstResult = await fetchChunk(state.bookId, chapters[0].file);
        mark('fetchChunk[0]', t2);

        state.chunks = [firstResult.content];

        createMeasurer();
        setupNavigation();

        const t3 = performance.now();
        setTimeout(() => {
            mark('setTimeout待機', t3);
            updateLayout(renderPages);
            mark('フェーズ1 合計 (DOMContentLoaded起点)', t0);
        }, 100);

        // リサイズ監視
        let resizeTimer;
        const resizeObserver = new ResizeObserver(() => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => {
                updateIsMobile();
                updateLayout(renderPages);
            }, 150);
        });
        if (state.elements.pagePaper) {
            resizeObserver.observe(state.elements.pagePaper);
        }

        // フェーズ2: 残りのチャンクをバックグラウンドで順次取得
        if (chapters.length > 1) {
            (async () => {
                for (const chapter of chapters.slice(1)) {
                    try {
                        const tChunk = performance.now();
                        const result = await fetchChunk(state.bookId, chapter.file);
                        mark(`fetchChunk[${chapter.file}]`, tChunk);
                        state.chunks.push(result.content);
                    } catch (e) {
                        console.warn(`チャンク取得失敗: ${chapter.file}`, e);
                        state.chunks.push('');
                    }
                }
                // 全チャンク取得完了 → レイアウト再計算で総ページ数を確定
                const tLayout2 = performance.now();
                updateLayout(renderPages);
                mark('フェーズ2 updateLayout', tLayout2);
            })();
        }

    } catch (err) {
        console.error("コンテンツの読み込みに失敗しました:", err);
        state.elements.textContainers.forEach(container => {
            container.innerHTML = `<p>読込みに失敗しました (${err.message})<br><br>ファイルがダウンロードされていないか、存在しない可能性があります。</p>`;
        });
    }
});
