import { state, initElements } from './state.js';
import { fetchManifest, fetchChunk } from './api.js';
import { createMeasurer, updateLayout } from './layout.js';
import { renderPages } from './renderer.js';
import { setupNavigation } from './navigation.js';

document.addEventListener('DOMContentLoaded', async () => {
    // 1. 各要素の初期化
    initElements();

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
        // 1. マニフェストとチャンクの取得
        state.bookData = await fetchManifest(state.bookId);
        
        const bookTitle = state.bookData.title || '電子書籍';
        document.title = `${bookTitle} - 青空文庫リーダー`;
        if (state.elements.titleRight) state.elements.titleRight.textContent = bookTitle;
        if (state.elements.titleLeft) state.elements.titleLeft.textContent = bookTitle;

        const chunkPromises = state.bookData.chapters.map(chapter => fetchChunk(state.bookId, chapter.file));
        const chunkResults = await Promise.all(chunkPromises);
        state.chunks = chunkResults.map(res => res.content);

        // 2. 基本機能のセットアップ
        createMeasurer();
        setupNavigation();

        // 3. 初回レイアウト計算と描画
        setTimeout(() => updateLayout(renderPages), 100);

        // 4. リサイズ監視
        let resizeTimer;
        const resizeObserver = new ResizeObserver(() => {
            clearTimeout(resizeTimer);
            resizeTimer = setTimeout(() => updateLayout(renderPages), 150);
        });
        if (state.elements.pagePaper) {
            resizeObserver.observe(state.elements.pagePaper);
        }

    } catch (err) {
        console.error("コンテンツの読み込みに失敗しました:", err);
        state.elements.textContainers.forEach(container => {
            container.innerHTML = `<p>読込みに失敗しました (${err.message})<br><br>ファイルがダウンロードされていないか、存在しない可能性があります。</p>`;
        });
    }
});
