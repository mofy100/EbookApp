const API_BASE = '/api';
let currentPage = 0;
const limit = 50;
let currentSearch = '';
let selectedTags = [];
let selectedBookId = null;

const bookList        = document.getElementById('book-list');
const searchInput     = document.getElementById('search-input');
const searchButton    = document.getElementById('search-button');
const prevPageBtn     = document.getElementById('prev-page');
const nextPageBtn     = document.getElementById('next-page');
const pageInfo        = document.getElementById('page-info');
const tagFilterEl     = document.getElementById('tag-filter');
const tagFilterTitle  = document.getElementById('tag-filter-title');
const tagClearBtn     = document.getElementById('tag-clear-btn');

const mobileBackBtn   = document.getElementById('mobile-back-btn');
const filterOpenBtn   = document.getElementById('filter-open-btn');
const filterCloseBtn  = document.getElementById('filter-close-btn');

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

mobileBackBtn.addEventListener('click', () => {
    document.body.classList.remove('mobile-detail-open');
});

filterOpenBtn.addEventListener('click', () => {
    document.body.classList.add('mobile-filter-open');
});

filterCloseBtn.addEventListener('click', () => {
    document.body.classList.remove('mobile-filter-open');
});

tagClearBtn.addEventListener('click', () => {
    selectedTags = [];
    document.querySelectorAll('.filter-chip').forEach(btn => btn.classList.remove('active'));
    updateFilterHeader();
    fetchBooks();
});

// タグフィルター
const CAT_ORDER = ["ジャンル", "サブジャンル", "時代", "文学運動・流派", "テーマ", "形式・文体"];

async function fetchTags() {
    try {
        const res = await fetch(`${API_BASE}/tags`);
        const tags = await res.json();
        renderTagFilter(tags);
    } catch (e) {
        console.error(e);
    }
}

function renderTagFilter(tags) {
    const byCategory = {};
    tags.forEach(t => {
        const cat = t.category || 'その他';
        if (!byCategory[cat]) byCategory[cat] = [];
        byCategory[cat].push(t);
    });

    tagFilterEl.innerHTML = '';
    CAT_ORDER.forEach(cat => {
        if (!byCategory[cat]) return;

        const section = document.createElement('div');
        section.className = 'filter-section';
        section.dataset.cat = cat;

        const label = document.createElement('span');
        label.className = 'filter-section-label';
        label.textContent = cat;
        section.appendChild(label);

        const chipsRow = document.createElement('div');
        chipsRow.className = 'filter-section-chips';
        byCategory[cat].sort((a, b) => a.order - b.order);
        byCategory[cat].forEach(t => {
            const btn = document.createElement('button');
            btn.className = 'filter-chip' + (selectedTags.includes(t.tag) ? ' active' : '');
            btn.dataset.cat = cat;
            btn.dataset.tag = t.tag;
            btn.textContent = t.tag;
            btn.title = `${t.count}件`;
            btn.addEventListener('click', () => toggleTag(t.tag));
            chipsRow.appendChild(btn);
        });
        section.appendChild(chipsRow);
        tagFilterEl.appendChild(section);
    });
}

function toggleTag(tag) {
    const idx = selectedTags.indexOf(tag);
    if (idx === -1) {
        selectedTags.push(tag);
    } else {
        selectedTags.splice(idx, 1);
    }
    currentPage = 0;
    document.querySelectorAll('.filter-chip').forEach(btn => {
        btn.classList.toggle('active', selectedTags.includes(btn.dataset.tag));
    });
    updateFilterHeader();
    fetchBooks();
}

function updateFilterHeader() {
    const count = selectedTags.length;
    tagClearBtn.hidden = count === 0;
    tagFilterTitle.textContent = count === 0 ? 'タグで絞り込む' : `タグで絞り込む（${count}）`;
    filterOpenBtn.textContent = count === 0 ? '絞り込む' : `絞り込む（${count}）`;
    filterOpenBtn.classList.toggle('has-filter', count > 0);
}

async function fetchBooks() {
    bookList.innerHTML = '<div class="list-message">読み込み中...</div>';

    const offset = currentPage * limit;
    let url = `${API_BASE}/books?limit=${limit}&offset=${offset}`;
    if (currentSearch) url += `&search=${encodeURIComponent(currentSearch)}`;
    selectedTags.forEach(tag => { url += `&tags=${encodeURIComponent(tag)}`; });

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
        card.className = 'book-card' + (book.book_id === selectedBookId ? ' selected' : '');
        card.dataset.id = book.book_id;
        card.title = book.title;

        card.innerHTML = `
            <div class="book-title">${escapeHTML(book.title)}</div>
            <div class="book-author">${escapeHTML(book.author || '')}</div>
        `;

        card.addEventListener('click', () => selectBook(book.book_id, book));
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

    if (window.innerWidth < 768) {
        document.body.classList.add('mobile-detail-open');
    }

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
    const tagEntries = CAT_ORDER
        .filter(cat => tagsObj[cat]?.length > 0)
        .map(cat => [cat, tagsObj[cat]]);
    const tagLines = tagEntries.map(([cat, vals]) =>
        `<div class="tag-category" data-cat="${escapeHTML(cat)}"><span class="tag-category-label">${escapeHTML(cat)}：</span><div class="tag-items">${vals.map(t => `<span class="tag-item" data-tag="${escapeHTML(t)}" title="このタグで絞り込む">${escapeHTML(t)}</span>`).join('')}</div></div>`
    );
    detailTags.innerHTML = tagLines.join('');

    // 詳細パネルのタグをクリックでフィルター適用
    detailTags.querySelectorAll('.tag-item').forEach(el => {
        el.addEventListener('click', () => toggleTag(el.dataset.tag));
    });

    // 読むボタン
    detailReadBtn.onclick = () => { window.location.href = `viewer.html?id=${book.book_id}`; };
}

function escapeHTML(str) {
    if (!str) return '';
    return str.replace(/[&<>'"]/g,
        tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
    );
}

fetchTags();
fetchBooks();
