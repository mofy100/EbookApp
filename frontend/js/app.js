const API_BASE = '/api';
let currentPage = 0;
const limit = 50;
let currentSearch = '';
let selectedBookId = null;

const bookList        = document.getElementById('book-list');
const searchInput     = document.getElementById('search-input');
const searchButton    = document.getElementById('search-button');
const prevPageBtn     = document.getElementById('prev-page');
const nextPageBtn     = document.getElementById('next-page');
const pageInfo        = document.getElementById('page-info');

const detailPlaceholder = document.getElementById('detail-placeholder');
const detailContent     = document.getElementById('detail-content');
const detailThumbnail   = document.getElementById('detail-thumbnail');
const detailGenre       = document.getElementById('detail-genre');
const detailTitle       = document.getElementById('detail-title');
const detailAuthor      = document.getElementById('detail-author');
const detailMeta        = document.getElementById('detail-meta');
const detailSummary     = document.getElementById('detail-summary');
const detailTags        = document.getElementById('detail-tags');
const detailReadBtn     = document.getElementById('detail-read-btn');

searchButton.addEventListener('click', () => {
    currentPage = 0;
    currentSearch = searchInput.value.trim();
    fetchBooks();
});

searchInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') searchButton.click();
});

prevPageBtn.addEventListener('click', () => {
    if (currentPage > 0) { currentPage--; fetchBooks(); }
});

nextPageBtn.addEventListener('click', () => {
    currentPage++;
    fetchBooks();
});

async function fetchBooks() {
    bookList.innerHTML = '<div class="list-message">読み込み中...</div>';

    const offset = currentPage * limit;
    let url = `${API_BASE}/books?limit=${limit}&offset=${offset}`;
    if (currentSearch) url += `&search=${encodeURIComponent(currentSearch)}`;

    try {
        const res = await fetch(url);
        const data = await res.json();
        renderBooks(data.books, data.total);
    } catch (err) {
        console.error(err);
        bookList.innerHTML = '<div class="list-message">エラーが発生しました。</div>';
    }
}

function renderBooks(books, total) {
    bookList.innerHTML = '';

    if (books.length === 0) {
        bookList.innerHTML = '<div class="list-message">本が見つかりませんでした。</div>';
        pageInfo.textContent = '0 / 0 件';
        prevPageBtn.disabled = true;
        nextPageBtn.disabled = true;
        return;
    }

    books.forEach(book => {
        const card = document.createElement('div');
        card.className = 'book-card' + (book.id === selectedBookId ? ' selected' : '');
        card.dataset.id = book.id;
        card.title = book.title;

        card.innerHTML = `
            <div class="book-title">${escapeHTML(book.title)}</div>
            <div class="book-author">${escapeHTML(book.author || '')}</div>
        `;

        card.addEventListener('click', () => selectBook(book.id, book));
        bookList.appendChild(card);
    });

    const start = currentPage * limit + 1;
    const end = Math.min((currentPage + 1) * limit, total);
    pageInfo.textContent = `${start}–${end} / ${total}`;

    prevPageBtn.disabled = currentPage === 0;
    nextPageBtn.disabled = end >= total;
}

async function selectBook(bookId, bookFromList) {
    selectedBookId = bookId;

    document.querySelectorAll('.book-card').forEach(c => {
        c.classList.toggle('selected', Number(c.dataset.id) === bookId);
    });

    // リストデータで即時表示（summaryなし）
    showDetail(bookFromList, null);

    // 全量summaryを取得して上書き
    try {
        const res = await fetch(`${API_BASE}/books/${bookId}/summary`);
        const summary = await res.json();
        showDetail(bookFromList, summary);
    } catch (e) {
        console.error(e);
    }
}

function showDetail(book, summary) {
    detailPlaceholder.hidden = true;
    detailContent.hidden = false;

    // サムネイル（テキストで代替）
    detailThumbnail.innerHTML = '';
    const thumb = document.createElement('span');
    thumb.textContent = book.title;
    detailThumbnail.appendChild(thumb);

    // ジャンル（overallタグに統合したため非表示）
    detailGenre.innerHTML = '';

    // タイトル・著者
    detailTitle.textContent = book.title || '';
    detailAuthor.textContent = book.author || '';

    // メタ情報（新フォーマットではフィールドなし）
    detailMeta.innerHTML = '';

    // 概要
    const overallSummary = summary?.overall?.summary;
    detailSummary.textContent = overallSummary || '';
    detailSummary.hidden = !overallSummary;

    // タグ（カテゴリ別）
    const tagsObj = summary?.overall?.tags || {};
    const tagLines = Object.entries(tagsObj)
        .filter(([, vals]) => vals.length > 0)
        .map(([cat, vals]) =>
            `<div class="tag-category"><span class="tag-category-label">${escapeHTML(cat)}：</span>${vals.map(t => `<span>${escapeHTML(t)}</span>`).join('')}</div>`
        );
    detailTags.innerHTML = tagLines.join('');

    // 読むボタン
    detailReadBtn.onclick = () => { window.location.href = `viewer.html?id=${book.id}`; };
}

function escapeHTML(str) {
    if (!str) return '';
    return str.replace(/[&<>'"]/g,
        tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
    );
}

fetchBooks();
